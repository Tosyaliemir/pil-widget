# Wireless Battery'yi (vendor/wireless-battery, json-cikti dalı) MSYS2 MinGW ile derler ve
# exe ile lisansını pilwidget\bin\ içine koyar. Gerekenler: MSYS2 ve
#   pacman -S --needed mingw-w64-x86_64-gcc make
# Kullanım: powershell -NoProfile -ExecutionPolicy Bypass -File tools\build-wb.ps1 [-Test]
param([switch]$Test)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root "vendor\wireless-battery"
$bin = Join-Path $root "pilwidget\bin"
$msys = if ($env:MSYS2_ROOT) { $env:MSYS2_ROOT } else { "C:\msys64" }
$bash = Join-Path $msys "usr\bin\bash.exe"

if (-not (Test-Path (Join-Path $src "Makefile"))) {
    git -C $root submodule update --init vendor/wireless-battery
    if ($LASTEXITCODE) { throw "Submodule alınamadı" }
}
if (-not (Test-Path $bash)) { throw "MSYS2 bulunamadı: $bash (winget install MSYS2.MSYS2)" }

$env:MSYSTEM = "MINGW64"
$env:CHERE_INVOKING = "1"
Push-Location $src
try {
    $target = if ($Test) { "WirelessBattery.exe test" } else { "WirelessBattery.exe" }
    & $bash -lc "make -j8 $target"
    if ($LASTEXITCODE) { throw "Wireless Battery derlenemedi" }
} finally { Pop-Location }

New-Item -ItemType Directory -Force $bin | Out-Null
Copy-Item (Join-Path $src "WirelessBattery.exe") $bin -Force
Copy-Item (Join-Path $src "LICENSE") (Join-Path $bin "WirelessBattery-LICENSE.txt") -Force
Write-Host "Tamam: $bin\WirelessBattery.exe"
