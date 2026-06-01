"""
main.py — GameLang Translator v2
PyQt6 Desktop App | Pre-translate full game before playing
"""

import sys
import os
import json
import threading
import time

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QStackedWidget,
    QDialog, QScrollArea, QFrame, QFileDialog, QMessageBox, QProgressBar,
    QSizeGrip, QLineEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer, QRectF
from PyQt6.QtGui import (QPixmap, QColor, QPalette, QIcon,
                          QPainter, QLinearGradient, QFont, QPen)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

from core.engine_detector import detect, PatchMethod, Engine, DetectionResult
from core.font_bundle import check_and_inject
from core.rollback import RollbackManager
from core.extractor import extract_all, to_smart_translator_input, GameString
from core.glpack import (GLPack, GLPackWriter, GLPackReader,
                          build_glpack, merge_glpacks,
                          GLPackCheckpoint, GLPACK_DIR,
                          CHECKPOINT_EVERY)
from core.updater import (APP_VERSION, UpdateChecker, UpdateDownloader,
                          launch_installer_and_quit, UpdateInfo)
from core.pack_store import (PackFetchWorker, PackDownloadWorker,
                              find_pack, size_str, PackInfo)
from core.library import (load_library, save_library,
                           add_game, remove_game, make_entry)
from core.pack_uploader import PackUploadWorker

# ── Config helpers (GitHub token) ─────────────────────────────────────────────
_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".gamelang", "config.json")

def _load_config() -> dict:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_config(data: dict):
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── Theme ─────────────────────────────────────────────────────────────────────
NV_GREEN  = "#6b9eff"
NV_BG     = "#090912"
NV_PANEL  = "#0f0f1e"
NV_BORDER = "#1e1e38"
NV_TEXT   = "#e2e4f0"
NV_MUTED  = "#7880a8"
NV_LABEL  = "#5060a0"
NV_RED    = "#f06292"
NV_CYAN   = "#38bdf8"
NV_PURPLE = "#a78bfa"

STYLESHEET = f"""
QMainWindow, QWidget {{ background:{NV_BG}; color:{NV_TEXT};
  font-family:'Segoe UI',sans-serif; font-size:13px; }}
QWidget#mainRoot {{ border:1px solid #1e1e3a; }}
QLabel {{ color:{NV_TEXT}; }}
QPushButton {{
  background:transparent; border:1px solid #1e1e38; color:#4a5280;
  border-radius:2px; padding:7px 18px;
  font-size:10px; letter-spacing:2px; font-weight:bold; }}
QPushButton:enabled {{ border-color:{NV_GREEN}; color:{NV_GREEN};
  background:rgba(91,141,238,0.08); }}
QPushButton:enabled:hover {{ background:{NV_GREEN}; color:#fff; }}
QPushButton:disabled {{ border-color:#1e1e38; color:#3a3a58; }}
QListWidget {{ background:{NV_PANEL}; border:none; outline:none; color:{NV_TEXT}; }}
QListWidget::item {{ padding:8px 12px; border-left:2px solid transparent; }}
QListWidget::item:selected {{
  background:rgba(91,141,238,0.1); border-left:2px solid {NV_GREEN}; color:#d0e0ff; }}
QListWidget::item:hover {{ background:rgba(107,158,255,0.04); }}
QProgressBar {{ background:#14142a; border:1px solid #1e1e38; border-radius:2px;
  color:{NV_GREEN}; text-align:center; font-size:10px; }}
QProgressBar::chunk {{ background:{NV_GREEN}; }}
QScrollBar:vertical {{ background:transparent; width:4px; }}
QScrollBar::handle:vertical {{ background:#2a2a50; border-radius:2px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
"""

METHOD_LABELS = {
    PatchMethod.LOCALIZATION_FILE: ("📄", "Localization File",  "#5b8dee"),
    PatchMethod.BEPINEX_MOD:       ("🔧", "BepInEx Mod",        "#4a9fff"),
    PatchMethod.RENPY_PATCH:       ("📖", "Ren'Py Translation", "#ff9f4a"),
    PatchMethod.RPGMAKER_PATCH:    ("🎮", "RPG Maker Patch",    "#ff4a9f"),
    PatchMethod.UE4_PAK:           ("📦", "UE4 Pak Patch",      "#ff9f4a"),
    PatchMethod.OVERLAY:           ("🖥", "Overlay Layer",      "#aaaaaa"),
}

# Steam App ID lookup (ใช้โหลด artwork เท่านั้น — ไม่ได้ populate sidebar แล้ว)
KNOWN_APPIDS: dict[str, int] = {
    "Wandering Sword": 1876890,
    "Elden Ring":      1245620,
    "Cyberpunk 2077":  1091500,
    "Sekiro":           814380,
    "Dota 2":               570,
    "The Witcher 3":    292030,
    "Hades":           1145360,
    "Stardew Valley":   413150,
}


# ── Workers ───────────────────────────────────────────────────────────────────
class ScanWorker(QThread):
    """Scan game context (world, tone, register) via Claude Opus"""
    finished = pyqtSignal(dict)

    def __init__(self, game):
        super().__init__()
        self.game = game

    def run(self):
        if HAS_ANTHROPIC:
            try:
                client = anthropic.Anthropic()
                r = client.messages.create(
                    model="claude-opus-4-5", max_tokens=400,
                    messages=[{"role": "user", "content":
                        f"Game '{self.game['name']}': return JSON only: "
                        "{world,era,tone,no_translate_terms[],register}"}])
                txt = r.content[0].text.strip().replace("```json","").replace("```","")
                self.finished.emit(json.loads(txt))
                return
            except Exception:
                pass
        time.sleep(0.8)
        self.finished.emit(self._mock())

    def _mock(self):
        m = {
            "Wandering Sword": {"world":"Jianghu — ยุคราชวงศ์หมิง","tone":"กล้าหาญ · โศกเศร้า",
                "register":"วรรณกรรมจีนโบราณ","no_translate_terms":["Jianghu","Qi","Shifu"]},
            "Elden Ring":      {"world":"The Lands Between","tone":"มืด · กวีนิพนธ์",
                "register":"ภาษาโบราณ","no_translate_terms":["Grace","Erdtree","Tarnished"]},
            "Hades":           {"world":"Greek Underworld","tone":"ทันสมัย · มีอารมณ์ขัน",
                "register":"กลาง","no_translate_terms":["Zagreus","Nyx","Charon"]},
            "Stardew Valley":  {"world":"Countryside","tone":"อบอุ่น · เรียบง่าย",
                "register":"สบายๆ","no_translate_terms":["Stardew Valley"]},
        }
        return m.get(self.game["name"], {"world":"Fantasy","tone":"กลาง",
            "register":"อัตโนมัติตามบริบท","no_translate_terms":[]})


class ExtractWorker(QThread):
    """Extract all translatable strings from game files"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)    # list[GameString]

    def __init__(self, game_dir: str, engine: str):
        super().__init__()
        self.game_dir = game_dir
        self.engine   = engine

    def run(self):
        try:
            strings = extract_all(
                self.game_dir, self.engine,
                progress=lambda m: self.progress.emit(m),
            )
            self.finished.emit(strings)
        except Exception as e:
            self.progress.emit(f"⚠ Extract ล้มเหลว: {e}")
            self.finished.emit([])


class TranslateAllWorker(QThread):
    """
    แปล strings ทั้งหมดแบบ batch + emit progress
    รองรับ checkpoint resume: ถ้ามี existing_pack จะ merge ตอนสิ้นสุด
    """
    tick     = pyqtSignal(int, int, str)   # current, total, message
    finished = pyqtSignal(str)             # glpack_path  (empty = failed)

    def __init__(self, game_name: str, engine: str,
                 strings: list[GameString],
                 game_context: dict,
                 existing_pack: "GLPack | None" = None,
                 start_offset: int = 0):
        super().__init__()
        self.game_name     = game_name
        self.engine        = engine
        self.strings       = strings       # เฉพาะ strings ที่ยังไม่ได้แปล
        self.game_context  = game_context
        self.existing_pack = existing_pack  # checkpoint ที่โหลดมา (หรือ None)
        self.start_offset  = start_offset   # จำนวนที่แปลไปแล้ว (จาก checkpoint)

    def run(self):
        total   = len(self.strings)
        game_id = self.game_name.lower().replace(" ", "_")

        # กรณีพิเศษ: ทุก string แปลแล้วใน checkpoint (resume ที่ครบ)
        if total == 0:
            if self.existing_pack:
                save_path = self.existing_pack.pack_path()
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                GLPackWriter.save(save_path, self.existing_pack)
                GLPackCheckpoint.clear(game_id)
                n = len(self.existing_pack.strings)
                self.tick.emit(n, n, f"✓ ครบแล้ว — {n:,} strings (จาก checkpoint)")
                self.finished.emit(save_path)
            else:
                self.finished.emit("")
            return

        try:
            from core.translation_memory import SmartTranslator
            translator = SmartTranslator(
                game_id      = game_id,
                game_context = self.game_context,
                speaker_roles= {},
            )
        except Exception as e:
            self.tick.emit(0, self.start_offset + total,
                           f"⚠ SmartTranslator error: {e}")
            self.finished.emit("")
            return

        CHUNK   = 50
        results: list[str] = []
        done    = 0

        for start in range(0, total, CHUNK):
            chunk   = self.strings[start:start + CHUNK]
            payload = to_smart_translator_input(chunk)
            try:
                chunk_results = translator.process_batch(payload)
                results.extend(chunk_results)
            except Exception:
                results.extend([s.text for s in chunk])   # fallback

            done += len(chunk)

            # ── Checkpoint ทุก CHECKPOINT_EVERY strings ─────────────────
            if done % CHECKPOINT_EVERY < CHUNK:
                try:
                    partial = build_glpack(self.game_name, self.engine,
                                           self.strings[:done], results)
                    if self.existing_pack:
                        partial = merge_glpacks(self.existing_pack, partial)
                    GLPackCheckpoint.save(partial)
                except Exception:
                    pass

            # ── Progress signal (รวม start_offset) ───────────────────────
            done_total = self.start_offset + done
            total_all  = self.start_offset + total
            pct        = int(done_total / total_all * 100)
            spk        = chunk[0].speaker or ""
            loc        = chunk[0].location or ""
            resume_tag = " ▶resume" if self.start_offset else ""
            msg = (f"กำลังแปล {done_total:,} / {total_all:,} strings"
                   f" ({pct}%){resume_tag}"
                   + (f" — {spk}" if spk else "")
                   + (f" [{loc}]" if loc else ""))
            self.tick.emit(done_total, total_all, msg)

        # ── สร้าง final pack ─────────────────────────────────────────────
        try:
            new_pack = build_glpack(self.game_name, self.engine,
                                    self.strings, results)
            final    = (merge_glpacks(self.existing_pack, new_pack)
                        if self.existing_pack else new_pack)

            save_path = final.pack_path()
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            GLPackWriter.save(save_path, final)
            GLPackCheckpoint.clear(game_id)   # ลบ checkpoint เมื่อเสร็จ

            n = len(final.strings)
            self.tick.emit(n, n, f"✓ บันทึก .glpack — {n:,} strings")
            self.finished.emit(save_path)
        except Exception as e:
            t = self.start_offset + total
            self.tick.emit(t, t, f"⚠ บันทึก .glpack ล้มเหลว: {e}")
            self.finished.emit("")


class PatchGlpackWorker(QThread):
    """Apply a .glpack to game files"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, glpack_path: str, game_dir: str,
                 game_name: str, method, rollback_mgr=None):
        super().__init__()
        self.glpack_path = glpack_path
        self.game_dir    = game_dir
        self.game_name   = game_name
        self.method      = method
        self.rollback_mgr = rollback_mgr

    def run(self):
        try:
            from core.patchers import GLPackPatcher
            pack   = GLPackReader.load(self.glpack_path)
            patcher = GLPackPatcher(
                game_dir     = self.game_dir,
                game_name    = self.game_name,
                glpack       = pack,
                method       = self.method,
                progress     = lambda m: self.progress.emit(m),
                rollback_mgr = self.rollback_mgr,
            )
            result = patcher.apply()
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit(f"⚠ Patch ล้มเหลว: {e}")


