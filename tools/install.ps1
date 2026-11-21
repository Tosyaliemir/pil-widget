# Pil Widget'ı bu kullanıcı için kurar (yönetici izni gerekmez).
#   - Program:  %LOCALAPPDATA%\Programs\Pil Widget\PilWidget.exe
#   - Kısayol:  Başlat menüsü
#   - "Yüklü uygulamalar" listesinde kaldırma kaydı
# Kullanım:  powershell -ExecutionPolicy Bypass -File tools\install.ps1 [-Exe dist\PilWidget.exe] [-NoLaunch]
param(
    [string]$Exe = (Join-Path $PSScriptRoot '..\dist\PilWidget.exe'),
    [switch]$NoLaunch
)
$ErrorActionPreference = 'Stop'
$AppName = 'Pil Widget'
$Version = '1.0.0'
$Dir = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$Target = Join-Path $Dir 'PilWidget.exe'
$StartMenu = Join-Path ([Environment]::GetFolderPath('Programs')) "$AppName.lnk"
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\PilWidget'
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
# Eski sürümler Pil Widget'ı Momentum Kontrol'ün klasörüne kuruyordu
$OldTarget = Join-Path $env:LOCALAPPDATA 'Programs\Momentum Kontrol\PilWidget.exe'

if (-not (Test-Path $Exe)) { throw "Program dosyası bulunamadı: $Exe (önce build.bat çalıştırın)" }

# Açıksa kapat ki dosya değiştirilebilsin
Get-Process PilWidget -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 800

New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Copy-Item $Exe $Target -Force
Copy-Item (Join-Path $PSScriptRoot 'uninstall.ps1') (Join-Path $Dir 'uninstall.ps1') -Force
if (Test-Path $OldTarget) { Remove-Item $OldTarget -Force -ErrorAction SilentlyContinue }

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($StartMenu)
$lnk.TargetPath = $Target
$lnk.WorkingDirectory = $Dir
$lnk.IconLocation = "$Target,0"
$lnk.Description = 'Masaüstü pil widget''ı'
$lnk.Save()

# Kaldırma kaydı (Ayarlar > Uygulamalar > Yüklü uygulamalar)
New-Item -Path $UninstallKey -Force | Out-Null
$uninstall = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Dir\uninstall.ps1`""
$props = @{
    DisplayName = $AppName; DisplayVersion = $Version; Publisher = 'Emir'
    DisplayIcon = "$Target,0"; InstallLocation = $Dir
    UninstallString = $uninstall; QuietUninstallString = $uninstall
    NoModify = 1; NoRepair = 1
    EstimatedSize = [int]((Get-Item $Target).Length / 1KB)
}
foreach ($k in $props.Keys) {
    $type = if ($props[$k] -is [int]) { 'DWord' } else { 'String' }
    New-ItemProperty -Path $UninstallKey -Name $k -Value $props[$k] -PropertyType $type -Force | Out-Null
}

# "Windows ile başlat" açıksa yeni konuma yönlendir
if (Get-ItemProperty -Path $RunKey -Name 'PilWidget' -ErrorAction SilentlyContinue) {
    Set-ItemProperty -Path $RunKey -Name 'PilWidget' -Value "`"$Target`" --autostart"
}

Write-Output "Kuruldu: $Target"
if (-not $NoLaunch) { Start-Process $Target }
