"""
main.py — GameLang Translator v2
PyQt6 Desktop App | Cross-platform
"""

import sys
import os
import json
import threading

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QStackedWidget,
    QTextEdit, QDialog, QScrollArea, QFrame, QFileDialog,
    QMessageBox, QProgressBar
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
from core.patchers import get_patcher
from core.font_bundle import check_and_inject
from core.rollback import RollbackManager

# ── Theme ─────────────────────────────────────────────────────────────────────
NV_GREEN  = "#6b9eff"   # accent หลัก — น้ำเงินสดใส
NV_BG     = "#090912"   # พื้นหลังหลัก
NV_PANEL  = "#0f0f1e"   # panel หลัก
NV_BORDER = "#1e1e38"   # border
NV_TEXT   = "#e2e4f0"   # text หลัก — อ่านง่าย
NV_MUTED  = "#7880a8"   # text รอง — contrast พอดี
NV_LABEL  = "#5060a0"   # label/tag
NV_RED    = "#f06292"   # warning — ชมพูสว่าง
NV_CYAN   = "#38bdf8"   # accent ฟ้า
NV_PURPLE = "#a78bfa"   # accent ม่วง

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
QTextEdit {{ background:#14142a; border:1px solid #1e1e38;
  color:{NV_TEXT}; border-radius:2px; padding:8px; font-size:13px; }}
QTextEdit:focus {{ border-color:#6b9eff; }}
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
    finished = pyqtSignal(dict)
    def __init__(self, game): super().__init__(); self.game = game
    def run(self):
        if HAS_ANTHROPIC:
            try:
                client = anthropic.Anthropic()
                r = client.messages.create(
                    model="claude-opus-4-5", max_tokens=400,
                    messages=[{"role":"user","content":
                        f"Game '{self.game['name']}': return JSON only: "
                        "{world,era,tone,no_translate_terms[],register}"}])
                txt = r.content[0].text.strip().replace("```json","").replace("```","")
                self.finished.emit(json.loads(txt)); return
            except Exception: pass
        import time; time.sleep(1.2)
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


class TranslateWorker(QThread):
    finished = pyqtSignal(str)
    def __init__(self, text, ctx): super().__init__(); self.text=text; self.ctx=ctx
    def run(self):
        if HAS_ANTHROPIC:
            try:
                sys_p = (f"Translate EN→TH for game.\nWorld:{self.ctx.get('world','')}\n"
                         f"Tone:{self.ctx.get('tone','')}\nRegister:{self.ctx.get('register','')}\n"
                         f"Keep untranslated:{','.join(self.ctx.get('no_translate_terms',[]))}\n"
                         "Return Thai text only.")
                r = anthropic.Anthropic().messages.create(
                    model="claude-sonnet-4-20250514", max_tokens=800,
                    system=sys_p, messages=[{"role":"user","content":self.text}])
                self.finished.emit(r.content[0].text.strip()); return
            except Exception: pass
        import time; time.sleep(1.0)
        self.finished.emit("หนทางแห่งกระบี่นั้นยาวไกลนัก มีเพียงผู้ที่ฝืนทนเท่านั้น จึงจะบรรลุถึงยอดแห่งวิทยายุทธ์")


class PatchWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)
    def __init__(self, method, game_dir, game_name, translation,
                 no_translate, rollback_mgr=None):
        super().__init__()
        self.method=method; self.game_dir=game_dir; self.game_name=game_name
        self.translation=translation; self.no_translate=no_translate
        self.rollback_mgr=rollback_mgr
    def run(self):
        patcher = get_patcher(
            self.method, self.game_dir, self.game_name,
            self.translation, self.no_translate,
            progress=lambda m: self.progress.emit(m),
            rollback_mgr=self.rollback_mgr
        )
        result = patcher.apply()
        self.finished.emit(result)


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

        font_line = f"<br>🔤 Font ที่ inject: <b>{'จะถูกลบออก' if font_injected else 'ไม่มี'}</b>" if font_injected else ""
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
        cancel = QPushButton("ยกเลิก")
        cancel.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid #1e1e38;"
            "color:#4a5280;padding:9px 20px;font-size:11px;letter-spacing:2px;"
            "font-weight:bold;border-radius:2px;}"
        )
        confirm = QPushButton("↺  ยืนยัน — คืนค่าเดิม")
        confirm.setEnabled(True)
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)
        btn_row.addWidget(cancel); btn_row.addWidget(confirm)
        lay.addLayout(btn_row)


