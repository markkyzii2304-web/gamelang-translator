"""
library.py — Persistent Game Library
เก็บรายการเกมที่ผ่านการ scan engine แล้ว
Location: ~/.gamelang/library.json

Rules:
- เกมจะถูกเพิ่มก็ต่อเมื่อ engine detect ได้ (Engine != UNKNOWN)
- dedup โดยใช้ game_dir (case-insensitive)
"""

import os
import json
from datetime import datetime

LIBRARY_DIR  = os.path.expanduser("~/.gamelang")
LIBRARY_PATH = os.path.join(LIBRARY_DIR, "library.json")


def load_library() -> list[dict]:
    """โหลด library จาก disk — คืน [] ถ้าไฟล์ไม่มีหรือ corrupt"""
    try:
        with open(LIBRARY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        games = data.get("games", [])
        # กรอง entries ที่ game_dir ไม่ถูกต้อง
        return [g for g in games if g.get("name") and g.get("game_dir")]
    except Exception:
        return []


def save_library(games: list[dict]) -> None:
    """บันทึก library ลง disk"""
    os.makedirs(LIBRARY_DIR, exist_ok=True)
    with open(LIBRARY_PATH, "w", encoding="utf-8") as f:
        json.dump({"games": games, "updated": datetime.now().isoformat()},
                  f, ensure_ascii=False, indent=2)


def _normalize_dir(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def add_game(games: list[dict], entry: dict) -> list[dict]:
    """
    เพิ่มเกมลง library (ถ้ามี game_dir ซ้ำ → อัปเดต entry เดิม)
    คืน list ที่อัปเดตแล้ว
    """
    new_key = _normalize_dir(entry.get("game_dir", ""))
    updated = [g for g in games
               if _normalize_dir(g.get("game_dir", "")) != new_key]
    updated.append(entry)
    return updated


def remove_game(games: list[dict], game_dir: str) -> list[dict]:
    """ลบเกมออกจาก library โดยใช้ game_dir — คืน list ที่อัปเดตแล้ว"""
    key = _normalize_dir(game_dir)
    return [g for g in games
            if _normalize_dir(g.get("game_dir", "")) != key]


def make_entry(name: str, game_dir: str,
               engine: str, method: str,
               appid: int = 0) -> dict:
    """สร้าง library entry"""
    return {
        "name":      name,
        "game_dir":  game_dir,
        "engine":    engine,
        "method":    method,
        "appid":     appid,
        "added_at":  datetime.now().isoformat(),
    }
