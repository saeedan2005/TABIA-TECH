; TABIA TECH 1.1 — 32-bit Windows 7 SP1+ installer (Inno Setup 6.x).
; Run after build_win7_x86.cmd / build_win7_x86.ps1.
#define MyAppName "TABIA TECH - تعبئة تك"
#define MyAppVersion "1.1.0"
#define MyAppExeName "TABIA_TECH.exe"

[Setup]
AppId={{492C82E5-1FC0-44B9-A559-6E83AC4E99D0}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion} (32-bit)
AppPublisher=TABIA TECH
DefaultDirName={localappdata}\Programs\TABIA_TECH
DefaultGroupName=TABIA TECH
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
MinVersion=6.1.7601
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=installer_output
OutputBaseFilename=TABIA_TECH_Setup_Win7_x86
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes

[Files]
Source: "dist\TABIA_TECH\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TABIA TECH - تعبئة تك"; Filename: "{app}\{#MyAppExeName}"
Name: "{userdesktop}\TABIA TECH - تعبئة تك"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch TABIA TECH"; Flags: nowait postinstall skipifsilent

; User data is at %LOCALAPPDATA%\TABIA_TECH, OUTSIDE the install directory.
; The setup never overwrites or deletes the user's live database.