# ── Warning Dialog ────────────────────────────────────────────────────────────
class WarningDialog(QDialog):
    def __init__(self, game_name, method, game_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("คำเตือน — แก้ไขไฟล์เกม")
        self.setFixedWidth(500)
        self.setStyleSheet(f"QDialog{{background:{NV_PANEL};border:1px solid {NV_RED};}}"
                           f"QLabel{{color:{NV_TEXT};}}")
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
            f"แอปนี้จะ<b>{method_desc.get(method,'ดัดแปลงเกม')}</b> สำหรับ <b>{game_name}</b><br><br>"
            f"<b>โฟลเดอร์เกม:</b><br>"
            f"<span style='color:{NV_GREEN};font-size:11px;'>{game_dir}</span><br><br>"
            "⚠ ระบบจะสำรองไฟล์ต้นฉบับไว้ก่อนเสมอ (.bak)<br>"
            "⚠ ปิดเกมก่อนดำเนินการทุกครั้ง<br>"
            "⚠ การดัดแปลงนี้ใช้สำหรับเกม offline / co-op เท่านั้น"
        )
        detail.setWordWrap(True); detail.setStyleSheet("font-size:13px;line-height:1.6;")
        lay.addWidget(detail)

        note = QLabel("กด <b>ยอมรับ</b> เพื่อดำเนินการ หรือ <b>ยกเลิก</b> เพื่อออก")
        note.setStyleSheet(f"color:{NV_MUTED};font-size:11px;"); lay.addWidget(note)

        btn_row = QHBoxLayout(); btn_row.addStretch()
        cancel = QPushButton("✕  ยกเลิก")
        cancel.setStyleSheet(f"QPushButton{{background:transparent;border:1px solid #1a103a;"
                             f"color:{NV_RED};padding:9px 20px;font-size:11px;letter-spacing:2px;"
                             f"font-weight:bold;border-radius:2px;}}"
                             f"QPushButton:hover{{background:rgba(180,40,120,0.1);}}")
        accept = QPushButton("✓  ยอมรับ — ดำเนินการ")
        accept.setEnabled(True)
        cancel.clicked.connect(self.reject); accept.clicked.connect(self.accept)
        btn_row.addWidget(cancel); btn_row.addWidget(accept)
        lay.addLayout(btn_row)


