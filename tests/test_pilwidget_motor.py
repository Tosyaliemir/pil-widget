"""Pil Widget motoru: --json ayrıştırma, Momentum Kontrol durumunu birleştirme, hata durumları (gerçek exe çalıştırılmaz)."""

import json
import subprocess

import pytest

from pilwidget import motor as da

# Gerçek makinede alınan çıktı (2026-11-18)
GERCEK = (
    '[{"key":"razer:00B7","name":"Razer DeathAdder V3 Pro","via":"Razer receiver","kind":"mouse","levelText":"",'
    '"detail":"","percent":30,"charging":false,"asleep":false,"connected":true,"millivolts":0,"graceSec":120,"vid":5426},'
    '{"key":"bt:{19000512-6EAA-59E7-B37A-1E6F5A671BA4}","name":"MOMENTUM 4","via":"Bluetooth","kind":"headset",'
    '"levelText":"","detail":"","percent":70,"charging":false,"asleep":false,"connected":true,"millivolts":0,'
    '"graceSec":0,"vid":0}]'
)


def test_parse_gercek_cikti():
    devs = da.parse_json(GERCEK)
    assert [d["key"] for d in devs] == ["razer:00B7", "bt:{19000512-6EAA-59E7-B37A-1E6F5A671BA4}"]
    assert devs[0]["kind"] == "mouse" and devs[0]["percent"] == 30 and devs[0]["graceSec"] == 120


def test_parse_utf8_ve_eksik_alanlar():
    devs = da.parse_json('[{"key":"k","name":"Klavye ğüşİ","kind":"uzayli","percent":250}, {"name":"anahtarsız"}, 5]')
    assert len(devs) == 1
    d = devs[0]
    assert d["name"] == "Klavye ğüşİ" and d["kind"] == "other" and d["percent"] == -1
    assert d["connected"] is True and d["charging"] is False


@pytest.mark.parametrize("bozuk", ["", "{", '{"key":"x"}', "null", "Razer  [x]  30%"])
def test_parse_bozuk(bozuk):
    with pytest.raises(da.WBError):
        da.parse_json(bozuk)


def test_momentum_tanima():
    devs = da.parse_json(GERCEK)
    assert [d["key"] for d in devs if not da.is_momentum(d)] == ["razer:00B7"]
    assert da.is_momentum({"name": "Kulaklık", "vid": 0x0492})
    assert da.is_momentum({"name": "Sennheiser MOMENTUM 4 Wireless", "vid": 0})
    assert not da.is_momentum({"name": "MOMENTUM True Wireless 3", "vid": 0})


def test_durum_birlestirme():
    devs = da.parse_json(GERCEK)
    now = 10_000
    durum = {"connected": True, "battery": 68, "charging": True, "noise_mode": "anc", "name": "Kulaklığım", "t": now - 60}
    out = da.apply_status(devs, durum, now)
    assert len(out) == 2                                    # tekrar yok
    m4 = out[0]
    assert m4["key"].startswith("bt:") and m4["percent"] == 68 and m4["charging"] and m4["noise_mode"] == "anc"
    assert m4["name"] == "Kulaklığım" and m4["precise"]
    # Eski durum dosyası yok sayılır: Wireless Battery değeri kalır, yine başa alınır
    out = da.apply_status(devs, {**durum, "t": now - 3600}, now)
    assert out[0]["percent"] == 70 and not out[0]["charging"]
    # Wireless Battery kulaklığı görmüyorsa Momentum Kontrol'den eklenir
    out = da.apply_status(devs[:1], durum, now)
    assert [d["key"] for d in out] == ["m4", "razer:00B7"]
    # Bağlı değilse dokunulmaz
    assert da.apply_status(devs[:1], {**durum, "connected": False}, now)[0]["key"] == "razer:00B7"
    assert da.apply_status(devs, None, now)[0]["percent"] == 70


def test_exe_yok(tmp_path):
    with pytest.raises(da.WBError, match="bulunamadı"):
        da.run_wb(None)
    with pytest.raises(da.WBError, match="bulunamadı"):
        da.run_wb(tmp_path / "yok.exe")


def _sahte_exe(tmp_path):
    exe = tmp_path / "WirelessBattery.exe"
    exe.write_bytes(b"")
    return exe


def test_zaman_asimi(tmp_path, monkeypatch):
    def run(*a, **k):
        raise subprocess.TimeoutExpired(a[0], k["timeout"])
    monkeypatch.setattr(da.subprocess, "run", run)
    with pytest.raises(da.WBError, match="cevap vermedi"):
        da.run_wb(_sahte_exe(tmp_path))


