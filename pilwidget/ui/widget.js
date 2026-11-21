"use strict";
// Masaüstüne gömülü pil widget'ı. Veri Python'dan yayınla gelir (window.onDevices / onPrefs).
// Üç mod: nano (yan yana hücreler), mini (tek satırlık liste), detay (kartlar).

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const NOISE = { anc: "Gürültü engelleme", transparency: "Şeffaf duyma", off: "Gürültü kontrolü kapalı" };
const SIZES = ["nano", "mini", "detay"];
const SIZE_NAMES = { nano: "Nano", mini: "Mini", detay: "Detay" };
const THEMES = ["auto", "dark", "light"];
const THEME_NAMES = { auto: "Otomatik", dark: "Koyu", light: "Açık" };
// Üst çubuktaki tema simgeleri: Otomatik = yarım daire, Koyu = ay, Açık = güneş
const THEME_ICONS = {
  auto: '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none"/>',
  dark: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  light: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
};

let bridge = null;      // pencere işlemleri (her zaman gerçek pywebview api)
let data = null;        // veri kaynağı (--demo ise demo.js)
let devs = { devices: [], error: "" };
let prefs = { size: "nano", theme: "auto", locked: false };
const hist = {};        // key → { at, rows } (kalan süre tahmini için)

function sub(d) {
  const parts = [];
  if (d.via) parts.push(d.via);
  if (d.noise_mode && NOISE[d.noise_mode]) parts.push(NOISE[d.noise_mode]);
  const st = Cihaz.stateText(d);
  if (st) parts.push(st);
  else {
    const est = Cihaz.estimate(hist[d.key]?.rows, d.percent >= 0 ? d.percent : null, d.charging);
    if (est) parts.push(`~${Math.round(est)} sa kaldı`);
  }
  return parts.join(" · ");
}

const bar = (d) => `<div class="track"><i style="width:${Math.max(0, Math.min(100, d.percent))}%"></i></div>`;
const tip = (d) => `${d.name} — ${Cihaz.pctText(d)}${d.detail ? ` (${d.detail})` : ""}`;

function podsLine(d) {
  const p = Cihaz.pods(d);
  if (!p) return "";
  const parts = [];
  if (p.l != null) parts.push(`<span>L ${p.l}%</span>`);
  if (p.r != null) parts.push(`<span>R ${p.r}%</span>`);
  if (p.box != null) parts.push(`<span class="r">Kutu ${p.box}%</span>`);
  return `<div class="pods num">${parts.join("")}</div>`;
}

function itemHtml(d, size) {
  const m = Cihaz.meta(d);
  const pct = esc(Cihaz.pctText(d));
  const bolt = m.isCharging ? Cihaz.bolt : "";
  if (size === "mini") {
    return `<li class="${m.cls}" title="${esc(tip(d))}">${Cihaz.icon(d, true)}<span class="nm">${esc(d.name)}</span>${bar(d)}<span class="pct num">${pct}</span></li>`;
  }
  if (size === "detay") {
    const s = sub(d);
    return `<li class="${m.cls}" title="${esc(tip(d))}"><div class="r1">${Cihaz.icon(d)}
      <span class="nm"><b>${esc(d.name)}</b>${s ? `<span class="sub">${esc(s)}</span>` : ""}</span>
      <span class="pct num">${bolt}${pct}</span></div>${bar(d)}${podsLine(d)}</li>`;
  }
  return `<li class="${m.cls}" title="${esc(tip(d))}"><span class="ico">${Cihaz.icon(d)}${bolt}</span><span class="pct num">${pct}</span>${bar(d)}</li>`;
}

