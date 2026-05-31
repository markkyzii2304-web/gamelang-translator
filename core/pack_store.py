"""
pack_store.py — Community Translation Pack Store
ดึง packs.json manifest จาก GitHub raw → แสดงรายการ → download .glpack

Rules:
- Manifest URL ชี้ไปที่ main branch (ไม่ใช่ releases API) → ไม่กระทบ auto-update
- Pack releases ใช้ tag "pack-*" (ห้ามใช้ "v*") → ไม่ทริก app build workflow
- Apply path ไม่ต้องการ API key — ใช้ GLPackPatcher / UE4PakPatcher โดยตรง
"""

import os
import json
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

# ── Constants ─────────────────────────────────────────────────────────────────
MANIFEST_URL = (
    "https://raw.githubusercontent.com/"
    "markkyzii2304-web/gamelang-translator/main/packs.json"
)
TIMEOUT_S  = 8
BLOCK_SIZE = 65536   # 64 KB


# ── Data class ────────────────────────────────────────────────────────────────
@dataclass
class PackInfo:
    game_id:      str    # "wandering_sword"  (lowercase + underscore)
    game_name:    str    # "Wandering Sword"
    language:     str    # "th"
    source_lang:  str    # "zh-Hans"
    string_count: int
    size_bytes:   int
    download_url: str
    pack_version: str
    description:  str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────
def fetch_manifest() -> list[PackInfo]:
    """
    Download packs.json from GitHub main branch.
    Returns [] on any error (network down, 404, parse error).
    Does NOT touch GitHub Releases API — no collision with app updater.
    """
    try:
        req = urllib.request.Request(
            MANIFEST_URL,
            headers={"User-Agent": "GameLang-PackStore/1.0"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        packs: list[PackInfo] = []
        for entry in data.get("packs", []):
            packs.append(PackInfo(
                game_id      = entry["game_id"],
                game_name    = entry["game_name"],
                language     = entry.get("language", "th"),
                source_lang  = entry.get("source_lang", ""),
                string_count = entry.get("string_count", 0),
                size_bytes   = entry.get("size_bytes", 0),
                download_url = entry["download_url"],
                pack_version = entry.get("pack_version", "1.0"),
                description  = entry.get("description", ""),
            ))
        return packs

    except Exception:
        return []


def find_pack(manifest: list[PackInfo], game_name: str) -> Optional[PackInfo]:
    """
    หา pack ที่ตรงกับ game_name
    ใช้ key เดียวกับที่ GLPack/SmartTranslator ใช้: lowercase + replace spaces with _
    """
    game_id = game_name.lower().replace(" ", "_")
    for p in manifest:
        if p.game_id == game_id:
            return p
    return None


def size_str(size_bytes: int) -> str:
    """แปลง bytes → "2.1 MB" หรือ "850 KB" """
    if size_bytes >= 1_048_576:
        return f"{size_bytes / 1_048_576:.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes // 1024} KB"
    return f"{size_bytes} B"


# ── Workers ───────────────────────────────────────────────────────────────────
class PackFetchWorker(QThread):
    """Fetch packs.json manifest in background — ไม่บล็อก UI"""
    finished = pyqtSignal(list)  # list[PackInfo]

    def run(self):
        manifest = fetch_manifest()
        self.finished.emit(manifest)


class PackDownloadWorker(QThread):
    """
    Download .glpack file in background.
    Saves to ~/.gamelang/packs/{game_id}.glpack
    """
    progress = pyqtSignal(int, int)   # downloaded_bytes, total_bytes
    finished = pyqtSignal(str)        # local file path (empty string = failed)
    error    = pyqtSignal(str)        # error message

    def __init__(self, pack: PackInfo):
        super().__init__()
        self.pack = pack

    def run(self):
        try:
            from core.glpack import GLPACK_DIR
            os.makedirs(GLPACK_DIR, exist_ok=True)
            dest = os.path.join(GLPACK_DIR, f"{self.pack.game_id}.glpack")

            req = urllib.request.Request(
                self.pack.download_url,
                headers={"User-Agent": "GameLang-PackStore/1.0"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp, \
                 open(dest, "wb") as f:
                total      = int(resp.headers.get("Content-Length", 0)
                                 or self.pack.size_bytes)
                downloaded = 0
                while True:
                    chunk = resp.read(BLOCK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    self.progress.emit(downloaded, total)

            self.finished.emit(dest)

        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit("")
