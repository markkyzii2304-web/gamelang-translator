"""
engine_detector.py
ตรวจสอบ engine ของเกมจาก game directory
แล้วคืนค่า PatchStrategy ที่เหมาะสม
"""

import os
from enum import Enum
from dataclasses import dataclass
from typing import Optional


class Engine(Enum):
    UNITY       = "unity"
    UNREAL      = "unreal"
    GODOT       = "godot"
    RPGMAKER    = "rpgmaker"
    RENPY       = "renpy"
    UNKNOWN     = "unknown"


class PatchMethod(Enum):
    LOCALIZATION_FILE = "localization_file"   # patch .json/.csv/.xml/.yaml
    BEPINEX_MOD       = "bepinex_mod"         # Unity BepInEx
    RENPY_PATCH       = "renpy_patch"         # Ren'Py .rpy translation
    RPGMAKER_PATCH    = "rpgmaker_patch"      # RPG Maker .json data
    UE4_PAK           = "ue4_pak"             # Unreal Engine pak file modding
    OVERLAY           = "overlay"             # fallback: subtitle overlay


@dataclass
class DetectionResult:
    engine:       Engine
    method:       PatchMethod
    confidence:   float          # 0.0 – 1.0
    loc_files:    list[str]      # localization files found
    reason:       str            # human-readable explanation


# ── Signatures ────────────────────────────────────────────────────────────────
_ENGINE_SIGNATURES = {
    Engine.UNITY: [
        "UnityPlayer.dll", "UnityPlayer.so", "UnityPlayer.dylib",
        "globalgamemanagers", "data.unity3d",
    ],
    Engine.UNREAL: [
        "UE4Game.exe", "UE5Game.exe", "Engine/Binaries",
        "Content/Paks", "Manifest_DebugFiles_Win64.txt",
    ],
    Engine.GODOT: [
        "*.pck", "*.godot", "project.godot",
    ],
    Engine.RPGMAKER: [
        "www/data/Actors.json", "Game.rpgproject",
        "data/Actors.json", "nwjs.exe",
    ],
    Engine.RENPY: [
        "renpy/", "game/script.rpy", "game/options.rpy",
        "lib/py3-linux-x86_64/",
    ],
}

_LOC_EXTENSIONS = [".json", ".csv", ".xml", ".yaml", ".yml", ".po", ".pot", ".tsv"]
_LOC_DIR_HINTS  = ["localization", "locale", "lang", "language", "l10n", "i18n",
                   "text", "strings", "translations", "data/text"]


def detect(game_dir: str) -> DetectionResult:
    """Main entry — walk game_dir and return DetectionResult."""
    if not os.path.isdir(game_dir):
        return DetectionResult(Engine.UNKNOWN, PatchMethod.OVERLAY, 0.0, [],
                               "ไม่พบโฟลเดอร์เกม")

    all_files = _walk_files(game_dir, max_depth=5)
    engine, conf = _detect_engine(all_files, game_dir)
    loc_files    = _find_loc_files(all_files, game_dir)

    method, reason = _choose_method(engine, loc_files, game_dir)
    return DetectionResult(engine, method, conf, loc_files, reason)


# ── Internal helpers ──────────────────────────────────────────────────────────
def _walk_files(root: str, max_depth: int = 5) -> list[str]:
    result = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath.replace(root, "").count(os.sep)
        if depth > max_depth:
            dirnames.clear()
            continue
        for f in filenames:
            result.append(os.path.join(dirpath, f))
    return result


def _detect_engine(files: list[str], game_dir: str) -> tuple[Engine, float]:
    scores: dict[Engine, int] = {e: 0 for e in Engine}
    file_names = {os.path.basename(f).lower() for f in files}
    rel_paths   = {os.path.relpath(f, game_dir).replace("\\", "/").lower() for f in files}

    for engine, sigs in _ENGINE_SIGNATURES.items():
        for sig in sigs:
            sig_l = sig.lower()
            if sig_l.startswith("*"):
                ext = sig_l[1:]
                if any(f.endswith(ext) for f in file_names):
                    scores[engine] += 1
            elif "/" in sig_l:
                if any(sig_l in rp for rp in rel_paths):
                    scores[engine] += 2
            else:
                if sig_l in file_names:
                    scores[engine] += 2

    best  = max(scores, key=lambda e: scores[e])
    total = sum(scores.values()) or 1
    conf  = min(scores[best] / total, 1.0) if scores[best] > 0 else 0.0
    return (best if scores[best] > 0 else Engine.UNKNOWN, round(conf, 2))


def _find_loc_files(files: list[str], game_dir: str) -> list[str]:
    found = []
    for f in files:
        rel = os.path.relpath(f, game_dir).replace("\\", "/").lower()
        ext = os.path.splitext(f)[1].lower()
        in_loc_dir = any(hint in rel for hint in _LOC_DIR_HINTS)
        if ext in _LOC_EXTENSIONS and in_loc_dir:
            found.append(f)
    return found


def _choose_method(engine: Engine,
                   loc_files: list[str],
                   game_dir: str) -> tuple[PatchMethod, str]:
    # 1. Ren'Py — has own translation system
    if engine == Engine.RENPY:
        return (PatchMethod.RENPY_PATCH,
                "Ren'Py engine — ใช้ระบบ translation .rpy ของ engine")

    # 2. RPG Maker — JSON data files
    if engine == Engine.RPGMAKER:
        return (PatchMethod.RPGMAKER_PATCH,
                "RPG Maker engine — patch ไฟล์ JSON ใน www/data/")

    # 3. Unity — BepInEx mod (มีตัวเลือก Settings ได้)
    if engine == Engine.UNITY:
        return (PatchMethod.BEPINEX_MOD,
                "Unity/Mono engine — ติดตั้ง BepInEx mod เพิ่มตัวเลือกภาษาไทยใน Settings")

    # 3.5. Unreal Engine — pak file modding
    if engine == Engine.UNREAL:
        return (PatchMethod.UE4_PAK,
                "Unreal Engine — สร้าง patch _p.pak ที่มี .locres ภาษาไทย")

    # 4. Has localization files → patch directly
    if loc_files:
        return (PatchMethod.LOCALIZATION_FILE,
                f"พบไฟล์ localization {len(loc_files)} ไฟล์ — patch โดยตรง")

    # 5. Fallback
    return (PatchMethod.OVERLAY,
            "ไม่พบ localization file และ engine ไม่รองรับ mod — ใช้ Overlay layer แทน")
