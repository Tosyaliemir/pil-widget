"""Pil Widget'ın Windows ayrıntıları (ctypes): masaüstüne gömme, ekrana sığdırma, sağ tık menüsü."""

from __future__ import annotations

import ctypes
import logging
import math
import os
import time
from ctypes import wintypes

log = logging.getLogger(__name__)

TITLE = "Pil Widget"
SIZES = ("nano", "mini", "detay")

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
MONITOR_DEFAULTTONULL = 0
MONITOR_DEFAULTTOPRIMARY = 1
MF_STRING, MF_SEPARATOR, MF_CHECKED, MF_GRAYED, MF_DISABLED = 0x0, 0x800, 0x8, 0x1, 0x2
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x2, 0x80, 0x100

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
user32.MonitorFromRect.restype = wintypes.HMONITOR
user32.MonitorFromRect.argtypes = (ctypes.POINTER(wintypes.RECT), wintypes.DWORD)
user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.c_void_p)
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = (wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR)
user32.TrackPopupMenu.argtypes = (wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, ctypes.c_void_p)
user32.DestroyMenu.argtypes = (wintypes.HMENU,)
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = (wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, ctypes.c_void_p)
user32.DestroyWindow.argtypes = (wintypes.HWND,)
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
GWLP_HWNDPARENT = -8
HWND_BOTTOM = 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT)
LWA_ALPHA = 0x2
OPACITY = 236  # 0-255: hafif yarı saydam
user32.SetLayeredWindowAttributes.argtypes = (wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD)


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = (WNDENUMPROC, wintypes.LPARAM)
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)


def find_own_window(title: str):
    """Başlığı `title` olan, BU işleme ait üst düzey pencere (yoksa None). Yalnızca başlığa bakmak başka bir
    programın (ör. 'Pil Widget' adlı bir Explorer klasörü) penceresine denk gelebilir; işlem kimliği de denetlenir."""
    found = []
    pid = os.getpid()

    def each(hwnd, _lp):
        buf = ctypes.create_unicode_buffer(256)
        if user32.GetWindowTextW(hwnd, buf, 256) and buf.value == title:
            owner = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid:
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(WNDENUMPROC(each), 0)
    return found[0] if found else None


_embedded_progman = 0   # widget'ın sahibi yaptığımız Progman tutamacı (Explorer yeniden başlayınca değişir)


def embed_stale() -> bool:
    """Masaüstü (Progman) embed'den sonra yeniden oluştuysa (Explorer yeniden başladı) True: embed() tekrar çağrılmalı."""
    cur = user32.FindWindowW("Progman", None)
    return bool(cur) and cur != _embedded_progman


def lower_widget() -> bool:
    """Widget'ı etkinleştirmeden tekrar Z-sırasının en altına (pencerelerin arkasına) indir.
    pywebview'in resize() çağrısı SetWindowPos(..., HWND_TOP, SWP_SHOWWINDOW) kullandığı için gereklidir."""
    hwnd = find_own_window(TITLE)
    if not hwnd:
        return False
    user32.SetWindowPos(hwnd, wintypes.HWND(HWND_BOTTOM), 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
    return True


def embed(light: bool = False) -> bool:
    """Widget'ı masaüstüne göm (Android widget'ı gibi):
    - sahibi masaüstü (Progman): pencerelerin arkasında durur, Win+D / "Masaüstünü göster"de kaybolmaz
    - araç penceresi + etkinleşmez: görev çubuğunda ve Alt+Tab'da yok, tıklayınca öne gelmez
    - Windows 11'de yuvarlak köşe, hafif yarı saydam (pywebview'in transparent seçeneği WebView2'de güvenilir değil)"""
    global _embedded_progman
    hwnd = find_own_window(TITLE)
    if not hwnd:
        return False
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    new = (style | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW
    if new != style:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new)
    user32.SetLayeredWindowAttributes(hwnd, 0, OPACITY, LWA_ALPHA)
    progman = user32.FindWindowW("Progman", None)
    if progman:
        user32.SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, progman)
        _embedded_progman = progman
    user32.SetWindowPos(hwnd, wintypes.HWND(HWND_BOTTOM), 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
    try:
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
        val = ctypes.c_int(2)                                   # DWMWCP_ROUND
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(val), 4)
        border = ctypes.c_int(0xDDDDDD if light else 0x2E2E2E)  # COLORREF (BGR)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), 34, ctypes.byref(border), 4)
    except OSError:
        pass  # Windows 10: köşeler düz kalır
    acrylic(hwnd, light)
    return True


