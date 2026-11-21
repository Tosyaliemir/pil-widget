"""Pil Widget görev çubuğu şeridi: çizim (Win32'siz) ve Controller ayar doğrulaması (pencere açılmaz)."""

import pytest
from PIL import Image

from pilwidget import app
from pilwidget import gorev_cubugu as gc


def dev(name, kind, pct, **kw):
    return {**dict(name=name, kind=kind, percent=pct, connected=True, charging=False, asleep=False, stale=False,
                   detail="", levelText=""), **kw}


ORNEK = [
    dev("MOMENTUM 4", "headset", 72),
    dev("G502", "mouse", 41, charging=True),
    dev("Keychron", "keyboard", 58, asleep=True),
    dev("Xbox", "gamepad", 12),
    dev("Buds", "headset", 66, detail="L 70%, R 66%"),
    dev("Pixel", "phone", 83),
    dev("Bilinmeyen", "other", -1, levelText="Yüksek"),
    dev("Kapalı", "mouse", 50, connected=False),
]


@pytest.mark.parametrize("style", gc.STYLES)
@pytest.mark.parametrize("light", [False, True])
@pytest.mark.parametrize("scale", [1.0, 1.25, 2.0])
def test_ciz_her_gorunum(style, light, scale):
    im = gc.ciz(ORNEK, style, light, scale)
    assert isinstance(im, Image.Image) and im.mode == "RGBA"
    assert im.width > 20 and im.height == round(gc.CANVAS_H * scale)
    assert im.getchannel("A").getbbox() is not None   # bir şey çizildi


@pytest.mark.parametrize("style", gc.STYLES)
def test_ciz_bos_liste_none(style):
    assert gc.ciz([], style, False, 1.25) is None
    assert gc.ciz([dev("Kapalı", "mouse", 50, connected=False)], style, False, 1.25) is None


def test_ciz_kapali_cihaz_gosterilmez():
    one = gc.ciz(ORNEK[:1], "yuzde", False, 1.0)
    with_off = gc.ciz(ORNEK[:1] + [dev("Kapalı", "mouse", 50, connected=False)], "yuzde", False, 1.0)
    assert one.size == with_off.size


def test_ciz_cihaz_arttikca_genisler_ve_hover_ayni_boyut():
    a = gc.ciz(ORNEK[:2], "kapsul", False, 1.25)
    b = gc.ciz(ORNEK[:4], "kapsul", False, 1.25)
    assert b.width > a.width
    assert gc.ciz(ORNEK, "simge", True, 1.25, hover=True).size == gc.ciz(ORNEK, "simge", True, 1.25).size


def test_ciz_bilinmeyen_stil_yuzdeye_duser():
    assert gc.ciz(ORNEK, "garip", False, 1.0).size == gc.ciz(ORNEK, "yuzde", False, 1.0).size


def test_ciz_acik_koyu_on_plan_rengi_farkli():
    def ink(light):
        im = gc.ciz([dev("Fare", "mouse", 80)], "simge", light, 1.0)   # simge: tek renkli, ön plan rengi
        pix = im.load()
        px = [pix[x, y] for x in range(im.width) for y in range(im.height) if pix[x, y][3] > 240]
        return max(px, key=lambda p: p[3])[:3]
    assert sum(ink(False)) > sum(ink(True))


def test_durum_renkleri():
    assert gc.durum(dev("a", "mouse", 80))["accent"] == gc.COLORS["ok"]
    assert gc.durum(dev("a", "mouse", 30))["mid"] and gc.durum(dev("a", "mouse", 30))["accent"] == gc.COLORS["mid"]
    assert gc.durum(dev("a", "mouse", 15))["low"]
    assert gc.durum(dev("a", "mouse", 5, charging=True))["accent"] == gc.COLORS["chg"]
    assert gc.durum(dev("a", "mouse", 5, asleep=True))["accent"] == gc.COLORS["slp"]
    assert gc.durum(dev("a", "mouse", -1))["accent"] == gc.COLORS["slp"]


