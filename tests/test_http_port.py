"""Arayüz sunucusu sabit 42001'i kullanmasın: Momentum Kontrol ve Pil Widget aynı anda açıkken
ikincinin sayfaları birincinin sunucusundan istenip 404 oluyordu."""

import inspect
import socket

from pilwidget import app


def test_bos_port_42001_degil_ve_baglanabilir():
    port = app.free_http_port()
    assert port != 42001 and 1024 < port < 65536
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))


def test_kalici_modda_kendi_portunu_verir():
    src = inspect.getsource(app.Controller.run)
    assert "private_mode=False" in src and "http_port=free_http_port()" in src
