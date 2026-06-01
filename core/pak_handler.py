"""
pak_handler.py — UE4 Pak file handler (pure Python, seek-based)
Supports: pak v3 (legacy FString index) and v10/v11 (path-hash index)
"""
import os, struct, zlib, hashlib
from dataclasses import dataclass, field

PAK_MAGIC   = 0x5A6F12E1
PAK_VERSION = 3   # version used when creating patch paks


def _read_fstring_fh(fh) -> str:
    """Read UE4 FString from file handle."""
    buf = fh.read(4)
    if len(buf) < 4:
        return ""
    length = struct.unpack('<i', buf)[0]
    if length == 0:
        return ""
    if length < 0:
        byte_count = (-length) * 2
        raw = fh.read(byte_count)
        return raw[:-2].decode('utf-16-le', errors='replace')
    else:
        raw = fh.read(length)
        return raw[:-1].decode('latin-1', errors='replace')


def _read_fstring_mem(data: bytes, pos: int) -> tuple[str, int]:
    """Read UE4 FString from bytes buffer at pos. Returns (string, new_pos)."""
    length = struct.unpack_from('<i', data, pos)[0]; pos += 4
    if length == 0:
        return ("", pos)
    if length < 0:
        byte_count = (-length - 1) * 2
        text = data[pos:pos + byte_count].decode('utf-16-le', errors='replace')
        pos += byte_count + 2
    else:
        text = data[pos:pos + length - 1].decode('latin-1', errors='replace')
        pos += length
    return (text, pos)


@dataclass
class _PakEntryMeta:
    filename:    str
    data_offset: int    # v3: actual data start; v10+: per-file-header base
    size:        int    # compressed size
    size_decom:  int    # decompressed size
    sha1:        bytes
    comp_method: int    # 0=none, 1=zlib
    comp_blocks: list = field(default_factory=list)  # v3: [(abs_start, abs_end)]
    v10:         bool  = False  # True = v10+ format (blocks relative to data_offset)


# ── Footer detection ──────────────────────────────────────────────────────────

def _find_footer(fh) -> tuple[int, int, int]:
    """
    Scan last bytes for PAK magic. Returns (version, idx_offset, idx_size).
    v3 footer = 44 bytes; v8+ footer = 44 + 5×32 = 204 bytes (+ optional 17 for encryption).
    """
    fh.seek(0, 2)
    file_size = fh.tell()

    for footer_size in [44, 204, 221, 205, 222]:
        if footer_size > file_size:
            continue
        fh.seek(-footer_size, 2)
        magic = struct.unpack('<I', fh.read(4))[0]
        if magic == PAK_MAGIC:
            version    = struct.unpack('<I', fh.read(4))[0]
            idx_offset = struct.unpack('<q', fh.read(8))[0]
            idx_size   = struct.unpack('<q', fh.read(8))[0]
            return version, idx_offset, idx_size

    raise ValueError("Not a valid UE4 pak (magic not found in footer)")


# ── v3 index (FString-per-file) ───────────────────────────────────────────────

def _read_index_v3(pak_path: str, idx_offset: int, idx_size: int
                   ) -> tuple[str, list[_PakEntryMeta]]:
    """Parse legacy v3 index: mount_point + per-file (FString, entry header)."""
    with open(pak_path, 'rb') as fh:
        fh.seek(idx_offset)
        mount      = _read_fstring_fh(fh)
        file_count = struct.unpack('<i', fh.read(4))[0]

        entries = []
        for _ in range(file_count):
            fname = _read_fstring_fh(fh)

            # UE4 pak v3 entry layout (verified empirically):
            # offset(8) + size(8) + uncompressed(8) + comp_method(4) + sha1(20)
            # + block_count(4) + blocks(n×16) + bEncrypted(1)
            # + CompressionBlockSize(4)  ← only when comp_method != 0
            offset      = struct.unpack('<q', fh.read(8))[0]
            size        = struct.unpack('<q', fh.read(8))[0]
            size_decom  = struct.unpack('<q', fh.read(8))[0]
            comp_method = struct.unpack('<I', fh.read(4))[0]
            sha1        = fh.read(20)
            block_count = struct.unpack('<I', fh.read(4))[0]

            comp_blocks = []
            for _ in range(block_count):
                bs, be = struct.unpack('<qq', fh.read(16))
                comp_blocks.append((bs, be))

            fh.read(1)  # bEncrypted
            if comp_method != 0:
                fh.read(4)  # CompressionBlockSize

            per_file_header = 53 + len(comp_blocks) * 16 + (4 if comp_method != 0 else 0)
            data_offset = offset + per_file_header

            entries.append(_PakEntryMeta(
                filename=fname,
                data_offset=data_offset,
                size=size,
                size_decom=size_decom,
                sha1=sha1,
                comp_method=comp_method,
                comp_blocks=comp_blocks,
                v10=False,
            ))

    return mount, entries