# ── Rollback Dialog ───────────────────────────────────────────────────────────
class RollbackDialog(QDialog):
    def __init__(self, game_name, patched_at, file_count,
                 font_injected, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rollback — คืนค่าเดิม")
        self.setFixedWidth(460)
        self.setStyleSheet(
            f"QDialog{{background:#0f0f1e;border:1px solid #3a4a8e;}}"
            f"QLabel{{color:#e2e4f0;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24,24,24,20); lay.setSpacing(14)

        hdr = QLabel("↺  ROLLBACK — คืนค่าไฟล์เกมเดิม")
        hdr.setStyleSheet("color:#6b9eff;font-size:14px;font-weight:bold;letter-spacing:2px;")
        lay.addWidget(hdr)

        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color:#1e1e38;"); lay.addWidget(line)

        font_line = (f"<br>🔤 Font ที่ inject: <b>จะถูกลบออก</b>"
                     if font_injected else "")
        detail = QLabel(
            f"ระบบจะคืนค่าไฟล์ทั้งหมดของ <b>{game_name}</b> กลับสู่สถานะเดิม<br><br>"
            f"📅 Patched เมื่อ: <b>{patched_at}</b><br>"
            f"📄 จำนวนไฟล์: <b>{file_count} ไฟล์</b>"
            f"{font_line}<br><br>"
            "⚠ ปิดเกมก่อนดำเนินการ<br>"
            "⚠ การแปลภาษาไทยจะถูกลบออกทั้งหมด"
        )
        detail.setWordWrap(True)
        detail.setStyleSheet("font-size:13px;line-height:1.6;")
        lay.addWidget(detail)

        btn_row = QHBoxLayout(); btn_row.addStretch()
        cancel  = QPushButton("ยกเลิก")
        cancel.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid #1e1e38;"
            "color:#4a5280;padding:9px 20px;font-size:11px;letter-spacing:2px;"
            "font-weight:bold;border-radius:2px;}"
        )
        confirm = QPushButton("↺  ยืนยัน — คืนค่าเดิม")
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)
        btn_row.addWidget(cancel); btn_row.addWidget(confirm)
        lay.addLayout(btn_row)


# ── Warning Dialog ────────────────────────────────────────────────────────────
class WarningDialog(QDialog):
    def __init__(self, game_name, method, game_dir, string_count, parent=None):
        super().__init__(parent)
        self.setWindowTitle("คำเตือน — แก้ไขไฟล์เกม")
        self.setFixedWidth(500)
        self.setStyleSheet(
            f"QDialog{{background:{NV_PANEL};border:1px solid {NV_RED};}}"
            f"QLabel{{color:{NV_TEXT};}}"
        )
        lay = QVBoxLayout(self); lay.setContentsMargins(24,24,24,20); lay.setSpacing(14)

        icon_lbl, label, color = METHOD_LABELS.get(method, ("⚠","Unknown","#aaa"))
        hdr = QLabel(f"⚠  คำเตือน — {label}")
        hdr.setStyleSheet(f"color:{NV_RED};font-size:15px;font-weight:bold;letter-spacing:2px;")
        lay.addWidget(hdr)

        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{NV_RED};"); lay.addWidget(line)

        method_desc = {
            PatchMethod.LOCALIZATION_FILE: "แก้ไขไฟล์ภาษาของเกมโดยตรง",
            PatchMethod.BEPINEX_MOD:       "ติดตั้ง BepInEx framework และ mod plugin",
            PatchMethod.RENPY_PATCH:       "เพิ่มไฟล์ translation .rpy ในโฟลเดอร์เกม",
            PatchMethod.RPGMAKER_PATCH:    "แก้ไขไฟล์ data JSON ของ RPG Maker",
            PatchMethod.OVERLAY:           "สร้าง overlay script แสดงคำแปลทับหน้าจอ",
        }
        detail = QLabel(
            f"แอปนี้จะ<b>{method_desc.get(method,'ดัดแปลงเกม')}</b> "
            f"สำหรับ <b>{game_name}</b><br><br>"
            f"<b>จำนวน strings ที่จะ patch:</b> {string_count:,} strings<br>"
            f"<b>โฟลเดอร์เกม:</b><br>"
            f"<span style='color:{NV_GREEN};font-size:11px;'>{game_dir}</span><br><br>"
            "⚠ ระบบจะสำรองไฟล์ต้นฉบับไว้ก่อนเสมอ (.bak)<br>"
            "⚠ ปิดเกมก่อนดำเนินการทุกครั้ง<br>"
            "⚠ ใช้สำหรับเกม offline / co-op เท่านั้น"
        )
        detail.setWordWrap(True); detail.setStyleSheet("font-size:13px;line-height:1.6;")
        lay.addWidget(detail)

        note = QLabel("กด <b>ยอมรับ</b> เพื่อดำเนินการ หรือ <b>ยกเลิก</b> เพื่อออก")
        note.setStyleSheet(f"color:{NV_MUTED};font-size:11px;"); lay.addWidget(note)

        btn_row = QHBoxLayout(); btn_row.addStretch()
        cancel = QPushButton("✕  ยกเลิก")
        cancel.setStyleSheet(
            f"QPushButton{{background:transparent;border:1px solid #1a103a;"
            f"color:{NV_RED};padding:9px 20px;font-size:11px;letter-spacing:2px;"
            f"font-weight:bold;border-radius:2px;}}"
            f"QPushButton:hover{{background:rgba(180,40,120,0.1);}}"
        )
        accept = QPushButton("✓  ยอมรับ — Patch เกม")
        cancel.clicked.connect(self.reject)
        accept.clicked.connect(self.accept)
        btn_row.addWidget(cancel); btn_row.addWidget(accept)
        lay.addLayout(btn_row)


# ── Update Dialog ─────────────────────────────────────────────────────────────
class UpdateDialog(QDialog):
    """แสดงข้อมูล update + ดาวน์โหลด + ติดตั้ง"""

    def __init__(self, info: UpdateInfo, parent=None):
        super().__init__(parent)
        self.info        = info
        self._downloader = None
        self._installer  = ""

        self.setWindowTitle(f"Update — v{info.version}")
        self.setFixedWidth(520)
        self.setStyleSheet(
            f"QDialog{{background:{NV_PANEL};border:1px solid {NV_BORDER};}}"
            f"QLabel{{color:{NV_TEXT};}}"
            f"QProgressBar{{background:#14142a;border:1px solid #1e1e38;"
            f"border-radius:2px;color:{NV_GREEN};text-align:center;font-size:10px;}}"
            f"QProgressBar::chunk{{background:{NV_GREEN};}}"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(14)

        # ── Header ──
        hdr = QLabel(f"↑  UPDATE AVAILABLE — v{info.version}")
        hdr.setStyleSheet(
            f"color:{NV_CYAN};font-size:14px;font-weight:bold;letter-spacing:2px;"
        )
        lay.addWidget(hdr)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{NV_BORDER};")
        lay.addWidget(line)

        # ── Version info ──
        size_mb = f"{info.size_bytes / 1_048_576:.1f} MB" if info.size_bytes else "—"
        ver_lbl = QLabel(
            f"เวอร์ชันปัจจุบัน: <b>v{APP_VERSION}</b>  →  เวอร์ชันใหม่: "
            f"<b style='color:{NV_GREEN};'>v{info.version}</b>"
            f"<br>ขนาดไฟล์: {size_mb}"
        )
        ver_lbl.setStyleSheet("font-size:13px;line-height:1.6;")
        lay.addWidget(ver_lbl)

        # ── Changelog ──
        if info.body:
            cl_hdr = QLabel("CHANGELOG")
            cl_hdr.setStyleSheet(
                f"color:{NV_LABEL};font-size:8px;letter-spacing:3px;font-weight:bold;"
            )
            lay.addWidget(cl_hdr)

            cl_scroll = QScrollArea()
            cl_scroll.setFixedHeight(140)
            cl_scroll.setWidgetResizable(True)
            cl_scroll.setStyleSheet(
                f"QScrollArea{{background:#0d0d1e;border:1px solid #1e1e38;border-radius:2px;}}"
            )
            cl_lbl = QLabel(_md_to_simple(info.body))
            cl_lbl.setWordWrap(True)
            cl_lbl.setContentsMargins(12, 10, 12, 10)
            cl_lbl.setStyleSheet(f"color:{NV_MUTED};font-size:11px;line-height:1.5;background:transparent;")
            cl_scroll.setWidget(cl_lbl)
            lay.addWidget(cl_scroll)

        # ── Progress bar (ซ่อนก่อน) ──
        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        self.prog_bar.setFixedHeight(6)
        self.prog_bar.setVisible(False)
        lay.addWidget(self.prog_bar)

        self.prog_lbl = QLabel("")
        self.prog_lbl.setStyleSheet(f"color:{NV_MUTED};font-size:11px;")
        self.prog_lbl.setVisible(False)
        lay.addWidget(self.prog_lbl)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.skip_btn = QPushButton("ข้ามครั้งนี้")
        self.skip_btn.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid #1e1e38;"
            "color:#4a5280;padding:9px 20px;font-size:11px;letter-spacing:1px;"
            "font-weight:bold;border-radius:2px;}"
        )
        self.skip_btn.clicked.connect(self.reject)

        self.update_btn = QPushButton("↓  ดาวน์โหลด & อัปเดต")
        self.update_btn.clicked.connect(self._start_download)

        btn_row.addWidget(self.skip_btn)
        btn_row.addWidget(self.update_btn)
        lay.addLayout(btn_row)

    def _start_download(self):
        if not self.info.download_url:
            import webbrowser
            webbrowser.open(
                f"https://github.com/markkyzii2304-web/gamelang-translator/releases/latest"
            )
            return

        self.update_btn.setEnabled(False)
        self.update_btn.setText("⟳  กำลังดาวน์โหลด...")
        self.skip_btn.setEnabled(False)
        self.prog_bar.setVisible(True)
        self.prog_lbl.setVisible(True)
        self.prog_lbl.setText("กำลังเชื่อมต่อ...")

        self._downloader = UpdateDownloader(
            self.info.download_url, self.info.size_bytes
        )
        self._downloader.progress.connect(self._on_dl_progress)
        self._downloader.finished.connect(self._on_dl_finished)
        self._downloader.error.connect(self._on_dl_error)
        self._downloader.start()

    def _on_dl_progress(self, downloaded: int, total: int):
        if total > 0:
            pct = int(downloaded / total * 100)
            self.prog_bar.setRange(0, 100)
            self.prog_bar.setValue(pct)
            mb_done  = downloaded / 1_048_576
            mb_total = total / 1_048_576
            self.prog_lbl.setText(
                f"ดาวน์โหลด {mb_done:.1f} / {mb_total:.1f} MB ({pct}%)"
            )
        else:
            self.prog_bar.setRange(0, 0)   # indeterminate
            mb_done = downloaded / 1_048_576
            self.prog_lbl.setText(f"ดาวน์โหลด {mb_done:.1f} MB...")

    def _on_dl_finished(self, path: str):
        if not path:
            self._on_dl_error("ดาวน์โหลดล้มเหลว")
            return
        self._installer = path
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(100)
        self.prog_lbl.setText("✓ ดาวน์โหลดเสร็จ — กำลังเปิด installer...")
        self.update_btn.setText("⚙  กำลังติดตั้ง...")
        QTimer.singleShot(800, self._run_installer)

    def _run_installer(self):
        launch_installer_and_quit(self._installer)

    def _on_dl_error(self, msg: str):
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        self.prog_lbl.setText(f"⚠ {msg}")
        self.update_btn.setEnabled(True)
        self.update_btn.setText("↓  ลองอีกครั้ง")
        self.skip_btn.setEnabled(True)


