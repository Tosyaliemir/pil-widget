"""Pil Widget'ın motoru: tüm kablosuz cihazların pili Wireless Battery (`WirelessBattery.exe --json`) ile okunur.

Wireless Battery ayrı bir GPL-3.0 programıdır (bkz. CREDITS.md); burada yalnızca çalıştırılıp
çıktısı okunur. Ağ özelliğine hiç dokunulmaz.
"""

from __future__ import annotations

import json
import logging
import math
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

EXE_NAME = "WirelessBattery.exe"
KINDS = ("mouse", "headset", "keyboard", "gamepad", "phone", "other")
M4_KEY = "m4"  # Momentum Kontrol açıkken kulaklığın kaydı (Wireless Battery onu görmüyorsa)
STATUS_MAX_AGE = 7 * 60  # Momentum Kontrol durum.json'u 5 dakikada bir yeniler; bu kadar eskiyse (çökmüş) yok sayılır
SENNHEISER_VIDS = {0x0492, 0x1395, 0x3542}  # Sennheiser / Sonova / EPOS (gerçek çıktıda MOMENTUM 4'ün vid'i 0)


class WBError(Exception):
    """Wireless Battery çalıştırılamadı ya da çıktısı okunamadı."""


def find_exe() -> Path | None:
    """Önce PyInstaller paketinin içi (sys._MEIPASS/bin), sonra geliştirme klasörü (pilwidget/bin)."""
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "bin" / EXE_NAME)
    candidates.append(Path(__file__).resolve().parent / "bin" / EXE_NAME)
    return next((c for c in candidates if c.is_file()), None)


def _bool(v) -> bool:
    return v is True or v == 1


def _int(v, default: int = 0) -> int:
    """Bozuk değer (metin, liste, bool, NaN, sonsuz...) istisna fırlatmaz; varsayılan döner."""
    if isinstance(v, bool):
        return default
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return default