# ── v10/v11 index (path-hash + FullDirIndex) ──────────────────────────────────

def _decode_compact_entry(enc_data: bytes, byte_offset: int) -> dict | None:
    """
    Decode a v10+ compact entry at byte_offset within enc_data.
    Returns dict with keys: offset, unc_sz, cmp_sz, method, blocks (count).
    The 'offset' is the per-file-header base in the pak file.
    """
    if byte_offset + 4 > len(enc_data):
        return None

    raw = enc_data[byte_offset:]
    pos = 0
    flags   = struct.unpack_from('<I', raw, pos)[0]; pos += 4

    off32   = (flags >> 31) & 1
    unc32   = (flags >> 30) & 1
    cmp32   = (flags >> 29) & 1
    eq      = (flags >> 28) & 1
    method  = (flags >> 23) & 0x3F   # empirically: bit28-23 = 6 bits, method=1 = Zlib
    enc     = (flags >> 22) & 1
    blocks  = (flags >> 6)  & 0xFFF  # 12-bit block count

    if pos + (4 if off32 else 8) > len(raw):
        return None
    offset  = struct.unpack_from('<I' if off32 else '<Q', raw, pos)[0]; pos += 4 if off32 else 8

    if pos + (4 if unc32 else 8) > len(raw):
        return None
    unc_sz  = struct.unpack_from('<I' if unc32 else '<Q', raw, pos)[0]; pos += 4 if unc32 else 8

    if eq:
        cmp_sz = unc_sz
    else:
        if pos + (4 if cmp32 else 8) > len(raw):
            return None
        cmp_sz = struct.unpack_from('<I' if cmp32 else '<Q', raw, pos)[0]; pos += 4 if cmp32 else 8

    return dict(offset=offset, unc_sz=unc_sz, cmp_sz=cmp_sz,
                method=method, enc=enc, block_count=blocks)


def _parse_v10_per_file_header(pak_path: str, hdr_base: int
                                ) -> tuple[int, int, int, list]:
    """
    Read per-file header at hdr_base. Returns (cmp_sz, unc_sz, cmethod, blocks_relative).
    blocks_relative = [(start_rel, end_rel)] — offsets relative to hdr_base.
    """
    with open(pak_path, 'rb') as fh:
        fh.seek(hdr_base)
        hdr = fh.read(512)   # enough for any reasonable header

    pos = 0
    pos += 8                                                  # skip self-referential offset
    cmp_sz  = struct.unpack_from('<q', hdr, pos)[0]; pos += 8
    unc_sz  = struct.unpack_from('<q', hdr, pos)[0]; pos += 8
    cmethod = struct.unpack_from('<I', hdr, pos)[0]; pos += 4
    pos    += 20                                              # skip sha1
    nblocks = struct.unpack_from('<I', hdr, pos)[0]; pos += 4

    blocks = []
    for _ in range(nblocks):
        bs, be = struct.unpack_from('<qq', hdr, pos); pos += 16
        blocks.append((bs, be))

    pos += 1  # bEncrypted
    if cmethod != 0:
        pos += 4  # CompressionBlockSize

    return cmp_sz, unc_sz, cmethod, blocks


