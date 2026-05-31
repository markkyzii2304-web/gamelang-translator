"""
pak_handler.py — UE4 Pak file handler (pure Python)
Extract files from .pak and create patch _p.pak
"""
import os, struct, zlib, io
from dataclasses import dataclass

PAK_MAGIC   = 0x5A6F12E1
PAK_VERSION = 3

@dataclass
class PakEntry:
    filename:     str
    offset:       int
    size:         int
    size_decom:   int
    sha1:         bytes
    compressed:   bool = False
    data:         bytes = b""


def _read_fstring_pak(data: bytes, pos: int) -> tuple[str, int]:
    length = struct.unpack_from('<i', data, pos)[0]; pos += 4
    if length == 0:
        return ("", pos)
    if length < 0:
        byte_count = (-length) * 2
        text = data[pos:pos+byte_count-2].decode('utf-16-le', errors='replace')
        pos += byte_count
    else:
        text = data[pos:pos+length-1].decode('latin-1', errors='replace')
        pos += length
    return (text, pos)


def list_files(pak_path: str) -> list[str]:
    """List all file paths inside a .pak file"""
    with open(pak_path, 'rb') as f:
        data = f.read()

    size = len(data)
    # Footer: 44 bytes from end
    footer_pos = size - 44
    magic   = struct.unpack_from('<I', data, footer_pos)[0]
    if magic != PAK_MAGIC:
        raise ValueError("Not a valid UE4 pak file")

    version     = struct.unpack_from('<I', data, footer_pos+4)[0]
    idx_offset  = struct.unpack_from('<q', data, footer_pos+8)[0]
    idx_size    = struct.unpack_from('<q', data, footer_pos+16)[0]

    idx = idx_offset
    mount, idx = _read_fstring_pak(data, idx)
    file_count = struct.unpack_from('<i', data, idx)[0]; idx += 4

    files = []
    for _ in range(file_count):
        fname, idx = _read_fstring_pak(data, idx)
        idx += 8 + 8 + 8 + 20  # offset + size + size_decom + sha1
        comp_method = struct.unpack_from('<I', data, idx)[0]; idx += 4
        encrypted   = data[idx]; idx += 1
        comp_block_size = struct.unpack_from('<I', data, idx)[0]; idx += 4
        if comp_method != 0:
            block_count = struct.unpack_from('<I', data, idx)[0]; idx += 4
            idx += block_count * 16  # comp blocks
        files.append(fname)
    return files


def extract_file(pak_path: str, target_filename: str) -> bytes | None:
    """Extract a single file from pak by filename. Returns raw bytes or None."""
    with open(pak_path, 'rb') as f:
        data = f.read()

    size = len(data)
    footer_pos = size - 44
    magic = struct.unpack_from('<I', data, footer_pos)[0]
    if magic != PAK_MAGIC:
        return None

    idx_offset = struct.unpack_from('<q', data, footer_pos+8)[0]
    idx = idx_offset
    mount, idx = _read_fstring_pak(data, idx)
    file_count = struct.unpack_from('<i', data, idx)[0]; idx += 4

    for _ in range(file_count):
        fname, idx = _read_fstring_pak(data, idx)
        offset    = struct.unpack_from('<q', data, idx)[0]; idx += 8
        fsize     = struct.unpack_from('<q', data, idx)[0]; idx += 8
        fsize_d   = struct.unpack_from('<q', data, idx)[0]; idx += 8
        sha1      = data[idx:idx+20]; idx += 20
        comp_method = struct.unpack_from('<I', data, idx)[0]; idx += 4
        encrypted   = data[idx]; idx += 1
        comp_block_size = struct.unpack_from('<I', data, idx)[0]; idx += 4
        comp_blocks = []
        if comp_method != 0:
            block_count = struct.unpack_from('<I', data, idx)[0]; idx += 4
            for _ in range(block_count):
                bs = struct.unpack_from('<qq', data, idx); idx += 16
                comp_blocks.append(bs)

        norm_fname = fname.replace('\\', '/')
        norm_target = target_filename.replace('\\', '/')
        if norm_fname == norm_target or norm_fname.endswith('/' + norm_target):
            # Read file data
            # Each file entry in pak has its own mini-header before data
            entry_pos = offset
            # Skip per-entry header (same structure but without filename)
            entry_pos += 8 + 8 + 8 + 20 + 4 + 1 + 4  # offset+size+sized+sha1+comp+enc+blocksize
            if comp_method != 0:
                bc = struct.unpack_from('<I', data, entry_pos)[0]; entry_pos += 4
                entry_pos += bc * 16

            raw = data[entry_pos:entry_pos + fsize]
            if comp_method == 0:
                return raw
            else:
                # Decompress zlib blocks
                out = bytearray()
                for (bs, be) in comp_blocks:
                    chunk = data[bs:be]
                    out += zlib.decompress(chunk)
                return bytes(out)
    return None


def create_patch_pak(output_path: str,
                     files: dict[str, bytes],
                     mount_point: str = "../../../") -> None:
    """
    Create a _p.pak patch file.
    files: {relative_path: raw_bytes}
    """
    import hashlib

    entries = []
    data_buf = bytearray()

    for fname, content in files.items():
        offset = len(data_buf)
        sha1 = hashlib.sha1(content).digest()
        fsize = len(content)

        # Per-file entry header in data section
        entry_header = bytearray()
        entry_header += struct.pack('<q', offset + _calc_entry_header_size(fname))  # will patch
        entry_header += struct.pack('<q', fsize)
        entry_header += struct.pack('<q', fsize)   # size_decom = size (uncompressed)
        entry_header += sha1
        entry_header += struct.pack('<I', 0)  # compression = NONE
        entry_header += b'\x00'               # not encrypted
        entry_header += struct.pack('<I', 0)  # block size

        actual_offset = len(data_buf) + len(entry_header)
        data_buf += entry_header
        data_buf += content

        entries.append((fname, offset, fsize, fsize, sha1))

    # Build index
    index = bytearray()
    # Mount point
    mp = (mount_point + '\x00').encode('latin-1')
    index += struct.pack('<i', len(mp))
    index += mp
    # File count
    index += struct.pack('<i', len(entries))

    for fname, offset, fsize, fsize_d, sha1 in entries:
        fn = (fname + '\x00').encode('latin-1')
        index += struct.pack('<i', len(fn))
        index += fn
        # Find actual offset of content (after per-file header)
        content_offset = offset + 8+8+8+20+4+1+4  # entry header size
        index += struct.pack('<q', content_offset)
        index += struct.pack('<q', fsize)
        index += struct.pack('<q', fsize_d)
        index += sha1
        index += struct.pack('<I', 0)   # compression NONE
        index += b'\x00'                # not encrypted
        index += struct.pack('<I', 0)   # block size

    import hashlib
    idx_offset = len(data_buf)
    idx_sha1   = hashlib.sha1(index).digest()

    # Footer
    footer = bytearray()
    footer += struct.pack('<I', PAK_MAGIC)
    footer += struct.pack('<I', PAK_VERSION)
    footer += struct.pack('<q', idx_offset)
    footer += struct.pack('<q', len(index))
    footer += idx_sha1
    footer += b'\x00' * 4  # padding to 44 bytes (sha1=20, we need 20 more)

    with open(output_path, 'wb') as f:
        f.write(data_buf)
        f.write(index)
        f.write(footer)


def _calc_entry_header_size(fname: str) -> int:
    return 8+8+8+20+4+1+4  # fixed size without filename (per-file data header)