def parse_json(text: str) -> list[dict]:
    """`--json` çıktısını doğrular ve sadeleştirir. Bozuk çıktıda WBError."""
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise WBError(f"Bozuk JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise WBError("JSON bir dizi değil")
    out = []
    for d in raw:
        if not isinstance(d, dict) or not d.get("key"):
            continue
        pct = _int(d.get("percent", -1), -1)
        kind = d.get("kind") if d.get("kind") in KINDS else "other"
        out.append({
            "key": str(d["key"]),
            "name": str(d.get("name") or d["key"]),
            "via": str(d.get("via") or ""),
            "kind": kind,
            "percent": pct if 0 <= pct <= 100 else -1,
            "levelText": str(d.get("levelText") or ""),
            "detail": str(d.get("detail") or ""),
            "charging": _bool(d.get("charging")),
            "asleep": _bool(d.get("asleep")),
            "connected": d.get("connected", True) is not False,
            "millivolts": _int(d.get("millivolts")),
            "graceSec": max(0, _int(d.get("graceSec"))),
            "vid": _int(d.get("vid")),
        })
    return out


def is_momentum(d: dict) -> bool:
    """Wireless Battery'nin gördüğü cihaz MOMENTUM 4 mü?"""
    return "MOMENTUM 4" in d.get("name", "").upper() or d.get("vid") in SENNHEISER_VIDS


def apply_status(devices: list[dict], status: dict | None, now: float) -> list[dict]:
    """Momentum Kontrol açıksa kulaklığın kendi bağlantısından gelen daha hassas durumu (şarj, gürültü
    modu) Wireless Battery'nin MOMENTUM 4 kaydının yerine koyar ve onu listenin başına alır."""
    out = [dict(d) for d in devices]
    fresh, percent = False, 0
    if isinstance(status, dict) and status.get("connected") and status.get("battery") is not None:
        raw_bat = status["battery"]
        if not isinstance(raw_bat, bool):
            try:   # bozuk/eksik değerli durum.json sessizce yok sayılır
                percent = int(raw_bat)
                ts = float(status.get("t") or 0)
                age = now - ts
                fresh = 0 <= percent <= 100 and math.isfinite(ts) and -60 <= age <= STATUS_MAX_AGE
            except (TypeError, ValueError, OverflowError):
                fresh = False
    idx = next((i for i, d in enumerate(out) if is_momentum(d)), None)
    if fresh:
        base = out.pop(idx) if idx is not None else {
            "key": M4_KEY, "via": "Bluetooth", "kind": "headset", "levelText": "", "detail": "", "asleep": False,
            "connected": True, "stale": False, "millivolts": 0, "graceSec": 0, "vid": 0}
        base.update(name=str(status.get("name") or base.get("name") or "MOMENTUM 4"), percent=percent,
                    charging=bool(status.get("charging")), noise_mode=status.get("noise_mode"),
                    connected=True, stale=False, asleep=False, precise=True)
        out.insert(0, base)
    elif idx is not None:
        out.insert(0, out.pop(idx))
    return out


def run_wb(exe: Path | None, demo: bool = False, timeout: float = 15) -> list[dict]:
    """`WirelessBattery.exe --json` çalıştırır. Exe yoksa, zaman aşımında ya da hata kodunda WBError."""
    if exe is None or not Path(exe).is_file():
        raise WBError(f"{EXE_NAME} bulunamadı")
    args = [str(exe), "--json"] + (["--demo"] if demo else [])
    try:
        res = subprocess.run(args, capture_output=True, timeout=timeout, encoding="utf-8", errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise WBError(f"{EXE_NAME} {timeout:.0f} sn içinde cevap vermedi") from exc
    except OSError as exc:
        raise WBError(f"{EXE_NAME} çalıştırılamadı: {exc}") from exc
    if res.returncode != 0:
        raise WBError(f"{EXE_NAME} hata kodu {res.returncode}")
    return parse_json(res.stdout.strip() or "[]")


class DeviceMonitor:
    """Wireless Battery'yi ayrı bir iş parçacığında düzenli çalıştırır, son listeyi önbellekte tutar."""

    def __init__(self, on_change: Callable[[], None] | None = None, interval: int = 120,
                 exe: Path | None = None, demo: bool = False, runner=run_wb, clock=time.time) -> None:
        self.interval = interval
        self.exe = exe if exe is not None else find_exe()
        self.demo = demo
        self.error = ""
        self.updated = 0.0
        self._runner = runner
        self._clock = clock
        self._on_change = on_change
        self._cache: dict[str, dict] = {}   # key → {"dev": {...}, "seen": zaman, "seq": tur}
        self._lock = threading.Lock()
        self._stop = False
        self._thread: threading.Thread | None = None
        self._cond = threading.Condition()
        self._started = 0      # başlayan tur sayısı
        self._completed = 0    # bitmiş en son turun numarası (başlangıç sırasıyla)
        self._refresh_req = 0  # refresh() istek sayacı (Event wait/clear yarışı olmaz)
        self._poll_seq = 0     # başarılı tarama sırası (saat geri sıçrasa da stale doğru kalır)

    # -- tarama -------------------------------------------------------------
    def poll(self) -> None:
        """Bir tur: çalıştır, önbelleği güncelle."""
        with self._cond:
            self._started += 1
            number = self._started
        try:
            self._poll()
        finally:
            with self._cond:
                self._completed = number
                self._cond.notify_all()

    def _poll(self) -> None:
        try:
            found = self._runner(self.exe, self.demo)
            err = ""
        except WBError as exc:
            log.warning("Diğer cihazlar okunamadı: %s", exc)
            found, err = None, "Diğer cihazlar okunamadı"
        now = self._clock()
        with self._lock:
            self.error = err
            # Tur başarısızsa son geçerli liste olduğu gibi kalır.
            if found is not None:
                self.updated = now
                self._poll_seq += 1
                seq = self._poll_seq
                for d in found:
                    self._cache[d["key"]] = {"dev": d, "seen": now, "seq": seq}
                # Bu turda cevap vermeyenler graceSec > 0 ise o süre boyunca soluk (stale) kalır, sonra düşer.
                self._cache = {k: e for k, e in self._cache.items()
                               if e["seq"] == seq or (e["dev"]["graceSec"] > 0
                                                      and max(0.0, now - e["seen"]) <= e["dev"]["graceSec"])}
        if self._on_change:
            self._on_change()

    def devices(self) -> list[dict]:
        with self._lock:
            return [{**e["dev"], "stale": e["seq"] != self._poll_seq} for e in self._cache.values()]

    # -- iş parçacığı ---------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="cihaz-tarama")
        self._thread.start()

    def refresh(self, wait: float = 0) -> None:
        """Hemen yeni bir tur ister. wait>0 ise, bu istekten SONRA başlayan turun bitmesini en çok o kadar saniye
        bekler (GUI iş parçacığında çağırma)."""
        with self._cond:
            number = self._started
            self._refresh_req += 1
            self._cond.notify_all()
            if wait > 0 and self._thread is not None and self._thread.is_alive():
                self._cond.wait_for(lambda: self._completed > number or self._stop, timeout=wait)

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()

    def _loop(self) -> None:
        while True:
            with self._cond:
                if self._stop:
                    return
                seen_req = self._refresh_req
            try:
                self.poll()
            except Exception:  # noqa: BLE001 - tek bir hata tarama iş parçacığını öldürmesin
                log.exception("Cihaz taraması başarısız")
            with self._cond:
                self._cond.wait_for(lambda: self._stop or self._refresh_req > seen_req, timeout=self.interval)


# ---------------------------------------------------------------------------
# Pil geçmişi
# ---------------------------------------------------------------------------
class BatteryLog:
    """Cihaz başına pil seviyesi (en fazla 5 dakikada bir, 7 gün): {anahtar: [[zaman, %, şarj], ...]}.
    Diske en çok dakikada bir yazılır (WRITE_GAP); bekleyen veri flush() ile (çıkışta) hemen yazılır."""

    KEEP_SECONDS = 7 * 24 * 3600
    MIN_GAP = 300
    WRITE_GAP = 60

    def __init__(self, path: Path, read_json, write_json, clock=time.time) -> None:
        self._path = path
        self._write = write_json
        self._clock = clock
        raw = read_json(path, {})
        self.samples: dict[str, list[list]] = {}
        for k, v in (raw if isinstance(raw, dict) else {}).items():
            rows = [r for r in v if self._valid_row(r)] if isinstance(v, list) else []
            if rows:
                self.samples[str(k)] = rows
        self._lock = threading.Lock()
        self._dirty = False
        self._last_write = 0.0

    @staticmethod
    def _valid_row(r) -> bool:
        return (isinstance(r, list) and len(r) >= 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                            for x in r[:3]))

    def add(self, key: str, level: int | None, charging: bool | None) -> None:
        if level is None or level < 0:
            return
        now = int(self._clock())
        with self._lock:
            rows = self.samples.setdefault(key, [])
            last = rows[-1] if rows else None
            if not (last and now - last[0] < self.MIN_GAP and last[1] == level and bool(last[2]) == bool(charging)):
                rows.append([now, level, 1 if charging else 0])
                self.samples[key] = [s for s in rows if now - s[0] <= self.KEEP_SECONDS]
                self.samples = {k: v for k, v in self.samples.items() if v}
                self._dirty = True
            if self._dirty and now - self._last_write >= self.WRITE_GAP:
                self._flush_locked(now)

    def flush(self) -> None:
        """Bekleyen veriyi hemen yaz (çıkışta)."""
        with self._lock:
            if self._dirty:
                self._flush_locked(self._clock())

    def _flush_locked(self, now: float) -> None:
        self._last_write = now   # başarısız olsa da dakikada bir denenir
        try:
            self._write(self._path, self.samples)
            self._dirty = False
        except OSError as exc:
            log.warning("Pil geçmişi yazılamadı: %s", exc)

    def recent(self, key: str, hours: int = 24) -> list[list]:
        since = self._clock() - hours * 3600
        with self._lock:
            return [s for s in self.samples.get(key, []) if s[0] >= since]
