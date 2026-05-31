# GameLang Translator v2

## 🤖 Dashboard Status Updates (ทำทุก task — ห้ามข้าม)

ทุกครั้งที่เริ่มหรือจบงาน ต้องรัน st.py เพื่ออัปเดต AI Dev Studio dashboard

### คำสั่ง (copy-paste ได้เลย)

```bash
# เมื่อเริ่มทำงาน — เปลี่ยน <Agent> และ "<กิจกรรม>"
"C:\Users\markk\OneDrive\Desktop\claude workspace\AI Dev Studio\.venv\Scripts\python.exe" "C:\Users\markk\OneDrive\Desktop\claude workspace\AI Dev Studio\st.py" set <Agent> running "<สิ่งที่กำลังทำ>"

# เมื่อทำเสร็จ
"C:\Users\markk\OneDrive\Desktop\claude workspace\AI Dev Studio\.venv\Scripts\python.exe" "C:\Users\markk\OneDrive\Desktop\claude workspace\AI Dev Studio\st.py" set <Agent> done "<ผลลัพธ์>"
```

### ใช้ Agent ชื่อไหน?

| งานที่ทำ | Agent |
|---------|-------|
| เขียนโค้ด, implement feature | `Cody` |
| แก้บั๊ก, debug | `Felix` |
| ออกแบบ architecture | `Aria` |
| review โค้ด | `Rex` |
| เขียน test | `Tessa` |
| เขียน docs | `Dora` |
| security | `Sam` |
| git, deploy | `Dana` |

### ตัวอย่าง workflow จริง

```bash
# 1. เริ่ม task
"C:\Users\markk\OneDrive\Desktop\claude workspace\AI Dev Studio\.venv\Scripts\python.exe" "C:\Users\markk\OneDrive\Desktop\claude workspace\AI Dev Studio\st.py" set Cody running "แก้ไข lexer ให้รองรับ syntax ใหม่"

# ... ทำงาน ...

# 2. เสร็จแล้ว
"C:\Users\markk\OneDrive\Desktop\claude workspace\AI Dev Studio\.venv\Scripts\python.exe" "C:\Users\markk\OneDrive\Desktop\claude workspace\AI Dev Studio\st.py" set Cody done "lexer รองรับ syntax ใหม่แล้ว"
```

### กฎเหล็ก
- **รัน `running` ก่อนเริ่มทำงานทุกครั้ง ไม่มีข้อยกเว้น**
- **รัน `done` ทันทีหลังทำเสร็จ ก่อนตอบ user**
- ถ้าไม่แน่ใจว่าใช้ agent ไหน → ใช้ `Cody`

---

## Project Overview

GameLang Translator — แปลงภาษาโปรแกรมมิ่งระหว่างกัน

## Language
- ตอบเป็น **ภาษาไทย** สำหรับคำอธิบาย
- ใช้ **ภาษาอังกฤษ** สำหรับโค้ดและ technical output
