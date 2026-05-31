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
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QPixmap, QColor, QPalette, QIcon

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

from core.engine_detector import detect, PatchMethod, Engine
from core.font_bundle import check_and_inject
from core.rollback import RollbackManager
from core.extractor import extract_all, to_smart_translator_input, GameString
from core.glpack import GLPack, GLPackWriter, GLPackReader, build_glpack, GLPACK_DIR
from core.updater import (APP_VERSION, UpdateChecker, UpdateDownloader,
                          launch_installer_and_quit, UpdateInfo)

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

MOCK_GAMES = [
    {"appid": 1876890, "name": "Wandering Sword"},
    {"appid": 1245620, "name": "Elden Ring"},
    {"appid": 1091500, "name": "Cyberpunk 2077"},
    {"appid":  814380, "name": "Sekiro"},
    {"appid":     570, "name": "Dota 2"},
    {"appid":  292030, "name": "The Witcher 3"},
    {"appid": 1145360, "name": "Hades"},
    {"appid":  413150, "name": "Stardew Valley"},
]


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
    """Translate all extracted strings in batches, emit progress"""
    tick     = pyqtSignal(int, int, str)   # current, total, message
    finished = pyqtSignal(str)             # glpack_path  (empty = failed)

    def __init__(self, game_name: str, engine: str,
                 strings: list[GameString],
                 game_context: dict):
        super().__init__()
        self.game_name    = game_name
        self.engine       = engine
        self.strings      = strings
        self.game_context = game_context

    def run(self):
        total = len(self.strings)
        if total == 0:
            self.finished.emit("")
            return

        try:
            from core.translation_memory import SmartTranslator
            translator = SmartTranslator(
                game_id      = self.game_name.lower().replace(" ", "_"),
                game_context = self.game_context,
                speaker_roles= {},
            )
        except Exception as e:
            self.tick.emit(0, total, f"⚠ SmartTranslator error: {e}")
            self.finished.emit("")
            return

        CHUNK = 50
        results: list[str] = []
        done = 0

        for start in range(0, total, CHUNK):
            chunk   = self.strings[start:start + CHUNK]
            payload = to_smart_translator_input(chunk)
            try:
                chunk_results = translator.process_batch(payload)
                results.extend(chunk_results)
            except Exception as e:
                # Fallback: keep original text
                results.extend([s.text for s in chunk])

            done += len(chunk)
            pct  = int(done / total * 100)
            spk  = chunk[0].speaker or ""
            loc  = chunk[0].location or ""
            msg  = (f"กำลังแปล {done:,} / {total:,} strings ({pct}%)"
                    + (f" — {spk}" if spk else "")
                    + (f" [{loc}]" if loc else ""))
            self.tick.emit(done, total, msg)

        # Save .glpack
        try:
            pack = build_glpack(
                self.game_name, self.engine,
                self.strings, results,
            )
            save_path = pack.pack_path()
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            GLPackWriter.save(save_path, pack)
            self.tick.emit(total, total,
                           f"✓ บันทึก .glpack — {total:,} strings")
            self.finished.emit(save_path)
        except Exception as e:
            self.tick.emit(total, total, f"⚠ บันทึก .glpack ล้มเหลว: {e}")
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


def _md_to_simple(text: str) -> str:
    """แปลง Markdown อย่างง่ายเป็น plain text สำหรับ QLabel"""
    import re
    text = re.sub(r"#{1,6}\s*", "", text)          # ลบ headers
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)  # bold
    text = re.sub(r"\*(.+?)\*",   r"\1", text)     # italic
    text = re.sub(r"`(.+?)`",     r"\1", text)     # code
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


