# Pil Widget

Bilgisayara bağlı kablosuz cihazların (fare, klavye, kumanda, kulaklık; 70+ cihaz) pilini [Wireless Battery](https://github.com/krisgfx9/Wireless-Device-Battery-Monitor) ile okuyup masaüstüne gömülü küçük bir widget'ta gösteren Windows programı (`PilWidget.exe`). İnternet, hesap ya da bulut kullanmaz.

- **Masaüstüne gömülü:** pencerelerin arkasında durur, Win+D'de kaybolmaz; görev çubuğunda ve Alt+Tab'da görünmez. Windows açık/koyu temasını izler.
- **Boyutlar:** Nano, Mini ve Detay. %15 ve altı kırmızı, şarjda mavi, uykudaki cihaz soluk.
- **Sürükle:** widget'ın üst çubuğundan tutup taşı. Konum kaydedilir; masaüstü simgelerinin üstüne düşerse kenara kayar, ekran söküldüyse görünür alana geri gelir.
- **Sağ tık menüsü:** boyut, konumu kilitle, widget'ı gizle, görev çubuğu görünümü, cihazları yenile, Pil Kontrol, düşük pil bildirimi, Windows ile başlat, çık.
- **Pil Kontrol penceresi** (çift tık ya da tepsi simgesi): bağlı cihazlar, seçilen cihazın son 24 saatlik pil grafiği, widget ve görev çubuğu ayarları.
- **Görev çubuğu:** isteğe bağlı pil alanı (sadece simge, simge + %, cam kapsül; solda ya da sağda).
- **Düşük pil bildirimi:** bir cihaz %15'e inince Windows bildirimi (şarj edilene kadar bir kez; kapatılabilir).
- **Veriler:** ayarlar, pil geçmişi ve günlük `%APPDATA%\PilWidget\` içinde. Cihazlar 2 dakikada bir okunur.

### Momentum Kontrol ile birlikte (isteğe bağlı)

[Momentum Kontrol](https://github.com/Tosyaliemir/momentum4-kontrol) ayrı bir programdır ve Pil Widget ona bağlı değildir. Açıksa kulaklığın durumunu `%APPDATA%\Momentum4Kontrol\durum.json` dosyasına yazar; Pil Widget bu dosyayı bulursa kulaklık için şarj durumunu ve gürültü modunu da gösterir (7 dakikadan eskiyse yok sayılır). Dosya yoksa kulaklığın pili Wireless Battery'den (Bluetooth) okunur.

## Kurulum

`build.bat kur` programı derler ve bu kullanıcıya kurar (yönetici izni gerekmez):

- Program: `%LOCALAPPDATA%\Programs\Pil Widget\PilWidget.exe`
- Başlat menüsü kısayolu ve Ayarlar > Uygulamalar listesinde kaldırma kaydı
- Eski sürümlerin Momentum Kontrol klasörüne kurduğu `PilWidget.exe` silinir; "Windows ile başlat" açıksa yeni konuma yönlendirilir.

Hazır exe'yi kurmak için: `powershell -ExecutionPolicy Bypass -File tools\install.ps1`. Program aynı anda tek kopya çalışır.

## Geliştirici olarak çalıştırma

Gereken: Windows 10/11, Python 3.12.

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run_pilwidget.py
```

Cihaz olmadan görmek için `--demo` (boyut: `--demo&widget=nano|mini|detay`, tema: `&theme=light`). Tek dosyalık exe için: `build.bat` (çıktı `dist\PilWidget.exe`).

### Wireless Battery'yi derleme

Pil motoru `vendor/wireless-battery` alt modülünde (GPL-3.0, `--json` eklenmiş `json-cikti` dalı). Derlemek için [MSYS2](https://www.msys2.org/) gerekir:

```powershell
winget install MSYS2.MSYS2
C:\msys64\usr\bin\bash.exe -lc "pacman -S --needed --noconfirm mingw-w64-x86_64-gcc make"
git submodule update --init
powershell -ExecutionPolicy Bypass -File tools\build-wb.ps1 -Test
```

`build-wb.ps1` exe'yi ve lisans metnini `pilwidget\bin\` içine koyar; `build.bat` bu adımı kendisi çalıştırır ve klasörü `PilWidget.exe`'nin içine paketler. Exe yoksa Pil Widget cihazları okuyamaz. Elle denemek için: `pilwidget\bin\WirelessBattery.exe --json` (örnek veri: `--json --demo`).

## Geliştirme

```powershell
.venv\Scripts\python -m pytest
```

| Dosya | İçerik |
|---|---|
| `pilwidget/app.py` | Pencereler, JS köprüsü, tepsi, sağ tık menüsü, düşük pil bildirimi, otomatik başlatma |
| `pilwidget/motor.py` | Wireless Battery'yi çalıştırma, `--json` ayrıştırma, önbellek, cihaz başına pil geçmişi, `durum.json` okuma |
| `pilwidget/masaustu.py` | Widget penceresinin Windows ayrıntıları (masaüstüne gömme, ekrana sığdırma, simgelerden kaçma) |
| `pilwidget/gorev_cubugu.py` | Görev çubuğundaki pil alanı |
| `pilwidget/ui/` | Widget ve Pil Kontrol penceresi arayüzü (HTML, CSS, JS) |
| `tools/` | Derleme ve kurulum betikleri (`build-wb.ps1`, `install.ps1`, `uninstall.ps1`, `make_pil_icon.py`) |
| `wallpaper/` | Wallpaper Engine web wallpaper'ı (yapım aşamasında, bkz. `HANDOFF.md`) |
