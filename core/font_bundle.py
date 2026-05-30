"""
font_bundle.py
ตรวจสอบ font ภาษาไทยในเกม และ inject Thai font subset ถ้าไม่มี
รองรับ Unity, RPG Maker, Ren'Py, และ font folder ทั่วไป
"""

import os
import shutil
import urllib.request
from dataclasses import dataclass

# Google Noto Sans Thai — subset ขนาดเล็ก (ฟรี, open license)
FONT_URL  = "https://fonts.gstatic.com/s/notosansthai/v25/iJWnBXeUZi_OHPqn4wq6hQ2_hbJ1xyN9wd43SofCRiE.woff2"
FONT_NAME = "NotoSansThai.woff2"
FONT_TTF_URL  = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansThai/NotoSansThai-Regular.ttf"
FONT_TTF_NAME = "NotoSansThai-Regular.ttf"

THAI_RANGE = range(0x0E00, 0x0E7F)  # Unicode Thai block

@dataclass
class FontCheckResult:
    has_thai_font: bool
    font_paths:    list[str]   # existing Thai fonts found
    inject_dirs:   list[str]   # dirs where font should be injected
    engine:        str


def check_and_inject(game_dir: str, engine: str,
                     progress=None) -> FontCheckResult:
    """ตรวจสอบและ inject Thai font ถ้าจำเป็น"""
    log = progress or (lambda m: None)

    existing = _find_thai_fonts(game_dir)
    inject_dirs = _get_font_dirs(game_dir, engine)

    if existing:
        log(f"พบ Thai font อยู่แล้ว: {len(existing)} ไฟล์")
        return FontCheckResult(True, existing, inject_dirs, engine)

    log("ไม่พบ Thai font — กำลัง inject...")
    injected = []
    ttf_path = _download_font(game_dir, log)

    if ttf_path:
        for d in inject_dirs:
            os.makedirs(d, exist_ok=True)
            dest = os.path.join(d, FONT_TTF_NAME)
            shutil.copy2(ttf_path, dest)
            injected.append(dest)
            log(f"Inject font → {os.path.relpath(dest, game_dir)}")

        # Engine-specific font registration
        _register_font(game_dir, engine, ttf_path, inject_dirs, log)

    return FontCheckResult(bool(injected), injected, inject_dirs, engine)


def _find_thai_fonts(game_dir: str) -> list[str]:
    found = []
    for dirpath, _, files in os.walk(game_dir):
        depth = dirpath.replace(game_dir, "").count(os.sep)
        if depth > 6:
            continue
        for f in files:
            fl = f.lower()
            if any(kw in fl for kw in ["thai","noto","th_","_th."]) and \
               fl.endswith((".ttf",".otf",".woff",".woff2")):
                found.append(os.path.join(dirpath, f))
    return found


def _get_font_dirs(game_dir: str, engine: str) -> list[str]:
    """คืน directories ที่ควร inject font ตาม engine"""
    candidates = {
        "unity":    ["Assets/StreamingAssets/Fonts", "Assets/Fonts",
                     "GameData/Fonts"],
        "renpy":    ["game/fonts"],
        "rpgmaker": ["www/fonts", "fonts"],
        "unknown":  ["fonts", "data/fonts", "resources/fonts"],
    }
    dirs = candidates.get(engine, candidates["unknown"])
    # เพิ่ม common font dirs เสมอ
    dirs += ["fonts", "data/fonts"]
    return list({os.path.join(game_dir, d) for d in dirs})


def _download_font(game_dir: str, log) -> str | None:
    """ดาวน์โหลด NotoSansThai.ttf ไปเก็บ temp"""
    tmp = os.path.join(game_dir, "_gamelang_font_tmp")
    os.makedirs(tmp, exist_ok=True)
    dest = os.path.join(tmp, FONT_TTF_NAME)
    if os.path.exists(dest):
        return dest
    try:
        log("ดาวน์โหลด NotoSansThai font...")
        urllib.request.urlretrieve(FONT_TTF_URL, dest)
        log("ดาวน์โหลด font สำเร็จ")
        return dest
    except Exception as e:
        log(f"⚠ ดาวน์โหลด font ล้มเหลว: {e}")
        return None


def _register_font(game_dir: str, engine: str, font_path: str,
                   inject_dirs: list[str], log):
    """ลงทะเบียน font ใน engine config ถ้าทำได้"""
    if engine == "renpy":
        opts = os.path.join(game_dir, "game", "options.rpy")
        if os.path.exists(opts):
            with open(opts, "r", encoding="utf-8") as f:
                content = f.read()
            if FONT_TTF_NAME not in content:
                content += f'\n## GameLang Thai Font\ndefine gui.text_font = "fonts/{FONT_TTF_NAME}"\n'
                with open(opts, "w", encoding="utf-8") as f:
                    f.write(content)
                log("ลงทะเบียน font ใน Ren'Py options.rpy")

    elif engine == "rpgmaker":
        # RPG Maker MZ uses CSS-like font stack in js/
        js_dir = os.path.join(game_dir, "js")
        if os.path.isdir(js_dir):
            for js_file in ["rmmz_core.js", "main.js"]:
                js_path = os.path.join(js_dir, js_file)
                if os.path.exists(js_path):
                    with open(js_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    if "NotoSansThai" not in content:
                        # Prepend Thai font to font-family stack
                        content = content.replace(
                            '"GameFont"',
                            '"NotoSansThai-Regular", "GameFont"'
                        )
                        with open(js_path, "w", encoding="utf-8") as f:
                            f.write(content)
                        log(f"ลงทะเบียน font ใน {js_file}")
                    break