# ── Main Window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GameLang Translator v2")
        self.setMinimumSize(960, 680)
        self.setStyleSheet(STYLESHEET)

        # State
        self.selected_game  = None
        self.game_context   = {}
        self.detect_result  = None
        self.game_dir       = None
        self._extracted:    list[GameString] = []
        self._glpack_path:  str = ""
        self._update_info:  UpdateInfo | None = None

        self._build_ui()
        self._check_update_async()

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        rl   = QVBoxLayout(root); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        rl.addWidget(self._navbar())
        body = QWidget(); bl = QHBoxLayout(body)
        bl.setContentsMargins(0,0,0,0); bl.setSpacing(0)
        bl.addWidget(self._sidebar())
        bl.addWidget(self._main_area(), 1)
        rl.addWidget(body, 1)

    def _navbar(self):
        bar = QWidget(); bar.setFixedHeight(48)
        bar.setStyleSheet(f"background:#0f0f1e;border-bottom:1px solid {NV_BORDER};")
        lay = QHBoxLayout(bar); lay.setContentsMargins(20,0,20,0); lay.setSpacing(10)

        logo = QLabel("G"); logo.setFixedSize(22,22); logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {NV_GREEN},stop:1 #3050b0);color:#000;"
            f"font-weight:900;font-size:12px;border-radius:2px;"
        )
        nm  = QLabel("GameLang"); nm.setStyleSheet("color:#e0e8d8;font-size:13px;font-weight:800;")
        sub = QLabel("TRANSLATOR"); sub.setStyleSheet(f"color:{NV_LABEL};font-size:9px;letter-spacing:2px;")
        lay.addWidget(logo); lay.addWidget(nm); lay.addWidget(sub); lay.addStretch()

        # Version label
        ver_lbl = QLabel(f"v{APP_VERSION}")
        ver_lbl.setStyleSheet(f"color:{NV_LABEL};font-size:9px;letter-spacing:1px;")
        lay.addWidget(ver_lbl)

        # Update button — always visible, state changes based on check result
        self._update_btn = QPushButton("⟳  ตรวจสอบ...")
        self._update_btn.setFixedHeight(28)
        self._update_btn.setEnabled(False)   # disabled while checking
        self._update_btn_style_checking = (
            f"QPushButton{{background:transparent;border:1px solid #1e2456;"
            f"color:{NV_MUTED};border-radius:2px;font-size:9px;letter-spacing:1px;"
            f"font-weight:bold;padding:4px 12px;}}"
        )
        self._update_btn_style_ok = (
            f"QPushButton{{background:transparent;border:1px solid #1e2456;"
            f"color:{NV_LABEL};border-radius:2px;font-size:9px;letter-spacing:1px;"
            f"font-weight:bold;padding:4px 12px;}}"
            f"QPushButton:enabled:hover{{border-color:{NV_MUTED};color:{NV_MUTED};}}"
        )
        self._update_btn_style_new = (
            f"QPushButton{{background:rgba(56,189,248,0.1);border:1px solid {NV_CYAN};"
            f"color:{NV_CYAN};border-radius:2px;font-size:9px;letter-spacing:2px;"
            f"font-weight:bold;padding:4px 12px;}}"
            f"QPushButton:enabled:hover{{background:rgba(56,189,248,0.25);}}"
        )
        self._update_btn.setStyleSheet(self._update_btn_style_checking)
        self._update_btn.setVisible(True)
        self._update_btn.clicked.connect(self._on_update_click)
        lay.addWidget(self._update_btn)

        set_btn = QPushButton("⚙"); set_btn.setFixedSize(34,34)
        set_btn.clicked.connect(self._open_settings); lay.addWidget(set_btn)
        return bar

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
        for g in MOCK_GAMES:
            item = QListWidgetItem(g["name"])
            item.setData(Qt.ItemDataRole.UserRole, g)
            if HAS_REQUESTS:
                threading.Thread(target=self._load_icon,
                                 args=(item, g["appid"]), daemon=True).start()
            self.game_list.addItem(item)
        self.game_list.currentItemChanged.connect(self._on_game_selected)
        lay.addWidget(self.game_list, 1)

        self._hline(lay)
        ft = QLabel(f"  {len(MOCK_GAMES)} GAMES"); ft.setFixedHeight(28)
        ft.setStyleSheet("color:#2a3a2a;font-size:9px;letter-spacing:2px;padding-left:14px;")
        lay.addWidget(ft)
        return side

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

        # Hero image
        self.hero = QLabel(); self.hero.setFixedHeight(190)
        self.hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero.setStyleSheet(f"background:#0f0f1e;color:{NV_MUTED};")
        lay.addWidget(self.hero)

        # Scroll area
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;}")
        content = QWidget(); self.cl = QVBoxLayout(content)
        self.cl.setContentsMargins(24,20,24,24); self.cl.setSpacing(12)

        # ── Engine detect row ──────────────────────────────────────────────
        self.engine_row = QHBoxLayout(); self.engine_row.setSpacing(8)
        self.cl.addLayout(self.engine_row)

        # ── Context cards row ──────────────────────────────────────────────
        self.ctx_row = QHBoxLayout(); self.ctx_row.setSpacing(10)
        self.cl.addLayout(self.ctx_row)

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
        stage_row.addWidget(self.extract_btn, 2)

        self.scan_ctx_btn = QPushButton("⚙  SCAN CONTEXT")
        self.scan_ctx_btn.setEnabled(False); self.scan_ctx_btn.setFixedHeight(38)
        self.scan_ctx_btn.clicked.connect(self._on_scan_context)
        stage_row.addWidget(self.scan_ctx_btn, 1)

        self.cl.addLayout(stage_row)

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
        self.scan_ctx_btn.setEnabled(not busy)
        self.translate_btn.setEnabled(not busy)
        self.patch_btn.setEnabled(not busy)
        self.rollback_btn.setEnabled(not busy)

    def _update_stats(self):
        self._clear_layout(self.stats_row)
        count = len(self._extracted)
        if count:
            self.stats_row.addWidget(
                self._card("STRINGS", f"{count:,} strings", NV_GREEN)
            )
        if self._glpack_path and os.path.exists(self._glpack_path):
            size_mb = GLPackReader.file_size_mb(self._glpack_path)
            pack = GLPackReader.load(self._glpack_path)
            self.stats_row.addWidget(
                self._card(".glpack", f"{size_mb:.2f} MB · {pack.string_count:,} strings", NV_CYAN)
            )
            self.stats_row.addWidget(
                self._card("STATUS", "✓ พร้อม patch เกม", NV_PURPLE)
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
        self.game_dir      = self._find_steam_dir(self.selected_game["name"])

        self.stack.setCurrentIndex(1)
        self.extract_btn.setEnabled(bool(self.game_dir))
        self.scan_ctx_btn.setEnabled(True)
        self.translate_btn.setEnabled(False)
        self.patch_btn.setEnabled(False)
        self.prog_log.setText("")
        self.prog_bar.setVisible(False)

        self.hero.setText(f"  {self.selected_game['name']}")
        self.hero.setStyleSheet(
            f"background:#0f0f1e;color:#e0e8d8;font-size:22px;font-weight:bold;"
        )
        self.dir_label.setText(
            f"โฟลเดอร์เกม: {self.game_dir or '— (ไม่พบ กรุณาเลือกเอง)'}"
        )
        self._clear_layout(self.ctx_row)
        self._clear_layout(self.engine_row)
        self._clear_layout(self.stats_row)
        self._update_rollback_btn()

        if HAS_REQUESTS:
            threading.Thread(target=self._load_hero, daemon=True).start()

        # Auto-detect engine if folder found
        if self.game_dir:
            self._run_engine_detect()

    def _load_hero(self):
        try:
            url = (f"https://cdn.akamai.steamstatic.com/steam/apps/"
                   f"{self.selected_game['appid']}/header.jpg")
            r   = requests.get(url, timeout=4)
            pix = QPixmap(); pix.loadFromData(r.content)
            QTimer.singleShot(0, lambda: self.hero.setPixmap(
                pix.scaled(
                    self.hero.width(), self.hero.height(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            ))
        except Exception:
            pass

    def _pick_game_dir(self):
        d = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์เกม")
        if d:
            self.game_dir = d
            self.dir_label.setText(f"โฟลเดอร์เกม: {d}")
            self.extract_btn.setEnabled(True)
            self._run_engine_detect()

    def _run_engine_detect(self):
        self._clear_layout(self.engine_row)
        if not self.game_dir:
            return
        result = detect(self.game_dir)
        self.detect_result = result
        icon, label, color = METHOD_LABELS.get(result.method, ("?","Unknown","#aaa"))
        for c in [
            self._card("ENGINE DETECTED",
                       f"{result.engine.value.upper()} ({result.confidence*100:.0f}%)", color),
            self._card("PATCH METHOD", f"{icon} {label}", color),
            self._card("เหตุผล", result.reason, "#666"),
        ]:
            self.engine_row.addWidget(c)

    # ── Stage 1: Scan context (optional) ─────────────────────────────────────
    def _on_scan_context(self):
        if not self.selected_game: return
        self.scan_ctx_btn.setEnabled(False); self.scan_ctx_btn.setText("⟳  SCANNING...")
        self.prog_log.setText("กำลัง scan game context...")
        w = ScanWorker(self.selected_game)
        w.finished.connect(self._on_scan_ctx_done); w.start()
        self._scan_worker = w

    def _on_scan_ctx_done(self, ctx):
        self.game_context = ctx
        self.scan_ctx_btn.setEnabled(True); self.scan_ctx_btn.setText("⚙  SCAN CONTEXT")
        self._clear_layout(self.ctx_row)
        for label, key in [("WORLD","world"),("TONE","tone"),("REGISTER","register")]:
            self.ctx_row.addWidget(self._card(label, ctx.get(key,"—")))
        self.prog_log.setText("✓ Game context พร้อม — กด EXTRACT ได้เลย")

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
        self.scan_ctx_btn.setEnabled(True)
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

        engine  = (self.detect_result.engine.value if self.detect_result else "unknown")
        total   = len(self._extracted)

        self._set_busy(True)
        self.translate_btn.setText("⟳  TRANSLATING...")
        self.prog_bar.setRange(0, total); self.prog_bar.setValue(0)
        self.prog_bar.setVisible(True)
        self.prog_log.setText(f"กำลังเตรียมแปล {total:,} strings...")

        w = TranslateAllWorker(
            self.selected_game["name"], engine,
            self._extracted, self.game_context,
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
        self.scan_ctx_btn.setEnabled(True)
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
        self.scan_ctx_btn.setEnabled(True)
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
        self.scan_ctx_btn.setEnabled(True)

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
        dlg = QDialog(self); dlg.setWindowTitle("Settings"); dlg.setFixedSize(340,280)
        dlg.setStyleSheet(
            f"QDialog{{background:{NV_PANEL};border:1px solid {NV_BORDER};}}"
            f"QLabel{{color:{NV_TEXT};}}"
            f"QRadioButton{{color:#90b8f8;spacing:8px;}}"
        )
        lay = QVBoxLayout(dlg); lay.setContentsMargins(22,20,22,20); lay.setSpacing(12)
        hdr = QLabel("⚙  SETTINGS")
        hdr.setStyleSheet(
            f"color:{NV_GREEN};font-size:10px;letter-spacing:4px;font-weight:bold;"
        )
        lay.addWidget(hdr)
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{NV_BORDER};"); lay.addWidget(line)
        ll = QLabel("TARGET LANGUAGE")
        ll.setStyleSheet(
            f"color:{NV_LABEL};font-size:9px;letter-spacing:3px;font-weight:bold;"
        )
        lay.addWidget(ll)
        gb = QGroupBox(); gb.setStyleSheet(
            "QGroupBox{border:1px solid #1e2456;border-radius:2px;padding:8px;}"
        )
        gl = QVBoxLayout(gb)
        rb_th = QRadioButton("ภาษาไทย  (default)"); rb_th.setChecked(True)
        more  = QLabel("   — เพิ่มภาษาเร็วๆ นี้")
        more.setStyleSheet("color:#2a3a2a;font-size:11px;")
        gl.addWidget(rb_th); gl.addWidget(more); lay.addWidget(gb)
        ok = QPushButton("✓  บันทึก"); ok.clicked.connect(dlg.accept)
        lay.addWidget(ok); dlg.exec()

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
