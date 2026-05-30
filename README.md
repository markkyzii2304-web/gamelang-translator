# GameLang Translator v2

แอปแปลเกม offline/co-op เป็นภาษาไทย พร้อม patch ไฟล์เกมโดยตรง

---

## สร้าง .exe (ไม่ต้องติดตั้ง Python)

### ความต้องการ
- Windows 10+
- Python 3.11+ (เฉพาะตอน build — ผู้ใช้ปลายทางไม่ต้องมี)
- Inno Setup 6 → https://jrsoftware.org/isinfo.php

### สร้าง Installer
```bat
build_installer.bat
```

ได้ผลลัพธ์ 2 อย่าง:
- `dist\GameLang\GameLang.exe` — รันได้ทันที ไม่ต้อง Python
- `installer_output\GameLang_Translator_v2.0.0_Setup.exe` — แจกจ่ายให้คนอื่น

---

## รันจาก Source (สำหรับ developer)

```bash
pip install -r requirements.txt
set ANTHROPIC_API_KEY=sk-ant-...
python main.py
```

---

## Patch Methods

| Engine        | วิธี              | Settings เกม          |
|---------------|-------------------|-----------------------|
| Unity/Mono    | BepInEx mod       | ✓ ภาษาไทยใน Settings |
| Ren'Py        | .rpy translation  | ✓ Language → Thai     |
| RPG Maker     | JSON data patch   | ✓ ภาษาไทยใน Options  |
| Loc file      | Direct patch      | ✓ ตามรูปแบบเกม        |
| อื่นๆ         | Overlay layer     | แสดงทับหน้าจอ         |

---

## ฟีเจอร์หลัก
- Engine detection อัตโนมัติ
- Font Bundle — inject Thai font ถ้าเกมไม่มี
- Rollback One-Click — คืนค่าไฟล์เดิมได้ทันที
- Backup .bak ทุกครั้งก่อน patch
- ไม่มี API call ขณะเล่นเกม — download .glpack ล่วงหน้า
