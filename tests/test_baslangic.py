"""Windows ile başlatma: tek örnek kilidi sessizce kapanmasın, başlatma komutu System32'den çalışsın."""

import logging
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from pilwidget import app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def bos_port(monkeypatch):
    """Testler gerçek 47132'ye dokunmasın: boş bir port seç."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    monkeypatch.setattr(app, "INSTANCE_PORT", port)
    return port


def test_kilit_bos_portu_alir_ve_ikinci_ornek_kapanir(bos_port, caplog):
    shown = []
    go_on, lock = app.claim_single_instance(lambda: shown.append(1))
    try:
        assert go_on and lock is not None
        caplog.set_level(logging.INFO)
        go_on2, lock2 = app.claim_single_instance(lambda: None)
        assert not go_on2 and lock2 is None
        assert "zaten açık" in caplog.text
    finally:
        lock.close()


def test_port_dinlemeyen_birinde_ise_sessizce_kapanmaz(bos_port, caplog, monkeypatch):
    """Açılıştaki sorunun olası nedeni: port alınamıyor ama dinleyen Pil Widget yok → eskiden iz bırakmadan çıkıyordu."""
    hog = socket.socket()
    hog.bind(("127.0.0.1", bos_port))   # bağlı ama dinlemiyor: bind de connect de başarısız olur
    monkeypatch.setattr(app.time, "sleep", lambda s: None)
    try:
        caplog.set_level(logging.INFO)
        go_on, lock = app.claim_single_instance(lambda: None, attempts=3)
        assert go_on and lock is None
        assert caplog.text.count("dinleyen örnek yok") == 3
        assert "kilitsiz devam" in caplog.text
    finally:
        hog.close()


def test_port_bosalinca_yeniden_denemede_kilit_alinir(bos_port, monkeypatch):
    hog = socket.socket()
    hog.bind(("127.0.0.1", bos_port))
    monkeypatch.setattr(app.time, "sleep", lambda s: hog.close())   # ilk beklemede port boşalır
    go_on, lock = app.claim_single_instance(lambda: None, attempts=3)
    try:
        assert go_on and lock is not None
    finally:
        if lock:
            lock.close()


def test_main_her_acilisi_ve_kaynagini_gunluge_yazar(tmp_path, monkeypatch):
    import threading
    prev_sys, prev_thr = sys.excepthook, threading.excepthook
    calls = []
    monkeypatch.setattr(app, "DATA_DIR", tmp_path / "PilWidget")
    monkeypatch.setattr(app.sys, "argv", ["run_pilwidget.py", app.AUTOSTART_ARG])
    monkeypatch.setattr(app, "claim_single_instance", lambda cb, attempts=1: calls.append(attempts) or (False, None))
    try:
        app.main()
    finally:
        sys.excepthook, threading.excepthook = prev_sys, prev_thr
        for h in logging.getLogger().handlers[:]:
            h.close()
            logging.getLogger().removeHandler(h)
    log = (tmp_path / "PilWidget" / "gunluk.txt").read_text(encoding="utf-8")
    assert "Pil Widget açılıyor" in log and "Windows açılışı" in log
    assert calls == [10]   # açılışta sabırlı


def test_pil_widget_baslangic_komutu_autostart_bayragi_tasir():
    assert app.launch_command().endswith(f'"{ROOT / "run_pilwidget.py"}" {app.AUTOSTART_ARG}')


@pytest.mark.parametrize("betik", ["run_pilwidget.py"])
def test_betikler_system32_ve_safepath_altinda_paketi_bulur(betik):
    """Oturum açılışı koşulları: çalışma klasörü System32, PYTHONSAFEPATH=1. Yalnızca içe aktarma denenir."""
    kod = (f"import runpy, sys; sys.argv=['x']; "
           f"g = runpy.run_path(r'{ROOT / betik}', run_name='baslangic_testi'); print('ok' if 'main' in g else 'yok')")
    env = {**__import__("os").environ, "PYTHONSAFEPATH": "1"}
    out = subprocess.run([sys.executable, "-c", kod], cwd=r"C:\Windows\System32", env=env,
                         capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "ok", out.stderr
