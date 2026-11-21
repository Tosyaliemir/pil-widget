"""Pil Widget'ın görev çubuğu şeridi: Windows görev çubuğunun İÇİNDE duran küçük pil göstergesi.

Yaklaşım Wireless Battery'nin (vendor/wireless-battery/src/widget.cpp) denenmiş yöntemidir: görev çubuğunun
(Shell_TrayWnd) alt penceresi olarak katmanlı (layered) bir pencere açılır, PIL ile çizilen RGBA resim
UpdateLayeredWindow ile basılır. Saf ctypes; kendi iş parçacığında kendi mesaj döngüsü vardır.

KURALLAR (Explorer'ı kilitlememek için):
- UI Automation ASLA kullanılmaz (Explorer'ı kilitlemesiyle bilinir).
- Explorer pencerelerine senkron SendMessage atılmaz; yalnızca FindWindowEx/GetWindowRect okunur ve kendi
  penceremize SetWindowPos uygulanır.

Çizim (`ciz`) Win32'ye bağlı değildir; resim üretir, bu yüzden test edilebilir.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Callable

from PIL import Image, ImageChops, ImageDraw, ImageFont

log = logging.getLogger(__name__)

STYLES = ("simge", "yuzde", "kapsul")
POSITIONS = ("sol", "sag")
LOW, MID = 15, 30
COLORS = {"ok": "#10B981", "mid": "#F59E0B", "low": "#EF4444", "chg": "#38BDF8", "slp": "#64748B"}
FG_DARK, FG_LIGHT = "#F1F5F9", "#0F172A"
SS = 2          # süper örnekleme: 2x çiz, LANCZOS ile küçült
CANVAS_H = 32   # 96 dpi'de şerit yüksekliği (birim = 96 dpi pikseli)

def resource(rel: str) -> Path:
    """Paket dosyası: PyInstaller ile derlenmişse sys._MEIPASS içinde (PyInstaller --add-data ile ui klasörü), yoksa paket klasöründe."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / rel


