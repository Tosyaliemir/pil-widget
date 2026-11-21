// Yalnızca tasarım önizlemesi için: widget.html?demo / cihazlar.html?demo (ya da get_demo() doluysa)
(() => {
  const q = new URLSearchParams(window.__demoQuery || location.search);
  const now = Date.now() / 1000;
  const SIZES = ["nano", "mini", "detay"], THEMES = ["auto", "dark", "light"];
  const size = q.get("widget"), theme = q.get("theme");
  const prefs = { size: SIZES.includes(size) ? size : "nano", theme: THEMES.includes(theme) ? theme : "auto", locked: false, low_notify: true, autostart: true,
    widget_on: true, taskbar: q.get("taskbar") || "yuzde", taskbar_pos: "sol" };

  const dev = (key, name, via, kind, percent, extra = {}) => ({ key, name, via, kind, percent, levelText: "", detail: "",
    charging: false, asleep: false, connected: true, stale: false, graceSec: 120, vid: 0, ...extra });
  const list = [
    dev("m4", "MOMENTUM 4", "Bluetooth", "headset", 72, { noise_mode: "anc", precise: true }),
    dev("logi:4099", "Logitech G502 X PLUS", "LIGHTSPEED alıcısı", "mouse", 41, { charging: true, vid: 0x046d }),
    dev("bt:keychron", "Keychron K3 Pro", "Bluetooth", "keyboard", 58, { asleep: true }),
    dev("xinput:0", "Xbox Wireless Controller", "Bluetooth", "gamepad", 12, { vid: 0x045e }),
    dev("razer:00B7", "Razer DeathAdder V3 Pro", "Razer alıcısı", "mouse", 24, { vid: 0x1532 }),
    dev("bt:buds3", "Galaxy Buds3 Pro", "Bluetooth", "headset", 66, { detail: "L 70%, R 66%, case 92%" }),
    dev("bt:pixel", "Pixel 9", "Bluetooth", "phone", 83),
    dev("bt:kapali", "Kapalı kulaklık", "Bluetooth", "headset", -1, { connected: false }),
  ];

  // 24 saatlik makul geçmiş: yüzde saatte ~2 düşer; şarjdaki cihazda son birkaç saat yükselir
  const history = (d) => {
    if (d.percent < 0) return [];
    const out = [];
    for (let h = 24; h >= 0; h -= 0.5) {
      const t = now - h * 3600;
      let v, chg = 0;
      if (d.charging) { // 10 sa önceye kadar boşalır, sonra şarj olur
        if (h > 10) v = d.percent + 22 - (24 - h) * 1.4; else { v = d.percent - h * 2.6; chg = 1; }
      } else if (d.key === "m4" && h > 18) { v = 38 + (24 - h) * 14; chg = 1; } // gün başında şarj
      else v = d.percent + h * (d.key === "m4" ? 1.6 : 1.2);
      out.push([t, Math.max(3, Math.min(100, Math.round(v))), chg]);
    }
    return out;
  };
  const hist = Object.fromEntries(list.map((d) => [d.key, history(d)]));
  const payload = () => ({ devices: structuredClone(list), error: "", updated: Date.now() / 1000 });

  window.demoApi = {
    get_prefs: () => Promise.resolve({ ...prefs }),
    set_pref: (key, value) => {
      prefs[key] = value;
      window.onPrefs?.({ ...prefs });
      return Promise.resolve({ ok: true, prefs: { ...prefs } });
    },
    get_devices: () => Promise.resolve(payload()),
    refresh_devices: () => Promise.resolve(payload()),
    get_device_history: (key) => Promise.resolve(hist[key] || []),
  };
})();
