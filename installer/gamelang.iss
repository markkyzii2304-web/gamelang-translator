; GameLang Translator — Inno Setup Script v2
; สร้าง .exe installer สำหรับ Windows
; ต้องการ: Inno Setup 6+ (https://jrsoftware.org/isinfo.php)

#define MyAppName      "GameLang Translator"
#define MyAppVersion   "2.0.0"
#define MyAppPublisher "GameLang"
#define MyAppExeName   "GameLang.exe"
#define MyAppURL       "https://github.com/gamelang/translator"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\LICENSE.txt
OutputDir=..\installer_output
OutputBaseFilename=GameLang_Translator_v{#MyAppVersion}_Setup
SetupIconFile=..\assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
; ไม่ต้องการ .NET หรือ runtime เพิ่ม (bundle แล้ว)
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "thai"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";    Description: "สร้าง shortcut บน Desktop";    GroupDescription: "Shortcuts:"
Name: "startmenuicon";  Description: "สร้าง shortcut ใน Start Menu"; GroupDescription: "Shortcuts:"

[Files]
; bundle ทั้งโฟลเดอร์จาก PyInstaller
Source: "..\dist\GameLang\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";           Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}";   Filename: "{app}\{#MyAppExeName}"; \
  Tasks: desktopicon

[Registry]
; เก็บ API key ใน Registry (encrypted) ถ้าผู้ใช้ตั้งค่าไว้
Root: HKCU; Subkey: "Software\GameLang"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\GameLang\Translator"; Flags: uninsdeletekey

[Run]
; เปิดแอปหลังติดตั้ง
Filename: "{app}\{#MyAppExeName}"; \
  Description: "เปิด {#MyAppName}"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
Type: dirifempty;     Name: "{app}"

[Code]
// ── ตรวจสอบ Windows version (ต้องการ Windows 10+) ──────────────────────────
function InitializeSetup(): Boolean;
var
  Version: TWindowsVersion;
begin
  GetWindowsVersionEx(Version);
  if Version.Major < 10 then begin
    MsgBox(
      'GameLang Translator ต้องการ Windows 10 หรือใหม่กว่า' + #13#10 +
      'กรุณาอัปเดต Windows ก่อนติดตั้ง',
      mbError, MB_OK
    );
    Result := False;
  end else
    Result := True;
end;

// ── แสดงข้อความต้อนรับ ────────────────────────────────────────────────────
procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'GameLang Translator จะถูกติดตั้งในเครื่องของคุณ' + #13#10 + #13#10 +
    'แอปนี้ใช้สำหรับแปลเกม offline/co-op เป็นภาษาไทย' + #13#10 +
    'โดย patch ไฟล์เกมโดยตรง ไม่กระทบ performance' + #13#10 + #13#10 +
    'ต้องการ API Key จาก platform.anthropic.com' + #13#10 +
    '(ตั้งค่าได้ภายในแอปหลังติดตั้ง)';
end;
