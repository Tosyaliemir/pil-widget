"""Pil Widget: masaüstüne gömülü pil göstergesi + görev çubuğu şeridi + "Pil Kontrol" penceresi + tepsi simgesi.

Bağımsız bir programdır. Pilleri Wireless Battery ile okur. Momentum Kontrol (ayrı program) açıksa kulaklığın
daha hassas durumunu onun yazdığı durum.json'dan alır; bu yalnızca isteğe bağlı bir dosya okumasıdır. İnternete çıkmaz.
"""

from __future__ import annotations

import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import socket
import sys
import threading
import time
import winreg
from pathlib import Path

import webview

from . import masaustu
from .gorev_cubugu import GorevCubugu, resource
from .motor import BatteryLog, DeviceMonitor, apply_status

APP_NAME = "Pil Widget"
APP_ID = "Emir.PilWidget"
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "PilWidget"
SETTINGS_FILE = DATA_DIR / "ayarlar.json"
HISTORY_FILE = DATA_DIR / "pil.json"
M4_STATUS_FILE = Path(os.environ.get("APPDATA", Path.home())) / "Momentum4Kontrol" / "durum.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "PilWidget"
STARTUP_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
STARTUP_APPROVED_ENABLED = b"\x02" + b"\x00" * 11
INSTANCE_PORT = 47132   # tek örnek kilidi (yalnızca 127.0.0.1); Momentum Kontrol 47131 kullanır
AUTOSTART_ARG = "--autostart"
THEMES = ("auto", "dark", "light")
LOW_BATTERY = 15        # bu ve altı: kırmızı + bildirim
TASKBAR_STYLES = ("kapali", "simge", "yuzde", "kapsul")   # görev çubuğu şeridi: kapalı + 3 görünüm
TASKBAR_POSITIONS = ("sol", "sag")
DETAILS_TITLE = "Pil Kontrol"
# JS tarafındaki ayar adı -> ayarlar.json anahtarı
PREF_KEYS = {"size": "boyut", "theme": "tema", "locked": "kilitli", "low_notify": "dusuk_pil_bildirimi",
             "widget_on": "widget_acik", "taskbar": "gorev_cubugu", "taskbar_pos": "gorev_konum"}
PREF_CHOICES = {"size": masaustu.SIZES, "theme": THEMES, "taskbar": TASKBAR_STYLES, "taskbar_pos": TASKBAR_POSITIONS}
PREF_CHOICE_ERRORS = {"size": "Geçersiz boyut", "theme": "Geçersiz tema", "taskbar": "Geçersiz görev çubuğu görünümü",
                      "taskbar_pos": "Geçersiz görev çubuğu konumu"}

log = logging.getLogger(__name__)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data, compact: bool = False) -> None:
    """Atomik yazım. Geçici dosya adı iş parçacığına özgü: aynı anda iki yazım birbirinin dosyasını ezmez."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    text = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) if compact
            else json.dumps(data, ensure_ascii=False, indent=1))
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Windows ayrıntıları
# ---------------------------------------------------------------------------
def launch_command() -> str:
    # --autostart: açılışta başlatıldığını günlükte ayırt etmek ve tek örnek kilidinde sabırlı olmak için.
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {AUTOSTART_ARG}'
    # Oturum açılışında çalışma klasörü System32 olur: '-m pilwidget' paketi bulamaz; betiğin mutlak yolu verilir.
    pyw = Path(sys.executable).with_name("pythonw.exe")
    script = Path(__file__).resolve().parent.parent / "run_pilwidget.py"
    return f'"{pyw if pyw.exists() else sys.executable}" "{script}" {AUTOSTART_ARG}'


def autostart_value() -> str | None:
    """Run anahtarındaki PilWidget değeri (yoksa ya da boşsa None)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            val = str(winreg.QueryValueEx(key, RUN_VALUE)[0]).strip()
            return val or None
    except OSError:
        return None


def autostart_approved() -> bool:
    """Görev Yöneticisi / Ayarlar > Başlangıç uygulamaları tarafından devre dışı bırakılmamış mı?
    StartupApproved\\Run değerinde ilk bayt tek sayıysa (ör. 0x03) Windows Run girdisini çalıştırmaz."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_APPROVED_KEY) as key:
            data, _ = winreg.QueryValueEx(key, RUN_VALUE)
            if isinstance(data, (bytes, bytearray)) and data:
                return (data[0] & 1) == 0
    except OSError:
        pass
    return True


def _set_startup_approved(on: bool) -> None:
    """StartupApproved\\Run girdisi varsa: açarken etkinleştir (0x02...), kapatırken temizle."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_APPROVED_KEY, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
            try:
                winreg.QueryValueEx(key, RUN_VALUE)
            except FileNotFoundError:
                return
            if on:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_BINARY, STARTUP_APPROVED_ENABLED)
            else:
                winreg.DeleteValue(key, RUN_VALUE)
    except OSError:
        pass


def sync_autostart() -> bool:
    """Windows ile başlatma açıksa ama kayıtlı komut bugünkünden farklıysa (eski bozuk '-m pilwidget' gibi) yeniden yaz."""
    try:
        cur = autostart_value()
        if cur is not None and autostart_approved() and cur != launch_command():
            set_autostart(True)
            log.info("Windows ile başlatma komutu güncellendi: %s", launch_command())
            return True
    except OSError as exc:
        log.warning("Windows ile başlatma komutu güncellenemedi: %s", exc)
    return False


def autostart_enabled() -> bool:
    return autostart_value() is not None and autostart_approved()


def set_autostart(on: bool) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
    _set_startup_approved(on)


