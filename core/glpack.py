"""
glpack.py — GameLang Pack format
Offline pre-translated string database.
Format: gzip-compressed JSON  (.glpack)
"""

import os
import json
import gzip
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

GLPACK_VERSION = "1.0"
GLPACK_DIR     = os.path.join(os.path.expanduser("~"), ".gamelang", "packs")


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class GLPackEntry:
    original:   str
    translated: str
    file:       str
    location:   str
    speaker:    Optional[str] = None
    register:   str   = "neutral"
    confidence: float = 1.0


@dataclass
class GLPack:
    game:         str
    game_id:      str
    engine:       str
    version:      str  = GLPACK_VERSION
    created_at:   str  = ""
    string_count: int  = 0
    strings:      dict = field(default_factory=dict)   # id → GLPackEntry

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    @property
    def translated_count(self) -> int:
        return sum(1 for e in self.strings.values() if e.translated)

    def pack_path(self) -> str:
        """Default save path"""
        return os.path.join(GLPACK_DIR, f"{self.game_id}.glpack")


# ── Writer ────────────────────────────────────────────────────────────────────
class GLPackWriter:
    @staticmethod
    def save(path: str, pack: GLPack):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        data = {
            "game":         pack.game,
            "game_id":      pack.game_id,
            "engine":       pack.engine,
            "version":      pack.version,
            "created_at":   pack.created_at,
            "string_count": len(pack.strings),
            "strings": {
                sid: {
                    "o": e.original,
                    "t": e.translated,
                    "f": e.file,
                    "l": e.location,
                    "s": e.speaker,
                    "r": e.register,
                    "c": e.confidence,
                }
                for sid, e in pack.strings.items()
            },
        }
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        with gzip.open(path, "wb") as f:
            f.write(raw.encode("utf-8"))


# ── Reader ────────────────────────────────────────────────────────────────────
class GLPackReader:
    @staticmethod
    def load(path: str) -> GLPack:
        with gzip.open(path, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))

        pack = GLPack(
            game       = data.get("game", ""),
            game_id    = data.get("game_id", ""),
            engine     = data.get("engine", ""),
            version    = data.get("version", GLPACK_VERSION),
            created_at = data.get("created_at", ""),
            string_count = data.get("string_count", 0),
        )
        for sid, e in data.get("strings", {}).items():
            pack.strings[sid] = GLPackEntry(
                original   = e.get("o", ""),
                translated = e.get("t", ""),
                file       = e.get("f", ""),
                location   = e.get("l", "unknown"),
                speaker    = e.get("s"),
                register   = e.get("r", "neutral"),
                confidence = e.get("c", 1.0),
            )
        return pack

    @staticmethod
    def checksum(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:16]

    @staticmethod
    def exists(game_id: str) -> bool:
        return os.path.exists(
            os.path.join(GLPACK_DIR, f"{game_id}.glpack")
        )

    @staticmethod
    def file_size_mb(path: str) -> float:
        try:
            return os.path.getsize(path) / 1_048_576
        except Exception:
            return 0.0


# ── Builder helper ────────────────────────────────────────────────────────────
def build_glpack(game: str, engine: str,
                 extracted: list,          # list[GameString]
                 translations: list[str],  # same order as extracted
                 registers: list[str] | None = None) -> GLPack:
    """
    Combine extracted GameStrings + translation results into a GLPack.
    extracted and translations must be the same length.
    """
    game_id = game.lower().replace(" ", "_")
    pack    = GLPack(game=game, game_id=game_id, engine=engine)

    for gs, th in zip(extracted, translations):
        reg = (registers or [])
        pack.strings[gs.id] = GLPackEntry(
            original   = gs.text,
            translated = th,
            file       = gs.file,
            location   = gs.location,
            speaker    = gs.speaker,
            register   = "neutral",
            confidence = 1.0,
        )

    pack.string_count = len(pack.strings)
    return pack
