"""Pil Widget dayanıklılığı: bozuk girdi, iş parçacıkları, geçmiş/ayar yazımı, şerit sınıfları (pencere açılmaz)."""

import json
import time

import pytest

from pilwidget import app
from pilwidget import gorev_cubugu as gc
from pilwidget import motor as da

GERCEK = (
    '[{"key":"razer:00B7","name":"Razer DeathAdder V3 Pro","via":"Razer receiver","kind":"mouse","percent":30,'
    '"connected":true,"graceSec":120,"vid":5426},'
    '{"key":"bt:m4","name":"MOMENTUM 4","via":"Bluetooth","kind":"headset","percent":70,"connected":true}]'
)


# -- motor -----------------------------------------------------------------------------
def test_parse_bozuk_degerler_girdiyi_dusurmez():
    devs = da.parse_json('[{"key":"a","percent":"yuksek","millivolts":[1],"graceSec":"x","vid":null},'
                         '{"key":{"x":1},"name":null,"percent":1e999}]')
    assert len(devs) == 2
    assert devs[0]["percent"] == -1 and devs[0]["millivolts"] == 0 and devs[0]["graceSec"] == 0 and devs[0]["vid"] == 0
    assert devs[1]["percent"] == -1


@pytest.mark.parametrize("status", [
    None, [], "x", {"connected": True, "battery": "çok", "t": time.time()},
    {"connected": True, "battery": 70, "t": "dün"}, {"connected": True, "battery": 250, "t": time.time()},
    {"connected": True, "battery": [1], "t": time.time()}, {"connected": True, "battery": float("nan"), "t": time.time()},
    {"connected": False, "battery": 70, "t": time.time()},
])
def test_apply_status_bozuk_durum_yok_sayilir(status):
    out = da.apply_status(da.parse_json(GERCEK), status, time.time())
    assert [d["percent"] for d in out if "MOMENTUM" in d["name"]] == [70] and not any(d.get("precise") for d in out)


def test_apply_status_eski_durum_yok_sayilir():
    now = 10_000.0
    st = {"connected": True, "battery": 40, "charging": True, "t": now - da.STATUS_MAX_AGE - 1}
    assert not any(d.get("precise") for d in da.apply_status(da.parse_json(GERCEK), st, now))
    st["t"] = now - 60
    assert any(d.get("precise") and d["percent"] == 40 for d in da.apply_status(da.parse_json(GERCEK), st, now))


def test_monitor_dongusu_hatada_olmez():
    calls = []

    def runner(exe, demo):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("beklenmeyen")      # WBError değil
        return []

    m = da.DeviceMonitor(runner=runner, interval=0.05, exe=None)
    m.start()
    deadline = time.time() + 3
    while len(calls) < 3 and time.time() < deadline:
        time.sleep(0.02)
    m.stop()
    assert len(calls) >= 3   # ilk tur patladı, iş parçacığı yaşamaya devam etti


def test_monitor_refresh_bekler():
    n = []

    def runner(exe, demo):
        n.append(1)
        time.sleep(0.05)
        return []

    m = da.DeviceMonitor(runner=runner, interval=3600, exe=None)
    m.start()
    deadline = time.time() + 3
    while not n and time.time() < deadline:
        time.sleep(0.01)
    before = len(n)
    m.refresh(wait=5)
    assert len(n) > before and m.updated > 0   # dönüşte yeni tur bitmiş
    m.stop()


def test_battery_log_dakikada_bir_yazar_ve_kompakt(tmp_path):
    t = [1_000_000.0]
    writes = []

    def write(p, data):
        writes.append(json.dumps(data, separators=(",", ":")))
        p.write_text(writes[-1], "utf-8")

    path = tmp_path / "pil.json"
    log = da.BatteryLog(path, lambda p, d: d, write, clock=lambda: t[0])
    log.add("a", 50, False)
    assert len(writes) == 1                    # ilk yazım hemen
    t[0] += 10
    log.add("a", 49, False)
    t[0] += 10
    log.add("b", 80, True)
    assert len(writes) == 1                    # 1 dakika dolmadı: yalnızca bellekte
    t[0] += da.BatteryLog.WRITE_GAP
    log.add("a", 48, False)
    assert len(writes) == 2 and len(json.loads(writes[-1])["a"]) == 3
    t[0] += 5
    log.add("a", 47, False)
    log.flush()                                # çıkışta bekleyen yazılır
    assert len(writes) == 3 and len(json.loads(writes[-1])["a"]) == 4
    log.flush()
    assert len(writes) == 3                    # bekleyen yok: yazılmaz
    assert "\n" not in writes[-1] and ": " not in writes[-1]
    # mevcut biçim aynı: {anahtar: [[zaman, %, şarj], ...]}
    again = da.BatteryLog(path, lambda p, d: json.loads(p.read_text("utf-8")), write, clock=lambda: t[0])
    assert again.recent("b", 10)[0][1:] == [80, 1]


