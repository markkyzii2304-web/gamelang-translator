@echo off
setlocal EnableDelayedExpansion
title GameLang — Build Installer

echo.
echo  ================================================
echo   GameLang Translator — Build .exe + Installer
echo  ================================================
echo.

REM ── Step 1: ตรวจสอบ Python ────────────────────────────────────────────────
echo [1/5] ตรวจสอบ Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: ไม่พบ Python
    echo  ดาวน์โหลดที่ https://python.org แล้วติ๊ก "Add to PATH"
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  OK: Python %PY_VER%

REM ── Step 2: ติดตั้ง dependencies ──────────────────────────────────────────
echo.
echo [2/5] ติดตั้ง dependencies...
pip install pyinstaller PyQt6 requests anthropic --quiet
if errorlevel 1 (
    echo  ERROR: pip install ล้มเหลว
    pause & exit /b 1
)
echo  OK: dependencies พร้อม

REM ── Step 3: PyInstaller --onedir ──────────────────────────────────────────
echo.
echo [3/5] Build .exe ด้วย PyInstaller (onedir)...
if exist "dist\GameLang" rmdir /s /q "dist\GameLang"
if exist "build"         rmdir /s /q "build"

pyinstaller ^
  --name "GameLang" ^
  --onedir ^
  --windowed ^
  --add-data "core;core" ^
  --hidden-import PyQt6.QtWidgets ^
  --hidden-import PyQt6.QtCore ^
  --hidden-import PyQt6.QtGui ^
  --hidden-import anthropic ^
  --hidden-import requests ^
  --collect-all PyQt6 ^
  --clean ^
  --noconfirm ^
  main.py

if errorlevel 1 (
    echo  ERROR: PyInstaller ล้มเหลว
    pause & exit /b 1
)
echo  OK: dist\GameLang\GameLang.exe พร้อม

REM ── Step 4: สร้าง assets ──────────────────────────────────────────────────
echo.
echo [4/5] เตรียม assets...
if not exist "assets" mkdir assets
if not exist "assets\icon.ico" (
    echo  NOTE: ไม่พบ icon.ico — ใช้ default icon
    REM สร้าง icon จาก Python ถ้ามี Pillow
    python -c "
try:
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (64,64), (9,9,18,255))
    d = ImageDraw.Draw(img)
    d.rectangle([8,8,56,56], fill=(107,158,255,255))
    d.text((20,20), 'G', fill=(255,255,255,255))
    img.save('assets/icon.ico', format='ICO', sizes=[(64,64),(32,32),(16,16)])
    print('  OK: สร้าง icon สำเร็จ')
except:
    print('  SKIP: ไม่มี Pillow')
" 2>nul
)

REM สร้าง LICENSE.txt ถ้าไม่มี
if not exist "LICENSE.txt" (
    echo GameLang Translator > LICENSE.txt
    echo Copyright 2024 GameLang >> LICENSE.txt
    echo For personal use with offline/co-op games only. >> LICENSE.txt
)

REM ── Step 5: Inno Setup ────────────────────────────────────────────────────
echo.
echo [5/5] สร้าง Installer ด้วย Inno Setup...
mkdir installer_output 2>nul

set ISCC=""
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
)

if %ISCC%=="" (
    echo.
    echo  ┌─────────────────────────────────────────────────┐
    echo  │  Inno Setup ไม่พบในระบบ                        │
    echo  │  ดาวน์โหลด: https://jrsoftware.org/isinfo.php  │
    echo  │  ติดตั้งแล้วรัน build_installer.bat ใหม่       │
    echo  └─────────────────────────────────────────────────┘
    echo.
    echo  .exe ยังใช้ได้อยู่ที่: dist\GameLang\GameLang.exe
) else (
    %ISCC% "installer\gamelang.iss"
    if errorlevel 1 (
        echo  ERROR: Inno Setup ล้มเหลว
        echo  .exe ยังใช้ได้ที่: dist\GameLang\GameLang.exe
    ) else (
        echo  OK: Installer พร้อมที่ installer_output\
    )
)

REM ── Summary ────────────────────────────────────────────────────────────────
echo.
echo  ================================================
echo   Build เสร็จสิ้น!
echo  ================================================
echo.
echo   .exe โดยตรง : dist\GameLang\GameLang.exe
echo   Installer   : installer_output\GameLang_Translator_v2.0.0_Setup.exe
echo.
echo   วิธีแจกจ่าย:
echo   - แจก Setup.exe ให้ผู้ใช้ double-click ติดตั้ง
echo   - หรือแจก dist\GameLang\ ทั้งโฟลเดอร์ (zip ก่อน)
echo.
pause
