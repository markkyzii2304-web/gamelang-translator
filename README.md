# GameLang Translator v2

> **แปลเกม offline/co-op เป็นภาษาไทย**

[![Version](https://img.shields.io/badge/version-2.0.6-blue)](https://github.com/markkyzii2304-web/gamelang-translator/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)](https://github.com/markkyzii2304-web/gamelang-translator/releases/latest)

---

## จุดประสงค์

เกม offline/co-op หลายเกมไม่มีรองรับภาษาไทย GameLang Translator แก้ปัญหานี้ด้วยการ:

1. **อ่านไฟล์เกม** — ดึงข้อความทั้งหมดออกมาจากไฟล์เกมโดยตรง  
2. **แปลล่วงหน้า** — ส่งให้ AI แปลเป็นชุด บันทึกเป็นไฟล์ `.glpack`  
3. **Patch ไฟล์เกม** — เขียนคำแปลกลับเข้าไฟล์เกม ครั้งเดียวก่อนเล่น  

ผลลัพธ์: เล่นเกมได้เป็นภาษาไทยเต็ม ไม่มี API call ขณะเล่น ไม่มี overlay ไม่มี lag

---

## การติดตั้ง

### วิธีที่ 1 — ดาวน์โหลด Installer (แนะนำ สำหรับผู้ใช้ทั่วไป)

1. ไปที่ [Releases](https://github.com/markkyzii2304-web/gamelang-translator/releases/latest)
2. ดาวน์โหลด `GameLang_Translator_vX.X.X_Setup.exe`
3. รัน installer — ไม่ต้องติดตั้ง Python หรือ dependency ใดๆ
4. เปิด **GameLang Translator** จาก Start Menu

**ความต้องการของระบบ:**
- Windows 10 หรือใหม่กว่า (64-bit)
- พื้นที่ว่างประมาณ 150 MB
- การเชื่อมต่ออินเทอร์เน็ต (สำหรับการแปลครั้งแรกเท่านั้น)

### วิธีที่ 2 — รันจาก Source (สำหรับ developer)

```bash
# 1. Clone repo
git clone https://github.com/markkyzii2304-web/gamelang-translator.git
cd gamelang-translator

# 2. ติดตั้ง dependencies
pip install -r requirements.txt

# 3. ตั้งค่า API key
set ANTHROPIC_API_KEY=sk-ant-...

# 4. รันแอป
python main.py
```

### วิธีที่ 3 — Build Installer เอง

ต้องการ:
- Python 3.11+
- [Inno Setup 6](https://jrsoftware.org/isinfo.php)

```bat
build_installer.bat
```

ได้ผลลัพธ์:
- `dist\GameLang\GameLang.exe` — รันได้ทันที
- `installer_output\GameLang_Translator_vX.X.X_Setup.exe` — แจกจ่ายได้

---

## วิธีใช้งาน

### ขั้นตอนหลัก

```
[1] เพิ่มเกม  →  [2] แปลทั้งหมด  →  [3] Patch เกม  →  เล่นได้เลย
```

#### 1. เพิ่มเกม

- กดปุ่ม **＋** ที่ sidebar ซ้าย
- เลือกโฟลเดอร์ที่ติดตั้งเกม (เช่น `C:\Program Files (x86)\Steam\steamapps\common\GameName`)
- แอปจะตรวจจับ engine อัตโนมัติ — เกมที่รองรับจะปรากฏใน sidebar

> หากเกมไม่ปรากฏ แปลว่า engine ยังไม่รองรับ (ดู [Engine รองรับ](#engine-รองรับ))

#### 2. แปลทั้งหมด

- เลือกเกมใน sidebar
- กด **▶ TRANSLATE ALL** — แอปจะดึงข้อความจากไฟล์เกมและแปลเป็น batch
- แถบ progress แสดง `กำลังแปล X / Y strings`
- ไฟล์ `.glpack` จะถูกบันทึกที่ `~/.gamelang/packs/`

> **Checkpoint Resume**: ถ้าหยุดกลางคัน ครั้งหน้าจะเริ่มต่อจากจุดที่ค้างอยู่โดยอัตโนมัติ

#### 3. ดาวน์โหลด Pack สำเร็จรูป (ทางเลือก)

ถ้ามีคนแปลเกมนั้นไว้แล้ว สามารถดาวน์โหลดได้เลย:

- กดปุ่ม **Community Packs** ที่ด้านล่างของ detail page
- เลือก pack ที่ต้องการ → กด **ดาวน์โหลด**
- Pack จะถูก merge กับคำแปลที่มีอยู่

#### 4. Patch เกม

- กด **⚡ PATCH GAME**
- แอปเขียนคำแปลกลับเข้าไฟล์เกม (backup `.bak` ถูกสร้างอัตโนมัติ)
- เปิดเกมเล่นได้เลย — ข้อความเป็นภาษาไทย

#### 5. Rollback (ถ้าต้องการ)

- กด **↺ ROLLBACK** เพื่อคืนค่าไฟล์เดิม
- แอปจะใช้ backup `.bak` ที่สร้างไว้ก่อน patch

---

## การตั้งค่า

กดไอคอน **⚙** ที่มุมบนขวาเพื่อเปิด Settings

| การตั้งค่า | คำอธิบาย |
|------------|----------|
| **Anthropic API Key** | จำเป็นสำหรับการแปล — รับได้ที่ [console.anthropic.com](https://console.anthropic.com) |
| **GitHub Token** | (ไม่บังคับ) สำหรับ auto-upload `.glpack` ที่แปลแล้วให้คนอื่นใช้ — รับได้ที่ GitHub → Settings → Developer settings → Personal access tokens |
| **Translation Style** | เลือก tone ของคำแปล (formal / casual) |

---

## Engine รองรับ

| Engine | วิธี Patch | รองรับ |
|--------|------------|--------|
| Unity (BepInEx) | Mod plugin | ✅ |
| Ren'Py | `.rpy` translation files | ✅ |
| RPG Maker MV/MZ | JSON data patch | ✅ |
| Localization files | Direct patch | ✅ |
| Unreal Engine 4 | `.pak` injection | ✅ |
| อื่นๆ | Overlay | ⚠ ทดลอง |

---

## ฟีเจอร์ครบ

- **Engine Detection** อัตโนมัติ — รู้จักเกมได้ทันทีที่ชี้โฟลเดอร์
- **Batch Translation** — แปลทีเดียวทั้งเกม ก่อนเล่น
- **Checkpoint Resume** — แปลค้างไว้ได้ ครั้งหน้าต่อจากตรงนั้น
- **Community Pack Store** — ดาวน์โหลดคำแปลที่คนอื่นทำไว้แล้ว
- **Auto Upload** — แปลเสร็จแล้ว share ให้คนอื่นได้เลย (ต้องการ GitHub Token)
- **Thai Font Bundle** — inject font ไทยเข้าเกมที่ไม่มี
- **One-Click Rollback** — คืนค่าเกมต้นฉบับได้ทันที
- **Steam Art** — แสดงรูป hero จาก Steam ใน sidebar

---

## สำหรับนักพัฒนา

### โครงสร้างโปรเจกต์

```
gamelang_v2/
├── main.py                  # UI หลัก (PyQt6)
├── core/
│   ├── engine_detector.py   # ตรวจจับ engine เกม
│   ├── extractor.py         # ดึง string จากไฟล์เกม
│   ├── glpack.py            # รูปแบบไฟล์ .glpack
│   ├── patchers.py          # เขียนคำแปลกลับเข้าเกม
│   ├── translation_memory.py# AI translation (Anthropic)
│   ├── library.py           # รายการเกมที่บันทึกไว้
│   ├── pack_store.py        # Community Pack Store
│   ├── pack_uploader.py     # อัปโหลด pack ขึ้น GitHub
│   ├── rollback.py          # ระบบ backup/restore
│   ├── font_bundle.py       # Thai font injection
│   └── updater.py           # ตรวจสอบ app update
├── test_smoke.py            # Smoke tests
└── build_installer.bat      # สร้าง installer
```

### รัน Tests

```bash
python test_smoke.py
```

### Format ไฟล์ `.glpack`

ไฟล์ gzip-compressed JSON เก็บที่ `~/.gamelang/packs/{game_id}.glpack`

```json
{
  "game": "Wandering Sword",
  "game_id": "wandering_sword",
  "engine": "Unity",
  "string_count": 12483,
  "strings": {
    "data/dialogue/ch1.json::events[0].pages[0].list[1].parameters[0]": {
      "o": "Where am I?",
      "t": "ฉันอยู่ที่ไหนนี่?",
      "f": "data/dialogue/ch1.json",
      "l": "Chapter 1"
    }
  }
}
```

---

## License

MIT License — ดูไฟล์ [LICENSE](LICENSE)
