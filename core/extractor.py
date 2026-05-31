"""
extractor.py — GameLang Translator
Extract all translatable strings from game files before translation.
No API calls — pure file reading.
"""

import os
import re
import json
import csv
from dataclasses import dataclass
from typing import Optional


# ── Data class ────────────────────────────────────────────────────────────────
@dataclass
class GameString:
    id:       str              # unique: "rel/path/file.json::key.path[0]"
    text:     str              # original English text
    file:     str              # relative file path
    location: str              # scene/category hint
    speaker:  Optional[str] = None


# ── Main entry ────────────────────────────────────────────────────────────────
def extract_all(game_dir: str, engine: str,
                progress=None) -> list[GameString]:
    """
    Extract all translatable strings from game_dir based on engine type.
    Returns list[GameString] sorted by file.
    """
    log = progress or (lambda m: None)
    e   = engine.lower()

    if "rpgmaker" in e:
        return _extract_rpgmaker(game_dir, log)
    elif "renpy" in e:
        return _extract_renpy(game_dir, log)
    elif "unity" in e:
        return _extract_localization(game_dir, log)
    else:
        return _extract_generic(game_dir, log)


# ── RPG Maker MV/MZ ───────────────────────────────────────────────────────────
def _extract_rpgmaker(game_dir: str, log) -> list[GameString]:
    """Extract from RPG Maker JSON data files in www/data/ or data/"""
    results: list[GameString] = []

    data_dirs = [
        os.path.join(game_dir, "www", "data"),
        os.path.join(game_dir, "data"),
    ]

    for data_dir in data_dirs:
        if not os.path.isdir(data_dir):
            continue
        files = sorted(f for f in os.listdir(data_dir) if f.endswith(".json"))
        for fname in files:
            fpath = os.path.join(data_dir, fname)
            rel   = os.path.relpath(fpath, game_dir).replace("\\", "/")
            try:
                with open(fpath, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                before = len(results)
                _walk_json(data, fname.replace(".json", ""), rel,
                           results, _guess_rpg_location(fname))
                count = len(results) - before
                if count:
                    log(f"  {fname}: {count} strings")
            except Exception as e:
                log(f"  ข้าม {fname}: {e}")
        break   # ใช้แค่ dir แรกที่เจอ

    log(f"RPG Maker: รวม {len(results)} strings")
    return results


def _guess_rpg_location(fname: str) -> str:
    f = fname.lower()
    if "map" in f:          return "map"
    if "actor" in f:        return "character"
    if "common" in f:       return "dialogue"
    if "item" in f or "weapon" in f or "armor" in f: return "item"
    if "skill" in f:        return "skill"
    if "system" in f:       return "ui"
    if "enemy" in f:        return "enemy"
    if "state" in f:        return "status"
    if "class" in f:        return "class"
    return "unknown"


# ── Ren'Py ────────────────────────────────────────────────────────────────────
def _extract_renpy(game_dir: str, log) -> list[GameString]:
    """Extract dialogue from Ren'Py .rpy files (skip tl/ directories)"""
    results: list[GameString] = []

    game_subdir = os.path.join(game_dir, "game")
    search_root = game_subdir if os.path.isdir(game_subdir) else game_dir

    for dirpath, dirnames, files in os.walk(search_root):
        # Skip translation dirs
        dirnames[:] = [d for d in dirnames
                       if d.lower() not in ("tl", "translations")]
        for fname in sorted(files):
            if not fname.endswith(".rpy"):
                continue
            fpath = os.path.join(dirpath, fname)
            rel   = os.path.relpath(fpath, game_dir).replace("\\", "/")
            try:
                before = len(results)
                _parse_rpy_file(fpath, rel, results)
                count = len(results) - before
                if count:
                    log(f"  {fname}: {count} strings")
            except Exception as e:
                log(f"  ข้าม {fname}: {e}")

    log(f"Ren'Py: รวม {len(results)} strings")
    return results


def _parse_rpy_file(fpath: str, rel: str,
                    results: list[GameString]):
    """Parse a single .rpy file for translatable strings"""
    DIALOGUE_RE  = re.compile(r'^[ \t]*(\w+)\s+"((?:[^"\\]|\\.)+)"')
    NARRATION_RE = re.compile(r'^[ \t]*"((?:[^"\\]|\\.)+)"')
    LABEL_RE     = re.compile(r'^label\s+(\w+):')
    MENU_RE      = re.compile(r'^[ \t]+"((?:[^"\\]|\\.)+)":')

    # Keywords that introduce non-dialogue lines
    NON_SPEAKERS = {
        "define","default","image","show","hide","play","stop",
        "scene","init","python","call","jump","return","pass",
        "menu","voice","pause","window","nvl","transform",
    }

    current_label = "script"

    with open(fpath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        lm = LABEL_RE.match(line)
        if lm:
            current_label = lm.group(1)
            continue

        dm = DIALOGUE_RE.match(line)
        if dm:
            spk, text = dm.group(1), dm.group(2)
            if spk not in NON_SPEAKERS and _is_translatable(text):
                results.append(GameString(
                    id=f"{rel}::L{i+1}",
                    text=_unescape(text), file=rel,
                    location=current_label, speaker=spk,
                ))
            continue

        mm = MENU_RE.match(line)
        if mm:
            text = mm.group(1)
            if _is_translatable(text):
                results.append(GameString(
                    id=f"{rel}::L{i+1}",
                    text=_unescape(text), file=rel,
                    location=current_label,
                ))
            continue

        nm = NARRATION_RE.match(line)
        if nm:
            text = nm.group(1)
            if _is_translatable(text):
                results.append(GameString(
                    id=f"{rel}::L{i+1}",
                    text=_unescape(text), file=rel,
                    location=current_label,
                ))


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")


# ── Localization files (Unity / Generic) ─────────────────────────────────────
def _extract_localization(game_dir: str, log) -> list[GameString]:
    """Extract from localization files found via engine_detector helpers"""
    from core.engine_detector import _find_loc_files, _walk_files
    results: list[GameString] = []

    all_files = _walk_files(game_dir, max_depth=6)
    loc_files = _find_loc_files(all_files, game_dir)

    for fpath in loc_files:
        rel = os.path.relpath(fpath, game_dir).replace("\\", "/")
        ext = os.path.splitext(fpath)[1].lower()
        try:
            before = len(results)
            if ext == ".json":
                _extract_json_file(fpath, rel, results)
            elif ext == ".csv":
                _extract_csv_file(fpath, rel, results)
            elif ext in (".yaml", ".yml"):
                _extract_yaml_file(fpath, rel, results)
            count = len(results) - before
            if count:
                log(f"  {os.path.basename(fpath)}: {count} strings")
        except Exception as e:
            log(f"  ข้าม {os.path.basename(fpath)}: {e}")

    log(f"Localization: รวม {len(results)} strings")
    return results


def _extract_generic(game_dir: str, log) -> list[GameString]:
    """Generic fallback — scan all JSON/CSV in game dir"""
    log("Generic extraction mode...")
    return _extract_localization(game_dir, log)


# ── File-level parsers ────────────────────────────────────────────────────────
def _extract_json_file(fpath: str, rel: str,
                       results: list[GameString]):
    with open(fpath, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    prefix = os.path.basename(rel).replace(".json", "")
    _walk_json(data, prefix, rel, results, "localization")


def _extract_csv_file(fpath: str, rel: str,
                      results: list[GameString]):
    with open(fpath, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            for col, val in (row or {}).items():
                if val and _is_translatable(val):
                    results.append(GameString(
                        id=f"{rel}::row{i}::{col}",
                        text=val, file=rel, location=col,
                    ))


def _extract_yaml_file(fpath: str, rel: str,
                       results: list[GameString]):
    """Simple line-based YAML string extraction (no yaml dependency)"""
    with open(fpath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        m = re.match(r'^\s*\w[\w\.\-]*\s*:\s*["\']?(.+?)["\']?\s*$', line)
        if m:
            val = m.group(1).strip().strip("\"'")
            if _is_translatable(val):
                results.append(GameString(
                    id=f"{rel}::L{i+1}",
                    text=val, file=rel, location="yaml",
                ))


# ── JSON recursive walker ─────────────────────────────────────────────────────
def _walk_json(obj, path: str, rel: str,
               results: list[GameString],
               default_location: str, depth: int = 0):
    """Recursively walk JSON and collect translatable strings"""
    if depth > 8:
        return
    if isinstance(obj, str):
        if _is_translatable(obj):
            results.append(GameString(
                id=f"{rel}::{path}",
                text=obj, file=rel,
                location=_path_to_location(path, default_location),
            ))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _walk_json(item, f"{path}[{i}]", rel, results,
                       default_location, depth + 1)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk_json(v, f"{path}.{k}", rel, results,
                       default_location, depth + 1)


def _path_to_location(path: str, default: str) -> str:
    p = path.lower()
    if any(k in p for k in ["message","dialog","speech","text","caption"]):
        return "dialogue"
    if any(k in p for k in ["name","title"]):
        return "name"
    if "description" in p or "desc" in p:
        return "description"
    if any(k in p for k in ["ui","menu","button","label","hint"]):
        return "ui"
    return default


# ── Filter ────────────────────────────────────────────────────────────────────
def _is_translatable(text: str) -> bool:
    """Return True if this string should be translated"""
    t = text.strip()
    if not t or len(t) < 2:
        return False
    # Pure numbers / symbols
    if re.match(r'^[\d\s\.\,\-\+\%\:\/#@!*()_=]+$', t):
        return False
    # File paths or URLs
    if re.match(r'^(https?://|www\.|[A-Za-z]:[/\\]|\.{1,2}[/\\])', t):
        return False
    # Control codes / hex
    if re.match(r'^\\[a-zA-Z]|\\\{|0x[0-9a-fA-F]', t):
        return False
    # Must contain at least one Latin letter
    if not re.search(r'[a-zA-Z]', t):
        return False
    # Skip if already contains Thai characters
    if re.search(r'[฀-๿]', t):
        return False
    # Skip single-letter codes
    if len(t) <= 2 and not re.search(r'[a-z]{2}', t, re.IGNORECASE):
        return False
    return True


# ── Utility ───────────────────────────────────────────────────────────────────
def group_by_file(strings: list[GameString]) -> dict[str, list[GameString]]:
    """Group GameStrings by their source file (relative path)"""
    groups: dict[str, list[GameString]] = {}
    for s in strings:
        groups.setdefault(s.file, []).append(s)
    return groups


def to_smart_translator_input(strings: list[GameString]) -> list[dict]:
    """Convert GameString list to SmartTranslator.process_batch() format"""
    return [
        {
            "text":     s.text,
            "speaker":  s.speaker,
            "location": s.location,
            "scene":    s.location,
        }
        for s in strings
    ]
