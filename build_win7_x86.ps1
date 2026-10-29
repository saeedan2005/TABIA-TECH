# Build a self-contained 32-bit Windows GUI executable + one-file installer.
# Requires: Windows x86 Python 3.8.10, Inno Setup 6.x, Internet for pip.
param([string] $InnoCompiler = '')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

python -c "import sys, struct, tkinter, sqlite3; assert sys.version_info[:2]==(3,8), 'Python 3.8 required'; assert struct.calcsize('P')*8==32, 'Use x86 / 32-bit Python'; print('Python:',sys.version, 'SQLite:',sqlite3.sqlite_version)"
if ($LASTEXITCODE -ne 0) { throw 'The selected Python is not 3.8 x86 with Tkinter.' }

python -m pip install --disable-pip-version-check "pyinstaller==5.13.2"
if ($LASTEXITCODE -ne 0) { throw 'Could not install PyInstaller 5.13.2.' }

python TABIA_TECH_integration_tests.py
if ($LASTEXITCODE -ne 0) { throw 'Database tests failed.' }

python -m PyInstaller --noconfirm --clean --onedir --windowed --name TABIA_TECH `
    --add-data 'TABIA_TECH_schema.sql;.' --add-data 'TABIA_TECH.db;.' `
    TABIA_TECH_desktop.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

python verify_win32_build.py dist\TABIA_TECH\TABIA_TECH.exe
if ($LASTEXITCODE -ne 0) { throw 'Win32 verification failed.' }

if (-not $InnoCompiler) {
  $paths = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
  )
  foreach ($candidate in $paths) { if (Test-Path $candidate) { $InnoCompiler=$candidate; break } }
}
if (-not $InnoCompiler -or -not (Test-Path $InnoCompiler)) {
  throw 'Install Inno Setup 6 or pass its full ISCC.exe path via -InnoCompiler.'
}
& $InnoCompiler TABIA_TECH_Win7_x86.iss
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }
$setup=Join-Path $PSScriptRoot 'installer_output\TABIA_TECH_Setup_Win7_x86.exe'
if (-not (Test-Path $setup)) { throw "Installer was not created: $setup" }
Write-Host "SUCCESS: $setup"
Get-FileHash -Algorithm SHA256 $setup
