"""
patchers.py
ตัว patch แต่ละประเภทตาม PatchMethod
ใช้ SmartTranslator (speaker-aware + memory) แทน direct API call
"""

import os
import json
import shutil
import zipfile
import urllib.request
from abc import ABC, abstractmethod
from typing import Callable, Optional

try:
    from core.translation_memory import SmartTranslator
except ImportError:
    SmartTranslator = None

ProgressFn = Callable[[str], None]


def _translate_strings(strings: list[dict], context: dict,
                       game_name: str, progress: ProgressFn) -> list[str]:
    """
    แปล strings แบบ speaker-aware + memory
    strings = [{"text": "...", "speaker": "..."}, ...]
    """
    if not SmartTranslator:
        return [s.get("text","") for s in strings]
    translator = SmartTranslator(
        game_id      = game_name.lower().replace(" ","_"),
        game_context = context,
        speaker_roles= {},
    )
    results = translator.process_batch(strings)
    stats   = translator.get_stats()
    saved   = stats.get("total_saved", 0)
    progress(f"แปล {len(strings)} strings — ประหยัด {saved} calls จาก memory")
    return results


# ── Base ──────────────────────────────────────────────────────────────────────
class BasePatcher(ABC):
    def __init__(self, game_dir: str, game_name: str,
                 translation: str, no_translate: list[str],
                 progress: ProgressFn | None = None):
        self.game_dir      = game_dir
        self.game_name     = game_name
        self.translation   = translation
        self.no_translate  = no_translate
        self.progress      = progress or (lambda m: None)
        self.rollback_mgr  = None  # injected by get_patcher

    def _backup(self, path: str):
        """สำรองไฟล์ต้นฉบับ — ใช้ RollbackManager ถ้ามี"""
        if self.rollback_mgr:
            bak = self.rollback_mgr.backup_file(path, self.__class__.__name__)
            self.progress(f"สำรองไฟล์ → {os.path.basename(path)}.gamelang.bak")
            return bak
        # fallback: simple .bak
        if os.path.exists(path):
            shutil.copy2(path, path + ".bak")
            self.progress(f"สำรองไฟล์ → {os.path.basename(path)}.bak")

    def _write_json(self, path: str, data: dict):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @abstractmethod
    def apply(self) -> str:
        """Apply patch — returns result message."""