def _read_index_v10(pak_path: str, idx_offset: int, idx_size: int
                    ) -> tuple[str, list[_PakEntryMeta]]:
    """
    Parse v10/v11 path-hash index.
    Structure: mount + num + seed + [path_hash_section] + [full_dir_section]
               + encoded_entries_TArray + files_num
    """
    # Read entire index into memory (up to ~6MB — feasible)
    with open(pak_path, 'rb') as fh:
        fh.seek(idx_offset)
        data = fh.read(idx_size)

    pos = 0
    mount, pos    = _read_fstring_mem(data, pos)
    num_entries   = struct.unpack_from('<i', data, pos)[0]; pos += 4
    pos          += 8   # PathHashSeed (uint64)

    has_path_hash = struct.unpack_from('<i', data, pos)[0]; pos += 4
    if has_path_hash:
        pos += 8 + 8 + 20   # PathHashIndexOffset + Size + Hash

    has_full_dir  = struct.unpack_from('<i', data, pos)[0]; pos += 4
    fd_offset = fd_size = 0
    if has_full_dir:
        fd_offset = struct.unpack_from('<q', data, pos)[0]; pos += 8
        fd_size   = struct.unpack_from('<q', data, pos)[0]; pos += 8
        pos      += 20   # FullDirIndexHash

    # EncodedPakEntries (TArray<uint8>)
    enc_count = struct.unpack_from('<i', data, pos)[0]; pos += 4
    enc_data  = data[pos: pos + enc_count]; pos += enc_count

    if not has_full_dir or fd_size == 0:
        return mount, []   # no directory index available

    # Read FullDirIndex: {dir_name: {file_name: entry_byte_offset}}
    with open(pak_path, 'rb') as fh:
        fh.seek(fd_offset)
        fd_data = fh.read(fd_size)

    fp = 0
    num_dirs = struct.unpack_from('<i', fd_data, fp)[0]; fp += 4
    entries: list[_PakEntryMeta] = []

    for _ in range(num_dirs):
        dir_name, fp = _read_fstring_mem(fd_data, fp)
        num_files    = struct.unpack_from('<i', fd_data, fp)[0]; fp += 4

        for _ in range(num_files):
            fname, fp    = _read_fstring_mem(fd_data, fp)
            entry_idx    = struct.unpack_from('<I', fd_data, fp)[0]; fp += 4
            full_path    = dir_name + fname

            ce = _decode_compact_entry(enc_data, entry_idx)
            if ce is None:
                continue

            entries.append(_PakEntryMeta(
                filename    = full_path,
                data_offset = ce['offset'],    # per-file-header base
                size        = ce['cmp_sz'],
                size_decom  = ce['unc_sz'],
                sha1        = b'\x00' * 20,
                comp_method = 1 if ce['method'] > 0 else 0,
                comp_blocks = [],              # parsed on-demand in extract_file
                v10         = True,
            ))

    return mount, entries


# ── Unified entry point ───────────────────────────────────────────────────────

def _read_index(pak_path: str) -> tuple[str, list[_PakEntryMeta]]:
    """Read pak index. Auto-detects footer size and index format."""
    with open(pak_path, 'rb') as fh:
        version, idx_offset, idx_size = _find_footer(fh)

    if version >= 10:
        return _read_index_v10(pak_path, idx_offset, idx_size)
    else:
        return _read_index_v3(pak_path, idx_offset, idx_size)


def list_files(pak_path: str) -> list[str]:
    """List all file paths inside a .pak file."""
    _, entries = _read_index(pak_path)
    return [e.filename for e in entries]