class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]


WCA_ACCENT_POLICY = 19
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
ACRYLIC_DARK = 0xCC1C1512   # AABBGGRR: koyu ton (#12151c)
ACRYLIC_LIGHT = 0x99FBF6F3  # açık ton (#f3f6fb)


def acrylic(hwnd, light: bool = False) -> bool:
    """Arkadaki masaüstünü bulanıklaştıran cam (Acrylic) zemin. Belgelenmemiş SetWindowCompositionAttribute;
    WS_EX_LAYERED ile birlikte etkinleşmeyen pencerede de çalışıyor (denendi, Windows 11). Başarısız olursa
    widget yarı saydam düz görünümde kalır. Windows'ta 'Saydamlık efektleri' kapalıysa düz renge düşer."""
    try:
        fn = user32.SetWindowCompositionAttribute
        fn.argtypes = (wintypes.HWND, ctypes.c_void_p)
        p = ACCENT_POLICY(ACCENT_ENABLE_ACRYLICBLURBEHIND, 2, ACRYLIC_LIGHT if light else ACRYLIC_DARK, 0)
        d = WINCOMPATTRDATA(WCA_ACCENT_POLICY, ctypes.cast(ctypes.byref(p), ctypes.c_void_p), ctypes.sizeof(p))
        return bool(fn(wintypes.HWND(hwnd), ctypes.byref(d)))
    except (OSError, AttributeError):
        return False


user32.GetForegroundWindow.restype = wintypes.HWND
user32.BringWindowToTop.argtypes = (wintypes.HWND,)
user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)


