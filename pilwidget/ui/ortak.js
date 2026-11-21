// Ana pencere ve widget'ın ortak cihaz yardımcıları: SVG simgeler, renk durumu (meta), kalan süre tahmini.
"use strict";

const Cihaz = (() => {
  const LOW = 15;   // bu ve altı kırmızı
  const MID = 30;   // bu ve altı kehribar

  // Durum renkleri (tasarım kiti). CSS tarafında aynı değerler --ok/--mid/--low/--chg/--slp olarak durur.
  const COLORS = { ok: "#10B981", mid: "#F59E0B", low: "#EF4444", chg: "#38BDF8", slp: "#64748B" };
  const CHG_BAR = "linear-gradient(90deg, #0284C7, #38BDF8)";

  // Çizgi simgeler: tek çizgi, yuvarlak uç, küçük aksan (.acc dolgu / .acc-s çizgi, rengi --acc'den gelir).
  // 24x24 (widget ve liste simgeleri)
  const ICONS24 = {
    overear: '<path d="M4.5 14V12a7.5 7.5 0 0 1 15 0v2" stroke-width="1.75"/><rect x="3.5" y="12.5" width="3.5" height="6.5" rx="1.75" stroke-width="1.65"/><rect x="17" y="12.5" width="3.5" height="6.5" rx="1.75" stroke-width="1.65"/><circle class="acc" cx="18.75" cy="15.75" r="0.8" stroke="none"/>',
    inear: '<path d="M9.5 9.5C9.5 7.567 7.933 6 6 6a2.5 2.5 0 0 0-2.5 2.5v2a2 2 0 0 0 2 2h1v5a1 1 0 0 0 2 0v-5.7c.62-.62 1-1.42 1-2.3Z" stroke-width="1.65"/><path d="M14.5 9.5C14.5 7.567 16.067 6 18 6a2.5 2.5 0 0 1 2.5 2.5v2a2 2 0 0 1-2 2h-1v5a1 1 0 0 1-2 0v-5.7c-.62-.62-1-1.42-1-2.3Z" stroke-width="1.65"/><circle class="acc" cx="6.2" cy="9.2" r="0.85" stroke="none"/><circle class="acc" cx="17.8" cy="9.2" r="0.85" stroke="none"/>',
    mouse: '<rect x="6.5" y="3.5" width="11" height="17" rx="5.5" stroke-width="1.75"/><path class="acc-s" d="M12 7v3.5" stroke-width="1.9"/>',
    gamepad: '<path d="M6.5 7.5h11c1.9 0 3.4 1.3 3.8 3.2l.7 4.5c.4 2.2-1.3 4.1-3.5 4.1-1.2 0-2.3-.6-2.9-1.6L14.5 16h-5l-1.1 1.7c-.6 1-1.7 1.6-2.9 1.6-2.2 0-3.9-1.9-3.5-4.1l.7-4.5c.4-1.9 1.9-3.2 3.8-3.2Z" stroke-width="1.7"/><path d="M6.5 11.75h3M8 10.25v3" stroke-width="1.6"/><circle class="acc" cx="16.5" cy="11.75" r="1.15" stroke="none"/>',
    keyboard: '<rect x="2.5" y="6.5" width="19" height="11" rx="2.5" stroke-width="1.75"/><path d="M6.5 10.5h.01M10 10.5h.01M13.5 10.5h.01M8 14h6" stroke-width="1.9"/><circle class="acc" cx="17.5" cy="10.5" r="0.95" stroke="none"/>',
    phone: '<rect x="6.5" y="2.5" width="11" height="19" rx="3" stroke-width="1.75"/><path d="M10.5 18.5h3" stroke-width="1.65"/><circle class="acc" cx="12" cy="5.6" r="0.85" stroke="none"/>',
    other: '<rect x="3" y="7.5" width="16" height="9" rx="3" stroke-width="1.75"/><path d="M21.5 10.5v3" stroke-width="1.75"/><path class="acc-s" d="M7.5 12h.01M11 12h.01" stroke-width="2.1"/>',
  };
  // 16x16 (mini liste ve küçük yerler)
  const ICONS16 = {
    overear: '<path d="M2.8 9.2V7.6a5.2 5.2 0 0 1 10.4 0v1.6" stroke-width="1.55"/><rect x="2" y="8" width="2.5" height="5" rx="1.25" stroke-width="1.45"/><rect x="11.5" y="8" width="2.5" height="5" rx="1.25" stroke-width="1.45"/><circle class="acc" cx="12.75" cy="10.5" r="0.6" stroke="none"/>',
    inear: '<circle cx="5.2" cy="5.4" r="2.2" stroke-width="1.5"/><path d="M3.8 7.2v5" stroke-width="1.5"/><circle cx="10.8" cy="5.4" r="2.2" stroke-width="1.5"/><path d="M12.2 7.2v5" stroke-width="1.5"/><circle class="acc" cx="5.2" cy="5.4" r="0.7" stroke="none"/><circle class="acc" cx="10.8" cy="5.4" r="0.7" stroke="none"/>',
    mouse: '<rect x="4.5" y="1.8" width="7" height="12.4" rx="3.5" stroke-width="1.5"/><path class="acc-s" d="M8 4.4v2.4" stroke-width="1.7"/>',
    gamepad: '<path d="M4.2 4.8h7.6c1.3 0 2.3.9 2.6 2.2l.6 3.2c.3 1.5-.9 2.8-2.4 2.8-.8 0-1.5-.4-1.9-1.1l-.8-1.2H6.1l-.8 1.2c-.4.7-1.1 1.1-1.9 1.1-1.5 0-2.7-1.3-2.4-2.8L1.6 7c.3-1.3 1.3-2.2 2.6-2.2Z" stroke-width="1.5"/><path d="M4.4 7.8h2M5.4 6.8v2" stroke-width="1.35"/><circle class="acc" cx="11.2" cy="7.8" r="0.95" stroke="none"/>',
    keyboard: '<rect x="1.5" y="3.8" width="13" height="8.4" rx="2" stroke-width="1.5"/><path d="M4.5 7h.01M7.5 7h.01M5 9.6h4.5" stroke-width="1.6"/><circle class="acc" cx="11" cy="7" r="0.85" stroke="none"/>',
    phone: '<rect x="4.5" y="1.5" width="7" height="13" rx="2" stroke-width="1.5"/><path d="M7 12.2h2" stroke-width="1.5"/><circle class="acc" cx="8" cy="3.9" r="0.65" stroke="none"/>',
    other: '<rect x="1.5" y="4.8" width="11" height="6.4" rx="2" stroke-width="1.5"/><path d="M14.5 6.8v2.4" stroke-width="1.5"/><path class="acc-s" d="M5 8h.01M8 8h.01" stroke-width="1.7"/>',
  };

  const KIND_NAMES = { headset: "Kulaklık", mouse: "Fare", keyboard: "Klavye", gamepad: "Kumanda", phone: "Telefon", other: "Cihaz" };

  /** Cihazın L/R/kutu değerleri ("L 80%, R 75%, case 40%"); yoksa null. */
  function pods(d) {
    const s = String((d && d.detail) || "");
    const pick = (re) => { const m = s.match(re); return m ? Number(m[1]) : null; };
    const p = { l: pick(/\bL\s*:?\s*(\d{1,3})\s*%/i), r: pick(/\bR\s*:?\s*(\d{1,3})\s*%/i), box: pick(/\b(?:case|kutu)\s*:?\s*(\d{1,3})\s*%/i) };
    return p.l == null && p.r == null && p.box == null ? null : p;
  }

  /** Simge türü: overear | inear | mouse | gamepad | keyboard | phone | other. */
  function glyph(d) {
    const kind = d.kind;
    if (kind === "headset") {
      const p = pods(d);
      return /buds|airpods|earbuds|tws/i.test(d.name || "") || (p && (p.l != null || p.r != null)) ? "inear" : "overear";
    }
    return ICONS24[kind] ? kind : "other";
  }

  /** Cihaz simgesi. small=true: 16px set, aksi 24px set. Aksan rengi çevredeki --acc'den gelir. */
  function icon(d, small = false) {
    const g = glyph(d);
    const body = (small ? ICONS16 : ICONS24)[g];
    const v = small ? 16 : 24;
    return `<svg class="kind${small ? " k16" : ""}" viewBox="0 0 ${v} ${v}" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
  }

  /** Görünür mü? Yalnızca bağlı cihazlar gösterilir (uykudakiler bağlı sayılır, soluk görünür). */
  const visible = (d) => d && d.connected;

  /** Kitteki getDeviceVisualMeta karşılığı. cls: st-ok | st-mid | st-low | st-chg | st-slp | st-unk (CSS bunlara bağlı). */
  function meta(d) {
    const known = d.percent >= 0;
    const isSleeping = !!(d.asleep || d.stale);
    const isCharging = !!d.charging && !isSleeping;
    const isLow = !isSleeping && !isCharging && known && d.percent <= LOW;
    const isMedium = !isSleeping && !isCharging && !isLow && known && d.percent <= MID;
    let accent = COLORS.ok, barColor = COLORS.ok, cls = "st-ok";
    if (isSleeping) { accent = barColor = COLORS.slp; cls = "st-slp"; }
    else if (isCharging) { accent = COLORS.chg; barColor = CHG_BAR; cls = "st-chg"; }
    else if (isLow) { accent = barColor = COLORS.low; cls = "st-low"; }
    else if (isMedium) { accent = barColor = COLORS.mid; cls = "st-mid"; }
    else if (!known) { accent = barColor = COLORS.slp; cls = "st-unk"; }
    return { isSleeping, isCharging, isLow, isMedium, accent, barColor, cls };
  }

  function pctText(d) {
    if (d.percent >= 0) return `%${d.percent}`;
    if (d.levelText) return d.levelText;
    return "—";
  }

  function stateText(d) {
    if (d.asleep) return "uykuda";
    if (d.stale) return "cevap vermiyor";
    if (d.charging) return "şarj oluyor";
    return "";
  }

  /** Son şarjdan bu yana düşüş hızına göre kalan saat (en az 3 saat ve %3 düşüş gerekir). */
  function estimate(history, level, charging) {
    const h = history || [];
    if (h.length < 3 || charging) return null;
    let i = h.length - 1;
    while (i > 0 && !h[i - 1][2] && h[i - 1][1] >= h[i][1]) i--;
    const a = h[i], b = h[h.length - 1];
    const hours = (b[0] - a[0]) / 3600, drop = a[1] - b[1];
    if (hours < 3 || drop < 3) return null;
    return (level ?? b[1]) / (drop / hours);
  }

  const ring = (pct, size = 22) => {
    const v = pct >= 0 ? pct : 0;
    return `<svg class="mini-ring" viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true">
      <circle class="track" cx="12" cy="12" r="9.5"/>
      <circle class="val" cx="12" cy="12" r="9.5" pathLength="100" style="stroke-dasharray:${v} 100"/></svg>`;
  };
  const bolt = '<svg class="bolt-s" viewBox="0 0 12 16" aria-hidden="true"><path d="M7 1 2 9h4l-1 6 5-8H6z"/></svg>';

  return { LOW, MID, COLORS, icon, glyph, pods, KIND_NAMES, visible, meta, pctText, stateText, estimate, ring, bolt };
})();
