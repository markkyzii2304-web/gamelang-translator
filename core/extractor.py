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
    elif "unreal" in e:
        return _extract_ue4(game_dir, log)
    else:
        return _extract_generic(game_dir, log)


# ── RPG Maker MV/MZ helpers ───────────────────────────────────────────────────

def _read_json(fpath):
    """Try multiple encodings to read a JSON file; return parsed data or None."""
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030", "latin-1"):
        try:
            with open(fpath, "r", encoding=enc) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


def _walk_event_list(lst, rel, results, location, map_name=""):
    """Walk RPGMaker event command list, extract dialogue by code."""
    if not isinstance(lst, list):
        return
    for idx, cmd in enumerate(lst):
        if not isinstance(cmd, dict):
            continue
        code   = cmd.get("code", 0)
        params = cmd.get("parameters", [])

        if code == 401 and params:           # Show Text (dialogue line)
            text = params[0]
            if isinstance(text, str) and _is_translatable(text):
                results.append(GameString(
                    id=f"{rel}::ev{idx}",
                    text=text, file=rel,
                    location=location,
                    speaker=None,
                ))
        elif code == 101 and len(params) >= 5:  # Show Text header (speaker name)
            name = params[4]
            if isinstance(name, str) and _is_translatable(name):
                results.append(GameString(
                    id=f"{rel}::sp{idx}",
                    text=name, file=rel,
                    location=location,
                    speaker=name,
                ))
        elif code == 102 and params:         # Show Choices
            choices = params[0]
            if isinstance(choices, list):
                for ci, choice in enumerate(choices):
                    if isinstance(choice, str) and _is_translatable(choice):
                        results.append(GameString(
                            id=f"{rel}::ch{idx}_{ci}",
                            text=choice, file=rel,
                            location=location,
                        ))
        elif code == 405 and params:         # Show Scrolling Text
            text = params[0]
            if isinstance(text, str) and _is_translatable(text):
                results.append(GameString(
                    id=f"{rel}::sc{idx}",
                    text=text, file=rel,
                    location=location,
                ))


def _extract_rpg_obj_fields(obj, rel, results, location, fields):
    """Extract specific text fields from an RPGMaker data object."""
    if not isinstance(obj, dict):
        return
    for field in fields:
        val = obj.get(field)
        if isinstance(val, str) and _is_translatable(val):
            oid = obj.get("id", 0)
            results.append(GameString(
                id=f"{rel}::{field}_{oid}",
                text=val, file=rel,
                location=location,
            ))


def _extract_rpgmaker_data(data_dir: str, game_dir: str, log, results):
    """Parse each RPGMaker data file by type."""
    MAP_FIELDS    = ["name"]
    ACTOR_FIELDS  = ["name", "profile", "nickname"]
    ITEM_FIELDS   = ["name", "description"]
    ENEMY_FIELDS  = ["name"]
    CLASS_FIELDS  = ["name"]

    files = sorted(f for f in os.listdir(data_dir) if f.endswith(".json"))
    for fname in files:
        fpath  = os.path.join(data_dir, fname)
        rel    = os.path.relpath(fpath, game_dir).replace("\\", "/")
        fl     = fname.lower()
        before = len(results)

        data = _read_json(fpath)
        if data is None:
            log(f"  skip {fname} (unreadable)")
            continue

        try:
            if fl.startswith("map") and fl != "mapinfos.json":
                # Map file — walk events
                loc = f"map_{fname.replace('.json', '')}"
                for event in (data.get("events") or []):
                    if not isinstance(event, dict):
                        continue
                    for page in (event.get("pages") or []):
                        _walk_event_list(
                            page.get("list", []), rel, results, loc
                        )
                # Also extract display name
                _extract_rpg_obj_fields(data, rel, results, loc, ["displayName"])

            elif fl == "commonevents.json":
                for ev in (data if isinstance(data, list) else []):
                    if not isinstance(ev, dict):
                        continue
                    _walk_event_list(ev.get("list", []), rel, results, "common_event")
                    _extract_rpg_obj_fields(ev, rel, results, "common_event", ["name"])

            elif fl == "actors.json":
                for obj in (data if isinstance(data, list) else []):
                    _extract_rpg_obj_fields(obj, rel, results, "character", ACTOR_FIELDS)

            elif fl in ("items.json", "weapons.json", "armors.json", "skills.json", "states.json"):
                loc = fl.replace(".json", "")
                for obj in (data if isinstance(data, list) else []):
                    _extract_rpg_obj_fields(obj, rel, results, loc, ITEM_FIELDS)

            elif fl in ("enemies.json", "classes.json", "troops.json"):
                loc = fl.replace(".json", "")
                for obj in (data if isinstance(data, list) else []):
                    _extract_rpg_obj_fields(obj, rel, results, loc, ENEMY_FIELDS)

            elif fl == "system.json":
                title = data.get("gameTitle", "")
                if _is_translatable(title):
                    results.append(GameString(id=f"{rel}::gameTitle",
                        text=title, file=rel, location="ui"))
                terms = data.get("terms", {})
                for section in ("messages", ):
                    for k, v in (terms.get(section) or {}).items():
                        if isinstance(v, str) and _is_translatable(v):
                            results.append(GameString(id=f"{rel}::terms.{k}",
                                text=v, file=rel, location="ui"))
                for section in ("commands", "params", "etypes", "wtypes"):
                    for i, v in enumerate(terms.get(section) or []):
                        if isinstance(v, str) and _is_translatable(v):
                            results.append(GameString(id=f"{rel}::terms.{section}[{i}]",
                                text=v, file=rel, location="ui"))

            elif fl == "mapinfos.json":
                for obj in (data if isinstance(data, list) else []):
                    _extract_rpg_obj_fields(obj, rel, results, "map_info", ["name"])

        except Exception as e:
            log(f"  warning {fname}: {e}")

        count = len(results) - before
        if count:
            log(f"  {fname}: {count} strings")