def extract_file(pak_path: str, target_filename: str) -> bytes | None:
    """
    Extract a single file from pak by filename.
    Handles both v3 (absolute block offsets) and v10+ (relative to per-file header).
    """
    _, entries = _read_index(pak_path)

    norm_target = target_filename.replace('\\', '/')
    entry = None
    for e in entries:
        norm = e.filename.replace('\\', '/')
        if norm == norm_target or norm.endswith('/' + norm_target):
            entry = e
            break

    if entry is None:
        return None

    # ── v10+ format: parse per-file header on demand ──────────────────────────
    if entry.v10:
        hdr_base = entry.data_offset
        cmp_sz, unc_sz, cmethod, blocks_rel = _parse_v10_per_file_header(pak_path, hdr_base)

        if cmethod == 0 or not blocks_rel:
            # Uncompressed — read data directly after header
            hdr_size = 53 + len(blocks_rel) * 16  # base + blocks (no block_size for method=0)
            with open(pak_path, 'rb') as fh:
                fh.seek(hdr_base + hdr_size)
                return fh.read(unc_sz)

        if cmethod == 1:   # Zlib
            out = bytearray()
            with open(pak_path, 'rb') as fh:
                for (bs_rel, be_rel) in blocks_rel:
                    fh.seek(hdr_base + bs_rel)
                    chunk = fh.read(be_rel - bs_rel)
                    try:
                        out += zlib.decompress(chunk)
                    except zlib.error:
                        out += chunk   # pass through if decompress fails
            return bytes(out)

        # Unknown compression — return raw compressed block data
        with open(pak_path, 'rb') as fh:
            fh.seek(hdr_base + blocks_rel[0][0])
            return fh.read(cmp_sz)

    # ── v3 format ─────────────────────────────────────────────────────────────
    with open(pak_path, 'rb') as fh:
        fh.seek(entry.data_offset)
        raw = fh.read(entry.size)

    if entry.comp_method == 0:
        return raw

    if entry.comp_method == 1:
        try:
            out = bytearray()
            with open(pak_path, 'rb') as fh:
                for (bs, be) in entry.comp_blocks:
                    fh.seek(bs)
                    chunk = fh.read(be - bs)
                    out += zlib.decompress(chunk)
            return bytes(out)
        except Exception:
            return raw

    return raw


def create_patch_pak(output_path: str,
                     files: dict[str, bytes],
                     mount_point: str = "../../../") -> None:
    """
    Create a _p.pak patch file (uncompressed, UE4 v3 format — exactly 44-byte footer).

    Per-file header layout (53 bytes, no compression):
        Offset(8) + Size(8) + UncompressedSize(8) + CompressionMethod(4)
        + Hash(20) + BlockCount(4) + Flags(1)
    The index entry mirrors the same layout.
    Footer = magic(4) + version(4) + idx_offset(8) + idx_size(8) + sha1(20) = 44 bytes.
    """
    entries_meta = []
    data_buf = bytearray()

    for fname, content in files.items():
        sha1       = hashlib.sha1(content).digest()
        fsize      = len(content)
        file_start = len(data_buf)  # absolute offset of per-file header

        # Per-file header — 53 bytes, correct UE4 v3 field order
        header = bytearray()
        header += struct.pack('<q', file_start)   # Offset (self-referential)
        header += struct.pack('<q', fsize)         # Size (compressed == uncompressed)
        header += struct.pack('<q', fsize)         # UncompressedSize
        header += struct.pack('<I', 0)             # CompressionMethod = NONE
        header += sha1                             # Hash — SHA1 of raw content (20 bytes)
        header += struct.pack('<I', 0)             # CompressionBlocks count = 0
        header += b'\x00'                          # Flags (bEncrypted = false)
        # CompressionBlockSize omitted — only present when method != 0

        data_buf += header   # exactly 53 bytes
        data_buf += content
        entries_meta.append((fname, file_start, fsize, sha1))

    # Build index — each entry mirrors the per-file header layout
    index = bytearray()
    mp_enc = (mount_point + '\x00').encode('latin-1')
    index += struct.pack('<i', len(mp_enc))
    index += mp_enc
    index += struct.pack('<i', len(entries_meta))

    for fname, file_start, fsize, sha1 in entries_meta:
        fn_enc = (fname + '\x00').encode('latin-1')
        index += struct.pack('<i', len(fn_enc))
        index += fn_enc
        index += struct.pack('<q', file_start)     # Offset = start of per-file header
        index += struct.pack('<q', fsize)
        index += struct.pack('<q', fsize)
        index += struct.pack('<I', 0)               # CompressionMethod = NONE
        index += sha1                               # Hash (20 bytes)
        index += struct.pack('<I', 0)               # BlockCount = 0
        index += b'\x00'                            # Flags

    idx_offset = len(data_buf)
    idx_sha1   = hashlib.sha1(index).digest()

    # UE4 v3 footer = exactly 44 bytes (NOT 48 — no padding!)
    # magic(4) + version(4) + idx_offset(8) + idx_size(8) + sha1(20)
    footer = bytearray()
    footer += struct.pack('<I', PAK_MAGIC)
    footer += struct.pack('<I', PAK_VERSION)   # = 3
    footer += struct.pack('<q', idx_offset)
    footer += struct.pack('<q', len(index))
    footer += idx_sha1

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(data_buf)
        f.write(index)
        f.write(footer)
