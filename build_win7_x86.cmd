@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_win7_x86.ps1"
if errorlevel 1 (
  echo.
  echo ERROR: The installer build failed. Check Python 3.8 x86 / Inno Setup.
  pause
  exit /b 1
)
echo.
echo SUCCESS: installer_output\TABIA_TECH_Setup_Win7_x86.exe
pause
