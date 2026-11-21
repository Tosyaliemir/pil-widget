"use strict";
// "Pil Kontrol" penceresi: cihaz listesi, seçili cihazın 24 saatlik pil grafiği; masaüstü widget'ı, görev çubuğu ve genel ayarlar.
// Veri Python'dan yayınla gelir (window.onDevices / onPrefs).

const $ = (s) => document.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let bridge = null;   // pencere işlemleri (her zaman gerçek pywebview api)
let data = null;     // veri kaynağı (--demo ise demo.js)
let devs = { devices: [], error: "" };
let prefs = { size: "nano", theme: "auto", locked: false, low_notify: true, autostart: false,
  widget_on: true, taskbar: "kapali", taskbar_pos: "sol" };
const THEMES = ["auto", "dark", "light"];
const Bat = { key: null, history: [] };

const shown = () => devs.devices.filter(Cihaz.visible);
const current = () => devs.devices.find((d) => d.key === Bat.key && Cihaz.visible(d)) || null;

async function loadHistory() {
  const key = Bat.key;
  if (!key || !data?.get_device_history) { Bat.history = []; drawDetail(); return; }
  let h;
  try { h = await data.get_device_history(key, 24); } catch { h = []; }
  if (key !== Bat.key) return;   // bu arada başka cihaz seçildi
  Bat.history = h || [];
  drawDetail();
}

function selectDevice(key) {
  if (key === Bat.key) return;
  Bat.key = key;
  Bat.history = [];
  renderList();
  loadHistory();
}

function renderList() {
  const list = shown();
  // Seçili cihaz yoksa/kaybolduysa ilk görünene geç
  if (!list.some((d) => d.key === Bat.key)) {
    Bat.key = list[0]?.key ?? null;
    Bat.history = [];
    loadHistory();
  }
  const html = list.map((d) => {
    const sub = [d.via, Cihaz.stateText(d)].filter(Boolean).join(" · ");
    const title = `${Cihaz.KIND_NAMES[d.kind] || "Cihaz"}: ${d.name}${d.detail ? ` (${d.detail})` : ""}`;
    return `<li class="${Cihaz.meta(d).cls} ${d.key === Bat.key ? "sel" : ""}" data-key="${esc(d.key)}" tabindex="0" title="${esc(title)}">
      ${Cihaz.icon(d)}
      <span class="nm"><b>${esc(d.name)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</span>
      ${Cihaz.meta(d).isCharging ? Cihaz.bolt : ""}${Cihaz.ring(d.percent)}<span class="pct num">${esc(Cihaz.pctText(d))}</span>
    </li>`;
  }).join("") || '<li class="empty">Bağlı kablosuz cihaz yok</li>';
  const host = $("#batlist");
  if (host.dataset.html !== html) {
    host.dataset.html = html;
    host.innerHTML = html;
    $$("li[data-key]", host).forEach((li) => {
      li.addEventListener("click", () => selectDevice(li.dataset.key));
      li.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectDevice(li.dataset.key); }
      });
    });
  }
  $("#bat-err").hidden = !devs.error;
  $("#bat-err").textContent = devs.error ? `${devs.error}.` : "";
  drawDetail();
}

function drawDetail() {
  const d = current();
  $("#detail").hidden = !d;
  if (!d) return;
  const lvl = d.percent >= 0 ? d.percent : null;
  const live = d.connected && !d.stale && !d.asleep;
  $("#bat-name").textContent = d.name;
  const big = $("#bat-big");
  big.textContent = Cihaz.pctText(d);
  const m = Cihaz.meta(d);
  big.className = `big num ${m.cls}`;
  const est = m.isSleeping ? null : Cihaz.estimate(Bat.history, lvl, m.isCharging);
  $("#bat-sub").textContent = m.isSleeping ? Cihaz.stateText(d)
    : m.isCharging ? "şarj oluyor"
    : est ? `tahminen ${Math.round(est)} saat kaldı`
    : lvl != null && lvl <= Cihaz.LOW ? "şarj etmeyi unutma" : Cihaz.stateText(d);

  const now = Date.now() / 1000, from = now - 24 * 3600;
  const X = (t) => ((t - from) / (now - from)) * 400;
  const Y = (v) => 112 - v * 1.04;
  let pts = Bat.history.filter((s) => s[0] >= from);
  if (lvl != null && live) pts = [...pts, [now, lvl, d.charging ? 1 : 0]];
  let html = "";
  for (const v of [0, 50, 100]) html += `<line class="grid" x1="0" x2="400" y1="${Y(v)}" y2="${Y(v)}"/>`;
  if (pts.length >= 2) {
    for (let i = 0; i < pts.length - 1; i++) {
      if (pts[i][2]) html += `<rect class="chg" x="${X(pts[i][0]).toFixed(1)}" y="0" width="${Math.max(1, X(pts[i + 1][0]) - X(pts[i][0])).toFixed(1)}" height="112"/>`;
    }
    const line = pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    html += `<path class="area" d="${line}L${X(pts.at(-1)[0]).toFixed(1)},112L${X(pts[0][0]).toFixed(1)},112Z"/>`;
    html += `<path class="line" d="${line}"/>`;
  }
  $("#bat-chart").innerHTML = html;
  $("#bat-axis").innerHTML = "<span>24 sa önce</span><span>12 sa önce</span><span>şimdi</span>";
  $("#bat-empty").hidden = pts.length >= 3;
}