def test_hata_kodu_ve_bozuk_cikti(tmp_path, monkeypatch):
    exe = _sahte_exe(tmp_path)
    monkeypatch.setattr(da.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 3, "", ""))
    with pytest.raises(da.WBError, match="hata kodu"):
        da.run_wb(exe)
    monkeypatch.setattr(da.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "[{", ""))
    with pytest.raises(da.WBError, match="Bozuk"):
        da.run_wb(exe)


def test_run_wb_ayarlari(tmp_path, monkeypatch):
    seen = {}

    def run(args, **k):
        seen.update(k, args=args)
        return subprocess.CompletedProcess(args, 0, GERCEK + "\n", "")
    monkeypatch.setattr(da.subprocess, "run", run)
    assert len(da.run_wb(_sahte_exe(tmp_path), demo=True)) == 2
    assert seen["args"][1:] == ["--json", "--demo"]
    assert seen["timeout"] == 15 and seen["encoding"] == "utf-8"
    assert seen["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_monitor_onbellek_ve_grace():
    clock = [1000.0]
    rounds = [json.loads(GERCEK), da.WBError("x"), [], []]

    def runner(exe, demo):
        r = rounds.pop(0)
        if isinstance(r, Exception):
            raise r
        return da.parse_json(json.dumps(r))

    m = da.DeviceMonitor(runner=runner, clock=lambda: clock[0], exe=None)
    m.poll()
    assert [(d["key"], d["stale"]) for d in m.devices()][0] == ("razer:00B7", False)
    clock[0] += 60
    m.poll()                       # hata: son geçerli liste kalır
    assert m.error and len(m.devices()) == 2
    clock[0] += 50
    m.poll()                       # fare cevap vermedi, 110 sn < graceSec 120: soluk
    assert m.error == "" and [d["key"] for d in m.devices()] == ["razer:00B7"]   # M4 graceSec 0: düştü
    assert m.devices()[0]["stale"] is True
    clock[0] += 60
    m.poll()                       # 170 sn > 120: düşer
    assert m.devices() == []


def test_battery_log(tmp_path):
    def read(p, default):
        return json.loads(p.read_text("utf-8")) if p.exists() else default

    def write(p, data):
        p.write_text(json.dumps(data), "utf-8")

    path = tmp_path / "pil.json"
    log = da.BatteryLog(path, read, write)
    log.add("razer:00B7", 30, False)
    log.add("razer:00B7", 30, False)          # 5 dakikadan kısa sürede aynı değer: yazılmaz
    log.add("bt:m4", 70, True)
    log.add("x", -1, False)                    # bilinmeyen seviye: yazılmaz
    log.flush()                                # dakikada bir yazım: bekleyeni hemen yaz
    data = json.loads(path.read_text("utf-8"))
    assert list(data) == ["razer:00B7", "bt:m4"] and len(data["razer:00B7"]) == 1
    assert da.BatteryLog(path, read, write).recent("bt:m4")[0][1:] == [70, 1]


def test_bool_ve_sonsuz_zaman_reddedilir():
    devs = da.parse_json('[{"key":"a","percent":true,"millivolts":true,"graceSec":true,"vid":false}]')
    assert devs[0]["percent"] == -1 and devs[0]["millivolts"] == 0 and devs[0]["graceSec"] == 0 and devs[0]["vid"] == 0
    now = 10_000.0
    base = da.parse_json(GERCEK)
    assert not any(d.get("precise") for d in da.apply_status(base, {"connected": True, "battery": True, "t": now}, now))
    assert not any(d.get("precise") for d in da.apply_status(base, {"connected": True, "battery": 50, "t": float("inf")}, now))
    assert not any(d.get("precise") for d in da.apply_status(base, {"connected": True, "battery": 50, "t": now + 3600}, now))


def test_monitor_saat_geri_sicrasa_da_stale_dogru():
    clock = [1000.0]
    rounds = [json.loads(GERCEK), []]
    m = da.DeviceMonitor(runner=lambda exe, demo: da.parse_json(json.dumps(rounds.pop(0))), clock=lambda: clock[0], exe=None)
    m.poll()
    clock[0] -= 30   # NTP saat geri düzeltmesi
    m.poll()
    devs = m.devices()
    assert len(devs) == 1 and devs[0]["key"] == "razer:00B7" and devs[0]["stale"] is True


def test_monitor_stop_bekleyen_refreshi_aninda_uyandirir():
    import threading
    import time
    started = threading.Event()
    gate = threading.Event()

    def runner(exe, demo):
        started.set()
        gate.wait(5)
        return []

    m = da.DeviceMonitor(runner=runner, interval=3600, exe=None)
    m.start()
    assert started.wait(2)
    t0 = time.monotonic()
    threading.Timer(0.1, m.stop).start()
    m.refresh(wait=15)
    elapsed = time.monotonic() - t0
    gate.set()
    assert elapsed < 2.0