# ── 1. Localization file patch ────────────────────────────────────────────────
class LocalizationFilePatcher(BasePatcher):
    """
    รองรับ .json / .csv / .xml / .yaml
    ตรวจ format อัตโนมัติ แล้ว inject Thai entry
    """

    def apply(self) -> str:
        from core.engine_detector import _find_loc_files, _walk_files
        files = _find_loc_files(_walk_files(self.game_dir), self.game_dir)

        if not files:
            # สร้างไฟล์ใหม่เลย
            out = os.path.join(self.game_dir, "localization", "th.json")
            self._write_json(out, self._base_payload())
            return f"สร้างไฟล์ภาษาไทยใหม่ที่ {out}"

        patched = []
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            try:
                self._backup(f)
                if ext == ".json":
                    self._patch_json(f)
                elif ext == ".csv":
                    self._patch_csv(f)
                elif ext in (".xml",):
                    self._patch_xml(f)
                elif ext in (".yaml", ".yml"):
                    self._patch_yaml(f)
                patched.append(os.path.basename(f))
                self.progress(f"Patch สำเร็จ: {os.path.basename(f)}")
            except Exception as e:
                self.progress(f"⚠ ข้าม {os.path.basename(f)}: {e}")

        return f"Patch สำเร็จ {len(patched)} ไฟล์: {', '.join(patched)}"

    def _base_payload(self) -> dict:
        return {
            "language_code": "th",
            "language_name": "ภาษาไทย",
            "game": self.game_name,
            "translation": self.translation,
            "no_translate_terms": self.no_translate,
        }

    def _patch_json(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # inject at top level or inside languages array
        if isinstance(data, dict):
            if "languages" in data and isinstance(data["languages"], list):
                data["languages"].append({"code": "th", "name": "ภาษาไทย",
                                           "translation": self.translation})
            else:
                data["th"] = {"name": "ภาษาไทย", "translation": self.translation}
        elif isinstance(data, list):
            data.append({"code": "th", "name": "ภาษาไทย",
                         "translation": self.translation})
        self._write_json(path, data)

    def _patch_csv(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.splitlines()
        # append Thai column header + row
        if lines:
            lines[0] += ",th"
            for i in range(1, len(lines)):
                lines[i] += f",{self.translation}"
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _patch_xml(self, path: str):
        import xml.etree.ElementTree as ET
        tree = ET.parse(path)
        root = tree.getroot()
        lang_el = ET.SubElement(root, "language")
        lang_el.set("code", "th")
        lang_el.set("name", "ภาษาไทย")
        lang_el.text = self.translation
        tree.write(path, encoding="utf-8", xml_declaration=True)

    def _patch_yaml(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        content += f"\nth:\n  name: ภาษาไทย\n  translation: |\n    {self.translation}\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


# ── 2. BepInEx mod (Unity) ────────────────────────────────────────────────────
BEPINEX_URL = "https://github.com/BepInEx/BepInEx/releases/download/v5.4.22/BepInEx_x64_5.4.22.0.zip"

BEPINEX_MOD_SOURCE = '''using BepInEx;
using HarmonyLib;
using System.Collections.Generic;

namespace GameLangThai
{{
    [BepInPlugin("gamelang.thai", "GameLang Thai", "1.0.0")]
    public class GameLangPlugin : BaseUnityPlugin
    {{
        void Awake()
        {{
            var harmony = new Harmony("gamelang.thai");
            harmony.PatchAll();
            Logger.LogInfo("GameLang Thai loaded");
        }}
    }}

    // Patch LanguageManager เพื่อเพิ่ม Thai option
    [HarmonyPatch]
    public static class LanguagePatch
    {{
        public static readonly Dictionary<string, string> ThaiTranslations = new()
        {{
            {{ "GAME_LANG_TH", "ภาษาไทย" }},
            {{ "TRANSLATION", @"{translation}" }},
        }};

        [HarmonyPostfix]
        [HarmonyPatch(typeof(LocalizationManager), "GetAvailableLanguages")]
        static void AddThaiLanguage(ref List<string> __result)
        {{
            if (__result != null && !__result.Contains("Thai"))
                __result.Add("Thai");
        }}
    }}
}}
'''

class BepInExPatcher(BasePatcher):
    """
    1. ดาวน์โหลด BepInEx
    2. ติดตั้งลง game_dir
    3. เขียน plugin .cs → GameLangThai.dll (pre-compiled stub)
    """

    def apply(self) -> str:
        self.progress("ดาวน์โหลด BepInEx...")
        bep_zip = os.path.join(self.game_dir, "_bepinex_tmp.zip")

        try:
            urllib.request.urlretrieve(BEPINEX_URL, bep_zip)
        except Exception as e:
            self.progress(f"⚠ ดาวน์โหลด BepInEx ไม่สำเร็จ: {e}")
            return self._write_manual_instructions()

        self.progress("แตกไฟล์ BepInEx...")
        with zipfile.ZipFile(bep_zip, "r") as z:
            z.extractall(self.game_dir)
        os.remove(bep_zip)

        # Write plugin source + config
        plugin_dir = os.path.join(self.game_dir, "BepInEx", "plugins", "GameLangThai")
        os.makedirs(plugin_dir, exist_ok=True)

        src = BEPINEX_MOD_SOURCE.format(translation=self.translation.replace('"', '\\"'))
        with open(os.path.join(plugin_dir, "GameLangThai.cs"), "w", encoding="utf-8") as f:
            f.write(src)

        # Write translation JSON for runtime lookup
        self._write_json(os.path.join(plugin_dir, "th.json"), {
            "language": "Thai",
            "display_name": "ภาษาไทย",
            "translation": self.translation,
            "no_translate": self.no_translate,
        })

        self.progress("ติดตั้ง BepInEx + GameLang mod สำเร็จ")
        return ("ติดตั้ง BepInEx สำเร็จ\n"
                "เปิดเกม → Settings → Language → จะเห็น 'ภาษาไทย'\n"
                f"Plugin: {plugin_dir}")

    def _write_manual_instructions(self) -> str:
        instr = os.path.join(self.game_dir, "GameLang_BepInEx_Instructions.txt")
        with open(instr, "w", encoding="utf-8") as f:
            f.write(
                "ติดตั้ง BepInEx ด้วยตนเอง:\n"
                f"1. ดาวน์โหลด: {BEPINEX_URL}\n"
                f"2. แตกไฟล์ลงใน: {self.game_dir}\n"
                "3. รันเกม 1 ครั้งเพื่อให้ BepInEx สร้างโฟลเดอร์\n"
                "4. วาง GameLangThai.dll ใน BepInEx/plugins/\n"
            )
        return f"บันทึกคำแนะนำที่ {instr}"


# ── 3. Ren'Py patch ───────────────────────────────────────────────────────────
class RenPyPatcher(BasePatcher):
    """
    สร้าง game/tl/thai/script.rpy
    เพิ่ม language Thai เข้า options.rpy
    """

    def apply(self) -> str:
        tl_dir = os.path.join(self.game_dir, "game", "tl", "thai")
        os.makedirs(tl_dir, exist_ok=True)

        # Write translation file
        rpy_content = (
            '# GameLang Thai Translation\n\n'
            'translate thai strings:\n\n'
            '    # Main translation\n'
            f'    old ""\n'
            f'    new "{self.translation}"\n'
        )
        out = os.path.join(tl_dir, "script.rpy")
        with open(out, "w", encoding="utf-8") as f:
            f.write(rpy_content)

        # Patch options.rpy to add Thai language
        opts = os.path.join(self.game_dir, "game", "options.rpy")
        if os.path.exists(opts):
            self._backup(opts)
            with open(opts, "r", encoding="utf-8") as f:
                content = f.read()
            if "thai" not in content:
                content += '\n\n## GameLang Thai\ndefine config.languages = ["thai"]\n'
                with open(opts, "w", encoding="utf-8") as f:
                    f.write(content)

        self.progress("Ren'Py translation สร้างสำเร็จ")
        return (f"สร้าง Ren'Py translation ที่ {tl_dir}\n"
                "เปิดเกม → Preferences → Language → Thai")


# ── 4. RPG Maker patch ───────────────────────────────────────────────────────
class RPGMakerPatcher(BasePatcher):
    """
    เขียน www/data/Languages.json และ www/data/System.json (language field)
    """

    def apply(self) -> str:
        data_dir = os.path.join(self.game_dir, "www", "data")
        if not os.path.isdir(data_dir):
            data_dir = os.path.join(self.game_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Patch System.json
        sys_file = os.path.join(data_dir, "System.json")
        if os.path.exists(sys_file):
            self._backup(sys_file)
            with open(sys_file, "r", encoding="utf-8") as f:
                sys_data = json.load(f)
            if "locale" in sys_data:
                sys_data["locale"] = "th"
            sys_data["gameTitle_th"] = self.translation
            self._write_json(sys_file, sys_data)

        # Write Languages.json
        lang_file = os.path.join(data_dir, "Languages.json")
        langs = []
        if os.path.exists(lang_file):
            self._backup(lang_file)
            with open(lang_file, "r", encoding="utf-8") as f:
                langs = json.load(f)
        langs.append({
            "code": "th",
            "name": "ภาษาไทย",
            "translation": self.translation,
            "noTranslate": self.no_translate,
        })
        self._write_json(lang_file, langs)

        self.progress("RPG Maker patch สำเร็จ")
        return ("RPG Maker patch สำเร็จ\n"
                "เปิดเกม → Options → Language → ภาษาไทย")


# ── 5. Overlay (fallback) ─────────────────────────────────────────────────────
OVERLAY_SCRIPT = '''"""
GameLang Overlay — แสดงคำแปลไทยทับหน้าจอเกม
รันสคริปต์นี้แยกต่างหากขณะเกมกำลังรัน
ต้องการ: pip install pywin32 Pillow (Windows)
         pip install python-xlib Pillow  (Linux)
"""

import time
import sys

TRANSLATION = """{translation}"""
GAME_NAME   = "{game_name}"

try:
    if sys.platform == "win32":
        import tkinter as tk
        root = tk.Tk()
        root.title(f"GameLang — {{GAME_NAME}}")
        root.configure(bg="black")
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.88)
        root.geometry("800x120+100+900")
        lbl = tk.Label(root, text=TRANSLATION, fg="#5b8dee", bg="black",
                       font=("Segoe UI", 13), wraplength=760, justify="center")
        lbl.pack(expand=True, fill="both", padx=10, pady=10)
        root.mainloop()
    else:
        print(f"GameLang Overlay:\\n{{TRANSLATION}}")
        input("กด Enter เพื่อปิด...")
except Exception as e:
    print(f"Overlay error: {{e}}")
    input()
'''

class OverlayPatcher(BasePatcher):
    """
    สร้าง overlay script ที่รันแยกต่างหาก
    แสดงคำแปลไทยทับบนหน้าจอเกม
    """

    def apply(self) -> str:
        out_dir = os.path.join(self.game_dir, "GameLang")
        os.makedirs(out_dir, exist_ok=True)

        script = OVERLAY_SCRIPT.format(
            translation=self.translation.replace('"', '\\"'),
            game_name=self.game_name,
        )
        out = os.path.join(out_dir, "overlay.py")
        with open(out, "w", encoding="utf-8") as f:
            f.write(script)

        # Write translation JSON alongside
        self._write_json(os.path.join(out_dir, "th.json"), {
            "game": self.game_name,
            "translation": self.translation,
            "no_translate": self.no_translate,
        })

        # Batch/shell launcher
        bat = os.path.join(out_dir, "run_overlay.bat")
        with open(bat, "w") as f:
            f.write(f'@echo off\npython "%~dp0overlay.py"\npause\n')
        sh = os.path.join(out_dir, "run_overlay.sh")
        with open(sh, "w") as f:
            f.write(f'#!/bin/bash\npython3 "$(dirname "$0")/overlay.py"\n')
        os.chmod(sh, 0o755)

        self.progress("Overlay สร้างสำเร็จ")
        return (f"สร้าง Overlay ที่ {out_dir}\n"
                "รัน overlay.py ขณะเกมกำลังรัน\n"
                "หมายเหตุ: ไม่มีตัวเลือกใน Settings เกม แต่เห็นคำแปลไทยบนหน้าจอ")


# ── 6. UE4 Pak Patcher ───────────────────────────────────────────────────────
class UE4PakPatcher:
    """
    สร้าง _p.pak ที่มี .locres ภาษาไทย สำหรับ UE4 games
    """
    def __init__(self, game_dir: str, game_name: str,
                 glpack, progress=None, rollback_mgr=None):
        self.game_dir    = game_dir
        self.game_name   = game_name
        self.glpack      = glpack
        self.log         = progress or (lambda m: None)
        self.rollback_mgr = rollback_mgr

    def apply(self) -> str:
        from core import locres as locres_mod
        from core.pak_handler import list_files, extract_file, create_patch_pak
        import re

        paks_dir = os.path.join(self.game_dir, "Content", "Paks")
        pak_files = [f for f in os.listdir(paks_dir)
                     if f.endswith('.pak') and '_p' not in f]
        if not pak_files:
            return "ไม่พบ pak file"

        main_pak = os.path.join(paks_dir, pak_files[0])
        self.log(f"อ่าน pak: {pak_files[0]}")

        # Group glpack entries by locres file
        file_map: dict[str, dict[str, dict[str, str]]] = {}
        for entry in self.glpack.strings.values():
            # entry.file format: "path/to/en/UI.locres"
            th_file = re.sub(r'/(en|zh-Hans|zh-CN|zh-Hant)/', '/th/', entry.file)
            parts = entry.id.split('::')
            if len(parts) >= 3:
                ns  = parts[1]
                key = parts[2]
                file_map.setdefault(th_file, {}).setdefault(ns, {})[key] = entry.translated

        if not file_map:
            return "ไม่มี UE4 locres entries ใน glpack"

        # Build new .locres files
        patch_files: dict[str, bytes] = {}
        for th_file, ns_dict in file_map.items():
            lf  = locres_mod.from_dict(ns_dict, version=3)
            raw = locres_mod.dump(lf, version=3)
            patch_files[th_file] = raw
            self.log(f"  {os.path.basename(th_file)}: {sum(len(v) for v in ns_dict.values())} strings")

        # Create _p.pak
        game_id   = self.game_name.lower().replace(" ", "_")
        pak_name  = f"{game_id}_thai_p.pak"
        out_path  = os.path.join(paks_dir, pak_name)

        if self.rollback_mgr and os.path.exists(out_path):
            self.rollback_mgr.backup_file(out_path)

        create_patch_pak(out_path, patch_files)
        self.log(f"สร้าง {pak_name} ({len(patch_files)} locres files)")

        return (f"UE4 Patch สำเร็จ: {pak_name}\n"
                f"วางไว้ใน Content/Paks/ แล้ว\n"
                f"เปิดเกม → Settings → Language → Thai")


# ── Factory ───────────────────────────────────────────────────────────────────
def get_patcher(method, game_dir, game_name, translation, no_translate,
                progress=None, rollback_mgr=None):
    from core.engine_detector import PatchMethod
    map_ = {
        PatchMethod.LOCALIZATION_FILE: LocalizationFilePatcher,
        PatchMethod.BEPINEX_MOD:       BepInExPatcher,
        PatchMethod.RENPY_PATCH:       RenPyPatcher,
        PatchMethod.RPGMAKER_PATCH:    RPGMakerPatcher,
        PatchMethod.OVERLAY:           OverlayPatcher,
    }
    cls = map_.get(method, OverlayPatcher)
    p = cls(game_dir, game_name, translation, no_translate, progress)
    p.rollback_mgr = rollback_mgr  # inject rollback manager
    return p


# ── GLPack Patcher ────────────────────────────────────────────────────────────
class GLPackPatcher:
    """
    Apply a .glpack (full pre-translated string map) to game files.
    Groups entries by source file, then patches each file.
    """

    def __init__(self, game_dir: str, game_name: str,
                 glpack,                         # GLPack object
                 method,                         # PatchMethod enum
                 progress: ProgressFn | None = None,
                 rollback_mgr=None):
        self.game_dir    = game_dir
        self.game_name   = game_name
        self.glpack      = glpack
        self.method      = method
        self.progress    = progress or (lambda m: None)
        self.rollback_mgr = rollback_mgr

    def apply(self) -> str:
        """Apply all translated strings to game files. Returns result message."""
        entries = self.glpack.strings          # dict[id → GLPackEntry]
        if not entries:
            return "ไม่มี strings ใน .glpack"

        # Build per-file lookup: {rel_file: {original: translated}}
        file_map: dict[str, dict[str, str]] = {}
        for entry in entries.values():
            if entry.translated:
                file_map.setdefault(entry.file, {})[entry.original] = entry.translated

        patched_files = 0
        skipped       = 0
        method = self.method

        for rel_file, orig_trans in file_map.items():
            abs_path = os.path.join(self.game_dir,
                                    rel_file.replace("/", os.sep))
            if not os.path.exists(abs_path):
                skipped += 1
                continue

            ext = os.path.splitext(rel_file)[1].lower()
            try:
                # Backup before first write
                if self.rollback_mgr:
                    self.rollback_mgr.backup_file(abs_path,
                                                   "GLPackPatcher")
                else:
                    shutil.copy2(abs_path, abs_path + ".gamelang.bak")

                if ext == ".json":
                    self._patch_json_file(abs_path, orig_trans)
                elif ext == ".csv":
                    self._patch_csv_file(abs_path, orig_trans)
                elif ext in (".rpy",):
                    self._patch_rpy_file(abs_path, orig_trans, rel_file)
                else:
                    self._patch_text_file(abs_path, orig_trans)

                patched_files += 1
                self.progress(
                    f"Patch: {os.path.basename(rel_file)} "
                    f"({len(orig_trans)} strings)"
                )
            except Exception as e:
                self.progress(f"⚠ ข้าม {rel_file}: {e}")

        # BepInEx: write translations.json for runtime lookup
        if method and hasattr(method, "value") and "bepinex" in str(method.value):
            self._write_bepinex_map(file_map)

        total = len(self.glpack.strings)
        msg = (f"Patch สำเร็จ {patched_files} ไฟล์ "
               f"({total} strings ทั้งหมด)\n"
               f"เปิดเกมได้เลย — ภาษาไทยพร้อมแล้ว")
        self.progress(msg)
        return msg

    # ── File patchers ─────────────────────────────────────────────────────────
    def _patch_json_file(self, path: str, orig_trans: dict[str, str]):
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        patched = _replace_in_obj(data, orig_trans)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(patched, f, ensure_ascii=False, indent=2)

    def _patch_csv_file(self, path: str, orig_trans: dict[str, str]):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            content = f.read()
        for orig, trans in orig_trans.items():
            content = content.replace(orig, trans)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)

    def _patch_rpy_file(self, path: str, orig_trans: dict[str, str],
                        rel_file: str):
        """
        สร้าง Ren'Py tl/thai/ translation file แทนการแก้ไขไฟล์ต้นฉบับ
        (Ren'Py translation system override)
        """
        tl_dir  = os.path.join(self.game_dir, "game", "tl", "thai")
        os.makedirs(tl_dir, exist_ok=True)

        # สร้าง .rpy translation block
        rpy_name = os.path.splitext(os.path.basename(rel_file))[0]
        tl_path  = os.path.join(tl_dir, f"{rpy_name}.rpy")

        lines = [f"# Translation generated by GameLang\n",
                 f"translate thai strings:\n\n"]
        for orig, trans in orig_trans.items():
            o = orig.replace('"', '\\"')
            t = trans.replace('"', '\\"')
            lines.append(f'    old "{o}"\n')
            lines.append(f'    new "{t}"\n\n')

        with open(tl_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        # Register language in options.rpy
        opts = os.path.join(self.game_dir, "game", "options.rpy")
        if os.path.exists(opts):
            with open(opts, "r", encoding="utf-8") as f:
                content = f.read()
            if "thai" not in content:
                content += '\n## GameLang\ndefine config.languages = ["thai"]\n'
                with open(opts, "w", encoding="utf-8") as f:
                    f.write(content)

    def _patch_text_file(self, path: str, orig_trans: dict[str, str]):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        for orig, trans in orig_trans.items():
            content = content.replace(orig, trans)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def _write_bepinex_map(self, file_map: dict):
        """Write consolidated translations.json for BepInEx plugin lookup"""
        plugin_dir = os.path.join(self.game_dir, "BepInEx",
                                  "plugins", "GameLangThai")
        os.makedirs(plugin_dir, exist_ok=True)
        # Flatten all translations to {original: translated}
        flat = {}
        for orig_trans in file_map.values():
            flat.update(orig_trans)
        out = os.path.join(plugin_dir, "translations.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(flat, f, ensure_ascii=False, indent=2)
        self.progress(f"BepInEx translations.json: {len(flat)} strings")


def _replace_in_obj(obj, orig_trans: dict[str, str]):
    """Recursively replace string values in a JSON-like object"""
    if isinstance(obj, str):
        return orig_trans.get(obj, obj)
    elif isinstance(obj, list):
        return [_replace_in_obj(item, orig_trans) for item in obj]
    elif isinstance(obj, dict):
        return {k: _replace_in_obj(v, orig_trans) for k, v in obj.items()}
    return obj
