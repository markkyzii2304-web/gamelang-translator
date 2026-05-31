"""
test_smoke.py -- GameLang Translator Pre-commit Smoke Test
Run: python test_smoke.py
Pass = exit 0 | Fail = exit 1
"""

import sys
import os
import importlib
import ast

# Force UTF-8 output on Windows terminals
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# -- Color codes ---------------------------------------------------------------
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):   print(f"  {GREEN}[OK]{RESET} {msg}")
def fail(msg): print(f"  {RED}[FAIL]{RESET} {msg}")
def warn(msg): print(f"  {YELLOW}[WARN]{RESET} {msg}")
def hdr(msg):  print(f"\n{BOLD}{CYAN}{msg}{RESET}")

# ── เพิ่ม project root ใน sys.path ────────────────────────────────────────────
PROJECT = os.path.dirname(os.path.abspath(__file__))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

errors = []

# ─────────────────────────────────────────────────────────────────────────────
# 1. Syntax check (ast.parse) ทุก .py ใน project
# ─────────────────────────────────────────────────────────────────────────────
hdr("1 / 4  — Syntax check (ast.parse)")
SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", "build", "dist"}
py_files = []
for root, dirs, files in os.walk(PROJECT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for f in files:
        if f.endswith(".py"):
            py_files.append(os.path.join(root, f))

for path in sorted(py_files):
    rel = os.path.relpath(path, PROJECT)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        ast.parse(src, filename=path)
        ok(rel)
    except SyntaxError as e:
        fail(f"{rel}  →  SyntaxError line {e.lineno}: {e.msg}")
        errors.append(f"Syntax: {rel}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Import core modules (ไม่ต้องการ PyQt6 / anthropic ในขั้นตอนนี้)
# ─────────────────────────────────────────────────────────────────────────────
hdr("2 / 4  — Import core modules")

CORE_MODULES = [
    "core.engine_detector",
    "core.glpack",
    "core.rollback",
    "core.updater",
    "core.locres",
    "core.pak_handler",
]

for mod in CORE_MODULES:
    try:
        importlib.import_module(mod)
        ok(mod)
    except ImportError as e:
        # ยอมรับ ImportError ที่เกิดจาก optional deps (PyQt6 etc.)
        warn(f"{mod}  →  ImportError (optional dep?): {e}")
    except Exception as e:
        fail(f"{mod}  →  {type(e).__name__}: {e}")
        errors.append(f"Import: {mod}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Import extractor + glpack (ต้องการ dataclasses เท่านั้น)
# ─────────────────────────────────────────────────────────────────────────────
hdr("3 / 4  — Data model sanity (extractor / glpack)")

try:
    from core.extractor import GameString, _is_translatable
    # _is_translatable รับ: Latin, CJK, Hangul (source languages)
    # ไม่รับ: Thai (target), empty, numbers, single char
    assert _is_translatable("Hello World"),      "should accept Latin"
    assert _is_translatable("武侠"),               "should accept Chinese"
    assert _is_translatable("검사합니다"),            "should accept Korean"
    assert not _is_translatable(""),             "should reject empty"
    assert not _is_translatable("1234"),         "should reject number-only"
    assert not _is_translatable("a"),            "should reject single char"
    ok("extractor._is_translatable -- logic OK")
except Exception as e:
    fail(f"extractor: {e}")
    errors.append("extractor logic")

try:
    from core.glpack import GLPack, build_glpack
    from core.extractor import GameString

    gs = GameString(id="test::0", text="Hello", file="test.json", location="test")
    pack = build_glpack("TestGame", "rpgmaker", [gs], ["translated"])
    # GLPack.strings is a dict[str, GLPackEntry] keyed by GameString.id
    assert pack.string_count == 1,              "string_count wrong"
    assert len(pack.strings) == 1,             "strings dict wrong"
    entry = pack.strings["test::0"]
    assert entry.original == "Hello",          "original wrong"
    assert entry.translated == "translated",   "translated wrong"
    ok("glpack.build_glpack -- GLPack structure OK")
except Exception as e:
    fail(f"glpack: {e}")
    errors.append("glpack build")

# ─────────────────────────────────────────────────────────────────────────────
# 4. VERSION file ต้องมีและอ่านได้
# ─────────────────────────────────────────────────────────────────────────────
hdr("4 / 4  — VERSION file")

ver_path = os.path.join(PROJECT, "VERSION")
try:
    with open(ver_path) as f:
        ver = f.read().strip()
    parts = ver.split(".")
    assert len(parts) == 3,      f"VERSION ต้องมี 3 ส่วน, ได้ '{ver}'"
    assert all(p.isdigit() for p in parts), f"VERSION ต้องเป็นตัวเลข, ได้ '{ver}'"
    ok(f"VERSION = {ver}")
except FileNotFoundError:
    fail("ไม่พบไฟล์ VERSION")
    errors.append("VERSION missing")
except AssertionError as e:
    fail(str(e))
    errors.append("VERSION format")

# ─────────────────────────────────────────────────────────────────────────────
# สรุปผล
# ─────────────────────────────────────────────────────────────────────────────
print()
if errors:
    print(f"{RED}{BOLD}[FAILED] -- {len(errors)} error(s):{RESET}")
    for e in errors:
        print(f"   - {e}")
    sys.exit(1)
else:
    print(f"{GREEN}{BOLD}[ALL PASSED] -- code is ready to commit{RESET}")
    sys.exit(0)