def test_glyph_ve_metinler():
    assert gc.glyph(dev("MOMENTUM 4", "headset", 70)) == "overear"
    assert gc.glyph(dev("Galaxy Buds3", "headset", 70)) == "inear"
    assert gc.glyph(dev("X", "headset", 70, detail="L 80%, R 75%")) == "inear"
    assert gc.glyph(dev("X", "uzayli", 70)) == "other"
    assert gc.yuzde_metni(dev("a", "mouse", 7)) == "%7"
    assert gc.yuzde_metni(dev("a", "mouse", -1, levelText="Düşük")) == "Düşük"
    assert gc.ipucu_metni(ORNEK).splitlines()[0] == "MOMENTUM 4: %72"
    assert "Kapalı" not in gc.ipucu_metni(ORNEK)


def test_premultiplied_bgra():
    im = Image.new("RGBA", (1, 1), (200, 100, 50, 128))
    b, g, r, a = gc._premultiplied_bgra(im)
    assert a == 128 and abs(r - 100) <= 1 and abs(g - 50) <= 1 and abs(b - 25) <= 1


# -- Controller ayarları (pencere/şerit açılmadan) ---------------------------------
@pytest.fixture
def ctl(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "SETTINGS_FILE", tmp_path / "ayarlar.json")
    monkeypatch.setattr(app.Controller, "_save", lambda self, delay=0.8: None)
    monkeypatch.setattr(app.Controller, "_sync_strip", lambda self, devices=None: None)
    monkeypatch.setattr(app.Controller, "_apply_widget", lambda self: None)
    monkeypatch.setattr(app.masaustu, "embed", lambda light=False: True)
    return app.Controller()


def test_varsayilan_ayarlar(ctl):
    p = ctl.prefs()
    assert p["widget_on"] is True and p["taskbar"] == "kapali" and p["taskbar_pos"] == "sol"


@pytest.mark.parametrize("key,value", [("taskbar", "simge"), ("taskbar", "yuzde"), ("taskbar", "kapsul"),
                                       ("taskbar", "kapali"), ("taskbar_pos", "sag"), ("taskbar_pos", "sol"),
                                       ("widget_on", False), ("widget_on", True)])
def test_set_pref_gecerli(ctl, key, value):
    r = ctl.set_pref(key, value)
    assert r["ok"] and r["prefs"][key] == value


@pytest.mark.parametrize("key,value", [("taskbar", "garip"), ("taskbar", None), ("taskbar_pos", "orta"),
                                       ("size", "dev"), ("theme", "mor"), ("yok_boyle_ayar", 1)])
def test_set_pref_gecersiz(ctl, key, value):
    before = ctl.prefs()
    r = ctl.set_pref(key, value)
    assert not r["ok"] and r["error"]
    assert ctl.prefs() == before


def test_bozuk_kayitli_ayar_duzeltilir(tmp_path, monkeypatch):
    f = tmp_path / "ayarlar.json"
    f.write_text('{"gorev_cubugu": "x", "gorev_konum": 3, "widget_acik": 0}', encoding="utf-8")
    monkeypatch.setattr(app, "SETTINGS_FILE", f)
    p = app.Controller().prefs()
    assert p["taskbar"] == "kapali" and p["taskbar_pos"] == "sol" and p["widget_on"] is False


def test_bar_tray_yoksa_veya_rect_basarisizsa_none():
    strip = gc.GorevCubugu()

    class _FakeUser32:
        def __init__(self, tray_wnd, rect_ok):
            self.tray_wnd = tray_wnd
            self.rect_ok = rect_ok

        def FindWindowW(self, *_a):
            return 100

        def FindWindowExW(self, *_a):
            return self.tray_wnd

        def GetWindowRect(self, *_a):
            return self.rect_ok

    # TrayNotifyWnd yarışta kaybolduysa
    strip._u = _FakeUser32(tray_wnd=0, rect_ok=True)
    assert strip._bar() is None
    # GetWindowRect başarısızsa
    strip._u = _FakeUser32(tray_wnd=200, rect_ok=False)
    assert strip._bar() is None