def test_battery_log_bozuk_satirlar_atilir(tmp_path):
    raw = {"a": [[1, 2, 0], "x", [1], [None, 5, 1]], "b": "liste degil", "c": [[3, 4, 1]]}
    log = da.BatteryLog(tmp_path / "p.json", lambda p, d: raw, lambda p, d: None)
    assert log.samples == {"a": [[1, 2, 0]], "c": [[3, 4, 1]]}


# -- ayarlar ---------------------------------------------------------------------------
def test_ayar_dogrulama_anahtar_anahtar(tmp_path, monkeypatch):
    f = tmp_path / "ayarlar.json"
    f.write_text('{"boyut": "kompakt", "tema": 5, "x": "10", "y": 20, "kilitli": "evet", "dusuk_pil_bildirimi": false,'
                 ' "widget_acik": 7, "gorev_cubugu": "yuzde", "gorev_konum": null}', encoding="utf-8")
    monkeypatch.setattr(app, "SETTINGS_FILE", f)
    s = app.Controller().settings
    assert s["boyut"] == "nano" and s["tema"] == "auto"                       # eski ad çevrildi / geçersiz -> varsayılan
    assert s["x"] is None and s["y"] is None                                   # x bozuk: yarım konum atılır
    assert s["kilitli"] is False and s["dusuk_pil_bildirimi"] is False and s["widget_acik"] is True
    assert s["gorev_cubugu"] == "yuzde" and s["gorev_konum"] == "sol"


@pytest.mark.parametrize("raw", [[], "x", None, 5])
def test_ayar_dosyasi_dict_degilse_varsayilan(raw):
    assert app.validate_settings(raw, app.Controller.DEFAULTS) == app.Controller.DEFAULTS


def test_ayar_gecerli_konum_korunur():
    s = app.validate_settings({"x": -30, "y": 400}, app.Controller.DEFAULTS)
    assert (s["x"], s["y"]) == (-30, 400)


def test_write_json_kompakt_ve_gecici_dosya_kalmaz(tmp_path):
    f = tmp_path / "a.json"
    app.write_json(f, {"a": [1, 2]}, compact=True)
    assert f.read_text("utf-8") == '{"a":[1,2]}' and list(tmp_path.iterdir()) == [f]
    app.write_json(f, {"a": 1})
    assert "\n" in f.read_text("utf-8")


def test_ayar_kaydi_flush_ve_yazim_hatasi(tmp_path, monkeypatch):
    f = tmp_path / "ayarlar.json"
    monkeypatch.setattr(app, "SETTINGS_FILE", f)
    monkeypatch.setattr(app, "HISTORY_FILE", tmp_path / "pil.json")
    c = app.Controller()
    c.settings["kilitli"] = True
    c._save(60)                    # uzun gecikmeli zamanlayıcı
    assert not f.exists()
    c.flush_settings()             # çıkışta hemen yazılır
    assert '"kilitli": true' in f.read_text("utf-8")
    c.flush_settings()             # bekleyen yok: sorunsuz

    def boom(*a, **k):
        raise PermissionError("kilitli")
    monkeypatch.setattr(app, "write_json", boom)
    c._save(60)
    c._write_settings()            # OSError yutulur, bekleyen işaretli kalır
    assert c._save_pending
    c._save_timer.cancel()


def test_prefs_pahali_sorgulari_onbellekler(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "SETTINGS_FILE", tmp_path / "ayarlar.json")
    n = []
    monkeypatch.setattr(app, "autostart_enabled", lambda: n.append(1) or True)
    c = app.Controller()
    for _ in range(5):
        c.prefs()
    assert len(n) == 1


def test_baslangic_komutu_kaynaktan_mutlak_yol():
    cmd = app.launch_command()
    assert "run_pilwidget.py" in cmd and "-m pilwidget" not in cmd and cmd.count('"') == 4