def bring_to_front(title: str) -> None:
    """Pencereyi öne getir. Widget etkinleşmediği için Windows'un ön plan kilidi SetForegroundWindow'u tek başına
    engelleyebilir. Önce çağıran iş parçacığının girdisini şu anki ön plan penceresinin iş parçacığına bağlayıp
    (AttachThreadInput) öne getiririz; bu, sahte Alt tuşu gibi önceki uygulamada menü çubuğu açmaz. Olmazsa
    kısa bir 'her zaman üstte' geçişi yedektir."""
    hwnd = find_own_window(title)
    if not hwnd:
        return
    fg = user32.GetForegroundWindow()
    mine = ctypes.windll.kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(fg_thread and fg_thread != mine and user32.AttachThreadInput(mine, fg_thread, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(mine, fg_thread, False)
    if user32.GetForegroundWindow() != hwnd:
        flags = SWP_NOSIZE | SWP_NOMOVE
        user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, flags)   # HWND_TOPMOST
        user32.SetWindowPos(hwnd, wintypes.HWND(-2), 0, 0, 0, 0, flags)   # HWND_NOTOPMOST
        user32.SetForegroundWindow(hwnd)


def light_theme() -> bool:
    """Windows uygulama teması açık mı?"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 1
    except OSError:
        return False


MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                     ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
user32.EnumDisplayMonitors.argtypes = (wintypes.HDC, ctypes.c_void_p, MONITORENUMPROC, wintypes.LPARAM)


def work_areas() -> list[tuple[float, float, float, float, bool]]:
    """Her ekranın görev çubuğu hariç alanı, pywebview'in kullandığı mantıksal piksellerle
    (fiziksel / DPI ölçeği): sol, üst, sağ, alt, birincil mi."""
    out = []

    def each(mon, _hdc, _rect, _lp):
        info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        if user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            dx, dy = wintypes.UINT(96), wintypes.UINT(96)
            try:
                ctypes.windll.shcore.GetDpiForMonitor(wintypes.HMONITOR(mon), 0, ctypes.byref(dx), ctypes.byref(dy))
            except OSError:
                pass
            s = (dx.value or 96) / 96
            r = info.rcWork
            out.append((r.left / s, r.top / s, r.right / s, r.bottom / s, bool(info.dwFlags & 1)))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(each), 0)
    return out or [(0, 0, 1280, 720, True)]


def fit_on_screen(x: int | None, y: int | None, w: int, h: int) -> tuple[int, int]:
    """Kaydedilmiş konum hiçbir ekranda değilse (ekran söküldü, çözünürlük değişti) görünür alana getir.
    Bir ekrandaysa o ekranın içine sığdırır. Tüm değerler mantıksal piksel."""
    areas = work_areas()
    if x is not None and y is not None:
        cx, cy = x + w / 2, y + h / 2   # widget'ın ortası hangi ekranda?
        for left, top, right, bottom, _ in areas:
            if left <= cx < right and top <= cy < bottom:
                return int(max(left, min(x, right - w))), int(max(top, min(y, bottom - h)))
    left, top, right, bottom, _ = next((a for a in areas if a[4]), areas[0])
    return int(right - w - 24), int(bottom - h - 24)  # varsayılan: birincil ekranın sağ alt köşesi


def _dark_menus() -> None:
    """Sağ tık menüsü Windows koyu temasını izlesin (belgelenmemiş uxtheme sıra numaraları 135/136)."""
    try:
        ux = ctypes.WinDLL("uxtheme")
        ux[135](1)   # SetPreferredAppMode(AllowDark)
        ux[136]()    # FlushMenuThemes
    except (OSError, AttributeError):
        pass


def popup_menu(items: list[tuple | None]) -> int | None:
    """İmlecin yanında yerel bir menü açar, seçilen öğenin sırasını döndürür (vazgeçilirse None).
    items: (etiket, işaretli) ya da (etiket, işaretli, soluk) ya da ayırıcı için None. Soluk öğe başlık
    gibi tıklanamaz. Sıra numarası ayırıcılar dahil listedeki konumdur. Herhangi bir iş parçacığından çağrılabilir."""
    _dark_menus()
    menu = user32.CreatePopupMenu()
    if not menu:
        return None
    for i, item in enumerate(items):
        if item is None:
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        else:
            flags = MF_STRING | (MF_CHECKED if item[1] else 0) | (MF_GRAYED | MF_DISABLED if len(item) > 2 and item[2] else 0)
            user32.AppendMenuW(menu, flags, i + 1, item[0])
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    owner = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, None, None, None, None)
    if not owner:
        user32.DestroyMenu(menu)
        return None
    try:
        user32.SetForegroundWindow(owner)
        cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD, pt.x, pt.y, 0, owner, None)
        user32.PostMessageW(owner, 0, 0, 0)
    finally:
        user32.DestroyWindow(owner)
        user32.DestroyMenu(menu)
    return cmd - 1 if cmd > 0 else None


# ---------------------------------------------------------------------------
# Masaüstü simgeleri: widget'ın simgelerin üstüne binmemesi için
# ---------------------------------------------------------------------------
PROCESS_VM_OPERATION, PROCESS_VM_READ, PROCESS_VM_WRITE, PROCESS_QUERY_INFORMATION = 0x8, 0x10, 0x20, 0x400
MEM_COMMIT, MEM_RESERVE, MEM_RELEASE, PAGE_READWRITE = 0x1000, 0x2000, 0x8000, 0x04
LVM_GETITEMCOUNT, LVM_GETITEMRECT, LVIR_BOUNDS = 0x1004, 0x100E, 0
SMTO_BLOCK, SMTO_ABORTIFHUNG = 0x1, 0x2
ICON_QUERY_BUDGET = 1.5       # tüm simge sorgusu için üst süre sınırı (sn)
ICON_MSG_TIMEOUT_MS = 200     # tek bir iletinin bekleme sınırı
MAX_ICONS = 600               # makul üst sınır

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualAllocEx.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD)
kernel32.VirtualFreeEx.restype = wintypes.BOOL
kernel32.VirtualFreeEx.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD)
kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.WriteProcessMemory.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.POINTER(ctypes.c_size_t))
kernel32.ReadProcessMemory.restype = wintypes.BOOL
kernel32.ReadProcessMemory.argtypes = kernel32.WriteProcessMemory.argtypes
user32.FindWindowExW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = (wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t   # LRESULT
user32.SendMessageTimeoutW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT,
                                       wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))   # PDWORD_PTR
user32.MapWindowPoints.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.POINTER(wintypes.POINT), wintypes.UINT)


def _desktop_listview():
    """Masaüstü simge listesi (SysListView32). Simgeler gizliyse (sağ tık > Göster > Masaüstü simgelerini göster
    kapalı) liste görünmez olur; o zaman None."""
    defview = None
    progman = user32.FindWindowW("Progman", None)
    if progman:
        defview = user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None)
    if not defview:   # duvar kâğıdı slayt gösterisinde liste bir WorkerW'nin altına geçer
        worker = None
        while True:
            worker = user32.FindWindowExW(None, worker, "WorkerW", None)
            if not worker:
                break
            defview = user32.FindWindowExW(worker, None, "SHELLDLL_DefView", None)
            if defview:
                break
    if not defview:
        return None
    lv = user32.FindWindowExW(defview, None, "SysListView32", None)
    return lv if lv and user32.IsWindowVisible(lv) else None


def desktop_icon_count() -> int | None:
    """Masaüstü simge sayısı: yalnızca LVM_GETITEMCOUNT (Explorer belleğine yazmadan, ucuz). Okunamazsa None."""
    try:
        lv = _desktop_listview()
        if not lv:
            return 0
        res = ctypes.c_size_t(0)
        ok = user32.SendMessageTimeoutW(lv, LVM_GETITEMCOUNT, 0, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK,
                                        ICON_MSG_TIMEOUT_MS, ctypes.byref(res))
        return int(res.value) if ok else None
    except Exception as exc:  # noqa: BLE001
        log.info("Simge sayısı okunamadı: %s", exc)
        return None


def desktop_icon_rects() -> list[tuple[int, int, int, int]]:
    """Masaüstündeki tüm simgelerin (etiket dahil) ekran dikdörtgenleri: (sol, üst, sağ, alt), FİZİKSEL piksel.
    Liste explorer.exe'nin içinde olduğundan: LVM_GETITEMRECT'in RECT'i o işlemin belleğine yazması gerekir
    (VirtualAllocEx), sonuç ReadProcessMemory ile okunur. Herhangi bir hatada (explorer meşgul, yetki yok, simgeler
    gizli) [] döner, asla istisna fırlatmaz. Bloklayabilir (en çok ~1,5 sn): GUI iş parçacığından çağırma."""
    handle = remote = None
    try:
        lv = _desktop_listview()
        if not lv:
            return []
        deadline = time.monotonic() + ICON_QUERY_BUDGET
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(lv, ctypes.byref(pid))
        if not pid.value:
            return []
        res = ctypes.c_size_t(0)

        def send(msg: int, wparam: int, lparam: int) -> int | None:
            ok = user32.SendMessageTimeoutW(lv, msg, wparam, lparam, SMTO_ABORTIFHUNG | SMTO_BLOCK,
                                            ICON_MSG_TIMEOUT_MS, ctypes.byref(res))
            return res.value if ok else None

        count = send(LVM_GETITEMCOUNT, 0, 0)
        if not count:
            return []
        count = min(int(count), MAX_ICONS)
        handle = kernel32.OpenProcess(PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE
                                      | PROCESS_QUERY_INFORMATION, False, pid.value)
        if not handle:
            log.info("Masaüstü simge listesi işlemi açılamadı (hata %s)", ctypes.get_last_error())
            return []
        remote = kernel32.VirtualAllocEx(handle, None, ctypes.sizeof(wintypes.RECT), MEM_COMMIT | MEM_RESERVE,
                                         PAGE_READWRITE)
        if not remote:
            return []
        out = []
        moved = ctypes.c_size_t(0)
        for i in range(count):
            if time.monotonic() > deadline:
                log.info("Masaüstü simge sorgusu süreyi aştı")
                return []
            rc = wintypes.RECT(LVIR_BOUNDS, 0, 0, 0)   # left = LVIR_BOUNDS: istenen dikdörtgen türü
            if not kernel32.WriteProcessMemory(handle, remote, ctypes.byref(rc), ctypes.sizeof(rc), ctypes.byref(moved)):
                return []
            if not send(LVM_GETITEMRECT, i, remote):
                continue
            if not kernel32.ReadProcessMemory(handle, remote, ctypes.byref(rc), ctypes.sizeof(rc), ctypes.byref(moved)):
                return []
            if rc.right <= rc.left or rc.bottom <= rc.top:
                continue
            pts = (wintypes.POINT * 2)(wintypes.POINT(rc.left, rc.top), wintypes.POINT(rc.right, rc.bottom))
            user32.MapWindowPoints(lv, None, pts, 2)   # liste istemci koordinatı -> ekran
            out.append((pts[0].x, pts[0].y, pts[1].x, pts[1].y))
        return out
    except Exception as exc:  # noqa: BLE001 - simge algılama asla uygulamayı düşürmesin
        log.info("Masaüstü simgeleri okunamadı: %s", exc)
        return []
    finally:
        if remote and handle:
            kernel32.VirtualFreeEx(handle, remote, 0, MEM_RELEASE)
        if handle:
            kernel32.CloseHandle(handle)


def _nearest_free(rect: tuple[float, float, float, float], obstacles: list[tuple[float, float, float, float]],
                  area: tuple[float, float, float, float], step: int = 16, margin: float = 8) -> tuple[int, int]:
    """Saf hesap (Win32'siz): rect=(x, y, genişlik, yükseklik); engeller ve area=(sol, üst, sağ, alt) aynı birimde.
    rect (her yanına margin eklenerek) hiçbir engele değmiyorsa aynen döner; değiyorsa area içinde, 'step' ızgarasında
    mevcut konuma en yakın boş konumu verir. Boş yer yoksa ya da area'ya sığmıyorsa mevcut konum kalır."""
    x, y, w, h = rect
    x0, y0 = int(round(x)), int(round(y))
    if not obstacles:
        return x0, y0

    def hits(cx: float, cy: float) -> bool:
        l, t, r, b = cx - margin, cy - margin, cx + w + margin, cy + h + margin
        return any(l < o[2] and r > o[0] and t < o[3] and b > o[1] for o in obstacles)

    if not hits(x, y):
        return x0, y0
    left, top, right, bottom = area
    max_x, max_y = right - w, bottom - h
    if max_x < left or max_y < top:
        return x0, y0

    def axis(cur: float, lo: float, hi: float, st: int) -> list[int]:
        vals = {math.ceil(lo), math.floor(hi)}   # çalışma alanının içinde kalan uç değerler
        k = 0
        while cur - k * st >= lo or cur + k * st <= hi:
            for v in (cur - k * st, cur + k * st):
                if lo <= v <= hi:
                    vals.add(int(round(v)))
            k += 1
        return sorted(vals)

    # Arama alanı çalışma alanıyla sınırlı; aday sayısı da ~3000'i geçmesin (büyük ekranda ızgara seyreltilir)
    while True:
        xs, ys = axis(x, left, max_x, step), axis(y, top, max_y, step)
        if len(xs) * len(ys) <= MAX_CANDIDATES or step >= 512:
            break
        step *= 2
    cands = [(cx, cy) for cx in xs for cy in ys]
    cands.sort(key=lambda c: (c[0] - x) ** 2 + (c[1] - y) ** 2)
    for cx, cy in cands:
        if not hits(cx, cy):
            return cx, cy
    return x0, y0


MAX_CANDIDATES = 3000


def _monitor_scales() -> list[tuple[tuple[int, int, int, int], float]]:
    """Her ekranın fiziksel dikdörtgeni ve DPI ölçeği; tek tur EnumDisplayMonitors (simge başına değil)."""
    found = []

    def each(mon, _hdc, _rect, _lp):
        info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        if user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            dx, dy = wintypes.UINT(96), wintypes.UINT(96)
            try:
                ctypes.windll.shcore.GetDpiForMonitor(wintypes.HMONITOR(mon), 0, ctypes.byref(dx), ctypes.byref(dy))
            except OSError:
                pass
            r = info.rcMonitor
            found.append(((r.left, r.top, r.right, r.bottom), (dx.value or 96) / 96))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(each), 0)
    return found


def _scale_at(px: float, py: float, monitors=None) -> float:
    """Fiziksel ekran noktasındaki ekranın DPI ölçeği (önceden alınmış ekran listesiyle ucuz)."""
    monitors = _monitor_scales() if monitors is None else monitors
    return next((sc for (l, t, r, b), sc in monitors if l <= px < r and t <= py < b),
                monitors[0][1] if monitors else 1.0)


def avoid_icons(x: int, y: int, w: int, h: int) -> tuple[int, int]:
    """Widget (mantıksal piksel) masaüstü simgelerine biniyorsa, aynı ekranın çalışma alanında en yakın boş
    konumu döndürür; binmiyorsa, simge yoksa ya da yer bulunamazsa (x, y) aynen. Bloklayabilir: iş parçacığından çağır."""
    try:
        icons = desktop_icon_rects()
        if not icons:
            return x, y
        cx, cy = x + w / 2, y + h / 2
        areas = work_areas()
        area = next(((a[0], a[1], a[2], a[3]) for a in areas if a[0] <= cx < a[2] and a[1] <= cy < a[3]), None)
        if area is None:
            return x, y
        obstacles = []
        monitors = _monitor_scales()   # bir kez; her simge için yeniden sayılmaz
        for l, t, r, b in icons:
            s = _scale_at((l + r) / 2, (t + b) / 2, monitors)
            obstacles.append((l / s, t / s, r / s, b / s))   # fiziksel -> mantıksal
        return _nearest_free((x, y, w, h), obstacles, area)
    except Exception as exc:  # noqa: BLE001
        log.info("Simge kaçınma hesaplanamadı: %s", exc)
        return x, y
