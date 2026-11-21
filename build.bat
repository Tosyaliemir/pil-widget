@echo off
rem Tek dosyalik exe uretir: dist\PilWidget.exe
rem "build.bat kur" ile derledikten sonra bu kullaniciya kurar (Baslat menusu kisayolu dahil).
cd /d "%~dp0"
.venv\Scripts\python -m pip install -q pyinstaller
rem Pil motoru Wireless Battery (MSYS2 gerekir, bkz. README)
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build-wb.ps1 || exit /b 1
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --name PilWidget ^
  --add-data "pilwidget\ui;ui" ^
  --add-data "pilwidget\bin;bin" ^
  --icon assets\pil.ico ^
  --version-file tools\version_info.txt ^
  run_pilwidget.py || exit /b 1
if /i "%1"=="kur" powershell -NoProfile -ExecutionPolicy Bypass -File tools\install.ps1