# ── RPG Maker MV/MZ ───────────────────────────────────────────────────────────
def _extract_rpgmaker(game_dir: str, log) -> list[GameString]:
    results: list[GameString] = []

    data_dirs = [
        os.path.join(game_dir, "www", "data"),
        os.path.join(game_dir, "data"),
        os.path.join(game_dir, "Game", "data"),
    ]
    # Search one level deeper
    try:
        for entry in os.listdir(game_dir):
            sub = os.path.join(game_dir, entry)
            if os.path.isdir(sub):
                data_dirs.append(os.path.join(sub, "www", "data"))
                data_dirs.append(os.path.join(sub, "data"))
    except Exception:
        pass

    found = False
    for data_dir in data_dirs:
        if not os.path.isdir(data_dir):
            continue
        log(f"RPGMaker data: {data_dir}")
        _extract_rpgmaker_data(data_dir, game_dir, log, results)
        found = True
        break

    if not found:
        log("no www/data found — falling back to broad scan")
        results.extend(_extract_broad(game_dir, log))

    log(f"RPG Maker: total {len(results)} strings")
    return results


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
                log(f"  skip {fname}: {e}")

    log(f"Ren'Py: total {len(results)} strings")
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
            log(f"  skip {os.path.basename(fpath)}: {e}")

    log(f"Localization: total {len(results)} strings")
    return results


def _extract_ue4(game_dir: str, log) -> list[GameString]:
    """Extract from UE4 .pak files via .locres parsing"""
    from core.pak_handler import list_files, extract_file
    from core import locres as locres_mod
    results: list[GameString] = []

    paks_dir = os.path.join(game_dir, "Content", "Paks")
    if not os.path.isdir(paks_dir):
        log("ไม่พบ Content/Paks — ไม่ใช่ UE4 game")
        return results

    # หา pak ต้นฉบับก่อน ถ้าไม่มีให้ใช้ _p.pak
    all_paks = sorted(f for f in os.listdir(paks_dir) if f.endswith('.pak'))
    pak_files = [f for f in all_paks if not f.endswith('_p.pak')]
    if not pak_files:
        pak_files = all_paks   # fallback: ใช้ทุก pak รวม _p.pak
    if not pak_files:
        log("ไม่พบ pak file")
        return results

    main_pak = os.path.join(paks_dir, pak_files[0])
    log(f"UE4 pak: {pak_files[0]}")

    try:
        files = list_files(main_pak)
    except Exception as e:
        log(f"ไม่สามารถอ่าน pak: {e}")
        return results

    # หาไฟล์ .locres — prefer zh-Hans (Chinese source) ถ้ามี ไม่งั้นใช้ en
    zh_files = [f for f in files if f.endswith('.locres')
                and ('/zh-Hans/' in f or '/zh-CN/' in f or '/zh-Hant/' in f)]
    en_files  = [f for f in files if f.endswith('.locres') and '/en/' in f]
    locres_files = zh_files if zh_files else en_files
    log(f"พบ {len(locres_files)} locres files ({'zh-Hans' if zh_files else 'en'})")

    for fpath in locres_files:
        try:
            raw = extract_file(main_pak, fpath)
            if not raw:
                continue
            lf  = locres_mod.load(raw)
            d   = locres_mod.to_dict(lf)
            rel = fpath.replace('\\', '/')
            before = len(results)
            for ns, keys in d.items():
                for key, translation in keys.items():
                    if _is_translatable(translation):
                        results.append(GameString(
                            id=f"{rel}::{ns}::{key}",
                            text=translation,
                            file=rel,
                            location=ns or "ui",
                        ))
            count = len(results) - before
            if count:
                log(f"  {os.path.basename(fpath)}: {count} strings")
        except Exception as e:
            log(f"  ข้าม {os.path.basename(fpath)}: {e}")

    log(f"UE4: รวม {len(results)} strings")
    return results