# ── Main Window ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GameLang Translator v2")
        self.setMinimumSize(960, 660)
        self.setStyleSheet(STYLESHEET)

        self.selected_game  = None
        self.game_context   = None
        self.translation    = ""
        self.detect_result  = None
        self.game_dir       = None

        self._build_ui()

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        rl = QVBoxLayout(root); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        rl.addWidget(self._navbar())
        body_w = QWidget(); bl = QHBoxLayout(body_w)
        bl.setContentsMargins(0,0,0,0); bl.setSpacing(0)
        bl.addWidget(self._sidebar())
        bl.addWidget(self._main_area(), 1)
        rl.addWidget(body_w, 1)

    def _navbar(self):
        bar = QWidget(); bar.setFixedHeight(48)
        bar.setStyleSheet(f"background:#0f0f1e;border-bottom:1px solid {NV_BORDER};")
        lay = QHBoxLayout(bar); lay.setContentsMargins(20,0,20,0); lay.setSpacing(10)

        logo = QLabel("G"); logo.setFixedSize(22,22); logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                           f"stop:0 {NV_GREEN},stop:1 #3050b0);color:#000;"
                           f"font-weight:900;font-size:12px;border-radius:2px;")
        nm = QLabel("GameLang"); nm.setStyleSheet("color:#e0e8d8;font-size:13px;font-weight:800;")
        sub = QLabel("TRANSLATOR"); sub.setStyleSheet(f"color:{NV_LABEL};font-size:9px;letter-spacing:2px;")
        lay.addWidget(logo); lay.addWidget(nm); lay.addWidget(sub); lay.addStretch()

        self.scan_btn = QPushButton("◈  SCAN GAME"); self.scan_btn.setEnabled(False)
        self.scan_btn.setFixedHeight(32); self.scan_btn.clicked.connect(self._on_scan)
        lay.addWidget(self.scan_btn)

        set_btn = QPushButton("⚙"); set_btn.setFixedSize(34,34)
        set_btn.clicked.connect(self._open_settings); lay.addWidget(set_btn)
        return bar

    def _sidebar(self):
        side = QWidget(); side.setFixedWidth(210)
        side.setStyleSheet(f"background:#0f0f1e;border-right:1px solid {NV_BORDER};")
        lay = QVBoxLayout(side); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        hdr = QLabel("  MY LIBRARY"); hdr.setFixedHeight(36)
        hdr.setStyleSheet(f"color:{NV_LABEL};font-size:9px;letter-spacing:3px;"
                          f"font-weight:bold;padding-left:14px;")
        lay.addWidget(hdr)
        self._hline(lay)

        self.game_list = QListWidget(); self.game_list.setIconSize(QSize(28,28))
        for g in MOCK_GAMES:
            item = QListWidgetItem(g["name"])
            item.setData(Qt.ItemDataRole.UserRole, g)
            if HAS_REQUESTS:
                threading.Thread(target=self._load_icon, args=(item, g["appid"]),
                                 daemon=True).start()
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
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        self.hero = QLabel(); self.hero.setFixedHeight(190)
        self.hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero.setStyleSheet(f"background:#0f0f1e;color:{NV_MUTED};")
        lay.addWidget(self.hero)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;}")
        content = QWidget(); self.cl = QVBoxLayout(content)
        self.cl.setContentsMargins(24,20,24,24); self.cl.setSpacing(12)

        # Engine detect row
        self.engine_row = QHBoxLayout(); self.engine_row.setSpacing(8)
        self.cl.addLayout(self.engine_row)

        # Context cards
        self.ctx_row = QHBoxLayout(); self.ctx_row.setSpacing(10)
        self.cl.addLayout(self.ctx_row)

        # Game dir row
        dir_row = QHBoxLayout(); dir_row.setSpacing(8)
        self.dir_label = QLabel("โฟลเดอร์เกม: —")
        self.dir_label.setStyleSheet(f"color:{NV_MUTED};font-size:11px;")
        dir_btn = QPushButton("📁  เลือกโฟลเดอร์"); dir_btn.setEnabled(True)
        dir_btn.clicked.connect(self._pick_game_dir)
        dir_row.addWidget(self.dir_label, 1); dir_row.addWidget(dir_btn)
        self.cl.addLayout(dir_row)

        # Input
        in_lbl = QLabel("SOURCE TEXT (EN)")
        in_lbl.setStyleSheet(f"color:{NV_LABEL};font-size:9px;letter-spacing:3px;font-weight:bold;")
        self.cl.addWidget(in_lbl)
        self.input_text = QTextEdit(); self.input_text.setFixedHeight(100)
        self.input_text.setPlaceholderText("Paste in-game English text here...")
        self.cl.addWidget(self.input_text)

        # Translate + Rollback buttons row
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self.trans_btn = QPushButton("▶  TRANSLATE & PATCH GAME FILE")
        self.trans_btn.setEnabled(False); self.trans_btn.setFixedHeight(40)
        self.trans_btn.clicked.connect(self._on_translate)
        btn_row.addWidget(self.trans_btn, 1)

        self.rollback_btn = QPushButton("↺  ROLLBACK")
        self.rollback_btn.setEnabled(False)
        self.rollback_btn.setFixedHeight(40); self.rollback_btn.setFixedWidth(120)
        self.rollback_btn.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid #1a103a;"
            "color:#a78bfa;border-radius:2px;font-size:10px;letter-spacing:2px;"
            "font-weight:bold;padding:7px 12px;}"
            "QPushButton:enabled:hover{background:rgba(150,80,200,0.12);}"
            "QPushButton:disabled{border-color:#1e1e1e;color:#2a2a2a;}"
        )
        self.rollback_btn.clicked.connect(self._on_rollback)
        btn_row.addWidget(self.rollback_btn)
        self.cl.addLayout(btn_row)

        # Progress bar
        self.prog_bar = QProgressBar(); self.prog_bar.setRange(0,0)
        self.prog_bar.setFixedHeight(4); self.prog_bar.setVisible(False)
        self.cl.addWidget(self.prog_bar)

        # Progress log
        self.prog_log = QLabel(""); self.prog_log.setStyleSheet(f"color:{NV_MUTED};font-size:11px;")
        self.cl.addWidget(self.prog_log)

        # Output
        out_lbl = QLabel("TRANSLATION OUTPUT")
        out_lbl.setStyleSheet(f"color:{NV_LABEL};font-size:9px;letter-spacing:3px;font-weight:bold;")
        self.cl.addWidget(out_lbl)
        self.output_text = QTextEdit(); self.output_text.setReadOnly(True)
        self.output_text.setFixedHeight(90)
        self.output_text.setPlaceholderText("ผลการแปลจะแสดงที่นี่...")
        self.cl.addWidget(self.output_text)
        self.cl.addStretch()

        scroll.setWidget(content); lay.addWidget(scroll, 1)
        return w

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _hline(self, lay):
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{NV_BORDER};"); lay.addWidget(line)

    def _card(self, label, value, color=NV_GREEN):
        card = QWidget()
        card.setStyleSheet(f"QWidget{{background:{NV_PANEL};border:1px solid #1e2456;"
                           f"border-top:2px solid {color};border-radius:2px;}}")
        lay = QVBoxLayout(card); lay.setContentsMargins(12,10,12,10)
        lb = QLabel(label); lb.setStyleSheet(f"color:{NV_LABEL};font-size:8px;"
                                              f"letter-spacing:2px;font-weight:bold;border:none;")
        vl = QLabel(value); vl.setStyleSheet(f"color:#90b8f8;font-size:11px;border:none;")
        vl.setWordWrap(True); lay.addWidget(lb); lay.addWidget(vl)
        return card

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def _load_icon(self, item, appid):
        try:
            url = f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"
            r = requests.get(url, timeout=3); pix = QPixmap()
            pix.loadFromData(r.content)
            icon = QIcon(pix.scaled(28,28,Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                    Qt.TransformationMode.SmoothTransformation))
            QTimer.singleShot(0, lambda: item.setIcon(icon))
        except Exception: pass

    # ── Events ────────────────────────────────────────────────────────────────
    def _on_game_selected(self, current, _):
        if not current: return
        self.selected_game = current.data(Qt.ItemDataRole.UserRole)
        self.game_context = None; self.detect_result = None
        self.game_dir = self._find_steam_dir(self.selected_game["name"])
        self.stack.setCurrentIndex(1)
        self.scan_btn.setEnabled(True); self.scan_btn.setText("◈  SCAN GAME")
        self.trans_btn.setEnabled(False); self.output_text.clear()
        self.input_text.clear(); self.prog_log.setText("")
        self.hero.setText(f"  {self.selected_game['name']}")
        self.hero.setStyleSheet(f"background:#0f0f1e;color:#e0e8d8;font-size:22px;font-weight:bold;")
        self.dir_label.setText(f"โฟลเดอร์เกม: {self.game_dir or '— (ไม่พบ กรุณาเลือกเอง)'}")
        self._clear_layout(self.ctx_row); self._clear_layout(self.engine_row)
        self._update_rollback_btn()
        if HAS_REQUESTS:
            threading.Thread(target=self._load_hero, daemon=True).start()

    def _load_hero(self):
        try:
            url = f"https://cdn.akamai.steamstatic.com/steam/apps/{self.selected_game['appid']}/header.jpg"
            r = requests.get(url, timeout=4); pix = QPixmap(); pix.loadFromData(r.content)
            QTimer.singleShot(0, lambda: self.hero.setPixmap(
                pix.scaled(self.hero.width(), self.hero.height(),
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)))
        except Exception: pass

    def _pick_game_dir(self):
        d = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์เกม")
        if d:
            self.game_dir = d
            self.dir_label.setText(f"โฟลเดอร์เกม: {d}")
            # Re-detect engine
            if self.game_context:
                self._run_engine_detect()

    def _on_scan(self):
        if not self.selected_game: return
        self.scan_btn.setEnabled(False); self.scan_btn.setText("⟳  SCANNING...")
        self._clear_layout(self.ctx_row); self._clear_layout(self.engine_row)
        w = ScanWorker(self.selected_game); w.finished.connect(self._on_scan_done); w.start()
        self._scan_worker = w

    def _on_scan_done(self, ctx):
        self.game_context = ctx
        self.scan_btn.setEnabled(True); self.scan_btn.setText("✓  SCAN AGAIN")
        self._clear_layout(self.ctx_row)
        for label, key in [("WORLD","world"),("TONE","tone"),("REGISTER","register")]:
            self.ctx_row.addWidget(self._card(label, ctx.get(key,"—")))

        # Engine detect
        self._run_engine_detect()
        self.trans_btn.setEnabled(True)

    def _run_engine_detect(self):
        self._clear_layout(self.engine_row)
        if not self.game_dir:
            badge = self._card("ENGINE", "ไม่พบโฟลเดอร์ — เลือกโฟลเดอร์เกม", "#555")
            self.engine_row.addWidget(badge); return

        result = detect(self.game_dir)
        self.detect_result = result

        icon, label, color = METHOD_LABELS.get(result.method, ("?","Unknown","#aaa"))
        eng_card  = self._card("ENGINE DETECTED", f"{result.engine.value.upper()} ({result.confidence*100:.0f}%)", color)
        meth_card = self._card("PATCH METHOD", f"{icon} {label}", color)
        why_card  = self._card("เหตุผล", result.reason, "#666")
        for c in [eng_card, meth_card, why_card]:
            self.engine_row.addWidget(c)

    def _on_translate(self):
        text = self.input_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self,"ข้อผิดพลาด","กรุณาใส่ข้อความก่อน"); return
        if not self.game_dir:
            QMessageBox.warning(self,"ข้อผิดพลาด","กรุณาเลือกโฟลเดอร์เกมก่อน"); return

        method = self.detect_result.method if self.detect_result else PatchMethod.OVERLAY
        dlg = WarningDialog(self.selected_game["name"], method, self.game_dir, self)
        if dlg.exec() != QDialog.DialogCode.Accepted: return

        self.trans_btn.setEnabled(False); self.trans_btn.setText("⟳  TRANSLATING...")
        self.prog_bar.setVisible(True); self.prog_log.setText("กำลังแปล...")

        w = TranslateWorker(text, self.game_context or {})
        w.finished.connect(self._on_translated); w.start(); self._trans_worker = w

    def _on_translated(self, result):
        self.translation = result
        self.output_text.setPlainText(result)
        self.prog_log.setText("แปลสำเร็จ — กำลัง patch ไฟล์...")

        method  = self.detect_result.method if self.detect_result else PatchMethod.OVERLAY
        no_tr   = (self.game_context or {}).get("no_translate_terms", [])
        engine  = self.detect_result.engine.value if self.detect_result else "unknown"

        # ── Init Rollback Manager ──────────────────────────────────────────
        self._rollback_mgr = RollbackManager(self.game_dir, self.selected_game["name"])
        self._rollback_mgr.begin_patch(glpack_id="local")

        # ── Font Bundle ────────────────────────────────────────────────────
        self.prog_log.setText("ตรวจสอบ Thai font...")
        font_result = check_and_inject(
            self.game_dir, engine,
            progress=lambda m: self.prog_log.setText(m)
        )
        if font_result.font_paths:
            self._rollback_mgr.record_font(font_result.font_paths)

        # ── Patch ──────────────────────────────────────────────────────────
        w = PatchWorker(method, self.game_dir, self.selected_game["name"],
                        result, no_tr, self._rollback_mgr)
        w.progress.connect(lambda m: self.prog_log.setText(m))
        w.finished.connect(self._on_patched)
        w.start()
        self._patch_worker = w

    def _on_patched(self, msg):
        # บันทึก manifest ก่อนเสมอ
        if hasattr(self, "_rollback_mgr"):
            self._rollback_mgr.save_manifest()
            self._update_rollback_btn()

        self.trans_btn.setEnabled(True)
        self.trans_btn.setText("▶  TRANSLATE & PATCH GAME FILE")
        self.prog_bar.setVisible(False)
        self.prog_log.setText("✓ เสร็จสิ้น")
        QMessageBox.information(self, "Patch สำเร็จ ✓", msg)

    def _update_rollback_btn(self):
        """แสดง/ซ่อนปุ่ม Rollback ตามสถานะ backup"""
        if not hasattr(self, "rollback_btn"): return
        mgr = RollbackManager(self.game_dir, self.selected_game["name"]) \
              if self.game_dir and self.selected_game else None
        has_bak = mgr.has_backup() if mgr else False
        self.rollback_btn.setEnabled(has_bak)
        self.rollback_btn.setVisible(True)
        if has_bak:
            info = mgr.get_backup_info()
            self.rollback_btn.setToolTip(
                f"Patched: {info.get('patched_at','')[:10]}\n"
                f"Files: {info.get('file_count',0)}\n"
                f"Font injected: {info.get('font_injected',False)}"
            )

    def _on_rollback(self):
        """Full restore — คืนค่าทั้งหมดกลับสู่สถานะเดิม"""
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
            parent=self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted: return

        self.prog_bar.setVisible(True)
        self.prog_log.setText("กำลังคืนค่า...")
        restored, errors = mgr.restore_all(
            progress=lambda m: self.prog_log.setText(m)
        )
        self.prog_bar.setVisible(False)
        self._update_rollback_btn()

        if errors:
            QMessageBox.warning(self, "Rollback — มีข้อผิดพลาด",
                f"คืนค่า {restored} ไฟล์สำเร็จ\nข้อผิดพลาด:\n" + "\n".join(errors))
        else:
            QMessageBox.information(self, "Rollback สำเร็จ ✓",
                f"คืนค่าทั้งหมด {restored} ไฟล์กลับสู่สถานะเดิมแล้ว\n"
                "เปิดเกมได้เลย — ภาษากลับเป็นต้นฉบับ")

    def _find_steam_dir(self, name):
        bases = []
        if sys.platform == "win32":
            bases = ["C:/Program Files (x86)/Steam/steamapps/common",
                     "C:/Program Files/Steam/steamapps/common"]
        elif sys.platform == "darwin":
            bases = [os.path.expanduser("~/Library/Application Support/Steam/steamapps/common")]
        else:
            h = os.path.expanduser("~")
            bases = [f"{h}/.steam/steam/steamapps/common",
                     f"{h}/.local/share/Steam/steamapps/common"]
        for b in bases:
            p = os.path.join(b, name)
            if os.path.isdir(p): return p
        return None

    def _open_settings(self):
        from PyQt6.QtWidgets import QDialog, QRadioButton, QGroupBox
        dlg = QDialog(self); dlg.setWindowTitle("Settings"); dlg.setFixedSize(340,280)
        dlg.setStyleSheet(f"QDialog{{background:{NV_PANEL};border:1px solid {NV_BORDER};}}"
                          f"QLabel{{color:{NV_TEXT};}}"
                          f"QRadioButton{{color:#90b8f8;spacing:8px;}}")
        lay = QVBoxLayout(dlg); lay.setContentsMargins(22,20,22,20); lay.setSpacing(12)
        hdr = QLabel("⚙  SETTINGS")
        hdr.setStyleSheet(f"color:{NV_GREEN};font-size:10px;letter-spacing:4px;font-weight:bold;")
        lay.addWidget(hdr)
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{NV_BORDER};"); lay.addWidget(line)

        ll = QLabel("TARGET LANGUAGE")
        ll.setStyleSheet(f"color:{NV_LABEL};font-size:9px;letter-spacing:3px;font-weight:bold;")
        lay.addWidget(ll)
        gb = QGroupBox(); gb.setStyleSheet("QGroupBox{border:1px solid #1e2456;border-radius:2px;padding:8px;}")
        gl = QVBoxLayout(gb)
        rb_th = QRadioButton("ภาษาไทย  (default)"); rb_th.setChecked(True)
        more  = QLabel("   — เพิ่มภาษาเร็วๆ นี้"); more.setStyleSheet("color:#2a3a2a;font-size:11px;")
        gl.addWidget(rb_th); gl.addWidget(more); lay.addWidget(gb)

        ok = QPushButton("✓  บันทึก"); ok.setEnabled(True)
        ok.clicked.connect(dlg.accept); lay.addWidget(ok)
        dlg.exec()


# ── Entry ─────────────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GameLang Translator")
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,        QColor(NV_BG))
    pal.setColor(QPalette.ColorRole.WindowText,    QColor(NV_TEXT))
    pal.setColor(QPalette.ColorRole.Base,          QColor(NV_PANEL))
    pal.setColor(QPalette.ColorRole.Text,          QColor(NV_TEXT))
    pal.setColor(QPalette.ColorRole.Button,        QColor(NV_PANEL))
    pal.setColor(QPalette.ColorRole.ButtonText,    QColor(NV_TEXT))
    pal.setColor(QPalette.ColorRole.Highlight,     QColor(NV_GREEN))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#000"))
    app.setPalette(pal)
    win = MainWindow(); win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