def free_http_port() -> int:
    """Arayüz sunucusu için boş bir yerel port. pywebview kalıcı modda herkese aynı 42001'i verir: başka bir
    pywebview programı (ör. Momentum Kontrol / Pil Widget) önce açıldıysa sayfalar onun sunucusundan istenir ve 404 olur."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def style_window(title: str, light: bool = False) -> None:
    """Başlık çubuğu rengi ve teması (Windows 11); 64-bit HWND taşmasını önlemek için argtypes tanımlı."""
    try:
        from ctypes import wintypes

        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
        hwnd = masaustu.find_own_window(title)   # başlığa ek olarak işlem kimliği denetlenir
        if not hwnd:
            return
        wh = wintypes.HWND(hwnd)
        dark = ctypes.c_int(0 if light else 1)
        dwm.DwmSetWindowAttribute(wh, 20, ctypes.byref(dark), 4)
        color = ctypes.c_int(0xE8ECEE if light else 0x131313)   # COLORREF (BGR)
        dwm.DwmSetWindowAttribute(wh, 35, ctypes.byref(color), 4)
        dwm.DwmSetWindowAttribute(wh, 34, ctypes.byref(color), 4)
        text = ctypes.c_int(0x191A1B if light else 0xC8CCD0)
        dwm.DwmSetWindowAttribute(wh, 36, ctypes.byref(text), 4)
    except Exception:  # noqa: BLE001
        pass


def claim_single_instance(on_show, attempts: int = 1, delay: float = 1.5) -> tuple[bool, socket.socket | None]:
    """İlk örnek dinler; sonraki örnekler ilk örneğe 'göster' deyip kapanır.
    Dönüş (devam_et, kilit). Port alınamazsa ama dinleyen bir örnek de yoksa (port başka bir şeyde ya da Windows
    ayırmış) sessizce kapanmaz: yeniden dener, olmazsa kilitsiz açılır. Her karar gunluk.txt'ye yazılır."""
    srv = None
    for i in range(max(1, attempts)):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            srv.bind(("127.0.0.1", INSTANCE_PORT))
            break
        except OSError as exc:
            srv.close()
            srv = None
            try:
                ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ilk örnek Pil Kontrol penceresini öne getirebilsin
            except Exception:  # noqa: BLE001
                pass
            try:
                with socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=2) as c:
                    c.sendall(b"show")
                log.info("Pil Widget zaten açık; açık olan örneğe 'göster' gönderildi, bu örnek kapanıyor")
                return False, None
            except OSError as conn_exc:
                log.warning("Tek örnek portu %s alınamadı (%s) ve dinleyen örnek yok (%s); deneme %d/%d",
                            INSTANCE_PORT, exc, conn_exc, i + 1, attempts)
            if i + 1 < attempts:
                time.sleep(delay)
    if srv is None:
        log.warning("Tek örnek kilidi alınamadı; kilitsiz devam ediliyor")
        return True, None
    srv.listen(2)

    def serve() -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            try:
                with conn:
                    conn.settimeout(2)   # bağlanıp susan bir istemci döngüyü kilitlemesin
                    if conn.recv(16) == b"show":
                        on_show()
            except Exception:  # noqa: BLE001 - tek bağlantının hatası dinleyiciyi öldürmesin
                log.exception("Tek örnek isteği işlenemedi")

    threading.Thread(target=serve, daemon=True, name="tek-ornek").start()
    return True, srv


# ---------------------------------------------------------------------------
# JS köprüsü (widget ve Pil Kontrol penceresi aynı nesneyi kullanır)
# ---------------------------------------------------------------------------
class Api:
    def __init__(self, controller: "Controller") -> None:
        self._c = controller

    def get_demo(self) -> str:
        return self._c.demo

    def get_prefs(self) -> dict:
        return self._c.prefs()

    def get_devices(self) -> dict:
        return self._c.payload()

    def refresh_devices(self) -> dict:
        self._c.monitor.refresh(wait=15)   # yeni tur bitene kadar (en çok 15 sn) bekler; bu çağrı GUI iş parçacığında değil
        return self._c.payload()

    def get_device_history(self, key: str, hours: int = 24) -> list:
        return self._c.history.recent(str(key), int(hours))

    def widget_menu(self) -> None:
        self._c.widget_menu()

    def widget_fit(self, width: int, height: int) -> None:
        self._c.widget_fit(int(width), int(height))

    def open_details(self) -> None:
        self._c.show_details()

    def set_pref(self, key: str, value) -> dict:
        return self._c.set_pref(str(key), value)

    def hide_details(self) -> None:
        self._c.close_details()


# ---------------------------------------------------------------------------
# Denetleyici
# ---------------------------------------------------------------------------
def validate_settings(raw, defaults: dict) -> dict:
    """ayarlar.json'dan okunan değerleri anahtar anahtar doğrular; geçersiz/eksik olan varsayılana düşer."""
    raw = raw if isinstance(raw, dict) else {}
    out = dict(defaults)
    size = {"kompakt": "nano", "genis": "detay"}.get(raw.get("boyut"), raw.get("boyut"))   # eski boyut adları
    choices = {"boyut": masaustu.SIZES, "tema": THEMES, "gorev_cubugu": TASKBAR_STYLES, "gorev_konum": TASKBAR_POSITIONS}
    for key, values in choices.items():
        v = size if key == "boyut" else raw.get(key)
        if isinstance(v, str) and v in values:
            out[key] = v
    for key in ("kilitli", "dusuk_pil_bildirimi", "widget_acik"):
        v = raw.get(key)
        if isinstance(v, bool) or (isinstance(v, int) and v in (0, 1)):
            out[key] = bool(v)
    for key in ("x", "y"):
        v = raw.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and -100000 < v < 100000:
            out[key] = v
    if out["x"] is None or out["y"] is None:
        out["x"] = out["y"] = None   # yarım konum anlamsız
    return out