# ── Post-Patch Dialog ─────────────────────────────────────────────────────────
_NEXT_STEPS = {
    PatchMethod.RPGMAKER_PATCH: [
        ("✓", NV_GREEN,  "เปิดเกมได้เลย — ข้อความในเกมเป็นภาษาไทยทันที"),
        ("ℹ", NV_CYAN,   "ไม่ต้องเปลี่ยนภาษาในเกม เพราะแก้ไฟล์ข้อมูลโดยตรง"),
        ("⚠", "#f0a050", "ถ้าเกมมี DLC / อัปเดตใหม่ อาจต้อง patch ซ้ำอีกครั้ง"),
    ],
    PatchMethod.RENPY_PATCH: [
        ("1", NV_GREEN,  "เปิดเกม → ไปที่ <b>Preferences</b>"),
        ("2", NV_GREEN,  "เลือก <b>Language</b> → <b>Thai</b>"),
        ("3", NV_CYAN,   "ข้อความทั้งหมดจะเปลี่ยนเป็นภาษาไทยทันที"),
        ("ℹ", "#888",    "ถ้าไม่เห็น Thai ให้ restart เกม 1 ครั้ง"),
    ],
    PatchMethod.BEPINEX_MOD: [
        ("1", NV_GREEN,  "เปิดเกม — BepInEx mod จะโหลดอัตโนมัติ"),
        ("2", NV_CYAN,   "ดูข้อความใน console ว่า GameLangThai โหลดสำเร็จ"),
        ("ℹ", "#f0a050", "บางเกมอาจต้องเปิด mod ใน <b>Settings → Mods</b>"),
        ("⚠", "#888",    "ถ้าเกมแครชให้ลอง rollback แล้วใช้ Overlay แทน"),
    ],
    PatchMethod.LOCALIZATION_FILE: [
        ("✓", NV_GREEN,  "เปิดเกมได้เลย — ไฟล์ภาษาถูก replace แล้ว"),
        ("ℹ", NV_CYAN,   "บางเกมอาจต้องเลือก Language → Thai ใน Settings"),
        ("⚠", "#888",    "ถ้าเกม verify files → patch ซ้ำอีกครั้ง"),
    ],
    PatchMethod.OVERLAY: [
        ("1", NV_GREEN,  "เปิดเกม → ข้อความไทยจะแสดงทับหน้าจออัตโนมัติ"),
        ("ℹ", "#f0a050", "Overlay mode: ข้อความต้นฉบับยังอยู่ ไทยแสดงด้านบน"),
        ("⚠", "#888",    "ถ้า overlay ไม่แสดง ให้รัน app ในฐานะ Administrator"),
    ],
    PatchMethod.UE4_PAK: [
        ("✓", NV_GREEN,  "เปิดเกมได้เลย — patch pak ถูกโหลดอัตโนมัติ"),
        ("ℹ", NV_CYAN,   "ไฟล์ถูกสร้างใน Content/Paks/ เป็น _p.pak"),
        ("⚠", "#f0a050", "ถ้า Steam verify files → patch ซ้ำ (glpack ยังอยู่)"),
    ],
}

class PostPatchDialog(QDialog):
    def __init__(self, game_name: str, method: PatchMethod,
                 game_dir: str, string_count: int, parent=None):
        super().__init__(parent)
        self.game_dir = game_dir
        self.setWindowTitle("Patch สำเร็จ ✓")
        self.setFixedWidth(480)
        self.setStyleSheet(
            f"QDialog{{background:{NV_PANEL};border:1px solid #1e3a1e;}}"
            f"QLabel{{color:{NV_TEXT};}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)

        # ── Header ──
        hdr = QLabel("✓  PATCH สำเร็จ")
        hdr.setStyleSheet(
            f"color:{NV_GREEN};font-size:15px;font-weight:bold;letter-spacing:2px;"
        )
        lay.addWidget(hdr)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color:#1e3a1e;")
        lay.addWidget(line)

        # ── Summary ──
        icon, label, color = METHOD_LABELS.get(method, ("?","Unknown","#aaa"))
        summary = QLabel(
            f"<b>{game_name}</b> ถูก patch ด้วย <b>{string_count:,} strings</b><br>"
            f"วิธี: {icon} {label}"
        )
        summary.setStyleSheet("font-size:13px;line-height:1.6;")
        lay.addWidget(summary)

        # ── Next steps ──
        steps_hdr = QLabel("ขั้นตอนต่อไป")
        steps_hdr.setStyleSheet(
            f"color:{NV_LABEL};font-size:8px;letter-spacing:3px;font-weight:bold;margin-top:4px;"
        )
        lay.addWidget(steps_hdr)

        steps = _NEXT_STEPS.get(method, _NEXT_STEPS[PatchMethod.LOCALIZATION_FILE])
        for badge, color, text in steps:
            row = QHBoxLayout()
            row.setSpacing(10)

            badge_lbl = QLabel(badge)
            badge_lbl.setFixedSize(22, 22)
            badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge_lbl.setStyleSheet(
                f"background:rgba(0,0,0,0.3);border:1px solid {color};"
                f"color:{color};font-size:10px;font-weight:bold;border-radius:2px;"
            )
            text_lbl = QLabel(text)
            text_lbl.setWordWrap(True)
            text_lbl.setStyleSheet(f"color:{NV_MUTED};font-size:12px;")

            row.addWidget(badge_lbl)
            row.addWidget(text_lbl, 1)
            lay.addLayout(row)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        folder_btn = QPushButton("📁  เปิดโฟลเดอร์เกม")
        folder_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:1px solid #1e2456;"
            f"color:{NV_MUTED};padding:8px 16px;font-size:10px;letter-spacing:1px;"
            f"font-weight:bold;border-radius:2px;}}"
            f"QPushButton:hover{{border-color:{NV_GREEN};color:{NV_GREEN};}}"
        )
        folder_btn.clicked.connect(self._open_folder)

        ok_btn = QPushButton("✓  รับทราบ")
        ok_btn.clicked.connect(self.accept)

        btn_row.addWidget(folder_btn)
        btn_row.addWidget(ok_btn)
        lay.addLayout(btn_row)

    def _open_folder(self):
        import subprocess
        if sys.platform == "win32":
            os.startfile(self.game_dir)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", self.game_dir])
        else:
            subprocess.Popen(["xdg-open", self.game_dir])


