"""
rollback.py
จัดการ backup และ restore ไฟล์เกมที่ถูก patch
รองรับ full restore และ partial restore แบบเลือกไฟล์
"""

import os
import json
import shutil
from datetime import datetime
from dataclasses import dataclass, field, asdict


MANIFEST_NAME = ".gamelang_manifest.json"


@dataclass
class BackupEntry:
    original_path: str     # path ไฟล์จริงในเกม
    backup_path:   str     # path ไฟล์ .bak
    patch_method:  str     # วิธีที่ใช้ patch
    patched_at:    str     # timestamp
    file_size:     int     # ขนาดไฟล์ต้นฉบับ (bytes)
    checksum:      str     # sha256 ของไฟล์ต้นฉบับ


@dataclass
class PatchManifest:
    game_name:    str
    game_dir:     str
    glpack_id:    str
    patched_at:   str
    entries:      list[BackupEntry] = field(default_factory=list)
    font_injected: bool = False
    font_paths:   list[str] = field(default_factory=list)


class RollbackManager:
    """จัดการ backup manifest และ restore ไฟล์"""

    def __init__(self, game_dir: str, game_name: str):
        self.game_dir    = game_dir
        self.game_name   = game_name
        self.manifest_path = os.path.join(game_dir, MANIFEST_NAME)
        self.manifest    = self._load_manifest()

    # ── Backup ────────────────────────────────────────────────────────────────
    def begin_patch(self, glpack_id: str) -> PatchManifest:
        """เริ่มต้น patch session ใหม่"""
        self.manifest = PatchManifest(
            game_name  = self.game_name,
            game_dir   = self.game_dir,
            glpack_id  = glpack_id,
            patched_at = datetime.now().isoformat(),
        )
        return self.manifest

    def backup_file(self, file_path: str, patch_method: str) -> str:
        """สำรองไฟล์ก่อน patch — คืน path ของ .bak"""
        bak_path = file_path + ".gamelang.bak"
        if not os.path.exists(file_path):
            return bak_path

        checksum = _sha256(file_path)
        shutil.copy2(file_path, bak_path)

        entry = BackupEntry(
            original_path = file_path,
            backup_path   = bak_path,
            patch_method  = patch_method,
            patched_at    = datetime.now().isoformat(),
            file_size     = os.path.getsize(file_path),
            checksum      = checksum,
        )
        self.manifest.entries.append(entry)
        return bak_path

    def record_font(self, font_paths: list[str]):
        """บันทึก font ที่ inject"""
        self.manifest.font_injected = True
        self.manifest.font_paths = font_paths

    def save_manifest(self):
        """บันทึก manifest ลงไฟล์"""
        data = {
            "game_name":     self.manifest.game_name,
            "game_dir":      self.manifest.game_dir,
            "glpack_id":     self.manifest.glpack_id,
            "patched_at":    self.manifest.patched_at,
            "font_injected": self.manifest.font_injected,
            "font_paths":    self.manifest.font_paths,
            "entries": [
                {
                    "original_path": e.original_path,
                    "backup_path":   e.backup_path,
                    "patch_method":  e.patch_method,
                    "patched_at":    e.patched_at,
                    "file_size":     e.file_size,
                    "checksum":      e.checksum,
                }
                for e in self.manifest.entries
            ]
        }
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── Restore ───────────────────────────────────────────────────────────────
    def has_backup(self) -> bool:
        return os.path.exists(self.manifest_path)

    def get_backup_info(self) -> dict:
        """ดึงข้อมูล backup สำหรับแสดงใน UI"""
        if not self.has_backup():
            return {}
        return {
            "patched_at":    self.manifest.patched_at,
            "glpack_id":     self.manifest.glpack_id,
            "file_count":    len(self.manifest.entries),
            "font_injected": self.manifest.font_injected,
        }

    def restore_all(self, progress=None) -> tuple[int, list[str]]:
        """
        Full restore — คืนทุกไฟล์กลับสู่สถานะเดิม
        คืนค่า (จำนวนไฟล์ที่กู้คืน, รายการ error)
        """
        log = progress or (lambda m: None)
        restored, errors = 0, []

        for entry in self.manifest.entries:
            try:
                if os.path.exists(entry.backup_path):
                    shutil.copy2(entry.backup_path, entry.original_path)
                    os.remove(entry.backup_path)
                    log(f"คืนค่า: {os.path.basename(entry.original_path)}")
                    restored += 1
                else:
                    errors.append(f"ไม่พบ backup: {entry.backup_path}")
            except Exception as e:
                errors.append(f"{entry.original_path}: {e}")

        # ลบ font ที่ inject
        if self.manifest.font_injected:
            for fp in self.manifest.font_paths:
                try:
                    if os.path.exists(fp):
                        os.remove(fp)
                        log(f"ลบ font: {os.path.basename(fp)}")
                except Exception as e:
                    errors.append(f"ลบ font ล้มเหลว: {e}")

        # ลบ tmp font folder
        tmp = os.path.join(self.game_dir, "_gamelang_font_tmp")
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)

        # ลบ manifest
        if os.path.exists(self.manifest_path):
            os.remove(self.manifest_path)

        log(f"กู้คืนสำเร็จ {restored} ไฟล์")
        return restored, errors

    def restore_partial(self, file_paths: list[str],
                        progress=None) -> tuple[int, list[str]]:
        """
        Partial restore — คืนเฉพาะไฟล์ที่เลือก
        """
        log = progress or (lambda m: None)
        restored, errors = 0, []
        selected = set(file_paths)

        for entry in self.manifest.entries:
            if entry.original_path not in selected:
                continue
            try:
                if os.path.exists(entry.backup_path):
                    shutil.copy2(entry.backup_path, entry.original_path)
                    os.remove(entry.backup_path)
                    self.manifest.entries.remove(entry)
                    log(f"คืนค่า: {os.path.basename(entry.original_path)}")
                    restored += 1
                else:
                    errors.append(f"ไม่พบ backup: {entry.backup_path}")
            except Exception as e:
                errors.append(f"{entry.original_path}: {e}")

        self.save_manifest()
        return restored, errors

    # ── Internal ──────────────────────────────────────────────────────────────
    def _load_manifest(self) -> PatchManifest:
        if not os.path.exists(self.manifest_path):
            return PatchManifest("", self.game_dir, "", "")
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            m = PatchManifest(
                game_name    = data.get("game_name", ""),
                game_dir     = data.get("game_dir", self.game_dir),
                glpack_id    = data.get("glpack_id", ""),
                patched_at   = data.get("patched_at", ""),
                font_injected= data.get("font_injected", False),
                font_paths   = data.get("font_paths", []),
            )
            for e in data.get("entries", []):
                m.entries.append(BackupEntry(**e))
            return m
        except Exception:
            return PatchManifest("", self.game_dir, "", "")


def _sha256(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