class Controller:
    DEFAULTS = {"boyut": "nano", "tema": "auto", "x": None, "y": None, "kilitli": False, "dusuk_pil_bildirimi": True,
                "widget_acik": True, "gorev_cubugu": "kapali", "gorev_konum": "sol"}

    def __init__(self) -> None:
        self.settings = validate_settings(read_json(SETTINGS_FILE, {}), self.DEFAULTS)
        self.history = BatteryLog(HISTORY_FILE, read_json, lambda path, data: write_json(path, data, compact=True))
        self.demo = next((a[2:] for a in sys.argv if a.startswith("--demo")), "")
        self.monitor = DeviceMonitor(on_change=self._changed)
        self.widget: webview.Window | None = None
        self.details: webview.Window | None = None
        self.tray = None
        self.strip: GorevCubugu | None = None   # görev çubuğu şeridi (yalnızca ayar "kapalı" değilken)
        self._strip_lock = threading.Lock()
        self._quitting = False
        self._session_ending = False   # Windows kapanıyor / oturum kapanıyor (kısa süreli)
        self._low_notified: set[str] = set()
        self._save_timer: threading.Timer | None = None
        self._save_lock = threading.Lock()           # zamanlayıcı kurma ve dosyaya yazma tek kilit altında
        self._save_pending = False
        self._cache: dict[str, tuple[float, object]] = {}   # pahalı sorguların kısa süreli önbelleği (prefs)
        self._status_mtime = 0.0
        self._details_lock = threading.Lock()        # Pil Kontrol'ün aynı anda iki kez oluşmasını önler
        self._closing_wins: set[int] = set()         # kapanmakta olan Pil Kontrol pencereleri (id) — eskisi de yeniyi bozmaz
        self._details_ready: set[int] = set()        # sayfası yüklenmiş Pil Kontrol pencereleri (id)
        self._pump_lock = threading.Condition()
        self._pump: dict[str, tuple[object, str]] = {}   # fn -> (pencere, js): her olay için yalnızca en güncel
        self._pump_thread: threading.Thread | None = None
        self._avoid_timer: threading.Timer | None = None
        self._avoid_timer_lock = threading.Lock()
        self._avoid_lock = threading.Lock()
        self._last_move = 0.0                        # kullanıcının son sürüklemesi (time.monotonic)
        self._own_move: tuple[int, int, float] | None = None   # kendi yaptığımız taşıma (x, y, zaman); ev konumunu bozmaz
        self._pending_fit: tuple[int, int] | None = None       # widget gizliyken istenen boyut (açılınca uygulanır)
        self._icon_count: int | None = None          # son görülen masaüstü simge sayısı
        self._last_full_query = 0.0                  # son tam simge sorgusu (time.monotonic)
        self._icons_dirty = True                     # tam sorgu gerekli (taşıma/boyut/yeniden gömme)

    @property
    def _details_closing(self) -> bool:
        win = self.details
        return win is not None and id(win) in self._closing_wins

    # -- veri -----------------------------------------------------------------
    def payload(self) -> dict:
        status = read_json(M4_STATUS_FILE, None)
        devices = apply_status(self.monitor.devices(), status, time.time())
        return {"devices": devices, "error": self.monitor.error, "updated": self.monitor.updated}

    def _changed(self) -> None:
        p = self.payload()
        for d in p["devices"]:
            if d["connected"] and not d["stale"] and not d["asleep"] and d["percent"] >= 0:
                self.history.add(d["key"], d["percent"], d["charging"])
        self._yay("onDevices", p, skip_hidden_widget=True)
        self._check_low(p["devices"])
        self._sync_strip(p["devices"])

    def _watch_status(self) -> None:
        """Momentum Kontrol durum.json'u güncelleyince (gürültü modu, şarj) widget'ı hemen tazele."""
        while not self._quitting:
            try:
                try:
                    mtime = M4_STATUS_FILE.stat().st_mtime
                except OSError:
                    mtime = 0.0
                if mtime != self._status_mtime:
                    self._status_mtime = mtime
                    self._changed()
            except Exception:  # noqa: BLE001 - tek bir hata izleyiciyi öldürmesin
                log.exception("Durum izleme turu başarısız")
            time.sleep(3)

    def _yay(self, fn: str, payload, skip_hidden_widget: bool = False) -> None:
        """Aynı olayı iki pencereye (widget ve Pil Kontrol) gönderir: window.<fn>(payload).
        Pil Kontrol yoksa ya da kapanıyorsa (ve istenirse widget gizliyse) o pencereye JS çalıştırılmaz."""
        js = f"window.{fn} && window.{fn}({json.dumps(payload, ensure_ascii=False)})"
        widget = None if skip_hidden_widget and not self.settings["widget_acik"] else self.widget
        if widget is not None:
            try:
                widget.evaluate_js(js)
            except Exception:  # noqa: BLE001 - pencere kapanırken ya da gizliyken olabilir
                pass
        self._send_details(fn, js)

    def _send_details(self, fn: str, js: str) -> None:
        """Pil Kontrol'e JS gönderimi ayrı tek iş parçacığında (takılırsa izleme iş parçacıkları beklemesin);
        sayfa yüklenmemişse atlanır, bekleyen aynı olayın yerine en günceli konur."""
        win = self.details
        if win is None or id(win) not in self._details_ready or id(win) in self._closing_wins:
            return
        with self._pump_lock:
            self._pump[fn] = (win, js)
            if self._pump_thread is None or not self._pump_thread.is_alive():
                self._pump_thread = threading.Thread(target=self._pump_loop, daemon=True, name="details-js")
                self._pump_thread.start()
            self._pump_lock.notify()

    def _pump_loop(self) -> None:
        while not self._quitting:
            with self._pump_lock:
                if not self._pump:
                    self._pump_lock.wait(30)
                    if not self._pump:
                        if self.details is None:
                            self._pump_thread = None
                            return   # Pil Kontrol yok: iş parçacığı boşa beklemesin (gerekince yeniden başlar)
                        continue
                batch, self._pump = list(self._pump.values()), {}
            for win, js in batch:
                if win is self.details and id(win) in self._details_ready and id(win) not in self._closing_wins:
                    try:
                        win.evaluate_js(js)
                    except Exception:  # noqa: BLE001 - pencere kapanırken olabilir
                        pass

    def _check_low(self, devices: list[dict]) -> None:
        """%15 ve altına düşen etkin cihaz için bir kez bildirim; şarj edilene ya da %15 üstüne çıkana kadar tekrar yok."""
        for d in devices:
            key, pct = d["key"], d["percent"]
            if not d["connected"] or d["stale"] or d["asleep"]:
                continue
            if d["charging"] or pct > LOW_BATTERY:
                self._low_notified.discard(key)
            elif (0 <= pct <= LOW_BATTERY and key not in self._low_notified
                  and self.settings.get("dusuk_pil_bildirimi", True) and self.tray):
                self._low_notified.add(key)
                try:
                    self.tray.notify(f"{d['name']}: pil %{pct}. Şarj etmeyi unutma.", "Pil azaldı")
                except Exception as exc:  # noqa: BLE001
                    log.info("Bildirim gösterilemedi: %s", exc)

    # -- ayarlar --------------------------------------------------------------
    def prefs(self) -> dict:
        s = self.settings
        return {"size": s["boyut"] if s["boyut"] in masaustu.SIZES else "nano",
                "theme": s["tema"] if s["tema"] in THEMES else "auto", "locked": bool(s["kilitli"]),
                "low_notify": bool(s["dusuk_pil_bildirimi"]), "autostart": self._cached("autostart", autostart_enabled, ttl=10),
                "widget_on": bool(s["widget_acik"]),
                "taskbar": s["gorev_cubugu"] if s["gorev_cubugu"] in TASKBAR_STYLES else "kapali",
                "taskbar_pos": s["gorev_konum"] if s["gorev_konum"] in TASKBAR_POSITIONS else "sol"}

    def _cached(self, name: str, fn, ttl: float = 300):
        """Kayıt defteri/dosya sorgularını prefs() her çağrıldığında yapmamak için kısa süre önbellekler."""
        now = time.monotonic()
        hit = self._cache.get(name)
        if hit is None or now - hit[0] > ttl:
            hit = self._cache[name] = (now, fn())
        return hit[1]

    def _save(self, delay: float = 0.8) -> None:
        if self.demo:   # demo gerçek ayar dosyasına yazmaz
            return
        with self._save_lock:
            if self._save_timer:
                self._save_timer.cancel()
            self._save_pending = True
            self._save_timer = threading.Timer(delay, self._write_settings)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _write_settings(self) -> None:
        """Bekleyen ayarları yazar (kilit altında: iki yazım iç içe girmez, hep en güncel hâl yazılır)."""
        with self._save_lock:
            if not self._save_pending:
                return
            try:
                write_json(SETTINGS_FILE, dict(self.settings))
                self._save_pending = False
            except OSError as exc:
                log.warning("Ayarlar yazılamadı: %s", exc)

    def flush_settings(self) -> None:
        """Çıkışta: bekleyen zamanlayıcıyı iptal edip ayarları ve pil geçmişini hemen yaz."""
        with self._save_lock:
            if self._save_timer:
                self._save_timer.cancel()
        self._write_settings()
        self.history.flush()

    def set_pref(self, key: str, value) -> dict:
        if key == "autostart":
            if not self.demo:
                try:
                    set_autostart(bool(value))
                    self._cache.pop("autostart", None)
                except OSError as exc:
                    return {"ok": False, "error": f"Otomatik başlatma ayarlanamadı: {exc}", "prefs": self.prefs()}
        elif key in PREF_KEYS:
            if key in PREF_CHOICES and value not in PREF_CHOICES[key]:
                return {"ok": False, "error": PREF_CHOICE_ERRORS[key], "prefs": self.prefs()}
            self.settings[PREF_KEYS[key]] = value if key in PREF_CHOICES else bool(value)
            if key == "theme":
                light = self._light()
                masaustu.embed(light)   # cam tonu ve kenarlık temaya uysun
                if self.details is not None:
                    style_window(DETAILS_TITLE, light)
            elif key == "widget_on":
                self._apply_widget()
            elif key in ("taskbar", "taskbar_pos"):
                self._sync_strip()
            self._save(0)
        else:
            return {"ok": False, "error": key, "prefs": self.prefs()}
        self._yay("onPrefs", self.prefs())
        if self.tray:
            try:
                self.tray.update_menu()   # tepsi menüsündeki işaretler (checked) yeni ayara uysun
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "prefs": self.prefs()}

    # -- widget ---------------------------------------------------------------
    def widget_fit(self, width: int, height: int) -> None:
        """Widget içeriğine göre pencere boyutu (JS ölçer, buraya bildirir)."""
        if not self.widget or width < 20 or height < 20:
            return
        width, height = min(width, 900), min(height, 900)
        if not self.settings["widget_acik"]:
            # pywebview'in resize()/move() çağrıları SWP_SHOWWINDOW gönderir; gizli widget'ı görünür yapmamalı.
            self._pending_fit = (width, height)
            return
        self._pending_fit = None
        if (self.widget.width, self.widget.height) != (width, height):
            self.widget.resize(width, height)
            masaustu.lower_widget()   # resize()'ın HWND_TOP'a çekmesini geri al
        self._keep_widget_visible()
        self._schedule_avoid(0.4)   # boyut değişti: simgelere binmiş olabilir

    def _keep_widget_visible(self) -> None:
        """Pencere hiçbir ekranda değilse görünür alana al (geçici; ev konumu ayarlarda aynen kalır)."""
        w = self.widget
        if not w or not self.settings["widget_acik"]:
            return
        try:
            x, y = masaustu.fit_on_screen(w.x, w.y, w.width, w.height)
            if (x, y) != (w.x, w.y):
                self._move_own(x, y)
        except Exception as exc:  # noqa: BLE001
            log.info("Widget konumu düzeltilemedi: %s", exc)

    def _move_own(self, x: int, y: int) -> None:
        """Kendi isteğimizle taşı: 'moved' olayı bunu kullanıcı sürüklemesi sanıp ev konumunu ezmesin."""
        self._own_move = (x, y, time.monotonic())
        self.widget.move(x, y)

    def _on_moved(self, x: int, y: int) -> None:
        own = self._own_move
        if own and time.monotonic() - own[2] < 3 and abs(x - own[0]) <= 2 and abs(y - own[1]) <= 2:
            return   # kendi taşımamız (ardışık moved olayları dahil): ev konumu değişmez
        self._own_move = None
        if self.settings.get("kilitli"):
            return   # konum kilitliyken sistem kaynaklı taşınmalar ev konumunu bozmasın
        # Kullanıcı sürükledi: bırakılan yer yeni EV konumu; simge çakışması varsa görünen konum ayrıca ayarlanır
        self.settings["x"], self.settings["y"] = x, y
        self._save()
        self._last_move = time.monotonic()
        self._icons_dirty = True
        self._schedule_avoid(0.6)   # sürükleme bitince (son hareketten 0,6 sn sonra) simgelerden kaçın

    # -- masaüstü simgelerinden kaçınma ---------------------------------------------
    def _schedule_avoid(self, delay: float) -> None:
        """Gecikmeli (art arda gelen olaylar tek hesapta birleşir) ve ayrı iş parçacığında: explorer meşgulse GUI donmasın."""
        if self._quitting or self.demo:
            return
        self._icons_dirty = True   # zamanlanan kaçınma her zaman tam simge sorgusu yapar
        with self._avoid_timer_lock:
            if self._avoid_timer:
                self._avoid_timer.cancel()
            self._avoid_timer = threading.Timer(delay, self._avoid_icons)
            self._avoid_timer.daemon = True
            self._avoid_timer.start()

    def _avoid_icons(self) -> None:
        w = self.widget
        if not w or self._quitting or not self.settings["widget_acik"] or not self._avoid_lock.acquire(blocking=False):
            return
        try:
            if time.monotonic() - self._last_move < 0.5:
                return   # kullanıcı hâlâ sürüklüyor; son hareketten sonra zamanlayıcı yeniden dener
            width, height = w.width, w.height
            # Hep EV konumundan (ayarlardaki x/y; kilitliyken de) hesaplanır: ev yeri boşalınca widget oraya döner.
            hx, hy = self.settings.get("x"), self.settings.get("y")
            if hx is None or hy is None:
                hx, hy = w.x, w.y
            hx, hy = masaustu.fit_on_screen(hx, hy, width, height)
            self._icons_dirty = False
            self._last_full_query = time.monotonic()
            nx, ny = masaustu.avoid_icons(hx, hy, width, height)
            if abs(nx - w.x) > 2 or abs(ny - w.y) > 2:
                log.info("Widget görünen konumu: (%s, %s) -> (%s, %s) (ev: %s, %s)", w.x, w.y, nx, ny, hx, hy)
                self._move_own(nx, ny)   # kaydedilmez
        except Exception as exc:  # noqa: BLE001
            log.info("Simgelerden kaçınma başarısız: %s", exc)
        finally:
            self._avoid_lock.release()

    def _watch_icons(self) -> None:
        """Arka plan bekçisi (5 sn'de bir, ucuz denetimler): Explorer yeniden başladıysa widget'ı masaüstüne yeniden göm;
        ekran düzeni değiştiyse widget'ı görünür alana al; simge sayısı değiştiyse (ya da en geç 60 sn'de bir) simgelerden kaçın."""
        areas, turn = None, 0
        while not self._quitting:
            time.sleep(5)
            turn += 1
            try:
                if self.settings["widget_acik"]:
                    if masaustu.embed_stale():
                        log.info("Masaüstü (Progman) yeniden oluştu; widget yeniden gömülüyor")
                        masaustu.embed(self._light())
                        self._schedule_avoid(0.5)
                    now_areas = masaustu.work_areas()
                    if areas is not None and now_areas != areas:   # ekran eklendi/söküldü, çözünürlük/ölçek değişti
                        self._keep_widget_visible()
                        self._icons_dirty = True
                    areas = now_areas
                    # Ucuz denetim: yalnızca simge SAYISI (Explorer belleğine yazmadan); sayı değiştiyse, widget
                    # taşındı/boyutlandı/yeniden gömüldüyse ya da 60 sn geçtiyse tam sorgu.
                    count = masaustu.desktop_icon_count()
                    changed = count is not None and count != self._icon_count
                    if count is not None:
                        self._icon_count = count
                    if changed or self._icons_dirty or time.monotonic() - self._last_full_query >= 60:
                        self._avoid_icons()
            except Exception:  # noqa: BLE001 - tek bir hata bekçiyi öldürmesin
                log.exception("Widget bekçisi turu başarısız")

    def _apply_widget(self) -> None:
        """'Masaüstü widget'ı' ayarına göre widget penceresini göster/gizle (uygulama tepside çalışmaya devam eder)."""
        w = self.widget
        if not w:
            return
        try:
            if self.settings["widget_acik"]:
                pending, self._pending_fit = self._pending_fit, None
                self._show_widget_quietly(w)
                if pending and (w.width, w.height) != pending:
                    w.resize(*pending)
                masaustu.embed(self._light())
                self._keep_widget_visible()
                self._schedule_avoid(0.5)
                self._yay("onDevices", self.payload())   # gizliyken güncellenmediği için
            else:
                w.hide()
        except Exception as exc:  # noqa: BLE001
            log.warning("Widget göster/gizle başarısız: %s", exc)

    @staticmethod
    def _show_widget_quietly(w) -> None:
        """Widget'ı etkinleştirmeden (odak çalmadan) göster. pywebview'in show()'u Show()+Activate() çağırır; burada
        yalnızca Form.Visible = True verilir (etkinleştirme yok). Olmazsa normal show()'a düşer."""
        try:
            from System import Func, Type   # pythonnet: pywebview'in WinForms arka ucu zaten yüklü

            native = w.native

            def show() -> None:
                native.Visible = True

            if native.InvokeRequired:
                native.Invoke(Func[Type](show))
            else:
                show()
        except Exception as exc:  # noqa: BLE001
            log.info("Widget sessiz gösterilemedi, normal gösterim: %s", exc)
            w.show()

    def _sync_strip(self, devices: list[dict] | None = None) -> None:
        """Görev çubuğu şeridini ayara uydur: kapalıysa durdur, değilse başlat ve güncel cihazları ver."""
        with self._strip_lock:
            mode = self.settings["gorev_cubugu"]
            if mode == "kapali" or self._quitting or self.demo:   # demo hiçbir zaman gerçek şerit açmaz
                if self.strip:
                    self.strip.stop()
                    self.strip = None
                return
            if self.strip is None:
                strip = GorevCubugu(on_click=self.show_details, on_menu=self.strip_menu)
                if not strip.start():
                    log.warning("Görev çubuğu şeridi başlatılamadı")
                    strip.stop()
                    return
                self.strip = strip
            if devices is None:
                devices = self.payload()["devices"]
            self.strip.update(devices, mode, self.settings["gorev_konum"])

    def _show_menu(self, entries: list) -> None:
        """Yerel menü: her öğe (etiket, işaretli, eylem) ya da ayırıcı için None; eylemi None olan öğe başlıktır."""
        items = [None if e is None else (e[0], bool(e[1]), e[2] is None) for e in entries]
        choice = masaustu.popup_menu(items)
        if choice is not None and entries[choice] and entries[choice][2]:
            entries[choice][2]()

    def _taskbar_entries(self, header: bool = True) -> list:
        cur, pos = self.settings["gorev_cubugu"], self.settings["gorev_konum"]
        style = lambda label, v: (label, cur == v, lambda: self.set_pref("taskbar", v))  # noqa: E731
        place = lambda label, v: (label, pos == v, lambda: self.set_pref("taskbar_pos", v))  # noqa: E731
        return ([("Görev çubuğu", False, None)] if header else []) + [
            style("Sadece simge", "simge"), style("Simge + %", "yuzde"), style("Cam kapsül", "kapsul"),
            style("Kapalı", "kapali"), None, place("Sol", "sol"), place("Sağ", "sag")]

    def widget_menu(self) -> None:
        p = self.prefs()
        entries = [
            ("Nano", p["size"] == "nano", lambda: self.set_pref("size", "nano")),
            ("Mini", p["size"] == "mini", lambda: self.set_pref("size", "mini")),
            ("Detay", p["size"] == "detay", lambda: self.set_pref("size", "detay")),
            None,
            ("Konumu kilitle", p["locked"], lambda: self.set_pref("locked", not p["locked"])),
            ("Widget'ı gizle", False, lambda: self.set_pref("widget_on", False)),
            None, *self._taskbar_entries(), None,
            ("Cihazları yenile", False, self.monitor.refresh),
            ("Pil Kontrol'ü aç", False, self.show_details),
        ]
        entries += [None,
                    ("Düşük pil bildirimi", p["low_notify"], lambda: self.set_pref("low_notify", not p["low_notify"])),
                    ("Windows ile başlat", p["autostart"], lambda: self.set_pref("autostart", not p["autostart"])),
                    None, ("Çık", False, self.quit)]
        self._show_menu(entries)

    def strip_menu(self) -> None:
        """Görev çubuğu şeridine sağ tık."""
        p = self.prefs()
        self._show_menu([
            *self._taskbar_entries(header=False), None,
            ("Masaüstü widget'ı", p["widget_on"], lambda: self.set_pref("widget_on", not p["widget_on"])),
            None, ("Pil Kontrol'ü aç", False, self.show_details),
        ])

    # -- pencereler ve tepsi ----------------------------------------------------
    def _create_details(self) -> webview.Window:
        """Pil Kontrol penceresini oluşturur. pywebview, start() sonrası ana iş parçacığı dışından create_window'a
        izin verir (pencere GUI iş parçacığında senkron oluşur). Kapanınca yok edilir; WebView'i bellekten gider."""
        light = self._light()
        win = webview.create_window(
            DETAILS_TITLE, url=str(resource("ui/cihazlar.html")), js_api=Api(self),
            width=460, height=680, min_size=(360, 420), background_color="#eeece8" if light else "#131313",
        )
        win.events.closing += lambda: self._on_details_closing(win)
        win.events.closed += lambda: self._on_details_closed(win)
        win.events.loaded += lambda: self._details_ready.add(id(win))
        win.events.shown += lambda: style_window(DETAILS_TITLE, self._light())
        return win

    def show_details(self) -> None:
        """Pil Kontrol'ü aç (ilk çağrıda oluşturulur, kapatılınca yok edilir). Ana iş parçacığından çağrılmaz."""
        if self._quitting:
            return
        with self._details_lock:   # art arda iki çağrı tek pencere açar
            deadline = time.monotonic() + 3
            while self._details_closing and self.details is not None and time.monotonic() < deadline:
                time.sleep(0.05)   # önceki pencere kapanıyor; bitmesini bekle
            win = self.details
            try:
                if win is None or self._details_closing:
                    win = self.details = self._create_details()
                else:
                    win.show()
                    win.restore()
            except Exception as exc:  # noqa: BLE001
                log.warning("Pil Kontrol açılamadı: %s", exc)
                return
        style_window(DETAILS_TITLE, self._light())
        masaustu.bring_to_front(DETAILS_TITLE)

    def close_details(self) -> None:
        """Pil Kontrol'ü kapat (yok et). JS çağrısını bekletmemek için ayrı iş parçacığında."""
        win = self.details
        if win is not None:
            threading.Thread(target=lambda: self._safe_destroy(win), daemon=True, name="details-kapat").start()

    @staticmethod
    def _safe_destroy(win) -> None:
        try:
            win.destroy()
        except Exception as exc:  # noqa: BLE001
            log.info("Pencere kapatılamadı: %s", exc)

    def _on_details_closing(self, win) -> bool:
        if not self._quitting:
            self._closing_wins.add(id(win))
        return True   # kapanmasına izin ver (False iptal eder); closed olayında self.details temizlenir

    def _on_details_closed(self, win) -> None:
        # Pencere başına izlenir: eski pencerenin geç gelen 'closed'ı yeni pencerenin durumunu bozmaz.
        self._closing_wins.discard(id(win))
        self._details_ready.discard(id(win))
        if self.details is win:
            self.details = None

    def quit(self) -> None:
        self._quitting = True
        self.monitor.stop()
        with self._avoid_timer_lock:
            if self._avoid_timer:
                self._avoid_timer.cancel()
                self._avoid_timer = None
        with self._pump_lock:
            self._pump_lock.notify_all()
        try:
            self.flush_settings()
        except Exception:  # noqa: BLE001
            log.exception("Çıkışta ayarlar yazılamadı")
        try:
            self._sync_strip()   # _quitting iken şeridi durdurur
        except Exception:  # noqa: BLE001
            pass
        if self.tray:
            try:
                self.tray.stop()
            except Exception:  # noqa: BLE001
                pass
        for win in (self.details, self.widget):
            if win:
                try:
                    win.destroy()
                except Exception:  # noqa: BLE001
                    pass

    def _tray_image(self):
        """Basit pil simgesi (ayrı bir resim dosyası gerekmesin)."""
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((6, 18, 52, 46), radius=7, outline=(236, 232, 226, 255), width=5)
        d.rounded_rectangle((54, 26, 60, 38), radius=2, fill=(236, 232, 226, 255))
        d.rounded_rectangle((13, 25, 36, 39), radius=3, fill=(201, 128, 76, 255))
        return img

    def _start_tray(self) -> None:
        import pystray

        def style_item(label, v):
            return pystray.MenuItem(label, lambda *_: self.set_pref("taskbar", v), radio=True,
                                    checked=lambda item: self.settings["gorev_cubugu"] == v)

        items = [pystray.MenuItem("Pil Kontrol", lambda *_: self.show_details(), default=True),
                 pystray.MenuItem("Masaüstü widget'ı", lambda *_: self.set_pref("widget_on", not self.settings["widget_acik"]),
                                  checked=lambda item: self.settings["widget_acik"]),
                 pystray.MenuItem("Görev çubuğu", pystray.Menu(
                     style_item("Sadece simge", "simge"), style_item("Simge + %", "yuzde"),
                     style_item("Cam kapsül", "kapsul"), style_item("Kapalı", "kapali")))]
        items += [pystray.Menu.SEPARATOR, pystray.MenuItem("Çık", lambda *_: self.quit())]
        self.tray = pystray.Icon("pilwidget", self._tray_image(), APP_NAME, pystray.Menu(*items))
        self.tray.run_detached()

    def _light(self) -> bool:
        """Widget açık temada mı? (Otomatik ise Windows'un uygulama teması.)"""
        theme = self.prefs()["theme"]
        return masaustu.light_theme() if theme == "auto" else theme == "light"

    def run(self) -> None:
        api = Api(self)
        theme = self.prefs()["theme"]
        light = masaustu.light_theme() if theme == "auto" else theme == "light"
        size = self.prefs()["size"]
        # İlk tahmin (üst çubuk dahil); gerçek boyutu widget_fit düzeltir
        w, h = {"nano": (252, 112), "mini": (226, 200), "detay": (288, 330)}[size]
        x, y = masaustu.fit_on_screen(self.settings.get("x"), self.settings.get("y"), w, h)
        # Pencere içeriğe göre boyutlanır (widget_fit); masaüstüne gömme masaustu.embed'de.
        self.widget = webview.create_window(
            masaustu.TITLE, url=str(resource("ui/widget.html")), js_api=api,
            width=w, height=h, x=x, y=y, min_size=(40, 24), resizable=False, frameless=True, easy_drag=False,
            on_top=False, focus=False, shadow=False, background_color="#f4f2ef" if light else "#161616",
            hidden=not self.settings["widget_acik"],
        )
        self.widget.events.shown += lambda: masaustu.embed(self._light())
        self.widget.events.loaded += lambda: masaustu.embed(self._light())
        self.widget.events.moved += self._on_moved
        self.widget.events.closing += lambda: self._quitting or self._session_ending   # kullanıcı kapatması iptal; çıkış Çık menüsüyle

        # Pil Kontrol penceresi burada oluşturulmaz: ilk show_details'te açılır, kapatılınca yok edilir (bellek).

        def started() -> None:
            masaustu.embed(self._light())
            threading.Thread(target=self._allow_session_end, daemon=True, name="oturum-kapanisi").start()
            if self.demo:
                return
            # Önce asıl iş (izleme, şerit, bekçiler); tepsi başarısız olursa bunlar yine çalışsın.
            self.monitor.start()
            self._sync_strip()
            threading.Thread(target=self._watch_status, daemon=True, name="durum-izle").start()
            threading.Thread(target=self._watch_icons, daemon=True, name="simge-izle").start()
            self._schedule_avoid(1.5)   # açılışta widget simgelerin üstüne düştüyse kaydır
            if sync_autostart():
                self._cache.pop("autostart", None)
            try:
                self._start_tray()
            except Exception:  # noqa: BLE001
                log.exception("Tepsi simgesi başlatılamadı")

        try:
            if self.demo:
                webview.start(started, private_mode=True)
            else:
                webview.start(started, private_mode=False, storage_path=str(DATA_DIR / "webview"), http_port=free_http_port())
        finally:
            try:
                self.flush_settings()
            except Exception:  # noqa: BLE001
                log.exception("Çıkışta ayarlar yazılamadı")

    def _allow_session_end(self) -> None:
        """Windows kapanırken / oturum kapatılırken / Görev Yöneticisi'nden sonlandırılırken pencere kapanabilsin.
        pywebview'in closing olayı widget'ı her durumda tutar (kullanıcı kapatması iptal edilir); bu yüzden kapatma
        nedeni (CloseReason) UserClosing değilse WinForms FormClosing'de iptali geri alırız; aksi hâlde Windows
        'Pil Widget yeniden başlatmayı engelliyor' der."""
        try:
            # pywebview native'i GUI iş parçacığında form kurulunca atar; started() bundan önce koşabilir.
            native = None
            for _ in range(100):
                native = self.widget.native
                if native is not None:
                    break
                time.sleep(0.1)
            if native is None:
                log.warning("Oturum kapanışı işleyicisi bağlanamadı: pencere hazır değil")
                return
            from System.Windows.Forms import CloseReason  # pythonnet; pywebview winforms zaten yüklüyor
            izinli = (CloseReason.WindowsShutDown, CloseReason.TaskManagerClosing,
                      CloseReason.ApplicationExitCall, CloseReason.FormOwnerClosing)
            izinli_ad = ("WindowsShutDown", "TaskManagerClosing", "ApplicationExitCall", "FormOwnerClosing")

            def on_closing(_sender, args) -> None:
                try:
                    reason = args.CloseReason
                    if reason in izinli or str(reason).split(".")[-1] in izinli_ad:
                        # _quitting'i burada açmayız: başka bir program kapanışı iptal ederse uygulama yarım
                        # kalırdı (bekçiler durur, Pil Kontrol açılmaz). Pencere gerçekten kapanınca start() biter.
                        # pywebview'in closing işleyicisi bizden sonra da koşabilir; o da bu bayrağa bakar.
                        self._session_ending = True
                        args.Cancel = False
                        threading.Thread(target=self.flush_settings, daemon=True).start()

                        def geri_al() -> None:   # kapanış iptal edildiyse (başka program engelledi) normale dön
                            self._session_ending = False
                        t = threading.Timer(60, geri_al)
                        t.daemon = True
                        t.start()
                except Exception:  # noqa: BLE001
                    log.exception("Kapatma nedeni okunamadı")

            native.FormClosing += on_closing   # pywebview'in kendi işleyicisinden sonra çalışır, son söz bizim
        except Exception:  # noqa: BLE001
            log.exception("Oturum kapanışı işleyicisi bağlanamadı")


