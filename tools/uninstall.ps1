# Pil Widget'ı kaldırır. Ayarlar ve pil geçmişi (%APPDATA%\PilWidget) yerinde bırakılır.
$ErrorActionPreference = 'SilentlyContinue'
$AppName = 'Pil Widget'
$Dir = Join-Path $env:LOCALAPPDATA "Programs\$AppName"

Get-Process PilWidget | Stop-Process -Force
Start-Sleep -Milliseconds 800

Remove-Item (Join-Path ([Environment]::GetFolderPath('Programs')) "$AppName.lnk") -Force
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'PilWidget'
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\PilWidget' -Recurse -Force

# Bu betik de program klasöründe; klasörü kısa bir gecikmeyle sil
Start-Process cmd.exe -ArgumentList "/c timeout /t 2 >nul & rmdir /s /q `"$Dir`"" -WindowStyle Hidden