class DraggableBar(QWidget):
    """Navbar ที่ drag เพื่อย้ายหน้าต่าง + double-click เพื่อ maximize"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (event.globalPosition().toPoint()
                              - self.window().frameGeometry().topLeft())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (event.buttons() == Qt.MouseButton.LeftButton
                and self._drag_pos is not None):
            self.window().move(
                event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            w = self.window()
            w.showNormal() if w.isMaximized() else w.showMaximized()
        super().mouseDoubleClickEvent(event)


def _md_to_simple(text: str) -> str:
    """แปลง Markdown อย่างง่ายเป็น plain text สำหรับ QLabel"""
    import re
    text = re.sub(r"#{1,6}\s*", "", text)          # ลบ headers
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)  # bold
    text = re.sub(r"\*(.+?)\*",   r"\1", text)     # italic
    text = re.sub(r"`(.+?)`",     r"\1", text)     # code
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


# ── Community Pack Store Dialog ───────────────────────────────────────────────
class PackStoreDialog(QDialog):
    """
    Community Pack Store — แสดงและดาวน์โหลด .glpack จาก GitHub
    fetch manifest เอง เปิดได้เลยโดยไม่ต้องมีเกมใน library ก่อน
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers: dict = {}   # game_id → PackDownloadWorker
        self._rows:    dict = {}   # game_id → {btn, lbl, bar}

        self.setWindowTitle("Community Packs")
        self.setMinimumWidth(540)
        self.setMinimumHeight(320)
        self.setStyleSheet(
            f"QDialog{{background:{NV_BG};border:1px solid {NV_BORDER};}}"
            f"QLabel{{color:{NV_TEXT};}}"
            f"QScrollArea{{background:transparent;border:none;}}"
            f"QScrollBar:vertical{{background:transparent;width:4px;}}"
            f"QScrollBar::handle:vertical{{background:#2a2a50;border-radius:2px;}}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        # Header
        hdr = QLabel("COMMUNITY PACKS")
        hdr.setStyleSheet(
            f"color:{NV_CYAN};font-size:12px;font-weight:bold;letter-spacing:3px;"
        )
        root.addWidget(hdr)

        sub = QLabel(
            "ดาวน์โหลดไฟล์แปลสำเร็จรูปจากชุมชน  —  "
            "ไม่ต้องใช้ API key  —  แค่กด PATCH GAME"
        )
        sub.setStyleSheet(f"color:{NV_MUTED};font-size:11px;")
        root.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{NV_BORDER};"); root.addWidget(sep)

        # Scrollable pack list
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)

        self._status_lbl = QLabel("⟳  กำลังโหลด...")
        self._status_lbl.setStyleSheet(
            f"color:{NV_MUTED};font-size:12px;padding:20px;"
        )
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._list_layout.addWidget(self._status_lbl)

        scroll = QScrollArea()
        scroll.setWidget(self._list_widget)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(260)
        root.addWidget(scroll)

        # Footer buttons
        foot = QHBoxLayout(); foot.setSpacing(8)
        self._refresh_btn = QPushButton("⟳  Refresh")
        self._refresh_btn.setFixedWidth(100)
        self._refresh_btn.clicked.connect(self._fetch)
        foot.addWidget(self._refresh_btn)
        foot.addStretch()
        close_btn = QPushButton("ปิด")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.accept)
        foot.addWidget(close_btn)
        root.addLayout(foot)

        # Auto-fetch on open
        self._fetch()

    # ── Fetch ──────────────────────────────────────────────────────────────────
    def _fetch(self):
        self._refresh_btn.setEnabled(False)
        self._status_lbl.setText("⟳  กำลังโหลดรายการ pack...")
        self._status_lbl.setVisible(True)
        from core.pack_store import PackFetchWorker
        w = PackFetchWorker()
        w.finished.connect(self._on_fetched)
        w.start()
        self._fetch_worker = w

    def _on_fetched(self, manifest: list):
        self._refresh_btn.setEnabled(True)
        # Clear old rows
        for i in reversed(range(self._list_layout.count())):
            item = self._list_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
        self._rows.clear()

        if not manifest:
            self._status_lbl = QLabel(
                "ไม่พบ pack ที่พร้อมใช้งาน\n"
                "อาจเกิดจาก network error หรือยังไม่มีการอัปโหลด"
            )
            self._status_lbl.setStyleSheet(
                f"color:{NV_MUTED};font-size:12px;padding:20px;"
            )
            self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_layout.addWidget(self._status_lbl)
            return

        self._status_lbl.setVisible(False)
        for pack in manifest:
            self._list_layout.addWidget(self._make_row(pack))
        self._list_layout.addStretch()

    # ── Pack row ───────────────────────────────────────────────────────────────
    def _make_row(self, pack) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame{{background:{NV_PANEL};border:1px solid {NV_BORDER};"
            f"border-radius:2px;}}"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 10, 10, 10)
        row.setSpacing(10)

        # Info
        info_lay = QVBoxLayout(); info_lay.setSpacing(2)
        name_lbl = QLabel(f"<b>{pack.game_name}</b>")
        name_lbl.setStyleSheet(f"color:{NV_TEXT};font-size:13px;background:transparent;border:none;")
        size_info = size_str(pack.size_bytes) if pack.size_bytes else ""
        meta_lbl = QLabel(
            f"Thai  ·  {pack.string_count:,} strings"
            + (f"  ·  {size_info}" if size_info else "")
            + f"  ·  v{pack.pack_version}"
        )
        meta_lbl.setStyleSheet(f"color:{NV_MUTED};font-size:10px;background:transparent;border:none;")
        info_lay.addWidget(name_lbl)
        info_lay.addWidget(meta_lbl)
        row.addLayout(info_lay, 1)

        # Status label
        status_lbl = QLabel("")
        status_lbl.setStyleSheet(
            f"color:{NV_GREEN};font-size:10px;background:transparent;border:none;"
        )
        row.addWidget(status_lbl)

        # Progress bar
        prog = QProgressBar()
        prog.setFixedSize(90, 6)
        prog.setRange(0, 100)
        prog.setValue(0)
        prog.setVisible(False)
        prog.setStyleSheet(
            f"QProgressBar{{background:#14142a;border:1px solid #1e1e38;border-radius:2px;}}"
            f"QProgressBar::chunk{{background:{NV_CYAN};}}"
        )
        row.addWidget(prog)

        # Button
        local_path = os.path.join(GLPACK_DIR, f"{pack.game_id}.glpack")
        if os.path.exists(local_path):
            btn = QPushButton("✓  DOWNLOADED")
            btn.setEnabled(False)
            sz = os.path.getsize(local_path)
            status_lbl.setText(f"✓  {size_str(sz)}")
        else:
            btn = QPushButton("⬇  DOWNLOAD")
            btn.clicked.connect(
                lambda _checked, p=pack, b=btn, sl=status_lbl, pr=prog:
                self._start_dl(p, b, sl, pr)
            )

        btn.setFixedSize(130, 30)
        row.addWidget(btn)

        self._rows[pack.game_id] = {"btn": btn, "lbl": status_lbl, "bar": prog}
        return frame

    # ── Download ───────────────────────────────────────────────────────────────
    def _start_dl(self, pack, btn, status_lbl, prog):
        btn.setEnabled(False)
        btn.setText("⟳  DOWNLOADING...")
        prog.setValue(0)
        prog.setVisible(True)
        status_lbl.setText("")

        from core.pack_store import PackDownloadWorker
        w = PackDownloadWorker(pack)
        w.progress.connect(
            lambda dl, tot, pr=prog, sl=status_lbl:
            self._on_dl_progress(dl, tot, pr, sl)
        )
        w.finished.connect(
            lambda path, b=btn, sl=status_lbl, pr=prog:
            self._on_dl_done(path, b, sl, pr)
        )
        w.error.connect(
            lambda msg, b=btn, sl=status_lbl:
            self._on_dl_error(msg, b, sl)
        )
        w.start()
        self._workers[pack.game_id] = w

    def _on_dl_progress(self, dl: int, tot: int, prog, lbl):
        if tot > 0:
            prog.setValue(int(dl / tot * 100))
            lbl.setText(f"{size_str(dl)} / {size_str(tot)}")
        else:
            lbl.setText(size_str(dl))

    def _on_dl_done(self, path: str, btn, lbl, prog):
        prog.setVisible(False)
        if path and os.path.exists(path):
            btn.setText("✓  DOWNLOADED")
            btn.setEnabled(False)
            sz = os.path.getsize(path)
            lbl.setText(f"✓  {size_str(sz)}")
            lbl.setStyleSheet(f"color:{NV_GREEN};font-size:10px;background:transparent;border:none;")
        else:
            btn.setText("⬇  DOWNLOAD")
            btn.setEnabled(True)
            lbl.setText("⚠ ล้มเหลว ลองอีกครั้ง")
            lbl.setStyleSheet(f"color:{NV_RED};font-size:10px;background:transparent;border:none;")

    def _on_dl_error(self, msg: str, btn, lbl):
        btn.setText("⬇  DOWNLOAD")
        btn.setEnabled(True)
        lbl.setText(f"⚠ {msg[:50]}")
        lbl.setStyleSheet(f"color:{NV_RED};font-size:10px;background:transparent;border:none;")


# ── Main Window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GameLang Translator v2")
        self.setMinimumSize(960, 680)
        # Frameless — custom title bar
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Window)
        self.setStyleSheet(STYLESHEET)

        # State
        self.selected_game  = None
        self.game_context   = {}
        self.detect_result  = None
        self.game_dir       = None
        self._extracted:    list[GameString] = []
        self._glpack_path:  str = ""
        self._update_info:  UpdateInfo | None = None
        self._manifest:     list = []        # community pack manifest
        self._current_pack: PackInfo | None = None
        self._library:      list[dict] = load_library()   # persistent game library

        self._build_ui()
        self._check_update_async()
        self._fetch_pack_manifest()

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QWidget(); root.setObjectName("mainRoot")
        self.setCentralWidget(root)
        rl = QVBoxLayout(root); rl.setContentsMargins(1,1,1,1); rl.setSpacing(0)
        rl.addWidget(self._navbar())
        body = QWidget(); bl = QHBoxLayout(body)
        bl.setContentsMargins(0,0,0,0); bl.setSpacing(0)
        bl.addWidget(self._sidebar())
        bl.addWidget(self._main_area(), 1)
        rl.addWidget(body, 1)

        # Size grip — bottom-right drag-to-resize handle
        grip = QSizeGrip(self)
        grip.setFixedSize(16, 16)
        grip.setStyleSheet("QSizeGrip{background:transparent;}")

    def _navbar(self):
        bar = DraggableBar()
        bar.setFixedHeight(46)
        bar.setStyleSheet(f"background:#0a0a18;border-bottom:1px solid {NV_BORDER};")
        lay = QHBoxLayout(bar); lay.setContentsMargins(16,0,4,0); lay.setSpacing(8)

        # Logo + name
        logo = QLabel("G"); logo.setFixedSize(20,20)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {NV_GREEN},stop:1 #3050b0);color:#000;"
            f"font-weight:900;font-size:11px;border-radius:3px;"
        )
        nm  = QLabel("GameLang")
        nm.setStyleSheet("color:#e0e8d8;font-size:13px;font-weight:800;")
        sub = QLabel("TRANSLATOR")
        sub.setStyleSheet(f"color:{NV_LABEL};font-size:8px;letter-spacing:2px;")
        lay.addWidget(logo); lay.addWidget(nm); lay.addWidget(sub)
        lay.addStretch()

        # Version
        ver_lbl = QLabel(f"v{APP_VERSION}")
        ver_lbl.setStyleSheet(f"color:{NV_LABEL};font-size:9px;letter-spacing:1px;")
        lay.addWidget(ver_lbl)

        # Update button
        self._update_btn = QPushButton("⟳  ตรวจสอบ...")
        self._update_btn.setFixedHeight(26)
        self._update_btn.setEnabled(False)
        self._update_btn_style_checking = (
            f"QPushButton{{background:transparent;border:1px solid #1e2456;"
            f"color:{NV_MUTED};border-radius:2px;font-size:9px;letter-spacing:1px;"
            f"font-weight:bold;padding:3px 10px;}}"
        )
        self._update_btn_style_ok = (
            f"QPushButton{{background:transparent;border:1px solid #1e2456;"
            f"color:{NV_LABEL};border-radius:2px;font-size:9px;letter-spacing:1px;"
            f"font-weight:bold;padding:3px 10px;}}"
            f"QPushButton:enabled:hover{{border-color:{NV_MUTED};color:{NV_MUTED};}}"
        )
        self._update_btn_style_new = (
            f"QPushButton{{background:rgba(56,189,248,0.1);border:1px solid {NV_CYAN};"
            f"color:{NV_CYAN};border-radius:2px;font-size:9px;letter-spacing:2px;"
            f"font-weight:bold;padding:3px 10px;}}"
            f"QPushButton:enabled:hover{{background:rgba(56,189,248,0.25);}}"
        )
        self._update_btn.setStyleSheet(self._update_btn_style_checking)
        self._update_btn.clicked.connect(self._on_update_click)
        lay.addWidget(self._update_btn)

        # Settings — circular gear button
        set_btn = QPushButton("⚙")
        set_btn.setFixedSize(32, 32)
        set_btn.setToolTip("Settings")
        set_btn.setStyleSheet(
            f"QPushButton{{background:rgba(18,18,36,0.9);"
            f"border:1px solid #1e2456;color:{NV_MUTED};"
            f"border-radius:16px;font-size:15px;padding:0;}}"
            f"QPushButton:hover{{border-color:{NV_GREEN};color:{NV_GREEN};"
            f"background:rgba(91,141,238,0.12);}}"
        )
        set_btn.clicked.connect(self._open_settings)
        lay.addWidget(set_btn)

        # ── Window controls ────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedSize(1, 18)
        sep.setStyleSheet("color:#1e1e38;"); lay.addWidget(sep)

        for sym, slot, hover_c in [
            ("−", self.showMinimized,    NV_MUTED),
            ("□", self._toggle_maximize, NV_MUTED),
            ("✕", self.close,            NV_RED),
        ]:
            b = QPushButton(sym); b.setFixedSize(36, 46)
            b.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;"
                f"color:#5a6090;font-size:14px;font-weight:400;"
                f"border-radius:0;}}"
                f"QPushButton:hover{{background:rgba(255,255,255,0.07);"
                f"color:{hover_c};}}"
            )
            if sym == "✕":
                b.setStyleSheet(
                    f"QPushButton{{background:transparent;border:none;"
                    f"color:#5a6090;font-size:13px;font-weight:400;"
                    f"border-radius:0;}}"
                    f"QPushButton:hover{{background:rgba(240,98,146,0.18);"
                    f"color:{NV_RED};}}"
                )
            b.clicked.connect(slot)
            lay.addWidget(b)

        return bar

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _sidebar(self):
        side = QWidget(); side.setFixedWidth(210)
        side.setStyleSheet(f"background:#0f0f1e;border-right:1px solid {NV_BORDER};")
        lay = QVBoxLayout(side); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        hdr = QLabel("  MY LIBRARY"); hdr.setFixedHeight(36)
        hdr.setStyleSheet(
            f"color:{NV_LABEL};font-size:9px;letter-spacing:3px;"
            f"font-weight:bold;padding-left:14px;"
        )
        lay.addWidget(hdr)
        self._hline(lay)

        self.game_list = QListWidget(); self.game_list.setIconSize(QSize(28,28))
        # โหลดจาก library (ไม่มีรายการจนกว่าจะแสกนเจอ)
        for entry in self._library:
            self._add_item_to_list(entry)
        self.game_list.currentItemChanged.connect(self._on_game_selected)
        lay.addWidget(self.game_list, 1)

        self._hline(lay)

        # Footer: count + ADD GAME button
        footer = QWidget(); footer.setFixedHeight(42)
        footer.setStyleSheet(f"background:#0c0c1a;border-top:1px solid {NV_BORDER};")
        fl = QHBoxLayout(footer); fl.setContentsMargins(10,0,8,0); fl.setSpacing(6)

        self._lib_count_lbl = QLabel(f"  {len(self._library)} GAMES")
        self._lib_count_lbl.setStyleSheet(
            f"color:{NV_MUTED};font-size:9px;letter-spacing:2px;"
        )
        fl.addWidget(self._lib_count_lbl, 1)

        # Pack Store button
        store_btn = QPushButton("📦")
        store_btn.setFixedSize(28, 28)
        store_btn.setToolTip("Community Packs — ดาวน์โหลดไฟล์แปลสำเร็จรูป")
        store_btn.setStyleSheet(
            f"QPushButton{{background:rgba(56,189,248,0.06);border:1px solid #1e3040;"
            f"color:#4080a0;border-radius:2px;font-size:13px;}}"
            f"QPushButton:hover{{border-color:{NV_CYAN};color:{NV_CYAN};"
            f"background:rgba(56,189,248,0.15);}}"
        )
        store_btn.clicked.connect(self._open_pack_store)
        fl.addWidget(store_btn)

        add_btn = QPushButton("＋")
        add_btn.setFixedSize(28, 28)
        add_btn.setToolTip("เพิ่มเกมจากโฟลเดอร์")
        add_btn.setStyleSheet(
            f"QPushButton{{background:rgba(91,141,238,0.08);border:1px solid #3a4480;"
            f"color:#8899cc;border-radius:2px;font-size:14px;font-weight:bold;}}"
            f"QPushButton:hover{{border-color:{NV_GREEN};color:{NV_GREEN};"
            f"background:rgba(91,141,238,0.18);}}"
        )
        add_btn.clicked.connect(self._on_add_game)
        fl.addWidget(add_btn)

        lay.addWidget(footer)
        return side

    def _add_item_to_list(self, entry: dict):
        """เพิ่ม QListWidgetItem สำหรับ library entry"""
        item = QListWidgetItem(entry["name"])
        item.setData(Qt.ItemDataRole.UserRole, entry)
        appid = entry.get("appid", 0)
        if HAS_REQUESTS and appid:
            threading.Thread(target=self._load_icon,
                             args=(item, appid), daemon=True).start()
        self.game_list.addItem(item)

    def _update_library_count(self):
        self._lib_count_lbl.setText(f"  {self.game_list.count()} GAMES")

    def _open_pack_store(self):
        """เปิด Community Pack Store dialog"""
        dlg = PackStoreDialog(parent=self)
        dlg.exec()
        # หลัง dialog ปิด — ตรวจสอบว่ามี glpack ใหม่ดาวน์โหลดมาไหม
        if self.selected_game:
            _gid = self.selected_game["name"].lower().replace(" ", "_")
            _lp  = os.path.join(GLPACK_DIR, f"{_gid}.glpack")
            if os.path.exists(_lp) and not self._glpack_path:
                self._glpack_path = _lp
                self.patch_btn.setEnabled(bool(self.game_dir))
                self._update_stats()
                self.prog_log.setText(
                    "✓ Thai Pack พร้อมแล้ว — กด ⚡ PATCH GAME ได้เลย"
                )
        # Refresh manifest + banner
        self._fetch_pack_manifest()

    def _on_add_game(self):
        """ผู้ใช้กด ＋ → เลือกโฟลเดอร์ → detect engine → เพิ่มใน library ถ้าเจอ"""
        from PyQt6.QtWidgets import QMessageBox
        d = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์หลักของเกม")
        if not d:
            return

        # Detect engine
        result = detect(d)

        if result.engine == Engine.UNKNOWN:
            QMessageBox.warning(
                self, "ไม่พบเกม",
                f"ไม่พบ engine ที่รองรับในโฟลเดอร์:\n{d}\n\n"
                "ลองเลือกโฟลเดอร์หลักของเกมโดยตรง\n"
                "(เช่น .../Wandering Sword/ ไม่ใช่ .../steamapps/)"
            )
            return

        # ชื่อเกม = ชื่อโฟลเดอร์สุดท้าย
        name  = os.path.basename(d.rstrip("/\\")) or d
        appid = KNOWN_APPIDS.get(name, 0)

        # เช็คว่ามีอยู่แล้วหรือยัง (ซ้ำ game_dir)
        from core.library import _normalize_dir
        existing_dirs = {_normalize_dir(g.get("game_dir",""))
                         for g in self._library}
        if _normalize_dir(d) in existing_dirs:
            # เลือก item นั้นในรายการ
            for i in range(self.game_list.count()):
                it = self.game_list.item(i)
                g  = it.data(Qt.ItemDataRole.UserRole)
                if _normalize_dir(g.get("game_dir","")) == _normalize_dir(d):
                    self.game_list.setCurrentItem(it)
                    break
            return

        # เพิ่มใน library
        entry = make_entry(
            name     = name,
            game_dir = d,
            engine   = result.engine.value,
            method   = result.method.value,
            appid    = appid,
        )
        self._library = add_game(self._library, entry)
        save_library(self._library)

        # เพิ่มใน sidebar + เลือก
        self._add_item_to_list(entry)
        self._update_library_count()
        last_item = self.game_list.item(self.game_list.count() - 1)
        self.game_list.setCurrentItem(last_item)

    def _main_area(self):
        self.stack = QStackedWidget()
        self.stack.addWidget(self._empty_page())
        self.stack.addWidget(self._detail_page())
        return self.stack

    def _empty_page(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico = QLabel("⬡"); ico.setStyleSheet("font-size:40px;color:#1e2a1e;")
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("SELECT A GAME FROM LIBRARY")
        hint.setStyleSheet("color:#2a3a2a;font-size:9px;letter-spacing:3px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ico); lay.addWidget(hint)
        return w

    def _detail_page(self):
        w   = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        # Hero image — Steam artwork + gradient overlay + game name
        self.hero = QLabel(); self.hero.setFixedHeight(220)
        self.hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero.setScaledContents(False)
        self.hero.setStyleSheet("background:#09090e;")
        lay.addWidget(self.hero)

        # Scroll area
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;}")
        content = QWidget(); self.cl = QVBoxLayout(content)
        self.cl.setContentsMargins(24,20,24,24); self.cl.setSpacing(12)

        # engine_row / ctx_row ถูกลบออก — ข้อมูลใช้ internally ไม่แสดงใน UI

        # ── Game dir row ───────────────────────────────────────────────────
        dir_row = QHBoxLayout(); dir_row.setSpacing(8)
        self.dir_label = QLabel("โฟลเดอร์เกม: —")
        self.dir_label.setStyleSheet(f"color:{NV_MUTED};font-size:11px;")
        dir_btn = QPushButton("📁  เลือกโฟลเดอร์"); dir_btn.setEnabled(True)
        dir_btn.clicked.connect(self._pick_game_dir)
        dir_row.addWidget(self.dir_label, 1); dir_row.addWidget(dir_btn)
        self.cl.addLayout(dir_row)

        self._hline_widget()

        # ── Stage buttons row ──────────────────────────────────────────────
        stage_row = QHBoxLayout(); stage_row.setSpacing(8)

        self.extract_btn = QPushButton("◈  SCAN & EXTRACT ALL STRINGS")
        self.extract_btn.setEnabled(False); self.extract_btn.setFixedHeight(38)
        self.extract_btn.clicked.connect(self._on_extract)
        stage_row.addWidget(self.extract_btn)

        self.cl.addLayout(stage_row)

        # ── Community Pack Banner (hidden by default) ──────────────────────
        self.pack_frame = QFrame()
        self.pack_frame.setStyleSheet(
            f"QFrame{{background:rgba(56,189,248,0.06);"
            f"border:1px solid rgba(56,189,248,0.25);"
            f"border-left:3px solid {NV_CYAN};border-radius:2px;}}"
        )
        pack_lay = QHBoxLayout(self.pack_frame)
        pack_lay.setContentsMargins(14,8,10,8); pack_lay.setSpacing(10)

        self.pack_info_lbl = QLabel("")
        self.pack_info_lbl.setStyleSheet(
            f"color:{NV_CYAN};font-size:11px;background:transparent;border:none;"
        )
        pack_lay.addWidget(self.pack_info_lbl, 1)

        self.pack_dl_btn = QPushButton("⬇  DOWNLOAD THAI PACK")
        self.pack_dl_btn.setFixedHeight(30)
        self.pack_dl_btn.setStyleSheet(
            f"QPushButton{{background:rgba(56,189,248,0.12);"
            f"border:1px solid {NV_CYAN};color:{NV_CYAN};"
            f"border-radius:2px;font-size:9px;letter-spacing:2px;"
            f"font-weight:bold;padding:4px 14px;}}"
            f"QPushButton:hover{{background:rgba(56,189,248,0.3);}}"
            f"QPushButton:disabled{{border-color:#1e2456;color:#2a3a58;"
            f"background:transparent;}}"
        )
        self.pack_dl_btn.clicked.connect(self._on_download_pack)
        pack_lay.addWidget(self.pack_dl_btn)

        self.pack_frame.setVisible(False)
        self.cl.addWidget(self.pack_frame)

        # ── Progress bar ───────────────────────────────────────────────────
        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100); self.prog_bar.setValue(0)
        self.prog_bar.setFixedHeight(4); self.prog_bar.setVisible(False)
        self.cl.addWidget(self.prog_bar)

        # ── Progress log ───────────────────────────────────────────────────
        self.prog_log = QLabel("")
        self.prog_log.setStyleSheet(f"color:{NV_MUTED};font-size:11px;")
        self.prog_log.setWordWrap(True)
        self.cl.addWidget(self.prog_log)

        # ── Stats row (string count / glpack / status) ─────────────────────
        self.stats_row = QHBoxLayout(); self.stats_row.setSpacing(10)
        self.cl.addLayout(self.stats_row)

        # ── Action buttons row ─────────────────────────────────────────────
        action_row = QHBoxLayout(); action_row.setSpacing(8)

        self.translate_btn = QPushButton("▶  TRANSLATE ALL  →  .glpack")
        self.translate_btn.setEnabled(False); self.translate_btn.setFixedHeight(40)
        self.translate_btn.clicked.connect(self._on_translate_all)
        action_row.addWidget(self.translate_btn, 2)

        self.patch_btn = QPushButton("⚡  PATCH GAME")
        self.patch_btn.setEnabled(False); self.patch_btn.setFixedHeight(40)
        self.patch_btn.clicked.connect(self._on_patch)
        action_row.addWidget(self.patch_btn, 1)

        self.rollback_btn = QPushButton("↺  ROLLBACK")
        self.rollback_btn.setEnabled(False); self.rollback_btn.setFixedHeight(40)
        self.rollback_btn.setFixedWidth(120)
        self.rollback_btn.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid #1a103a;"
            "color:#a78bfa;border-radius:2px;font-size:10px;letter-spacing:2px;"
            "font-weight:bold;padding:7px 12px;}"
            "QPushButton:enabled:hover{background:rgba(150,80,200,0.12);}"
            "QPushButton:disabled{border-color:#1e1e1e;color:#2a2a2a;}"
        )
        self.rollback_btn.clicked.connect(self._on_rollback)
        action_row.addWidget(self.rollback_btn)

        self.delete_pack_btn = QPushButton("🗑")
        self.delete_pack_btn.setEnabled(False)
        self.delete_pack_btn.setFixedSize(40, 40)
        self.delete_pack_btn.setToolTip("ลบไฟล์แปล (.glpack)")
        self.delete_pack_btn.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid #1a1020;"
            "color:#3a2030;border-radius:2px;font-size:14px;}"
            "QPushButton:enabled{border-color:#3a1a2a;color:#7a3040;}"
            "QPushButton:enabled:hover{background:rgba(240,98,146,0.12);"
            "border-color:#f06292;color:#f06292;}"
            "QPushButton:disabled{border-color:#1a1020;color:#2a1020;}"
        )
        self.delete_pack_btn.clicked.connect(self._on_delete_pack)
        action_row.addWidget(self.delete_pack_btn)

        self.cl.addLayout(action_row)
        self.cl.addStretch()

        scroll.setWidget(content); lay.addWidget(scroll, 1)
        return w

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _hline(self, lay):
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{NV_BORDER};"); lay.addWidget(line)

    def _hline_widget(self):
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{NV_BORDER};"); self.cl.addWidget(line)

    def _card(self, label, value, color=NV_GREEN):
        card = QWidget()
        card.setStyleSheet(
            f"QWidget{{background:{NV_PANEL};border:1px solid #1e2456;"
            f"border-top:2px solid {color};border-radius:2px;}}"
        )
        lay = QVBoxLayout(card); lay.setContentsMargins(12,10,12,10)
        lb = QLabel(label)
        lb.setStyleSheet(
            f"color:{NV_LABEL};font-size:8px;letter-spacing:2px;font-weight:bold;border:none;"
        )
        vl = QLabel(value)
        vl.setStyleSheet(f"color:#90b8f8;font-size:11px;border:none;")
        vl.setWordWrap(True); lay.addWidget(lb); lay.addWidget(vl)
        return card

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def _load_icon(self, item, appid):
        try:
            url = (f"https://cdn.akamai.steamstatic.com/steam/apps/"
                   f"{appid}/library_600x900.jpg")
            r   = requests.get(url, timeout=3)
            pix = QPixmap(); pix.loadFromData(r.content)
            icon = QIcon(pix.scaled(
                28, 28,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            ))
            QTimer.singleShot(0, lambda: item.setIcon(icon))
        except Exception:
            pass

    def _set_busy(self, busy: bool):
        """Disable/enable interactive buttons during background work"""
        self.extract_btn.setEnabled(not busy)
        pass  # scan_ctx_btn removed
        self.translate_btn.setEnabled(not busy)
        self.patch_btn.setEnabled(not busy)
        self.rollback_btn.setEnabled(not busy)
        self.delete_pack_btn.setEnabled(not busy)
        # pack_dl_btn is managed separately (already disabled when downloading)

    def _update_stats(self):
        self._clear_layout(self.stats_row)
        # enable delete ถ้ามีไฟล์ .glpack
        has_pack = bool(self._glpack_path and os.path.exists(self._glpack_path))
        self.delete_pack_btn.setEnabled(has_pack)
        count = len(self._extracted)
        if count:
            self.stats_row.addWidget(
                self._card("STRINGS", f"{count:,} strings", NV_GREEN)
            )
        if self._glpack_path and os.path.exists(self._glpack_path):
            # Determine if this is a community pack or user-translated pack
            from core.glpack import GLPACK_DIR
            is_community = (self._current_pack is not None and
                            self._glpack_path == os.path.join(
                                GLPACK_DIR, f"{self._current_pack.game_id}.glpack"))
            try:
                size_mb = GLPackReader.file_size_mb(self._glpack_path)
                pack    = GLPackReader.load(self._glpack_path)
                pack_sc = pack.string_count
            except Exception:
                size_mb = os.path.getsize(self._glpack_path) / 1_048_576
                pack_sc = (self._current_pack.string_count
                           if self._current_pack else 0)

            label = "COMMUNITY PACK" if is_community else ".glpack"
            color = NV_CYAN
            self.stats_row.addWidget(
                self._card(label,
                           f"{size_mb:.2f} MB · {pack_sc:,} strings",
                           color)
            )
            source = ("สาธารณะ — ไม่ต้องใช้ API"
                      if is_community else "✓ พร้อม patch เกม")
            self.stats_row.addWidget(
                self._card("STATUS", source, NV_PURPLE)
            )
        elif count:
            self.stats_row.addWidget(
                self._card("STATUS", "รอแปล → กด TRANSLATE ALL", "#888")
            )

    def _update_rollback_btn(self):
        if not (self.game_dir and self.selected_game):
            self.rollback_btn.setEnabled(False)
            return
        mgr     = RollbackManager(self.game_dir, self.selected_game["name"])
        has_bak = mgr.has_backup()
        self.rollback_btn.setEnabled(has_bak)
        if has_bak:
            info = mgr.get_backup_info()
            self.rollback_btn.setToolTip(
                f"Patched: {info.get('patched_at','')[:10]}\n"
                f"Files: {info.get('file_count',0)}"
            )

    # ── Events ────────────────────────────────────────────────────────────────
    def _on_game_selected(self, current, _):
        if not current: return
        self.selected_game = current.data(Qt.ItemDataRole.UserRole)
        self.game_context  = {}
        self.detect_result = None
        self._extracted    = []
        self._glpack_path  = ""
        # game_dir มาจาก library entry (เพิ่มตอน scan แล้ว)
        stored_dir = self.selected_game.get("game_dir", "")
        if stored_dir and os.path.isdir(stored_dir):
            self.game_dir = stored_dir
        else:
            # fallback: ลองหาใน Steam (กรณี library เก่า/ย้ายไฟล์)
            self.game_dir = self._find_steam_dir(self.selected_game["name"]) or ""

        self.stack.setCurrentIndex(1)
        self.extract_btn.setEnabled(bool(self.game_dir))
        pass  # scan context runs automatically
        self.translate_btn.setEnabled(False)
        self.patch_btn.setEnabled(False)
        self.prog_log.setText("")
        self.prog_bar.setVisible(False)
        self.pack_frame.setVisible(False)
        self._current_pack = None

        # Reset hero — placeholder แสดงทันที, Steam art โหลดใน background
        self.hero.clear()
        self.hero.setStyleSheet("background:#09090e;")
        self._render_hero_placeholder(self.selected_game["name"])
        self.dir_label.setText(
            f"โฟลเดอร์เกม: {self.game_dir or '— (ไม่พบ กรุณาเลือกเอง)'}"
        )
        pass  # engine_row / ctx_row removed
        self._clear_layout(self.stats_row)
        self._update_rollback_btn()

        if HAS_REQUESTS:
            threading.Thread(target=self._load_hero, daemon=True).start()

        # Auto-detect engine if folder found
        if self.game_dir:
            self._run_engine_detect()

        # Auto-enable patch ถ้ามี .glpack ในเครื่องอยู่แล้ว (ไม่ต้องรอ manifest)
        _gid = self.selected_game["name"].lower().replace(" ", "_")
        _lp  = os.path.join(GLPACK_DIR, f"{_gid}.glpack")
        if os.path.exists(_lp):
            self._glpack_path = _lp
            self.patch_btn.setEnabled(bool(self.game_dir))

        # Show community pack banner if available (manifest-based)
        self._check_community_pack()

        # Auto-scan game context (non-blocking background)
        QTimer.singleShot(200, self._on_scan_context)

    def _load_hero(self):
        """โหลด Steam artwork ใน background thread"""
        game  = self.selected_game
        if not game:
            return
        appid = game.get("appid", 0)
        if not appid:
            return   # placeholder แสดงแล้วตอน _on_game_selected
        try:
            # ลอง URL จากใหญ่ไปเล็ก
            for suffix in ["library_hero.jpg",
                           "capsule_616x353.jpg",
                           "header.jpg"]:
                url = (f"https://cdn.akamai.steamstatic.com/"
                       f"steam/apps/{appid}/{suffix}")
                r   = requests.get(url, timeout=5)
                if r.status_code == 200:
                    raw  = r.content
                    name = game["name"]
                    QTimer.singleShot(
                        0, lambda b=raw, n=name: self._render_hero(b, n))
                    return
        except Exception:
            pass

    def _render_hero(self, raw_bytes: bytes, name: str):
        """วาด hero image พร้อม gradient overlay และชื่อเกม (main thread)"""
        pix = QPixmap()
        if not pix.loadFromData(raw_bytes):
            return

        w = max(self.hero.width(), 800)
        h = self.hero.height()

        # Scale-to-fill + center-crop
        scaled = pix.scaled(w, h,
                             Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                             Qt.TransformationMode.SmoothTransformation)
        cx = (scaled.width()  - w) // 2
        cy = (scaled.height() - h) // 2
        cropped = scaled.copy(cx, cy, w, h)

        # Composite: image + gradient overlay + game name
        result  = QPixmap(cropped.size())
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, cropped)

        # Dark gradient from bottom
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.00, QColor(9, 9, 18,   0))
        grad.setColorAt(0.35, QColor(9, 9, 18,  30))
        grad.setColorAt(0.68, QColor(9, 9, 18, 185))
        grad.setColorAt(1.00, QColor(9, 9, 18, 255))
        painter.fillRect(0, 0, w, h, grad)

        # Game name text
        font = QFont("Segoe UI", 20, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(215, 228, 255, 230))
        painter.drawText(QRectF(20, 0, w - 30, h - 14),
                         Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignBottom,
                         name)
        painter.end()
        self.hero.setPixmap(result)

    def _render_hero_placeholder(self, name: str):
        """แสดง placeholder แบบ gradient เมื่อไม่มี Steam artwork"""
        w = max(self.hero.width(), 800)
        h = self.hero.height()
        result  = QPixmap(w, h)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background gradient
        bg = QLinearGradient(0, 0, w, h)
        bg.setColorAt(0, QColor(18, 18, 48))
        bg.setColorAt(1, QColor(9,  9,  18))
        painter.fillRect(0, 0, w, h, bg)

        # Subtle dot grid
        painter.setPen(QPen(QColor(30, 38, 80, 70), 1))
        for gx in range(0, w, 36):
            for gy in range(0, h, 36):
                painter.drawPoint(gx, gy)

        # Bottom fade
        fade = QLinearGradient(0, h // 2, 0, h)
        fade.setColorAt(0, QColor(9, 9, 18,   0))
        fade.setColorAt(1, QColor(9, 9, 18, 220))
        painter.fillRect(0, 0, w, h, fade)

        # Game name
        font = QFont("Segoe UI", 20, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(180, 200, 255, 200))
        painter.drawText(QRectF(20, 0, w - 30, h - 14),
                         Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignBottom,
                         name)
        painter.end()
        self.hero.setPixmap(result)

    def _pick_game_dir(self):
        d = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์เกม")
        if d:
            self.game_dir = d
            self.dir_label.setText(f"โฟลเดอร์เกม: {d}")
            self.extract_btn.setEnabled(True)
            self._run_engine_detect()
            QTimer.singleShot(100, self._on_scan_context)

    def _run_engine_detect(self):
        if not self.game_dir:
            return
        result = detect(self.game_dir)
        self.detect_result = result   # เก็บไว้ใช้ตอน patch — ไม่แสดงใน UI

    # ── Community Pack ────────────────────────────────────────────────────────
    def _fetch_pack_manifest(self):
        """Fetch packs.json manifest from GitHub in background"""
        w = PackFetchWorker()
        w.finished.connect(self._on_manifest_fetched)
        w.start()
        self._manifest_worker = w

    def _on_manifest_fetched(self, manifest: list):
        self._manifest = manifest
        # Refresh banner if a game is already selected
        if self.selected_game:
            self._check_community_pack()

    def _check_community_pack(self):
        """Show/hide community pack banner for current game"""
        if not self.selected_game:
            self.pack_frame.setVisible(False)
            return

        pack = find_pack(self._manifest, self.selected_game["name"])
        if not pack:
            self.pack_frame.setVisible(False)
            self._current_pack = None
            return

        self._current_pack = pack

        # Check if already downloaded locally
        from core.glpack import GLPACK_DIR
        local_path = os.path.join(GLPACK_DIR, f"{pack.game_id}.glpack")
        if os.path.exists(local_path):
            sz = os.path.getsize(local_path)
            self.pack_info_lbl.setText(
                f"✓  Thai Pack v{pack.pack_version}  ·  {pack.string_count:,} strings"
                f"  ·  {size_str(sz)}  (downloaded)"
            )
            self.pack_dl_btn.setText("✓  DOWNLOADED")
            self.pack_dl_btn.setEnabled(False)
            # Enable PATCH button directly — no API key needed
            self._glpack_path = local_path
            self.patch_btn.setEnabled(bool(self.game_dir))
            self._update_stats()
        else:
            sz_str = size_str(pack.size_bytes) if pack.size_bytes else ""
            self.pack_info_lbl.setText(
                f"⬇  Thai Pack v{pack.pack_version}  ·  {pack.string_count:,} strings"
                + (f"  ·  {sz_str}" if sz_str else "")
                + "  — แปลสำเร็จแล้ว ไม่ต้องใช้ API key"
            )
            self.pack_dl_btn.setText("⬇  DOWNLOAD THAI PACK")
            self.pack_dl_btn.setEnabled(True)

        self.pack_frame.setVisible(True)

    def _on_download_pack(self):
        """Start downloading community pack (ไม่ต้องการ game_dir — download เก็บก่อนได้)"""
        if not self._current_pack:
            return

        self.pack_dl_btn.setText("⟳  DOWNLOADING...")
        self.pack_dl_btn.setEnabled(False)
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        self.prog_bar.setVisible(True)
        self.prog_log.setText(f"กำลังดาวน์โหลด Thai Pack v{self._current_pack.pack_version}...")
        self._set_busy(True)

        w = PackDownloadWorker(self._current_pack)
        w.progress.connect(self._on_pack_dl_progress)
        w.finished.connect(self._on_pack_dl_done)
        w.error.connect(self._on_pack_dl_error)
        w.start()
        self._pack_dl_worker = w

    def _on_pack_dl_progress(self, downloaded: int, total: int):
        if total > 0:
            pct = int(downloaded / total * 100)
            self.prog_bar.setValue(pct)
            self.prog_log.setText(
                f"กำลังดาวน์โหลด {size_str(downloaded)} / {size_str(total)} ({pct}%)"
            )
        else:
            self.prog_log.setText(f"กำลังดาวน์โหลด {size_str(downloaded)}...")

    def _on_pack_dl_error(self, msg: str):
        """Download error — re-enable UI"""
        self._set_busy(False)
        self.prog_bar.setVisible(False)
        self.pack_dl_btn.setText("⬇  DOWNLOAD THAI PACK")
        self.pack_dl_btn.setEnabled(True)
        self.prog_log.setText(f"⚠ Download ล้มเหลว: {msg}")
        self._update_stats()

    def _on_pack_dl_done(self, local_path: str):
        self._set_busy(False)   # คืนสถานะปุ่มทุกตัวก่อน
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(100)
        QTimer.singleShot(600, lambda: self.prog_bar.setVisible(False))

        if local_path and os.path.exists(local_path):
            self._glpack_path = local_path
            self.patch_btn.setEnabled(bool(self.game_dir))
            self.prog_log.setText(
                "✓ Thai Pack พร้อมแล้ว — กด ⚡ PATCH GAME ได้เลย"
            )
            # Update banner
            if self._current_pack:
                sz = os.path.getsize(local_path)
                self.pack_info_lbl.setText(
                    f"✓  Thai Pack v{self._current_pack.pack_version}"
                    f"  ·  {self._current_pack.string_count:,} strings"
                    f"  ·  {size_str(sz)}"
                )
                self.pack_dl_btn.setText("✓  DOWNLOADED")
                self.pack_dl_btn.setEnabled(False)
            self._update_rollback_btn()
            self._update_stats()
        else:
            self.patch_btn.setEnabled(False)
            self.pack_dl_btn.setText("⬇  DOWNLOAD THAI PACK")
            self.pack_dl_btn.setEnabled(True)
            self._update_stats()

    # ── Stage 1: Scan context (auto — ไม่มีปุ่ม) ────────────────────────────
    def _on_scan_context(self):
        """เรียกอัตโนมัติตอนเลือกเกม / เลือกโฟลเดอร์"""
        if not self.selected_game: return
        w = ScanWorker(self.selected_game)
        w.finished.connect(self._on_scan_ctx_done)
        w.start()
        self._scan_worker = w

    def _on_scan_ctx_done(self, ctx):
        self.game_context = ctx   # เก็บไว้ใช้ตอนแปล — ไม่แสดงใน UI

    # ── Stage 2: Extract strings ──────────────────────────────────────────────
    def _on_extract(self):
        if not self.game_dir:
            QMessageBox.warning(self, "ข้อผิดพลาด", "กรุณาเลือกโฟลเดอร์เกมก่อน")
            return

        engine = (self.detect_result.engine.value
                  if self.detect_result else "unknown")

        self._set_busy(True)
        self.extract_btn.setText("⟳  EXTRACTING...")
        self.prog_bar.setRange(0, 0); self.prog_bar.setVisible(True)
        self.prog_log.setText("กำลังอ่านไฟล์เกม...")
        self._clear_layout(self.stats_row)

        w = ExtractWorker(self.game_dir, engine)
        w.progress.connect(lambda m: self.prog_log.setText(m))
        w.finished.connect(self._on_extracted)
        w.start(); self._extract_worker = w

    def _on_extracted(self, strings: list):
        self._extracted = strings
        self.prog_bar.setRange(0, 100); self.prog_bar.setValue(100)
        QTimer.singleShot(600, lambda: self.prog_bar.setVisible(False))

        self.extract_btn.setEnabled(True); self.extract_btn.setText("◈  EXTRACT AGAIN")
        pass  # scan context runs automatically
        self.translate_btn.setEnabled(len(strings) > 0)
        self.patch_btn.setEnabled(False)
        self._update_rollback_btn()

        count = len(strings)
        if count:
            files = len(set(s.file for s in strings))
            self.prog_log.setText(
                f"✓ พบ {count:,} strings จาก {files} ไฟล์ — กด TRANSLATE ALL ได้เลย"
            )
        else:
            self.prog_log.setText(
                "ไม่พบ strings — ลองเลือกโฟลเดอร์เกมใหม่ หรือ engine ไม่รองรับ"
            )
        self._update_stats()

    # ── Stage 3: Translate all ────────────────────────────────────────────────
    def _on_translate_all(self):
        if not self._extracted:
            QMessageBox.warning(self, "ข้อผิดพลาด", "กรุณา Extract strings ก่อน")
            return
        if not HAS_ANTHROPIC:
            QMessageBox.warning(
                self, "ไม่พบ anthropic",
                "กรุณาติดตั้ง: pip install anthropic\nแล้วตั้ง ANTHROPIC_API_KEY"
            )
            return

        game_id = self.selected_game["name"].lower().replace(" ", "_")
        engine  = (self.detect_result.engine.value if self.detect_result else "unknown")
        total   = len(self._extracted)

        # ── ตรวจ checkpoint — auto resume ถ้ามี ─────────────────────────────
        checkpoint    = GLPackCheckpoint.load(game_id)
        existing_pack = None
        to_translate  = self._extracted
        start_offset  = 0

        if checkpoint and checkpoint.string_count > 0:
            already_ids  = set(checkpoint.strings.keys())
            to_translate = [s for s in self._extracted
                            if s.id not in already_ids]
            existing_pack = checkpoint
            start_offset  = checkpoint.string_count

        # ── เริ่ม translation ────────────────────────────────────────────────
        n_new     = len(to_translate)
        bar_total = start_offset + n_new

        self._set_busy(True)
        self.translate_btn.setText("⟳  TRANSLATING...")
        self.prog_bar.setRange(0, bar_total)
        self.prog_bar.setValue(start_offset)
        self.prog_bar.setVisible(True)
        resume_note = f" (resume จาก {start_offset:,})" if start_offset else ""
        self.prog_log.setText(
            f"กำลังเตรียมแปล {n_new:,} strings{resume_note}...")

        w = TranslateAllWorker(
            self.selected_game["name"], engine,
            to_translate, self.game_context,
            existing_pack=existing_pack,
            start_offset=start_offset,
        )
        w.tick.connect(self._on_translate_tick)
        w.finished.connect(self._on_translated_all)
        w.start(); self._translate_worker = w

    def _on_translate_tick(self, current: int, total: int, msg: str):
        self.prog_bar.setMaximum(total)
        self.prog_bar.setValue(current)
        self.prog_log.setText(msg)

    def _on_translated_all(self, glpack_path: str):
        self._glpack_path = glpack_path
        ok = bool(glpack_path and os.path.exists(glpack_path))

        self.translate_btn.setEnabled(True)
        self.translate_btn.setText("▶  TRANSLATE ALL  →  .glpack")
        self.patch_btn.setEnabled(ok)
        pass  # scan context runs automatically
        self.extract_btn.setEnabled(True)
        self._update_rollback_btn()

        if ok:
            self.prog_bar.setValue(self.prog_bar.maximum())
            QTimer.singleShot(600, lambda: self.prog_bar.setVisible(False))
            self._update_stats()
        else:
            self.prog_bar.setVisible(False)
            QMessageBox.warning(self, "แปลล้มเหลว",
                                 "ไม่สามารถสร้าง .glpack ได้\n"
                                 "ตรวจสอบ ANTHROPIC_API_KEY")

    # ── Stage 4: Patch game ───────────────────────────────────────────────────
    def _on_patch(self):
        if not self._glpack_path or not os.path.exists(self._glpack_path):
            QMessageBox.warning(self, "ข้อผิดพลาด",
                                 "ไม่พบ .glpack — กรุณาแปลก่อน")
            return
        if not self.game_dir:
            QMessageBox.warning(self, "ข้อผิดพลาด",
                                 "กรุณาเลือกโฟลเดอร์เกมก่อน")
            return

        method = (self.detect_result.method if self.detect_result
                  else PatchMethod.OVERLAY)
        count  = len(self._extracted)

        dlg = WarningDialog(
            self.selected_game["name"], method,
            self.game_dir, count, self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self._set_busy(True)
        self.patch_btn.setText("⟳  PATCHING...")
        self.prog_bar.setRange(0, 0); self.prog_bar.setVisible(True)
        self.prog_log.setText("กำลัง patch ไฟล์เกม...")

        # Init rollback manager
        self._rollback_mgr = RollbackManager(
            self.game_dir, self.selected_game["name"]
        )
        self._rollback_mgr.begin_patch(glpack_id=os.path.basename(self._glpack_path))

        # Font bundle
        engine = (self.detect_result.engine.value if self.detect_result else "unknown")
        font_result = check_and_inject(
            self.game_dir, engine,
            progress=lambda m: self.prog_log.setText(m),
        )
        if font_result.font_paths:
            self._rollback_mgr.record_font(font_result.font_paths)

        w = PatchGlpackWorker(
            self._glpack_path, self.game_dir,
            self.selected_game["name"], method,
            self._rollback_mgr,
        )
        w.progress.connect(lambda m: self.prog_log.setText(m))
        w.finished.connect(self._on_patched)
        w.start(); self._patch_worker = w

    def _on_patched(self, msg: str):
        if hasattr(self, "_rollback_mgr"):
            self._rollback_mgr.save_manifest()

        self.patch_btn.setEnabled(True); self.patch_btn.setText("⚡  PATCH GAME")
        self.translate_btn.setEnabled(True)
        self.extract_btn.setEnabled(True)
        self.prog_bar.setRange(0, 100); self.prog_bar.setValue(100)
        QTimer.singleShot(600, lambda: self.prog_bar.setVisible(False))
        self._update_rollback_btn()
        self._update_stats()

        method = (self.detect_result.method if self.detect_result
                  else PatchMethod.OVERLAY)
        count  = len(self._extracted)
        dlg = PostPatchDialog(
            self.selected_game["name"], method,
            self.game_dir, count, parent=self,
        )
        dlg.exec()

        # Auto-upload .glpack ถ้ามี GitHub token
        self._start_pack_upload()

    def _start_pack_upload(self):
        """อัปโหลด .glpack ขึ้น GitHub ถ้ามี token — เงียบๆ ใน background"""
        token = _load_config().get("github_token", "").strip()
        if not token or not self._glpack_path:
            return
        if not os.path.exists(self._glpack_path):
            return

        # นับ string count จาก pack
        try:
            pack   = GLPackReader.load(self._glpack_path)
            n_str  = len(pack.strings)
        except Exception:
            n_str  = 0

        self.prog_bar.setRange(0, 0); self.prog_bar.setVisible(True)
        self.prog_log.setText("⬆ กำลังอัปโหลด Thai Pack ขึ้น GitHub...")

        w = PackUploadWorker(
            self._glpack_path,
            self.selected_game["name"],
            n_str, token,
        )
        w.progress.connect(lambda m: self.prog_log.setText(f"⬆ {m}"))
        w.finished.connect(self._on_pack_uploaded)
        w.start()
        self._upload_worker = w

    def _on_pack_uploaded(self, url: str):
        self.prog_bar.setRange(0, 100); self.prog_bar.setValue(100)
        QTimer.singleShot(800, lambda: self.prog_bar.setVisible(False))
        # Refresh manifest so community pack banner updates
        if url:
            self._fetch_pack_manifest()

    # ── Delete pack ───────────────────────────────────────────────────────────
    def _on_delete_pack(self):
        """ลบ .glpack และ checkpoint ของเกมนี้ → reset สถานะ"""
        if not self._glpack_path:
            return
        game_id = self.selected_game["name"].lower().replace(" ", "_")

        # ลบ .glpack
        try:
            if os.path.exists(self._glpack_path):
                os.remove(self._glpack_path)
        except Exception as e:
            QMessageBox.warning(self, "ลบไม่ได้", f"ลบ .glpack ล้มเหลว:\n{e}")
            return

        # ลบ checkpoint ด้วย (ถ้ามี)
        GLPackCheckpoint.clear(game_id)

        # Reset UI state
        self._glpack_path = ""
        self.patch_btn.setEnabled(False)
        self.translate_btn.setEnabled(bool(self._extracted))
        self.delete_pack_btn.setEnabled(False)
        self.prog_log.setText("🗑 ลบไฟล์แปลแล้ว — กด TRANSLATE ALL เพื่อแปลใหม่")
        self._update_stats()

    # ── Rollback ──────────────────────────────────────────────────────────────
    def _on_rollback(self):
        if not self.game_dir or not self.selected_game: return
        mgr = RollbackManager(self.game_dir, self.selected_game["name"])
        if not mgr.has_backup():
            QMessageBox.information(self, "Rollback", "ไม่พบ backup สำหรับเกมนี้")
            return

        info = mgr.get_backup_info()
        dlg  = RollbackDialog(
            self.selected_game["name"],
            info.get("patched_at","")[:19].replace("T"," "),
            info.get("file_count", 0),
            info.get("font_injected", False),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted: return

        self._set_busy(True)
        self.prog_bar.setRange(0, 0); self.prog_bar.setVisible(True)
        self.prog_log.setText("กำลังคืนค่า...")

        restored, errors = mgr.restore_all(
            progress=lambda m: self.prog_log.setText(m)
        )
        self.prog_bar.setRange(0, 100); self.prog_bar.setValue(100)
        QTimer.singleShot(600, lambda: self.prog_bar.setVisible(False))
        self._update_rollback_btn()
        self.patch_btn.setEnabled(bool(self._glpack_path))
        self.extract_btn.setEnabled(True)
        self.translate_btn.setEnabled(bool(self._extracted))
        pass  # scan context runs automatically

        if errors:
            QMessageBox.warning(
                self, "Rollback — มีข้อผิดพลาด",
                f"คืนค่า {restored} ไฟล์สำเร็จ\n" + "\n".join(errors),
            )
        else:
            QMessageBox.information(
                self, "Rollback สำเร็จ ✓",
                f"คืนค่าทั้งหมด {restored} ไฟล์กลับสู่สถานะเดิมแล้ว\n"
                "เปิดเกมได้เลย — ภาษากลับเป็นต้นฉบับ",
            )

    # ── Settings ──────────────────────────────────────────────────────────────
    def _open_settings(self):
        from PyQt6.QtWidgets import QDialog, QRadioButton, QGroupBox
        cfg = _load_config()

        dlg = QDialog(self); dlg.setWindowTitle("Settings")
        dlg.setFixedSize(400, 320)
        dlg.setStyleSheet(
            f"QDialog{{background:{NV_PANEL};border:1px solid {NV_BORDER};}}"
            f"QLabel{{color:{NV_TEXT};}}"
            f"QRadioButton{{color:#90b8f8;spacing:8px;}}"
            f"QLineEdit{{background:#0a0a18;border:1px solid #1e2456;"
            f"color:{NV_TEXT};padding:5px 8px;border-radius:2px;}}"
        )
        lay = QVBoxLayout(dlg); lay.setContentsMargins(22,20,22,20); lay.setSpacing(12)

        hdr = QLabel("⚙  SETTINGS")
        hdr.setStyleSheet(
            f"color:{NV_GREEN};font-size:10px;letter-spacing:4px;font-weight:bold;"
        )
        lay.addWidget(hdr)
        self._hline(lay)

        # ── Target language ────────────────────────────────────────────────
        ll = QLabel("TARGET LANGUAGE")
        ll.setStyleSheet(f"color:{NV_LABEL};font-size:9px;letter-spacing:3px;font-weight:bold;")
        lay.addWidget(ll)
        gb = QGroupBox(); gb.setStyleSheet(
            "QGroupBox{border:1px solid #1e2456;border-radius:2px;padding:8px;}")
        gl = QVBoxLayout(gb)
        rb_th = QRadioButton("ภาษาไทย  (default)"); rb_th.setChecked(True)
        more  = QLabel("   — เพิ่มภาษาเร็วๆ นี้")
        more.setStyleSheet("color:#2a3a2a;font-size:11px;")
        gl.addWidget(rb_th); gl.addWidget(more); lay.addWidget(gb)

        # ── GitHub PAT (สำหรับ auto-upload pack) ──────────────────────────
        gh_lbl = QLabel("GITHUB TOKEN  (สำหรับ auto-upload Thai Pack)")
        gh_lbl.setStyleSheet(f"color:{NV_LABEL};font-size:9px;letter-spacing:2px;font-weight:bold;")
        lay.addWidget(gh_lbl)

        gh_edit = QLineEdit()
        gh_edit.setPlaceholderText("ghp_xxxxxxxxxxxxxxxxxxxx")
        gh_edit.setEchoMode(QLineEdit.EchoMode.Password)
        gh_edit.setText(cfg.get("github_token", ""))
        gh_hint = QLabel("สร้างได้ที่ github.com/settings/tokens → repo scope")
        gh_hint.setStyleSheet(f"color:#2a3a4a;font-size:10px;")
        lay.addWidget(gh_edit); lay.addWidget(gh_hint)

        # ── Save ───────────────────────────────────────────────────────────
        def _save():
            cfg["github_token"] = gh_edit.text().strip()
            _save_config(cfg)
            dlg.accept()

        ok = QPushButton("✓  บันทึก"); ok.clicked.connect(_save)
        lay.addWidget(ok)
        dlg.exec()

    # ── Auto-update ───────────────────────────────────────────────────────────
    def _check_update_async(self):
        """ตรวจสอบ update ใน background ตอนเปิด app"""
        self._update_btn.setText("⟳  ตรวจสอบ...")
        self._update_btn.setEnabled(False)
        self._update_btn.setStyleSheet(self._update_btn_style_checking)

        if not HAS_REQUESTS:
            self._update_btn.setText(f"v{APP_VERSION}")
            self._update_btn.setEnabled(False)
            return

        w = UpdateChecker()
        w.update_available.connect(self._on_update_found)
        w.up_to_date.connect(self._on_up_to_date)
        w.start()
        self._update_checker = w   # เก็บไว้ไม่ให้ GC เก็บ

    def _on_update_found(self, info: UpdateInfo):
        self._update_info = info
        self._update_btn.setText(f"↑  UPDATE v{info.version}")
        self._update_btn.setEnabled(True)
        self._update_btn.setStyleSheet(self._update_btn_style_new)

    def _on_up_to_date(self):
        """เวอร์ชันล่าสุดแล้ว — แสดงปุ่มสีเทาพร้อม re-check เมื่อคลิก"""
        self._update_btn.setText(f"✓  v{APP_VERSION}  (ล่าสุด)")
        self._update_btn.setEnabled(True)
        self._update_btn.setStyleSheet(self._update_btn_style_ok)

    def _on_update_click(self):
        if self._update_info:
            dlg = UpdateDialog(self._update_info, parent=self)
            dlg.exec()
        else:
            # Re-check manually
            self._update_info = None
            self._check_update_async()

    # ── Utility ───────────────────────────────────────────────────────────────
    def _find_steam_dir(self, name):
        bases = []
        if sys.platform == "win32":
            bases = [
                "C:/Program Files (x86)/Steam/steamapps/common",
                "C:/Program Files/Steam/steamapps/common",
            ]
        elif sys.platform == "darwin":
            bases = [os.path.expanduser(
                "~/Library/Application Support/Steam/steamapps/common"
            )]
        else:
            h = os.path.expanduser("~")
            bases = [
                f"{h}/.steam/steam/steamapps/common",
                f"{h}/.local/share/Steam/steamapps/common",
            ]
        for b in bases:
            p = os.path.join(b, name)
            if os.path.isdir(p): return p
        return None


# ── Entry ─────────────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GameLang Translator")
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,           QColor(NV_BG))
    pal.setColor(QPalette.ColorRole.WindowText,       QColor(NV_TEXT))
    pal.setColor(QPalette.ColorRole.Base,             QColor(NV_PANEL))
    pal.setColor(QPalette.ColorRole.Text,             QColor(NV_TEXT))
    pal.setColor(QPalette.ColorRole.Button,           QColor(NV_PANEL))
    pal.setColor(QPalette.ColorRole.ButtonText,       QColor(NV_TEXT))
    pal.setColor(QPalette.ColorRole.Highlight,        QColor(NV_GREEN))
    pal.setColor(QPalette.ColorRole.HighlightedText,  QColor("#000"))
    app.setPalette(pal)
    win = MainWindow(); win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