# WebView2 bellek/ağ tasarrufu. pywebview kendi '--disable-features=ElasticOverscroll' değerini verir; aynı anahtar
# iki kez geçince Chromium sonuncuyu alır, o yüzden ElasticOverscroll'u da burada tekrar yazıyoruz.
WEBVIEW2_ARGS = ("--disable-features=ElasticOverscroll,msSmartScreenProtection,msWebOOUI,msPdfOOUI,"
                 "SpareRendererForSitePerProcess "
                 "--renderer-process-limit=1 --disable-background-networking --disable-component-update --no-pings")


def _install_excepthooks() -> None:
    """pythonw.exe / penceresiz exe'de stderr yoktur; yakalanmamış hatalar gunluk.txt'ye yazılsın."""
    prev_sys = sys.excepthook
    prev_thr = threading.excepthook

    def on_sys(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            prev_sys(exc_type, exc_value, exc_tb)
            return
        log.critical("Yakalanmamış hata", exc_info=(exc_type, exc_value, exc_tb))
        if sys.stderr:
            prev_sys(exc_type, exc_value, exc_tb)

    def on_thread(args) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        name = args.thread.name if args.thread else "?"
        log.error("İş parçacığında yakalanmamış hata (%s)", name,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        if sys.stderr:
            prev_thr(args)

    sys.excepthook = on_sys
    threading.excepthook = on_thread


def main() -> None:
    is_demo = any(a.startswith("--demo") for a in sys.argv[1:])
    # Pencereler tek renderer paylaşsın; arka plan ağ trafiği ve güncelleme kontrolü olmasın (uygulama zaten
    # internete çıkmaz). WebView2 başlamadan önce ayarlanmalı.
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
        os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "") + " " + WEBVIEW2_ARGS).strip()
    handlers: list[logging.Handler] = []
    if not is_demo:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(DATA_DIR / "gunluk.txt", maxBytes=1_000_000, backupCount=2, encoding="utf-8"))
    if sys.stderr:
        handlers.append(logging.StreamHandler())
    if handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                            handlers=handlers, force=True)
    _install_excepthooks()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001
        pass

    holder: dict = {}
    lock = None
    if not is_demo:
        from_autostart = AUTOSTART_ARG in sys.argv[1:]
        # Her açılış denemesi iz bıraksın (açılışta sessizce kapanma bir daha görünmez kalmasın).
        log.info("Pil Widget açılıyor (pid=%s, kaynak=%s, cwd=%s)",
                 os.getpid(), "Windows açılışı" if from_autostart else "elle", os.getcwd())
        # Açılışta port geçici olarak meşgul olabilir: Windows ile başlarken daha sabırlı ol.
        go_on, lock = claim_single_instance(lambda: holder["c"].show_details() if "c" in holder else None,
                                            attempts=10 if from_autostart else 1)
        if not go_on:
            return  # zaten açık; Pil Kontrol penceresi öne getirildi
        log.info("Pil Widget başlatılıyor (autostart=%s)", autostart_enabled())
    try:
        controller = Controller()
        holder["c"] = controller
        controller.run()
    finally:
        if lock is not None:
            try:
                lock.close()
            except OSError:
                pass
