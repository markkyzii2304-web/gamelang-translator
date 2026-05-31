"""
updater.py — GameLang Translator Auto-Updater
ตรวจสอบ GitHub Releases → ดาวน์โหลด installer → รันอัปเดตอัตโนมัติ
"""

import os
import sys
import json
import tempfile
import urllib.request
import urllib.error
from PyQt6.QtCore import QThread, pyqtSignal

# ── Constants ─────────────────────────────────────────────────────────────────
import os as _os
def _read_app_version() -> str:
    try:
        _here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        with open(_os.path.join(_here, "VERSION"), "r") as f:
            return f.read().strip()
    except Exception:
        return "2.0.0"

APP_VERSION = _read_app_version()
GITHUB_REPO = "markkyzii2304-web/gamelang-translator"
API_URL     = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
TIMEOUT_S   = 8
BLOCK_SIZE  = 65536   # 64 KB read chunks


# ── Version helpers ───────────────────────────────────────────────────────────
def _parse_version(v: str) -> tuple[int, ...]:
    """'v2.1.3' → (2, 1, 3)  |  กรณี error → (0, 0, 0)"""
    v = v.lstrip("v").strip()
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except Exception:
        return (0, 0, 0)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return _parse_version(remote) > _parse_version(local)


# ── Data class ────────────────────────────────────────────────────────────────
class UpdateInfo:
    def __init__(self, version: str, name: str, body: str,
                 download_url: str, size_bytes: int):
        self.version      = version       # "2.1.3"
        self.name         = name          # "GameLang Translator v2.1.3"
        self.body         = body          # release notes (markdown)
        self.download_url = download_url  # URL ของ .exe installer
        self.size_bytes   = size_bytes    # ขนาดไฟล์


# ── Blocking helper (ใช้ใน thread เท่านั้น) ──────────────────────────────────
def check_for_update() -> UpdateInfo | None:
    """
    ดึง GitHub Releases API แล้วเปรียบเทียบเวอร์ชัน
    คืน UpdateInfo ถ้ามีเวอร์ชันใหม่ | None ถ้าเป็นเวอร์ชันล่าสุดหรือเน็ตล่ม
    """
    try:
        req = urllib.request.Request(
            API_URL,
            headers={
                "User-Agent": f"GameLang-Updater/{APP_VERSION}",
                "Accept":     "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tag = data.get("tag_name", "")
        if not tag or not is_newer(tag):
            return None

        # หา .exe asset
        download_url = ""
        size_bytes   = 0
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.lower().endswith(".exe"):
                download_url = asset.get("browser_download_url", "")
                size_bytes   = asset.get("size", 0)
                break

        return UpdateInfo(
            version      = tag.lstrip("v"),
            name         = data.get("name", tag),
            body         = data.get("body", "").strip(),
            download_url = download_url,
            size_bytes   = size_bytes,
        )

    except Exception:
        return None


# ── UpdateChecker Thread ──────────────────────────────────────────────────────
class UpdateChecker(QThread):
    """ตรวจสอบ update ใน background — ไม่บล็อก UI"""
    update_available = pyqtSignal(object)   # UpdateInfo
    up_to_date       = pyqtSignal()

    def run(self):
        info = check_for_update()
        if info:
            self.update_available.emit(info)
        else:
            self.up_to_date.emit()


# ── UpdateDownloader Thread ───────────────────────────────────────────────────
class UpdateDownloader(QThread):
    """ดาวน์โหลด installer ใน background + emit progress"""
    progress = pyqtSignal(int, int)   # downloaded_bytes, total_bytes
    finished = pyqtSignal(str)        # path ไฟล์ (ว่าง = ล้มเหลว)
    error    = pyqtSignal(str)        # ข้อความ error

    def __init__(self, url: str, size_bytes: int = 0):
        super().__init__()
        self.url        = url
        self.size_bytes = size_bytes

    def run(self):
        try:
            tmp = tempfile.mktemp(suffix=".exe", prefix="gamelang_update_")
            req = urllib.request.Request(
                self.url,
                headers={"User-Agent": f"GameLang-Updater/{APP_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp, \
                 open(tmp, "wb") as f:
                total      = int(resp.headers.get("Content-Length", 0) or self.size_bytes)
                downloaded = 0
                while True:
                    chunk = resp.read(BLOCK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    self.progress.emit(downloaded, total)
            self.finished.emit(tmp)

        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit("")


# ── Launcher ──────────────────────────────────────────────────────────────────
def launch_installer_and_quit(installer_path: str):
    """
    รัน installer ที่ดาวน์โหลดมา แล้วปิด app ปัจจุบัน
    Inno Setup installer จะอัปเดตไฟล์แล้วเปิด app ใหม่อัตโนมัติ
    """
    import subprocess
    try:
        # /SILENT = ไม่ถาม / CLOSEAPPLICATIONS = ปิด process เก่า
        subprocess.Popen(
            [installer_path, "/VERYSILENT", "/CLOSEAPPLICATIONS",
             "/RESTARTAPPLICATIONS", "/NORESTART"],
            close_fds=True,
        )
    except Exception:
        # fallback: shell=True
        subprocess.Popen(installer_path, shell=True)
    sys.exit(0)
