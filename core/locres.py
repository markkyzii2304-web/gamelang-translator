"""
locres.py — Unreal Engine 4 Localization Resource parser
อ่านและเขียน .locres binary files
"""
import struct
from dataclasses import dataclass, field

LOCRES_MAGIC_1 = 0x7574F4CF
LOCRES_MAGIC_2 = 0x4B4946A4

@dataclass
class LocresEntry:
    namespace: str
    key:       str
    translation: str
    key_hash:  int = 0
    ns_hash:   int = 0

@dataclass
class LocresFile:
    version:  int = 3
    entries:  list = field(default_factory=list)  # list[LocresEntry]


def _read_fstring(data: bytes, pos: int) -> tuple[str, int]:
    """Read UE4 FString: int32 length + chars. Negative = UTF-16."""
    length = struct.unpack_from('<i', data, pos)[0]; pos += 4
    if length == 0:
        return ("", pos)
    if length < 0:
        # UTF-16 LE
        byte_count = (-length - 1) * 2
        text = data[pos:pos+byte_count].decode('utf-16-le', errors='replace')
        pos += byte_count + 2  # +2 for null terminator
    else:
        # ASCII/Latin-1
        text = data[pos:pos+length-1].decode('latin-1', errors='replace')
        pos += length
    return (text, pos)


def _write_fstring(text: str) -> bytes:
    """Write UE4 FString."""
    if not text:
        return struct.pack('<i', 0)
    # Check if needs UTF-16
    try:
        encoded = text.encode('ascii') + b'\x00'
        return struct.pack('<i', len(encoded)) + encoded
    except UnicodeEncodeError:
        encoded = text.encode('utf-16-le') + b'\x00\x00'
        char_count = -(len(encoded) // 2)
        return struct.pack('<i', char_count) + encoded


def _crc32_ci(s: str) -> int:
    """UE4 case-insensitive CRC32 for string hashing."""
    import binascii
    return binascii.crc32(s.upper().encode('utf-16-le')) & 0xFFFFFFFF


def load(data: bytes) -> LocresFile:
    """Parse .locres binary data → LocresFile"""
    pos = 0
    lf = LocresFile()

    # Magic
    m1 = struct.unpack_from('<I', data, pos)[0]; pos += 4
    if m1 != LOCRES_MAGIC_1:
        raise ValueError(f"Bad magic: {m1:#010x}")

    m2 = struct.unpack_from('<I', data, pos)[0]; pos += 4
    if m2 == LOCRES_MAGIC_2:
        # New format (version byte follows)
        lf.version = data[pos]; pos += 1
    else:
        # Old format — reset pos
        lf.version = 0
        pos = 4

    if lf.version >= 2:
        # String array (shared string pool)
        string_count = struct.unpack_from('<i', data, pos)[0]; pos += 4
        strings = []
        for _ in range(string_count):
            s, pos = _read_fstring(data, pos)
            _hash = struct.unpack_from('<I', data, pos)[0]; pos += 4
            strings.append(s)

        # Namespace table
        ns_count = struct.unpack_from('<i', data, pos)[0]; pos += 4
        for _ in range(ns_count):
            ns_hash = struct.unpack_from('<I', data, pos)[0]; pos += 4
            ns_idx  = struct.unpack_from('<i', data, pos)[0]; pos += 4
            namespace = strings[ns_idx] if 0 <= ns_idx < len(strings) else ""

            entry_count = struct.unpack_from('<i', data, pos)[0]; pos += 4
            for _ in range(entry_count):
                key_hash = struct.unpack_from('<I', data, pos)[0]; pos += 4
                key_idx  = struct.unpack_from('<i', data, pos)[0]; pos += 4
                key = strings[key_idx] if 0 <= key_idx < len(strings) else ""
                translation, pos = _read_fstring(data, pos)
                if lf.version >= 3:
                    pos += 4  # source string hash
                lf.entries.append(LocresEntry(
                    namespace=namespace, key=key,
                    translation=translation,
                    key_hash=key_hash, ns_hash=ns_hash,
                ))
    else:
        # Version 1 format
        ns_count = struct.unpack_from('<i', data, pos)[0]; pos += 4
        for _ in range(ns_count):
            namespace, pos = _read_fstring(data, pos)
            key_count = struct.unpack_from('<i', data, pos)[0]; pos += 4
            for _ in range(key_count):
                key, pos = _read_fstring(data, pos)
                translation, pos = _read_fstring(data, pos)
                lf.entries.append(LocresEntry(namespace=namespace, key=key, translation=translation))

    return lf


def dump(lf: LocresFile, version: int = 3) -> bytes:
    """Serialize LocresFile → .locres binary bytes"""
    out = bytearray()

    # Magic + version
    out += struct.pack('<I', LOCRES_MAGIC_1)
    out += struct.pack('<I', LOCRES_MAGIC_2)
    out += bytes([version])

    if version >= 2:
        # Build string pool
        all_strings = []
        seen = {}
        def intern(s):
            if s not in seen:
                seen[s] = len(all_strings)
                all_strings.append(s)
            return seen[s]

        # Collect namespaces + keys
        ns_map = {}  # namespace → list of (key, translation, key_hash)
        for e in lf.entries:
            intern(e.namespace)
            intern(e.key)
            ns_map.setdefault(e.namespace, []).append(e)

        # Write string pool
        out += struct.pack('<i', len(all_strings))
        for s in all_strings:
            out += _write_fstring(s)
            out += struct.pack('<I', _crc32_ci(s))

        # Write namespace table
        out += struct.pack('<i', len(ns_map))
        for ns, entries in ns_map.items():
            ns_hash = _crc32_ci(ns)
            ns_idx  = seen[ns]
            out += struct.pack('<I', ns_hash)
            out += struct.pack('<i', ns_idx)
            out += struct.pack('<i', len(entries))
            for e in entries:
                key_hash = _crc32_ci(e.key)
                key_idx  = seen[e.key]
                out += struct.pack('<I', key_hash)
                out += struct.pack('<i', key_idx)
                out += _write_fstring(e.translation)
                if version >= 3:
                    out += struct.pack('<I', _crc32_ci(e.translation))
    else:
        # Version 1
        ns_map = {}
        for e in lf.entries:
            ns_map.setdefault(e.namespace, []).append(e)
        out += struct.pack('<i', len(ns_map))
        for ns, entries in ns_map.items():
            out += _write_fstring(ns)
            out += struct.pack('<i', len(entries))
            for e in entries:
                out += _write_fstring(e.key)
                out += _write_fstring(e.translation)

    return bytes(out)


def to_dict(lf: LocresFile) -> dict[str, dict[str, str]]:
    """Convert to {namespace: {key: translation}} dict"""
    result = {}
    for e in lf.entries:
        result.setdefault(e.namespace, {})[e.key] = e.translation
    return result


def from_dict(d: dict[str, dict[str, str]], version: int = 3) -> LocresFile:
    """Build LocresFile from {namespace: {key: translation}} dict"""
    lf = LocresFile(version=version)
    for ns, keys in d.items():
        for key, trans in keys.items():
            lf.entries.append(LocresEntry(namespace=ns, key=key, translation=trans))
    return lf
