"""
pak_handler.py — UE4 Pak file handler (pure Python, seek-based)
"""
import os, struct, zlib, hashlib
from dataclasses import dataclass, field

PAK_MAGIC   = 0x5A6F12E1
PAK_VERSION = 3


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


@dataclass
class _PakEntryMeta:
    filename:    str
    data_offset: int    # offset of actual file data in pak
    size:        int    # compressed size
    size_decom:  int    # decompressed size
    sha1:        bytes
    comp_method: int    # 0=none, 1=zlib, others=oodle etc
    comp_blocks: list = field(default_factory=list)  # [(start,end), ...]


def _read_index(pak_path: str) -> tuple[str, list[_PakEntryMeta]]:
    """Read pak index. Returns (mount_point, list of entry metadata)."""
    with open(pak_path, 'rb') as fh:
        # Read footer (last 44 bytes)
        fh.seek(-44, 2)
        magic   = struct.unpack('<I', fh.read(4))[0]
        if magic != PAK_MAGIC:
            raise ValueError(f"Not a valid UE4 pak (magic={magic:#010x})")
        version    = struct.unpack('<I', fh.read(4))[0]
        idx_offset = struct.unpack('<q', fh.read(8))[0]
        idx_size   = struct.unpack('<q', fh.read(8))[0]

        # Read index
        fh.seek(idx_offset)
        mount = _read_fstring_fh(fh)
        file_count = struct.unpack('<i', fh.read(4))[0]

        entries = []
        for _ in range(file_count):
            fname = _read_fstring_fh(fh)

            offset      = struct.unpack('<q', fh.read(8))[0]
            size        = struct.unpack('<q', fh.read(8))[0]
            size_decom  = struct.unpack('<q', fh.read(8))[0]
            sha1        = fh.read(20)
            comp_method = struct.unpack('<I', fh.read(4))[0]
            encrypted   = struct.unpack('B', fh.read(1))[0]
            block_size  = struct.unpack('<I', fh.read(4))[0]

            comp_blocks = []
            if comp_method != 0:
                block_count = struct.unpack('<I', fh.read(4))[0]
                for _ in range(block_count):
                    bs, be = struct.unpack('<qq', fh.read(16))
                    comp_blocks.append((bs, be))

            # Each file in pak has a per-file mini-header before data
            # Size: offset(8)+size(8)+size_decom(8)+sha1(20)+comp(4)+enc(1)+blocksize(4) = 53
            # + optional comp_blocks
            per_file_header = 53 + len(comp_blocks) * 16
            if comp_method != 0:
                per_file_header += 4  # block_count field

            data_offset = offset + per_file_header

            entries.append(_PakEntryMeta(
                filename=fname,
                data_offset=data_offset,
                size=size,
                size_decom=size_decom,
                sha1=sha1,
                comp_method=comp_method,
                comp_blocks=comp_blocks,
            ))

    return mount, entries


def list_files(pak_path: str) -> list[str]:
    """List all file paths inside a .pak file (seek-based, no full load)."""
    _, entries = _read_index(pak_path)
    return [e.filename for e in entries]


def extract_file(pak_path: str, target_filename: str) -> bytes | None:
    """
    Extract a single file from pak by filename.
    Seek-based — works on multi-GB paks without loading everything.
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

    with open(pak_path, 'rb') as fh:
        fh.seek(entry.data_offset)
        raw = fh.read(entry.size)

    if entry.comp_method == 0:
        return raw

    # Zlib decompression (method 1 = zlib)
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
            return raw  # return compressed if decompress fails

    # Other compression (oodle etc) — return raw, caller handles
    return raw


def create_patch_pak(output_path: str,
                     files: dict[str, bytes],
                     mount_point: str = "../../../") -> None:
    """Create a _p.pak patch file with given files (uncompressed)."""
    entries_meta = []
    data_buf = bytearray()

    for fname, content in files.items():
        sha1 = hashlib.sha1(content).digest()
        fsize = len(content)

        # Per-file entry header (no compression)
        # We'll write: offset(8)+size(8)+size_decom(8)+sha1(20)+comp(4)+enc(1)+blocksize(4)
        per_header_size = 8 + 8 + 8 + 20 + 4 + 1 + 4  # = 53
        file_start = len(data_buf)
        data_offset = file_start + per_header_size

        header = bytearray()
        header += struct.pack('<q', data_offset)   # offset of data
        header += struct.pack('<q', fsize)          # compressed size
        header += struct.pack('<q', fsize)          # decompressed size
        header += sha1                              # sha1
        header += struct.pack('<I', 0)              # compression = NONE
        header += b'\x00'                           # not encrypted
        header += struct.pack('<I', 0)              # block size

        data_buf += header
        data_buf += content
        entries_meta.append((fname, file_start, fsize, sha1))

    # Build index
    index = bytearray()
    mp_enc = (mount_point + '\x00').encode('latin-1')
    index += struct.pack('<i', len(mp_enc))
    index += mp_enc
    index += struct.pack('<i', len(entries_meta))

    for fname, file_start, fsize, sha1 in entries_meta:
        fn_enc = (fname + '\x00').encode('latin-1')
        index += struct.pack('<i', len(fn_enc))
        index += fn_enc
        # data_offset as stored in index = file_start + 53 (per-file header size)
        index += struct.pack('<q', file_start + 53)
        index += struct.pack('<q', fsize)
        index += struct.pack('<q', fsize)
        index += sha1
        index += struct.pack('<I', 0)   # NONE compression
        index += b'\x00'                # not encrypted
        index += struct.pack('<I', 0)   # block size

    idx_offset = len(data_buf)
    idx_sha1   = hashlib.sha1(index).digest()

    footer = bytearray()
    footer += struct.pack('<I', PAK_MAGIC)
    footer += struct.pack('<I', PAK_VERSION)
    footer += struct.pack('<q', idx_offset)
    footer += struct.pack('<q', len(index))
    footer += idx_sha1
    footer += b'\x00' * 4  # pad to 44 bytes total

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(data_buf)
        f.write(index)
        f.write(footer)