function renderPrefs() {
  // Bölümlü seçiciler: <div class="seg" data-seg="ayar"> içindeki düğmeler data-v taşır
  $$(".seg[data-seg]").forEach((seg) => {
    const btns = $$("button", seg), vals = btns.map((b) => b.dataset.v);
    const cur = vals.includes(prefs[seg.dataset.seg]) ? prefs[seg.dataset.seg] : vals[0];
    seg.style.setProperty("--i", vals.indexOf(cur));
    btns.forEach((b) => b.setAttribute("aria-checked", String(b.dataset.v === cur)));
  });
  document.documentElement.dataset.theme = THEMES.includes(prefs.theme) ? prefs.theme : "auto";
  $$("input[data-pref]").forEach((c) => { c.checked = !!prefs[c.dataset.pref]; });
  // Bağlı satırlar: widget kapalıyken boyut/tema/kilit, görev çubuğu kapalıyken konum soluk ve tıklanamaz
  $$("[data-needs]").forEach((row) => {
    const v = prefs[row.dataset.needs];
    const off = v === false || v === "kapali";
    row.classList.toggle("dim", off);
    row.inert = off;
  });
}

function showPrefError(msg) {
  const el = $("#pref-err");
  if (!el) return;
  el.hidden = !msg;
  el.textContent = msg || "";
}

async function setPref(key, value) {
  const prev = { ...prefs };
  showPrefError("");
  prefs[key] = value;   // iyimser güncelle
  renderPrefs();
  let r;
  try { r = await data.set_pref(key, value); } catch { r = null; }
  if (r?.prefs) prefs = { ...prefs, ...r.prefs };
  else if (!r || r.ok === false) prefs = prev;
  if (r && r.ok === false && r.error) showPrefError(r.error);
  else if (!r) showPrefError("Ayar kaydedilemedi.");
  renderPrefs();
}

window.onDevices = (p) => { if (data === bridge) { devs = p || devs; renderList(); } };
window.onPrefs = (p) => { prefs = { ...prefs, ...p }; renderPrefs(); };

$("#btn-refresh").addEventListener("click", async (e) => {
  const b = e.currentTarget;
  b.disabled = true;
  try { devs = await data.refresh_devices(); renderList(); loadHistory(); } catch { /* yok say */ }
  finally { setTimeout(() => (b.disabled = false), 1500); }
});
$$(".seg[data-seg] button").forEach((b) => b.addEventListener("click", () => setPref(b.closest(".seg").dataset.seg, b.dataset.v)));
$$("input[data-pref]").forEach((c) => c.addEventListener("change", () => setPref(c.dataset.pref, c.checked)));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") bridge?.hide_details?.(); });

async function start(src) {
  data = src;
  prefs = { ...prefs, ...(await data.get_prefs()) };
  devs = await data.get_devices();
  renderPrefs();
  renderList();
  setInterval(loadHistory, 5 * 60 * 1000);   // seçili cihazın geçmişini tazele
  if (data !== bridge) setInterval(async () => { devs = await data.get_devices(); renderList(); }, 30000);
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
// Tarayıcıda tasarım önizlemesi: cihazlar.html?demo
if (location.search.includes("demo")) loadDemo(location.search.slice(1));
