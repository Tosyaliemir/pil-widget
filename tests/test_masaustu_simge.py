"""Masaüstü simgelerinden kaçınma: saf hesap (_nearest_free), Win32 gerekmez."""

from pilwidget.masaustu import _nearest_free

AREA = (0, 0, 800, 600)


def test_cakisma_yoksa_ayni_kalir():
    assert _nearest_free((300, 300, 100, 80), [(0, 0, 50, 50)], AREA) == (300, 300)
    assert _nearest_free((300, 300, 100, 80), [], AREA) == (300, 300)


def test_kenar_payi_hesaba_katilir():
    # simge widget'a 4 px uzakta: 8 px pay yüzünden çakışma sayılır
    x, y = _nearest_free((300, 300, 100, 80), [(404, 300, 450, 380)], AREA)
    assert (x, y) != (300, 300)


def test_cakisinca_en_yakin_bos_yere_gider():
    obstacle = (290, 290, 420, 390)
    x, y = _nearest_free((300, 300, 100, 80), [obstacle], AREA)
    assert (x, y) != (300, 300)
    # yeni konum engele değmemeli (8 px pay ile)
    assert x + 100 + 8 <= obstacle[0] or x - 8 >= obstacle[2] or y + 80 + 8 <= obstacle[1] or y - 8 >= obstacle[3]
    # ... ve gereksiz uzağa gitmemeli (en fazla widget boyutu + pay + ızgara adımı kadar)
    assert abs(x - 300) + abs(y - 300) <= 100 + 8 + 16 + 100 + 80


def test_alan_siniri_asilmaz():
    x, y = _nearest_free((700, 520, 100, 80), [(650, 480, 800, 600)], AREA)
    assert 0 <= x <= 700 and 0 <= y <= 520
    assert (x, y) != (700, 520)


def test_bos_yer_yoksa_ayni_kalir():
    assert _nearest_free((300, 300, 100, 80), [(0, 0, 800, 600)], AREA) == (300, 300)


def test_alana_sigmiyorsa_ayni_kalir():
    assert _nearest_free((10, 10, 900, 80), [(0, 0, 100, 100)], AREA) == (10, 10)