function render() {
  const w = $("#w");
  const size = SIZES.includes(prefs.size) ? prefs.size : "nano";
  const theme = THEMES.includes(prefs.theme) ? prefs.theme : "auto";
  document.documentElement.dataset.theme = theme;
  // Kilitli değilken widget'ın her yerinden sürüklenir (pywebview sürükleme bölgesi)
  w.className = `w ${size}${prefs.locked ? "" : " pywebview-drag-region"}`;

  const shown = devs.devices.filter(Cihaz.visible);
  const items = $("#items");
  items.className = `items${shown.length ? "" : " none"}`;
  items.style.setProperty("--cols", Math.min(Math.max(shown.length, 1), 4));
  items.innerHTML = shown.map((d) => itemHtml(d, size)).join("")
    || `<li class="empty">${devs.error ? "Cihazlar okunamadı" : "Bağlı cihaz yok"}</li>`;

  // Üst çubuk
  const active = shown.some((d) => !d.asleep && !d.stale);
  $("#dot").className = `dot${active ? " on" : ""}`;
  $("#dot").title = active ? "Aktif cihaz var" : "Aktif cihaz yok";
  $("#b-size-t").textContent = SIZE_NAMES[size];
  $("#b-size").title = `Boyut: ${SIZE_NAMES[size]} (değiştirmek için tıkla)`;
  $("#b-theme").innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${THEME_ICONS[theme]}</svg>`;
  $("#b-theme").title = `Tema: ${THEME_NAMES[theme]} (değiştirmek için tıkla)`;
  const lock = $("#b-lock");
  lock.setAttribute("aria-pressed", String(!!prefs.locked));
  lock.title = prefs.locked ? "Konum kilitli (açmak için tıkla)" : "Konumu kilitle";

  fit();
  if (size === "detay") loadHistories(shown);
}

/** Pencereyi içeriğe göre boyutlandır. */
function fit() {
  requestAnimationFrame(() => {
    const r = $("#w").getBoundingClientRect();
    const w = Math.ceil(r.width), h = Math.ceil(r.height);
    if (bridge?.widget_fit && (w !== fit.w || h !== fit.h)) {
      fit.w = w; fit.h = h;
      bridge.widget_fit(w, h);
    }
  });
}

async function loadHistories(list) {
  if (!data?.get_device_history) return;
  const now = Date.now();
  let changed = false;
  for (const d of list) {
    if (hist[d.key] && now - hist[d.key].at < 10 * 60 * 1000) continue;
    hist[d.key] = { at: now, rows: [] };
    try { hist[d.key].rows = await data.get_device_history(d.key, 24); changed = true; } catch { /* yok say */ }
  }
  if (changed) render();
}

/** Tercihi değiştir (Python kaydeder ve her iki pencereye yayınlar); ekranı hemen güncelle. */
async function setPref(key, value) {
  const prev = prefs;
  prefs = { ...prefs, [key]: value };
  render();
  try {
    const r = await data.set_pref(key, value);   // demoda yalnızca demo verisi; gerçek ayarlara yazılmaz
    if (r?.prefs) { prefs = { ...prefs, ...r.prefs }; render(); }
    else if (r && r.ok === false) { prefs = prev; render(); }
  } catch { prefs = prev; render(); }
}
const next = (list, cur) => list[(list.indexOf(cur) + 1) % list.length];

window.onDevices = (p) => { if (data === bridge) { devs = p || devs; render(); } };
window.onPrefs = (p) => { prefs = { ...prefs, ...p }; render(); };

// Düğmeler sürüklemeyi ve çift tıkla "Cihazlar" açmayı tetiklemesin
const ctl = $("#ctl");
for (const ev of ["mousedown", "dblclick"]) ctl.addEventListener(ev, (e) => e.stopPropagation());
$("#b-size").addEventListener("click", () => setPref("size", next(SIZES, SIZES.includes(prefs.size) ? prefs.size : "nano")));
$("#b-theme").addEventListener("click", () => setPref("theme", next(THEMES, THEMES.includes(prefs.theme) ? prefs.theme : "auto")));
$("#b-lock").addEventListener("click", () => setPref("locked", !prefs.locked));

// Demoda gerçek menü/pencere açılmaz (menü gerçek ayarları değiştirir)
const live = () => (data === bridge ? bridge : null);
document.addEventListener("contextmenu", (e) => { e.preventDefault(); live()?.widget_menu?.(); });
document.addEventListener("dblclick", () => live()?.open_details?.());

async function start(src) {
  data = src;
  prefs = { ...prefs, ...(await data.get_prefs()) };
  devs = await data.get_devices();
  render();
  document.fonts?.ready?.then(() => { fit.w = 0; fit(); });
  if (data !== bridge) setInterval(async () => { devs = await data.get_devices(); render(); }, 30000);
}

function loadDemo(query) {
  window.__demoQuery = query;
  const sc = document.createElement("script");
  sc.src = "demo.js";
  sc.onload = () => start(window.demoApi);
  document.body.appendChild(sc);
}

window.addEventListener("pywebviewready", async () => {
  bridge = window.pywebview.api;
  const demo = await bridge.get_demo();
  if (demo) loadDemo(demo); else start(bridge);
});
// Tarayıcıda tasarım önizlemesi: widget.html?demo
if (location.search.includes("demo")) loadDemo(location.search.slice(1));