# -- şerit -----------------------------------------------------------------------------
def test_kaynak_yolu_donmus_paket(monkeypatch, tmp_path):
    monkeypatch.setattr(gc.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert gc.resource("ui/fonts/x.woff2") == tmp_path / "ui" / "fonts" / "x.woff2"
    monkeypatch.delattr(gc.sys, "_MEIPASS")
    assert gc.resource("ui").parent.name == "pilwidget"


def test_serit_pencere_siniflari_bir_kez_kaydolur():
    # Sınıf kaydı pencere açmaz (görev çubuğuna dokunulmaz); art arda çağrı güvenli ve geri çağrı sabit kalmalı.
    assert gc._ensure_classes() and gc._ensure_classes()
    cb = gc._wndproc_cb
    assert cb is not None
    assert gc._ensure_classes()
    assert gc._wndproc_cb is cb
    # Sınıf adı gerçekten kayıtlı: aynı adla yeniden kayıt 'sınıf zaten var' (1410) verir, yani hiç silinmedi.
    import ctypes
    u = gc._get_api()[0]
    wc = gc._WNDCLASSEXW(cbSize=ctypes.sizeof(gc._WNDCLASSEXW), lpfnWndProc=cb, hInstance=gc._hinstance(),
                         lpszClassName=gc.GorevCubugu.CLS_STRIP)
    assert not u.RegisterClassExW(ctypes.byref(wc)) and ctypes.get_last_error() == 1410


def test_tema_onbellegi():
    calls = []
    strip = gc.GorevCubugu(light_fn=lambda: calls.append(1) or True)
    assert strip._is_light(None) and strip._is_light(None) and len(calls) == 1
    assert strip._is_light(False) is False and len(calls) == 1   # geçersiz kılma okumaz
    strip._light_cache = None                                      # WM_SETTINGCHANGE
    assert strip._is_light(None) and len(calls) == 2


# -- ev konumu, kaçınma, Pil Kontrol iletisi ----------------------------------------------
class _Win:
    def __init__(self, x=100, y=100, w=200, h=100):
        self.x, self.y, self.width, self.height = x, y, w, h
        self.moves = []
        self.resizes = []
        self.js = []
        self.shown = 0
        self.hidden = 0

    def move(self, x, y):
        self.x, self.y = x, y
        self.moves.append((x, y))

    def resize(self, w, h):
        self.width, self.height = w, h
        self.resizes.append((w, h))

    def show(self):
        self.shown += 1

    def hide(self):
        self.hidden += 1

    def evaluate_js(self, js):
        self.js.append(js)


@pytest.fixture
def ctl2(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "SETTINGS_FILE", tmp_path / "ayarlar.json")
    monkeypatch.setattr(app, "HISTORY_FILE", tmp_path / "pil.json")
    monkeypatch.setattr(app.Controller, "_schedule_avoid", lambda self, delay: setattr(self, "_icons_dirty", True))
    c = app.Controller()
    c.widget = _Win()
    c.settings.update(x=100, y=100)
    return c


def test_kullanici_surukleyince_ev_konumu_degisir(ctl2):
    ctl2._on_moved(300, 250)
    assert (ctl2.settings["x"], ctl2.settings["y"]) == (300, 250)


def test_kendi_tasimamiz_ev_konumunu_ezmez(ctl2, monkeypatch):
    monkeypatch.setattr(app.masaustu, "fit_on_screen", lambda x, y, w, h: (x, y))
    monkeypatch.setattr(app.masaustu, "avoid_icons", lambda x, y, w, h: (x + 400, y))   # ev yeri dolu
    ctl2._avoid_icons()
    assert ctl2.widget.moves == [(500, 100)]
    ctl2._on_moved(500, 100)                                       # pywebview'in 'moved' olayı
    assert (ctl2.settings["x"], ctl2.settings["y"]) == (100, 100)  # ev yeri kaydedilmedi
    monkeypatch.setattr(app.masaustu, "avoid_icons", lambda x, y, w, h: (x, y))        # simge kalktı
    ctl2._avoid_icons()
    assert ctl2.widget.moves[-1] == (100, 100)                     # widget eve döndü


def test_demo_ayar_ve_kacinma_yapmaz(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "SETTINGS_FILE", tmp_path / "ayarlar.json")
    monkeypatch.setattr(app.sys, "argv", ["x", "--demo"])
    c = app.Controller()
    c._save(0)
    c._schedule_avoid(0)
    assert c._save_timer is None and c._avoid_timer is None


def test_pil_kontrol_iletisi_ayri_is_parcacigi_ve_son_deger(ctl2):
    import threading
    gate = threading.Event()
    seen = []
    det = _Win()

    def slow(js):
        gate.wait(2)
        seen.append(js)
    det.evaluate_js = slow
    ctl2.details = det
    ctl2._send_details("onDevices", "a")          # sayfa hazır değil: atlanır
    assert not ctl2._pump
    ctl2._details_ready.add(id(det))
    t0 = time.time()
    for i in range(5):
        ctl2._send_details("onDevices", f"v{i}")  # takılsa da çağıran beklemez
    assert time.time() - t0 < 1
    gate.set()
    deadline = time.time() + 3
    while len(seen) < 2 and time.time() < deadline:
        time.sleep(0.02)
    ctl2._quitting = True
    assert seen[-1] == "v4" and len(seen) <= 2     # eski değerler düşürüldü


def test_eski_pencerenin_closed_olayi_yenisini_bozmaz(ctl2):
    old, new = _Win(), _Win()
    ctl2.details = new
    ctl2._on_details_closing(old)
    ctl2._on_details_closing(new)
    ctl2._on_details_closed(old)
    assert ctl2._details_closing and ctl2.details is new
    ctl2._on_details_closed(new)
    assert not ctl2._details_closing and ctl2.details is None


def test_otomatik_baslatma_eski_komut_yeniden_yazilir(monkeypatch):
    vals = {"v": '"pythonw.exe" -m pilwidget'}
    monkeypatch.setattr(app, "autostart_value", lambda: vals["v"])
    monkeypatch.setattr(app, "autostart_approved", lambda: True)
    monkeypatch.setattr(app, "set_autostart", lambda on: vals.update(v=app.launch_command()))
    assert app.sync_autostart() and vals["v"] == app.launch_command()
    assert not app.sync_autostart()                 # artık güncel
    vals["v"] = None
    monkeypatch.setattr(app, "autostart_value", lambda: None)
    assert not app.sync_autostart()                 # kapalıysa açılmaz


def test_otomatik_baslatma_startup_approved_ve_bos_deger(monkeypatch):
    """StartupApproved\\Run kaydı 0x03 (devre dışı) ise autostart_enabled False dönmeli;
    set_autostart(True) hem Run'ı hem StartupApproved'ı etkinleştirmeli; boş Run değeri kapalı sayılmalı."""
    reg = {
        app.RUN_KEY: {app.RUN_VALUE: ('"pythonw.exe" "run_pilwidget.py"', 1)},
        app.STARTUP_APPROVED_KEY: {app.RUN_VALUE: (b"\x03" + b"\x00" * 11, 3)},
    }

    class _Key:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeWinreg:
        HKEY_CURRENT_USER = object()
        KEY_SET_VALUE = 2
        KEY_QUERY_VALUE = 1
        REG_SZ = 1
        REG_BINARY = 3

        def OpenKey(self, _hive, path, *_a):
            if path not in reg:
                raise FileNotFoundError(path)
            return _Key(path)

        def CreateKeyEx(self, _hive, path, *_a):
            reg.setdefault(path, {})
            return _Key(path)

        def QueryValueEx(self, key, name):
            if name not in reg[key.path]:
                raise FileNotFoundError(name)
            return reg[key.path][name]

        def SetValueEx(self, key, name, _res, typ, val):
            reg[key.path][name] = (val, typ)

        def DeleteValue(self, key, name):
            if name not in reg[key.path]:
                raise FileNotFoundError(name)
            del reg[key.path][name]

    monkeypatch.setattr(app, "winreg", _FakeWinreg())
    assert app.autostart_value() is not None
    assert app.autostart_approved() is False
    assert app.autostart_enabled() is False              # Görev Yöneticisi kapattıysa kapalı görünür
    assert app.sync_autostart() is False                 # kullanıcı kapattıysa zorla açılmaz

    app.set_autostart(True)
    assert app.autostart_approved() is True
    assert app.autostart_enabled() is True
    assert reg[app.STARTUP_APPROVED_KEY][app.RUN_VALUE][0] == app.STARTUP_APPROVED_ENABLED

    app.set_autostart(False)
    assert app.autostart_enabled() is False
    assert app.RUN_VALUE not in reg[app.RUN_KEY]
    assert app.RUN_VALUE not in reg[app.STARTUP_APPROVED_KEY]

    # Boşluk / boş dize geçerli başlatma sayılmaz
    reg[app.RUN_KEY][app.RUN_VALUE] = ("   ", 1)
    assert app.autostart_value() is None
    assert app.autostart_enabled() is False


def test_demo_modunda_autostart_kayit_defterine_yazmaz(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "SETTINGS_FILE", tmp_path / "ayarlar.json")
    monkeypatch.setattr(app.sys, "argv", ["x", "--demo"])
    called = []
    monkeypatch.setattr(app, "set_autostart", lambda on: called.append(on))
    monkeypatch.setattr(app, "autostart_enabled", lambda: False)
    c = app.Controller()
    r = c.set_pref("autostart", True)
    assert r["ok"] and not called


def test_nearest_free_aday_siniri_buyuk_ekranda():
    from pilwidget.masaustu import _nearest_free
    obstacles = [(0, 0, 3000, 1900)]               # her yer dolu: tüm adaylar denenir ama sınırlı
    t0 = time.time()
    assert _nearest_free((100, 100, 200, 100), obstacles, (0, 0, 3840, 2160)) is not None
    assert time.time() - t0 < 2


def test_simge_sayisi_int_ya_da_none():
    from pilwidget import masaustu
    n = masaustu.desktop_icon_count()
    assert n is None or isinstance(n, int)


def test_excepthook_hatalari_gunluge_yazar(monkeypatch, caplog):
    import sys
    import threading
    prev_sys, prev_thr = sys.excepthook, threading.excepthook
    try:
        monkeypatch.setattr(sys, "stderr", None)
        app._install_excepthooks()
        with caplog.at_level("ERROR", logger=app.log.name):
            try:
                raise RuntimeError("sessiz-hata")
            except RuntimeError as exc:
                sys.excepthook(type(exc), exc, exc.__traceback__)
            t = threading.Thread(target=lambda: (_ for _ in ()).throw(ValueError("ip-hatasi")), name="test-ip")
            t.start()
            t.join(2)
        assert any("sessiz-hata" in r.getMessage() or (r.exc_info and "sessiz-hata" in str(r.exc_info[1]))
                   for r in caplog.records)
        assert any("test-ip" in r.getMessage() for r in caplog.records)
    finally:
        sys.excepthook, threading.excepthook = prev_sys, prev_thr


def test_main_demo_gunluk_ve_tek_ornek_dokunmaz(tmp_path, monkeypatch):
    import sys
    import threading
    prev_sys, prev_thr = sys.excepthook, threading.excepthook
    claimed = []
    ran = []
    monkeypatch.setattr(app, "DATA_DIR", tmp_path / "PilWidget")
    monkeypatch.setattr(app, "SETTINGS_FILE", tmp_path / "PilWidget" / "ayarlar.json")
    monkeypatch.setattr(app, "HISTORY_FILE", tmp_path / "PilWidget" / "pil.json")
    monkeypatch.setattr(app.sys, "argv", ["run_pilwidget.py", "--demo"])
    monkeypatch.setattr(app, "claim_single_instance", lambda cb: claimed.append(1) or None)
    monkeypatch.setattr(app.Controller, "run", lambda self: ran.append(self.demo))
    try:
        app.main()
    finally:
        sys.excepthook, threading.excepthook = prev_sys, prev_thr
    assert ran == ["demo"] and not claimed and not (tmp_path / "PilWidget" / "gunluk.txt").exists()


def test_quit_kacinma_zamanlayicisini_iptal_eder(ctl2):
    import threading
    fired = []
    ctl2._avoid_timer = threading.Timer(60, lambda: fired.append(1))
    ctl2._avoid_timer.start()
    ctl2.quit()
    assert ctl2._avoid_timer is None and not fired


def test_gizli_widget_boyutlandirmada_gorunur_olmaz_ve_acilinca_uygulanir(ctl2, monkeypatch):
    lowered = []
    monkeypatch.setattr(app.masaustu, "lower_widget", lambda: lowered.append(1) or True)
    monkeypatch.setattr(app.masaustu, "embed", lambda light=False: True)
    monkeypatch.setattr(app.masaustu, "fit_on_screen", lambda x, y, w, h: (x, y))
    monkeypatch.setattr(app.Controller, "_show_widget_quietly", staticmethod(lambda w: w.show()))
    ctl2.settings["widget_acik"] = False
    ctl2.widget_fit(260, 180)
    assert not ctl2.widget.resizes and not ctl2.widget.moves and ctl2._pending_fit == (260, 180)
    ctl2.settings["widget_acik"] = True
    ctl2._apply_widget()
    assert ctl2.widget.resizes == [(260, 180)] and ctl2._pending_fit is None
    ctl2.widget_fit(288, 300)
    assert ctl2.widget.resizes[-1] == (288, 300) and len(lowered) == 1


def test_kilitli_ve_ardisik_kendi_tasima_ev_konumunu_ezmez(ctl2):
    ctl2._move_own(500, 100)
    ctl2._on_moved(500, 100)
    ctl2._on_moved(500, 100)   # ikinci ardışık moved olayı da yok sayılmalı
    assert (ctl2.settings["x"], ctl2.settings["y"]) == (100, 100)
    ctl2.settings["kilitli"] = True
    ctl2._on_moved(777, 333)
    assert (ctl2.settings["x"], ctl2.settings["y"]) == (100, 100)


def test_check_low_uyuyan_ve_stale_cihazi_bildirmez(ctl2):
    sent = []

    class _Tray:
        def notify(self, msg, title):
            sent.append((title, msg))

    ctl2.tray = _Tray()
    dev = {"key": "k1", "name": "Fare", "percent": 10, "connected": True, "charging": False, "stale": False, "asleep": True}
    ctl2._check_low([dev])
    assert not sent   # uykudayken bildirim yok
    dev["asleep"] = False
    ctl2._check_low([dev])
    assert len(sent) == 1
    # uyku + şarj bayrağı eski kalsa bile _low_notified sıfırlanmamalı
    ctl2._check_low([{**dev, "asleep": True, "charging": True}])
    ctl2._check_low([dev])
    assert len(sent) == 1


def test_style_window_64bit_hwnd_ve_acik_koyu_tema(monkeypatch):
    import ctypes
    calls = []

    class _FakeFn:
        argtypes = None

        def __call__(self, hwnd, attr, ptr, size):
            val = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_int)).contents.value
            calls.append((hwnd.value if hasattr(hwnd, "value") else hwnd, attr, val, size))
            return 0

    class _FakeDwm:
        def __init__(self):
            self.DwmSetWindowAttribute = _FakeFn()

    dwm = _FakeDwm()
    monkeypatch.setattr(app.masaustu, "find_own_window", lambda title: 0x1_0000_0042)
    monkeypatch.setattr(app.ctypes.windll, "dwmapi", dwm, raising=False)
    app.style_window("Pil Kontrol", light=False)
    app.style_window("Pil Kontrol", light=True)
    assert dwm.DwmSetWindowAttribute.argtypes is not None
    dark_attrs = {a: v for _, a, v, _ in calls[:4]}
    light_attrs = {a: v for _, a, v, _ in calls[4:]}
    assert dark_attrs[20] == 1 and light_attrs[20] == 0 and dark_attrs[35] != light_attrs[35]


def test_ui_js_sozdizimi_ve_hata_geri_alma():
    import shutil
    import subprocess
    from pathlib import Path

    ui_dir = Path(__file__).resolve().parent.parent / "pilwidget" / "ui"
    cihazlar_html = (ui_dir / "cihazlar.html").read_text(encoding="utf-8")
    widget_js = (ui_dir / "widget.js").read_text(encoding="utf-8")
    cihazlar_js = (ui_dir / "cihazlar.js").read_text(encoding="utf-8")
    assert 'id="pref-err"' in cihazlar_html
    assert "!d.asleep && !d.stale" in widget_js
    assert "document.fonts?.ready" in widget_js
    assert "m.isSleeping ? Cihaz.stateText(d)" in cihazlar_js
    assert "showPrefError" in cihazlar_js

    node = shutil.which("node")
    if node:
        for name in ("ortak.js", "widget.js", "cihazlar.js", "demo.js"):
            res = subprocess.run([node, "--check", str(ui_dir / name)], capture_output=True, text=True)
            assert res.returncode == 0, f"{name}: {res.stderr}"