def _extract_generic(game_dir: str, log) -> list[GameString]:
    """Generic fallback — scan all JSON/CSV in game dir"""
    log("Generic extraction mode...")
    results = _extract_localization(game_dir, log)
    if not results:
        log("no localization folder found — scanning all files...")
        results = _extract_broad(game_dir, log)
    return results


_SKIP_DIRS = {
    "__pycache__", ".git", "node_modules",
    "audio", "sound", "music", "video", "movies",
    "sprites", "images", "textures", "shaders",
    "saves", "logs", "cache",
}
_MAX_FILE_BYTES = 8 * 1024 * 1024   # 8 MB per file


def _extract_broad(game_dir: str, log) -> list[GameString]:
    """
    Broad fallback: walk ALL JSON/CSV/YAML/TXT files in game_dir (max depth 7).
    Used when no localization-named directory is found.
    """
    results: list[GameString] = []

    for dirpath, dirnames, files in os.walk(game_dir):
        rel_dir = os.path.relpath(dirpath, game_dir)
        depth   = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
        if depth > 7:
            dirnames.clear()
            continue
        # Prune heavy/irrelevant dirs
        dirnames[:] = [d for d in dirnames
                       if d.lower() not in _SKIP_DIRS
                       and not d.startswith(".")]

        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".json", ".csv", ".yaml", ".yml", ".txt"):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                if os.path.getsize(fpath) > _MAX_FILE_BYTES:
                    continue
                rel = os.path.relpath(fpath, game_dir).replace("\\", "/")
                before = len(results)
                if ext == ".json":
                    _extract_json_file(fpath, rel, results)
                elif ext == ".csv":
                    _extract_csv_file(fpath, rel, results)
                elif ext in (".yaml", ".yml"):
                    _extract_yaml_file(fpath, rel, results)
                elif ext == ".txt":
                    _extract_txt_file(fpath, rel, results)
                count = len(results) - before
                if count:
                    log(f"  {fname}: {count} strings")
            except Exception:
                pass   # skip unreadable files

    log(f"Broad scan: total {len(results)} strings")
    return results


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


def _extract_txt_file(fpath: str, rel: str,
                      results: list[GameString]):
    """Extract translatable lines from plain-text files"""
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return
    for i, line in enumerate(lines):
        val = line.strip()
        # Skip lines that look like code / config
        if val.startswith(("#", "//", ";", "[", "{")):
            continue
        # Only take lines that are predominantly words (not key=value pairs)
        if "=" in val:
            # "key = value" — take the value side if translatable
            parts = val.split("=", 1)
            if len(parts) == 2:
                val = parts[1].strip().strip("\"'")
        if _is_translatable(val):
            results.append(GameString(
                id=f"{rel}::L{i+1}",
                text=val, file=rel, location="text",
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
    if depth > 12:   # RPGMaker MV/MZ events nest up to 8-10 levels
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
    """
    Return True if this string should be translated.
    Supports: English (Latin), Chinese/Japanese (CJK), Korean (Hangul)
    """
    t = text.strip()
    if not t or len(t) < 2:
        return False
    # Pure numbers / symbols
    if re.match(r'^[\d\s\.\,\-\+\%\:\/#@!*()_=\[\]{}|\\<>^~]+$', t):
        return False
    # File paths or URLs
    if re.match(r'^(https?://|www\.|[A-Za-z]:[/\\]|\.{1,2}[/\\])', t):
        return False
    # Control codes / hex / escape sequences
    if re.match(r'^\\[a-zA-Z]|\\\{|0x[0-9a-fA-F]', t):
        return False
    # Skip if already contains Thai characters
    if re.search(r'[฀-๿]', t):
        return False
    # Must have at least one meaningful character group:
    # - Latin (English)
    has_latin  = bool(re.search(r'[a-zA-Z]', t))
    # - CJK (Chinese / Japanese kanji / Simplified+Traditional)
    has_cjk    = bool(re.search(
        r'[一-鿿'    # CJK Unified Ideographs
        r'㐀-䶿'     # CJK Extension A
        r'぀-ヿ'     # Hiragana + Katakana
        r'豈-﫿]',   # CJK Compatibility
        t
    ))
    # - Hangul (Korean)
    has_hangul = bool(re.search(r'[가-힯ᄀ-ᇿ]', t))

    if not (has_latin or has_cjk or has_hangul):
        return False

    # Very short Latin text (1-2 chars) that is not a word → skip
    if has_latin and not has_cjk and not has_hangul:
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