_FONT_FILE = resource("ui/fonts/geist-latin-wght-normal.woff2")
_FONT_FALLBACKS = (r"C:\Windows\Fonts\seguisb.ttf", r"C:\Windows\Fonts\segoeui.ttf")
_fonts: dict[tuple[int, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


# ---------------------------------------------------------------------------
# Çizim (Win32'den bağımsız)
# ---------------------------------------------------------------------------
def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _font(px: int, weight: int = 550):
    """Geist (değişken ağırlık, woff2'yi FreeType okuyor); olmazsa Segoe UI."""
    key = (px, weight)
    if key in _fonts:
        return _fonts[key]
    font = None
    try:
        font = ImageFont.truetype(str(_FONT_FILE), px)
        font.set_variation_by_axes([weight])
    except Exception:  # noqa: BLE001 - woff2/FreeType desteği yoksa
        font = None
    if font is None:
        for path in _FONT_FALLBACKS:
            try:
                font = ImageFont.truetype(path, px)
                break
            except OSError:
                continue
    if font is None:
        font = ImageFont.load_default()
    _fonts[key] = font
    return font


def durum(d: dict) -> dict:
    """ortak.js Cihaz.meta karşılığı: uyuyor / şarjda / düşük / orta ve vurgu rengi."""
    known = d.get("percent", -1) >= 0
    pct = d.get("percent", -1)
    sleeping = bool(d.get("asleep") or d.get("stale"))
    charging = bool(d.get("charging")) and not sleeping
    low = not sleeping and not charging and known and pct <= LOW
    mid = not sleeping and not charging and not low and known and pct <= MID
    if sleeping:
        accent = COLORS["slp"]
    elif charging:
        accent = COLORS["chg"]
    elif low:
        accent = COLORS["low"]
    elif mid:
        accent = COLORS["mid"]
    elif not known:
        accent = COLORS["slp"]
    else:
        accent = COLORS["ok"]
    return {"sleeping": sleeping, "charging": charging, "low": low, "mid": mid, "accent": accent, "known": known}


def glyph(d: dict) -> str:
    """ortak.js Cihaz.glyph karşılığı: overear | inear | mouse | gamepad | keyboard | phone | other."""
    import re

    kind = d.get("kind")
    if kind == "headset":
        detail = str(d.get("detail") or "")
        pods = re.search(r"\b[LR]\s*:?\s*\d{1,3}\s*%", detail, re.I)
        return "inear" if re.search(r"buds|airpods|earbuds|tws", str(d.get("name") or ""), re.I) or pods else "overear"
    return kind if kind in ("mouse", "gamepad", "keyboard", "phone") else "other"


def yuzde_metni(d: dict) -> str:
    if d.get("percent", -1) >= 0:
        return f"%{d['percent']}"
    return str(d.get("levelText") or "—")


def ipucu_metni(devices: list[dict]) -> str:
    """Fare üzerine gelince gösterilen çok satırlı özet: 'ad: %NN'."""
    lines = []
    for d in devices:
        if not d.get("connected"):
            continue
        extra = " (şarj oluyor)" if durum(d)["charging"] else " (uykuda)" if durum(d)["sleeping"] else ""
        lines.append(f"{d.get('name', '?')}: {yuzde_metni(d)}{extra}")
    return "\n".join(lines)


class _Layer:
    """Süper örneklenmiş tuval: birim (96 dpi px) -> piksel çevirisi, ilkel şekiller, yarı saydam katman."""

    def __init__(self, w_units: float, h_units: float, k: float):
        self.k = k
        self.size = (max(1, round(w_units * k)), max(1, round(h_units * k)))
        self.img = Image.new("RGBA", self.size, (0, 0, 0, 0))

    def layer(self):
        return Image.new("RGBA", self.size, (0, 0, 0, 0))

    def merge(self, layer: Image.Image, opacity: float = 1.0) -> None:
        if opacity < 1.0:
            layer.putalpha(layer.getchannel("A").point(lambda a: int(a * opacity)))
        self.img = Image.alpha_composite(self.img, layer)



def _glyph(dr: ImageDraw.ImageDraw, g: str, ox: float, oy: float, size: float, k: float, color) -> None:
    """16x16 çizgi simge (ortak.js ICONS16 ile aynı geometri), (ox, oy) köşesinde, size birim genişliğinde."""
    s = size / 16.0
    kk = k * s
    # Geometriyi 16'lık ızgarada çiz; ofseti piksel olarak ekle (ox, oy birim)
    ofs = (ox * k, oy * k)
    lw = 1.5  # çizgi kalınlığı (16'lık birimde)

    def X(v):  # ızgara -> piksel
        return ofs[0] + v * kk

    def Y(v):
        return ofs[1] + v * kk

    def line(x1, y1, x2, y2, w=lw):
        wp = max(1, round(w * kk))
        dr.line((X(x1), Y(y1), X(x2), Y(y2)), fill=color, width=wp)
        r = wp / 2
        for x, y in ((x1, y1), (x2, y2)):
            dr.ellipse((X(x) - r, Y(y) - r, X(x) + r, Y(y) + r), fill=color)

    def rr(x1, y1, x2, y2, r, w=lw):
        dr.rounded_rectangle((X(x1), Y(y1), X(x2), Y(y2)), radius=r * kk, outline=color, width=max(1, round(w * kk)))

    def dot(x, y, r):
        dr.ellipse((X(x - r), Y(y - r), X(x + r), Y(y + r)), fill=color)

    if g == "overear":
        wp = max(1, round(1.55 * kk))
        dr.arc((X(2.8), Y(2.4), X(13.2), Y(12.8)), 180, 360, fill=color, width=wp)
        line(2.8, 7.6, 2.8, 9.2, 1.55)
        line(13.2, 7.6, 13.2, 9.2, 1.55)
        rr(2, 8, 4.5, 13, 1.25, 1.45)
        rr(11.5, 8, 14, 13, 1.25, 1.45)
        dot(12.75, 10.5, 0.6)
    elif g == "inear":
        for cx, sx in ((5.2, 3.8), (10.8, 12.2)):
            dr.ellipse((X(cx - 2.2), Y(5.4 - 2.2), X(cx + 2.2), Y(5.4 + 2.2)), outline=color, width=max(1, round(1.5 * kk)))
            line(sx, 7.2, sx, 12.2, 1.5)
            dot(cx, 5.4, 0.7)
    elif g == "mouse":
        rr(4.5, 1.8, 11.5, 14.2, 3.5, 1.5)
        line(8, 4.4, 8, 6.8, 1.7)
    elif g == "gamepad":
        rr(1.4, 4.6, 14.6, 12.2, 3.2, 1.5)
        line(4.4, 7.8, 6.4, 7.8, 1.35)
        line(5.4, 6.8, 5.4, 8.8, 1.35)
        dot(11.2, 7.8, 0.95)
    elif g == "keyboard":
        rr(1.5, 3.8, 14.5, 12.2, 2, 1.5)
        dot(4.5, 7, 0.75)
        dot(7.5, 7, 0.75)
        line(5, 9.6, 9.5, 9.6, 1.6)
        dot(11, 7, 0.85)
    elif g == "phone":
        rr(4.5, 1.5, 11.5, 14.5, 2, 1.5)
        line(7, 12.2, 9, 12.2, 1.5)
        dot(8, 3.9, 0.65)
    else:  # other: pil
        rr(1.5, 4.8, 12.5, 11.2, 2, 1.5)
        line(14.5, 6.8, 14.5, 9.2, 1.5)
        dot(5, 8, 0.85)
        dot(8, 8, 0.85)


def _bolt(dr: ImageDraw.ImageDraw, x: float, y: float, h: float, k: float, color) -> float:
    """Küçük şimşek (12x16 yön oranı); (x, y) sol üst, h birim yüksekliğinde. Genişliği döndürür (birim)."""
    s = h / 16.0
    pts = [(7, 1), (2, 9), (6, 9), (5, 15), (10, 7), (6, 7)]
    dr.polygon([((x + px * s) * k, (y + py * s) * k) for px, py in pts], fill=color)
    return 12 * s


def _text(dr, k, x, cy, text, font, color) -> float:
    """Rakam yüksekliğine göre dikey ortalanmış metin; genişliği (birim) döndürür."""
    top = font.getbbox("0", anchor="ls")[1]   # negatif: taban çizgisinden yukarı
    base_y = cy * k - top / 2                 # rakamın ortası cy'ye gelsin
    dr.text((x * k, base_y), text, font=font, fill=color, anchor="ls")
    return font.getlength(text) / k


def ciz(devices: list[dict], style: str, light: bool, scale: float, hover: bool = False) -> Image.Image | None:
    """Görev çubuğu şeridini çizer: RGBA (düz, premultiplied DEĞİL), boyut ≈ (içerik, 32 * scale) piksel.
    Bağlı cihaz yoksa None. style: simge | yuzde | kapsul; scale: DPI / 96.
    Zemin saydamdır; yalnızca fare altında kalsın diye neredeyse görünmez (alfa 2) bir dolgu var."""
    devs = [d for d in devices if d.get("connected")]
    if not devs:
        return None
    if style not in STYLES:
        style = "yuzde"
    scale = max(0.5, float(scale))
    k = scale * SS
    fg = _rgb(FG_LIGHT if light else FG_DARK)
    fg_a = lambda a: (*fg, int(a * 255))  # noqa: E731
    font = _font(max(6, round((11 if style == "kapsul" else 11.5) * k)))
    metas = [durum(d) for d in devs]

    # -- ölçüler (birim) ---------------------------------------------------
    pad = 8.0
    if style == "simge":
        gap, item_w = 10.0, [16.0] * len(devs)
        width = 2 * pad + sum(item_w) + gap * (len(devs) - 1)
    elif style == "yuzde":
        gap = 12.0
        item_w = []
        for d, m in zip(devs, metas):
            tw = font.getlength(yuzde_metni(d)) / k
            item_w.append(16 + 6 + tw + (3 + 5 if m["charging"] else 0))
        width = 2 * pad + sum(item_w) + gap * (len(devs) - 1)
    else:  # kapsul
        gap, ppad = 10.0, 10.0
        item_w = []
        for d, m in zip(devs, metas):
            tw = font.getlength(yuzde_metni(d)) / k
            item_w.append(14 + 6 + tw + (3 + 5 if m["charging"] else 0))
        pill_w = 2 * ppad + sum(item_w) + (gap * 2 + 1) * (len(devs) - 1)
        width = pill_w + 4   # kenarlarda 2 birim pay
    H = float(CANVAS_H)
    cv = _Layer(width, H, k)
    base = cv.layer()
    bd = ImageDraw.Draw(base)

    # -- zemin: fare altında kalma dolgusu + üzerine gelme vurgusu --------------
    if style == "kapsul":
        px0, py0, px1, py1 = 2.0, (H - 28) / 2, 2.0 + pill_w, (H + 28) / 2
        bd.rounded_rectangle((px0 * k, py0 * k, px1 * k, py1 * k), radius=14 * k, fill=fg_a(0.10 if hover else 0.055))
        bd.rounded_rectangle((px0 * k, py0 * k, px1 * k, py1 * k), radius=14 * k, outline=fg_a(0.09),
                             width=max(1, round(1 * k)))
    else:
        bd.rounded_rectangle((0, 0, cv.size[0] - 1, cv.size[1] - 1), radius=8 * k,
                             fill=fg_a(0.08) if hover else (*fg, 2))
    cv.merge(base)

    # -- cihazlar -----------------------------------------------------------
    x = (2 + ppad) if style == "kapsul" else pad
    for i, (d, m, w) in enumerate(zip(devs, metas, item_w)):
        ly = cv.layer()
        dr = ImageDraw.Draw(ly)
        g = glyph(d)
        cy = H / 2
        if style == "simge":
            glyph_col = _rgb(COLORS["low"]) if m["low"] else _rgb(COLORS["chg"]) if m["charging"] else fg
            top = (H - (16 + 3 + 1.5)) / 2
            _glyph(dr, g, x, top, 16, k, glyph_col)
            by = top + 16 + 3
            bx0, bw = x + 2, 12.0
            dr.rounded_rectangle((bx0 * k, by * k, (bx0 + bw) * k, (by + 1.5) * k), radius=0.75 * k, fill=fg_a(0.2))
            if m["known"] and d["percent"] > 0:
                fw = max(1.5, bw * min(100, d["percent"]) / 100)
                dr.rounded_rectangle((bx0 * k, by * k, (bx0 + fw) * k, (by + 1.5) * k), radius=0.75 * k, fill=glyph_col)
        else:
            gs = 14 if style == "kapsul" else 16
            col = _rgb(COLORS["low"]) if m["low"] else _rgb(COLORS["chg"]) if m["charging"] else _rgb(m["accent"])
            txt_col = col if (m["low"] or m["charging"]) else fg
            if style == "kapsul" and i > 0:
                sx = x - gap - 0.5   # ayırıcı: önceki öğenin sağında
                dr.line((sx * k, (H / 2 - 7) * k, sx * k, (H / 2 + 7) * k), fill=fg_a(0.10), width=max(1, round(1 * k)))
            _glyph(dr, g, x, cy - gs / 2, gs, k, col)
            tx = x + gs + 6
            tw = _text(dr, k, tx, cy, yuzde_metni(d), font, (*txt_col, 255))
            if m["charging"]:
                _bolt(dr, tx + tw + 3, cy - 4, 8, k, _rgb(COLORS["chg"]))
        cv.merge(ly, 0.45 if m["sleeping"] else 1.0)
        x += w + (2 * gap + 1 if style == "kapsul" else gap)

    final = (max(1, round(width * scale)), max(1, round(H * scale)))
    return cv.img.resize(final, Image.LANCZOS)


# ---------------------------------------------------------------------------
# Win32 (yalnızca Windows)
# ---------------------------------------------------------------------------
def taskbar_light() -> bool:
    """Görev çubuğu açık temada mı? (Uygulama temasından ayrı: SystemUsesLightTheme.)"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "SystemUsesLightTheme")[0] == 1
    except OSError:
        return False


LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY, WM_CLOSE, WM_SETTINGCHANGE, WM_TIMER = 0x0002, 0x0010, 0x001A, 0x0113
WM_MOUSEMOVE, WM_LBUTTONUP, WM_RBUTTONUP, WM_MOUSELEAVE, WM_MOUSEACTIVATE = 0x0200, 0x0202, 0x0205, 0x02A3, 0x0021
WM_APP = 0x8000
WM_GC_UPDATE, WM_GC_STOP = WM_APP + 1, WM_APP + 2
WS_CHILD, WS_CLIPSIBLINGS, WS_POPUP = 0x40000000, 0x04000000, 0x80000000
WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOPMOST, WS_EX_LAYOUTRTL = 0x00080000, 0x08000000, 0x00000008, 0x00400000
GWL_EXSTYLE, GW_HWNDPREV = -20, 3
HWND_TOP = 0
SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0010, 0x0040
SW_HIDE = 0
ULW_ALPHA, AC_SRC_OVER, AC_SRC_ALPHA = 2, 0, 1
TME_LEAVE = 2
TTF_IDISHWND, TTF_SUBCLASS = 0x0001, 0x0010
TTS_ALWAYSTIP, TTS_NOPREFIX = 0x01, 0x02
TTM_SETMAXTIPWIDTH, TTM_ADDTOOLW, TTM_DELTOOLW, TTM_UPDATETIPTEXTW = 0x0418, 0x0432, 0x0433, 0x0439
ICC_WIN95_CLASSES = 0x000000FF
TIMER_ID, TIMER_MS = 1, 1000
THEME_TTL = 30      # sn: tema kaydı en çok bu sıklıkla okunur (WM_SETTINGCHANGE gelirse hemen)
RETOP_GAP = 5       # sn: üstümüzü örten kardeş pencere varsa en çok bu sıklıkla yeniden öne alınır
MA_NOACTIVATE = 3


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BLEND(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte), ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HANDLE), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HANDLE)]


class _TRACKMOUSE(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("hwndTrack", wintypes.HWND),
                ("dwHoverTime", wintypes.DWORD)]


class _TOOLINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("uFlags", wintypes.UINT), ("hwnd", wintypes.HWND), ("uId", ctypes.c_size_t),
                ("rect", wintypes.RECT), ("hinst", wintypes.HINSTANCE), ("lpszText", ctypes.c_void_p),
                ("lParam", wintypes.LPARAM), ("lpReserved", ctypes.c_void_p)]


class _INITCC(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("dwICC", wintypes.DWORD)]


def _api():
    """user32/gdi32 işlevlerini tiplendirir (64 bit tutamaç kırpılmasın). Yalnızca Windows'ta çağrılır."""
    u = ctypes.WinDLL("user32", use_last_error=True)
    g = ctypes.WinDLL("gdi32", use_last_error=True)
    H, P = wintypes.HWND, ctypes.c_void_p
    u.DefWindowProcW.restype, u.DefWindowProcW.argtypes = LRESULT, (H, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    u.RegisterClassExW.argtypes = (ctypes.POINTER(_WNDCLASSEXW),)
    u.CreateWindowExW.restype = H
    u.CreateWindowExW.argtypes = (wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, H, wintypes.HMENU, wintypes.HINSTANCE, P)
    u.DestroyWindow.argtypes = (H,)
    u.IsWindow.argtypes = (H,)
    u.FindWindowW.restype, u.FindWindowW.argtypes = H, (wintypes.LPCWSTR, wintypes.LPCWSTR)
    u.FindWindowExW.restype = H
    u.FindWindowExW.argtypes = (H, H, wintypes.LPCWSTR, wintypes.LPCWSTR)
    u.GetWindowRect.argtypes = (H, ctypes.POINTER(wintypes.RECT))
    u.GetWindowLongW.argtypes = (H, ctypes.c_int)
    try:
        u.GetDpiForWindow.argtypes = (H,)
    except AttributeError:
        pass
    u.GetParent.restype, u.GetParent.argtypes = H, (H,)
    u.GetWindow.restype, u.GetWindow.argtypes = H, (H, wintypes.UINT)
    u.ScreenToClient.argtypes = (H, ctypes.POINTER(_POINT))
    u.SetWindowPos.argtypes = (H, H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
    u.ShowWindow.argtypes = (H, ctypes.c_int)
    u.IsWindowVisible.argtypes = (H,)
    u.PostMessageW.argtypes = (H, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    u.SendMessageW.restype, u.SendMessageW.argtypes = LRESULT, (H, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    u.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), H, wintypes.UINT, wintypes.UINT)
    u.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
    u.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
    u.SetTimer.argtypes = (H, ctypes.c_size_t, wintypes.UINT, P)
    u.KillTimer.argtypes = (H, ctypes.c_size_t)
    u.GetDC.restype, u.GetDC.argtypes = wintypes.HDC, (H,)
    u.ReleaseDC.argtypes = (H, wintypes.HDC)
    u.UpdateLayeredWindow.argtypes = (H, wintypes.HDC, ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE), wintypes.HDC,
                                      ctypes.POINTER(_POINT), wintypes.COLORREF, ctypes.POINTER(_BLEND), wintypes.DWORD)
    u.TrackMouseEvent.argtypes = (ctypes.POINTER(_TRACKMOUSE),)
    u.LoadCursorW.restype, u.LoadCursorW.argtypes = wintypes.HANDLE, (wintypes.HINSTANCE, ctypes.c_void_p)
    u.RegisterWindowMessageW.argtypes = (wintypes.LPCWSTR,)
    g.CreateCompatibleDC.restype, g.CreateCompatibleDC.argtypes = wintypes.HDC, (wintypes.HDC,)
    g.CreateDIBSection.restype = wintypes.HBITMAP
    g.CreateDIBSection.argtypes = (wintypes.HDC, ctypes.POINTER(_BITMAPINFO), wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                   wintypes.HANDLE, wintypes.DWORD)
    g.SelectObject.restype, g.SelectObject.argtypes = wintypes.HGDIOBJ, (wintypes.HDC, wintypes.HGDIOBJ)
    g.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
    g.DeleteDC.argtypes = (wintypes.HDC,)
    return u, g


_kernel32 = None
_apis = None
_instances: dict[int, "GorevCubugu"] = {}   # pencere tutamacı -> şerit (pencere iletileri buraya yönlenir)
_classes_lock = threading.Lock()
_classes_ok = False
_wndproc_cb = None   # modül düzeyinde: sınıflar işlem boyunca kayıtlı kalır, geri çağrı hiç çöpe gitmemeli


def _hinstance():
    """Bu işlemin HMODULE'ü (64 bit tutamaç kırpılmasın diye tiplendirilmiş)."""
    global _kernel32
    if _kernel32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetModuleHandleW.restype = wintypes.HMODULE
        k.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        _kernel32 = k
    return _kernel32.GetModuleHandleW(None)


def _get_api():
    global _apis
    if _apis is None:
        _apis = _api()
    return _apis


def _dispatch(hwnd, msg, wparam, lparam):
    """Tüm şerit pencerelerinin ortak pencere yordamı: iletiyi tutamaca ait şerit nesnesine verir."""
    inst = _instances.get(hwnd)
    if inst is not None:
        return inst._proc(hwnd, msg, wparam, lparam)
    return _get_api()[0].DefWindowProcW(hwnd, msg, wparam, lparam)


def _ensure_classes() -> bool:
    """İki pencere sınıfını işlem başına BİR kez kaydeder ve hiç silmez (şerit kapatılıp açılınca, eski örneğin
    geri çağrısı yok olmuş bir sınıfa pencere açılmaz)."""
    global _classes_ok, _wndproc_cb
    with _classes_lock:
        if _classes_ok:
            return True
        u = _get_api()[0]
        _wndproc_cb = WNDPROC(_dispatch)
        arrow = u.LoadCursorW(None, ctypes.c_void_p(32512))
        ok = True
        for name in (GorevCubugu.CLS_STRIP, GorevCubugu.CLS_MSG):
            wc = _WNDCLASSEXW(cbSize=ctypes.sizeof(_WNDCLASSEXW), lpfnWndProc=_wndproc_cb, hInstance=_hinstance(),
                              hCursor=arrow, lpszClassName=name)
            if not u.RegisterClassExW(ctypes.byref(wc)):
                err = ctypes.get_last_error()
                if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                    log.warning("Pencere sınıfı kaydedilemedi (%s): %s", name, err)
                    ok = False
        _classes_ok = ok
        return ok


def _premultiplied_bgra(img: Image.Image) -> bytes:
    """RGBA -> premultiplied BGRA (UpdateLayeredWindow + AC_SRC_ALPHA bunu ister)."""
    r, g, b, a = img.split()
    r, g, b = ImageChops.multiply(r, a), ImageChops.multiply(g, a), ImageChops.multiply(b, a)
    return Image.merge("RGBA", (b, g, r, a)).tobytes()


class GorevCubugu:
    """Görev çubuğu pil şeridi. Kendi iş parçacığında çalışır; update() her iş parçacığından çağrılabilir.

    on_click(): şeride sol tık; on_menu(): sağ tık; light_fn(): görev çubuğu açık mı (varsayılan: sistem teması).
    Hata olursa uygulamayı düşürmez: günlüğe yazar ve kapalı kalır."""

    CLS_STRIP = "PilWidgetGorevCubugu"
    CLS_MSG = "PilWidgetGorevMesaj"

    def __init__(self, on_click: Callable[[], None] | None = None, on_menu: Callable[[], None] | None = None,
                 light_fn: Callable[[], bool] | None = None) -> None:
        self.on_click, self.on_menu = on_click, on_menu
        self.light_fn = light_fn or taskbar_light
        self._lock = threading.Lock()
        self._devices: list[dict] = []
        self._style, self._position, self._light_override = "yuzde", "sol", None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        # yalnızca şerit iş parçacığında kullanılır
        self._u = self._g = None
        self._msg = self._strip = self._tip = None
        self._hover = self._tracking = False
        self._size = (0, 0)
        self._last_pos: tuple | None = None
        self._last_light: bool | None = None
        self._light_cache: bool | None = None   # görev çubuğu teması önbelleği (yalnızca şerit iş parçacığı)
        self._light_at = 0.0
        self._last_retop = 0.0
        self._tip_text = ""
        self._tip_buf = None
        self._tb_msg = 0
        self._dpi = 96

    # -- genel API -------------------------------------------------------------
    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="gorev-cubugu")
        self._thread.start()
        self._ready.wait(3)
        return self._msg is not None

    def stop(self) -> None:
        t = self._thread
        if not t:
            return
        try:
            if self._u and self._msg:
                self._u.PostMessageW(self._msg, WM_GC_STOP, 0, 0)
        except Exception:  # noqa: BLE001
            pass
        t.join(3)
        self._thread = None

    def update(self, devices: list[dict], style: str, position: str, light: bool | None = None) -> None:
        """Durumu saklar ve yeniden çizdirir (iş parçacığı güvenli)."""
        with self._lock:
            self._devices = [dict(d) for d in devices]
            self._style = style if style in STYLES else "yuzde"
            self._position = position if position in POSITIONS else "sol"
            self._light_override = light
        try:
            if self._u and self._msg:
                self._u.PostMessageW(self._msg, WM_GC_UPDATE, 0, 0)
        except Exception:  # noqa: BLE001
            pass

    # -- iş parçacığı ----------------------------------------------------------
    def _run(self) -> None:
        try:
            self._loop()
        except Exception:  # noqa: BLE001
            log.exception("Görev çubuğu şeridi çalışmadı")
        finally:
            self._ready.set()

    def _loop(self) -> None:
        u, g = _get_api()
        self._u, self._g = u, g
        try:  # Explorer ile aynı DPI bağlamı: GetWindowRect fiziksel piksel versin
            u.SetThreadDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
            u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
        inst = _hinstance()
        if not _ensure_classes():
            return
        self._tb_msg = u.RegisterWindowMessageW("TaskbarCreated")
        # Gizli üst düzey pencere: TaskbarCreated yayını yalnızca üst düzey pencerelere gelir
        self._msg = u.CreateWindowExW(0, self.CLS_MSG, "", WS_POPUP, 0, 0, 0, 0, None, None, inst, None)
        if not self._msg:
            log.warning("Görev çubuğu mesaj penceresi açılamadı: %s", ctypes.get_last_error())
            return
        _instances[self._msg] = self
        try:
            icc = _INITCC(ctypes.sizeof(_INITCC), ICC_WIN95_CLASSES)
            ctypes.windll.comctl32.InitCommonControlsEx(ctypes.byref(icc))
        except Exception:  # noqa: BLE001
            pass
        u.SetTimer(self._msg, TIMER_ID, TIMER_MS, None)
        self._ready.set()
        self._create_strip()
        msg = wintypes.MSG()
        try:
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._destroy_strip()
            if self._tip and u.IsWindow(self._tip):
                u.DestroyWindow(self._tip)
            self._tip = None
            if self._msg:
                if u.IsWindow(self._msg):
                    u.KillTimer(self._msg, TIMER_ID)
                    u.DestroyWindow(self._msg)
                _instances.pop(self._msg, None)
                self._msg = None

    def _proc(self, hwnd, msg, wparam, lparam):
        u = self._u
        try:
            if hwnd == self._msg:
                if msg == WM_SETTINGCHANGE:
                    self._light_cache = None   # tema değişmiş olabilir; bir sonraki tikte yeniden okunur
                if msg == WM_TIMER:
                    self._tick()
                    return 0
                if msg == WM_GC_UPDATE:
                    self._paint()
                    return 0
                if msg == self._tb_msg and msg:
                    log.info("Görev çubuğu yeniden oluştu (Explorer); şerit yeniden kuruluyor")
                    self._destroy_strip()
                    self._create_strip()
                    return 0
                if msg == WM_GC_STOP:
                    u.KillTimer(hwnd, TIMER_ID)
                    self._destroy_strip()
                    if self._tip and u.IsWindow(self._tip):
                        u.DestroyWindow(self._tip)
                    self._tip = None
                    u.DestroyWindow(hwnd)
                    return 0
                if msg == WM_DESTROY:
                    ctypes.windll.user32.PostQuitMessage(0)
                    return 0
            elif hwnd == self._strip:
                if msg == WM_MOUSEACTIVATE:
                    return MA_NOACTIVATE
                if msg == WM_MOUSEMOVE:
                    if not self._tracking:
                        tme = _TRACKMOUSE(ctypes.sizeof(_TRACKMOUSE), TME_LEAVE, hwnd, 0)
                        u.TrackMouseEvent(ctypes.byref(tme))
                        self._tracking = True
                    if not self._hover:
                        self._hover = True
                        self._paint()
                    return 0
                if msg == WM_MOUSELEAVE:
                    self._tracking = False
                    if self._hover:
                        self._hover = False
                        self._paint()
                    return 0
                if msg == WM_LBUTTONUP:
                    self._fire(self.on_click)
                    return 0
                if msg == WM_RBUTTONUP:
                    self._fire(self.on_menu)
                    return 0
        except Exception:  # noqa: BLE001
            log.exception("Görev çubuğu pencere iletisi işlenemedi")
        return u.DefWindowProcW(hwnd, msg, wparam, lparam)

    @staticmethod
    def _fire(fn) -> None:
        """Geri çağrı ayrı iş parçacığında: menü/pencere açmak mesaj döngümüzü bekletmesin."""
        if fn:
            threading.Thread(target=fn, daemon=True, name="gorev-cubugu-tik").start()

    # -- şerit penceresi ---------------------------------------------------------
    def _taskbar(self):
        u = self._u
        tb = u.FindWindowW("Shell_TrayWnd", None)
        if not tb or not u.FindWindowExW(tb, None, "TrayNotifyWnd", None):
            return None
        return tb

    def _create_strip(self) -> bool:
        u = self._u
        try:
            tb = self._taskbar()
            if not tb:
                return False
            inst = _hinstance()
            hwnd = u.CreateWindowExW(WS_EX_LAYERED | WS_EX_NOACTIVATE, self.CLS_STRIP, "", WS_CHILD | WS_CLIPSIBLINGS,
                                     0, 0, 1, 1, tb, None, inst, None)
            if not hwnd:
                log.warning("Görev çubuğu şeridi açılamadı: %s", ctypes.get_last_error())
                return False
            self._strip = hwnd
            _instances[hwnd] = self
            self._hover = self._tracking = False
            self._last_pos = None
            self._ensure_tip()
            self._add_tool()
            self._paint()
            return True
        except Exception:  # noqa: BLE001
            log.exception("Görev çubuğu şeridi oluşturulamadı")
            return False

    def _destroy_strip(self) -> None:
        u = self._u
        hwnd, self._strip = self._strip, None
        if not hwnd:
            return
        try:
            if self._tip and u.IsWindow(self._tip):
                ti = self._toolinfo(hwnd, None)
                u.SendMessageW(self._tip, TTM_DELTOOLW, 0, ctypes.addressof(ti))
            if u.IsWindow(hwnd):
                u.DestroyWindow(hwnd)
        except Exception:  # noqa: BLE001
            log.exception("Görev çubuğu şeridi yok edilemedi")
        finally:
            _instances.pop(hwnd, None)

    # -- ipucu (tooltip) -----------------------------------------------------------
    def _apply_tip_theme(self, light: bool) -> None:
        if not (self._tip and self._u and self._u.IsWindow(self._tip)):
            return
        try:
            ux = ctypes.windll.uxtheme
            ux.SetWindowTheme.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
            ux.SetWindowTheme(wintypes.HWND(self._tip), "" if light else "DarkMode_Explorer", None)
        except Exception:  # noqa: BLE001
            pass

    def _ensure_tip(self) -> None:
        u = self._u
        if self._tip and u.IsWindow(self._tip):
            return
        inst = _hinstance()
        self._tip = u.CreateWindowExW(WS_EX_TOPMOST, "tooltips_class32", None, WS_POPUP | TTS_ALWAYSTIP | TTS_NOPREFIX,
                                      0, 0, 0, 0, self._msg, None, inst, None)
        if not self._tip:
            return
        u.SendMessageW(self._tip, TTM_SETMAXTIPWIDTH, 0, 600)
        _d, _s, _p, light_o = self._snapshot()
        self._apply_tip_theme(self._is_light(light_o))

    def _toolinfo(self, strip, text) -> _TOOLINFOW:
        ti = _TOOLINFOW()
        ti.cbSize = ctypes.sizeof(_TOOLINFOW)
        ti.uFlags = TTF_IDISHWND | TTF_SUBCLASS
        ti.hwnd = self._msg
        ti.uId = ctypes.cast(strip, ctypes.c_void_p).value or 0
        if text is not None:
            self._tip_buf = ctypes.create_unicode_buffer(text)
            ti.lpszText = ctypes.cast(self._tip_buf, ctypes.c_void_p).value
        return ti

    def _add_tool(self) -> None:
        if not (self._tip and self._strip):
            return
        ti = self._toolinfo(self._strip, self._tip_text or "Pil Widget")
        self._u.SendMessageW(self._tip, TTM_ADDTOOLW, 0, ctypes.addressof(ti))

    def _set_tip_text(self, text: str) -> None:
        if text == self._tip_text or not (self._tip and self._strip):
            return
        self._tip_text = text
        ti = self._toolinfo(self._strip, text or "Pil Widget")
        self._u.SendMessageW(self._tip, TTM_UPDATETIPTEXTW, 0, ctypes.addressof(ti))

    # -- çizim ve konum --------------------------------------------------------
    def _is_light(self, override) -> bool:
        """Görev çubuğu açık mı: kayıt defteri her saniye değil, THEME_TTL'de bir (ya da ayar değişince) okunur."""
        if override is not None:
            return bool(override)
        now = time.monotonic()
        if self._light_cache is None or now - self._light_at > THEME_TTL:
            self._light_cache, self._light_at = bool(self.light_fn()), now
        return self._light_cache

    def _obscured(self) -> bool:
        """Bir kardeş pencere şeridin üstünde VE onunla örtüşüyor mu? (Yalnızca üstte durmak yeterliyse boşuna
        yeniden öne almayız.)"""
        u = self._u
        mine = wintypes.RECT()
        if not u.GetWindowRect(self._strip, ctypes.byref(mine)):
            return False
        sib, r = u.GetWindow(self._strip, GW_HWNDPREV), wintypes.RECT()
        for _ in range(32):
            if not sib:
                return False
            if (u.IsWindowVisible(sib) and u.GetWindowRect(sib, ctypes.byref(r))
                    and r.left < mine.right and r.right > mine.left and r.top < mine.bottom and r.bottom > mine.top):
                return True
            sib = u.GetWindow(sib, GW_HWNDPREV)
        return False

    def _snapshot(self):
        with self._lock:
            return list(self._devices), self._style, self._position, self._light_override

    def _bar(self):
        """(taskbar, bar_rect, tray_rect) ya da None (yatay olmayan/yok görev çubuğu)."""
        u = self._u
        tb = self._taskbar()
        if not tb:
            return None
        tray_wnd = u.FindWindowExW(tb, None, "TrayNotifyWnd", None)
        if not tray_wnd:
            return None
        bar, tray = wintypes.RECT(), wintypes.RECT()
        if not u.GetWindowRect(tb, ctypes.byref(bar)) or not u.GetWindowRect(tray_wnd, ctypes.byref(tray)):
            return None
        if bar.bottom - bar.top > bar.right - bar.left or (u.GetWindowLongW(tb, GWL_EXSTYLE) & WS_EX_LAYOUTRTL):
            return None   # dikey ya da sağdan sola görev çubuğu: gizli kal
        return tb, bar, tray

    def _paint(self) -> None:
        """Resmi çizip pencereye basar; boşsa gizler. Konum bir sonraki _place ile düzelir."""
        u, g = self._u, self._g
        if not self._strip or not u.IsWindow(self._strip):
            return
        devices, style, position, light_o = self._snapshot()
        info = self._bar()
        light = self._is_light(light_o)
        if light != self._last_light:
            self._apply_tip_theme(light)
        self._last_light = light
        if info is None:
            self._hide()
            return
        tb, bar, _tray = info
        try:
            dpi = u.GetDpiForWindow(tb) or 96
        except (AttributeError, OSError):
            dpi = 96
        self._dpi = dpi
        bar_h = bar.bottom - bar.top
        scale = min(dpi / 96.0, max(0.5, bar_h / CANVAS_H))
        img = ciz(devices, style, light, scale, self._hover)
        self._set_tip_text(ipucu_metni(devices))
        if img is None:
            self._hide()
            return
        w, h = img.size
        data = _premultiplied_bgra(img)
        screen = u.GetDC(None)
        mem = g.CreateCompatibleDC(screen)
        try:
            bi = _BITMAPINFO()
            bi.bmiHeader = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
            bits = ctypes.c_void_p()
            bmp = g.CreateDIBSection(mem, ctypes.byref(bi), 0, ctypes.byref(bits), None, 0)
            if not bmp or not bits.value:
                log.warning("DIB oluşturulamadı")
                return
            old = g.SelectObject(mem, bmp)
            ctypes.memmove(bits, data, len(data))
            blend = _BLEND(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            sz, src = _SIZE(w, h), _POINT(0, 0)
            if not u.UpdateLayeredWindow(self._strip, screen, None, ctypes.byref(sz), mem, ctypes.byref(src), 0,
                                         ctypes.byref(blend), ULW_ALPHA):
                log.warning("UpdateLayeredWindow başarısız: %s", ctypes.get_last_error())
            g.SelectObject(mem, old)
            g.DeleteObject(bmp)
        finally:
            g.DeleteDC(mem)
            u.ReleaseDC(None, screen)
        self._size = (w, h)
        self._last_pos = None   # yeni boyutla konumlandır
        self._place()

    def _hide(self) -> None:
        u = self._u
        if self._strip and u.IsWindowVisible(self._strip):
            u.ShowWindow(self._strip, SW_HIDE)
        self._last_pos = None
        self._size = (0, 0)

    def _place(self) -> None:
        """Şeridi görev çubuğuna yerleştirir; yalnızca bir şey değiştiyse ya da başka kardeş pencere üstümüzü
        örtüyorsa SetWindowPos (Wireless Battery'deki 'covered' denetimi)."""
        u = self._u
        if not self._strip or not self._size[0]:
            return
        info = self._bar()
        if info is None:
            self._hide()
            return
        tb, bar, tray = info
        w, h = self._size
        scale = self._dpi / 96.0
        _d, _s, position, _l = self._snapshot()
        if position == "sag":
            sx = tray.left - w - round(2 * scale)
        else:
            sx = bar.left + round(8 * scale)
        sy = bar.top + (bar.bottom - bar.top - h) // 2
        pt = _POINT(sx, sy)
        u.ScreenToClient(tb, ctypes.byref(pt))
        key = (pt.x, pt.y, w, h)
        now = time.monotonic()
        if key == self._last_pos and u.IsWindowVisible(self._strip):
            # Konum aynı: yalnızca bir kardeş gerçekten üstümüzü örtüyorsa (ve son öne almadan RETOP_GAP geçtiyse)
            if now - self._last_retop < RETOP_GAP or not self._obscured():
                return
        self._last_pos = key
        self._last_retop = now
        u.SetWindowPos(self._strip, wintypes.HWND(HWND_TOP), pt.x, pt.y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def _tick(self) -> None:
        """Saniyede bir: Explorer yeniden başladıysa şeridi kur, tema/DPI/konum değiştiyse tazele."""
        u = self._u
        try:
            if self._strip and not u.IsWindow(self._strip):
                _instances.pop(self._strip, None)
                self._strip = None   # Explorer çöktü/yeniden başladı: şerit onunla birlikte yok oldu
            tb = self._taskbar()
            if self._strip and tb and u.GetParent(self._strip) != tb:
                self._destroy_strip()   # eski görev çubuğuna bağlı kalmış
            if not self._strip:
                if tb:
                    self._create_strip()
                return
            if not tb:
                return   # görev çubuğu şu an yok (yeniden başlıyor); bir sonraki tikte bakılır
            _d, _s, _p, light_o = self._snapshot()
            light = self._is_light(light_o)
            try:
                dpi = u.GetDpiForWindow(tb) or 96
            except (AttributeError, OSError):
                dpi = 96
            if light != self._last_light or dpi != self._dpi:
                self._paint()
            else:
                self._place()
        except Exception:  # noqa: BLE001
            log.exception("Görev çubuğu şeridi tazelenemedi")
