/* HomeDeck front-end shell. Apps register themselves; the shell owns navigation, state polling,
   idle screen, guest mode, night mode and toasts.

   APP CONTRACT (web/apps/<name>.js, loaded by index.html):
     HD.registerApp({
       id: "camera",                // matches the backend module NAME where applicable
       title: "Camera", icon: "camera", order: 30,   // icon = a name from HD.icon
       hidden: false,               // true = not on the app grid (settings-only or internal)
       guestHidden: true,           // hide in guest mode
       render(el) {...},            // build the app's DOM into el (called each time the app opens)
       update(state) {...},         // called every poll (~2 s) with the full /api/state while the app is open
       idleWidget(el, state) {...}, // optional: draw/refresh a small tile on the idle screen (called every poll)
       onEvent(name, data) {...}    // optional: server-pushed events (via state.events ring, see below)
     });
   Helpers:
     HD.state                       latest /api/state
     HD.config                      latest /api/config (general + every module's settings)
     HD.api(module, action, params) POST /api/<module>/<action>  -> promise(json)
     HD.saveConfig(partial)         POST /api/config with a partial dict (deep-merged server side)
     HD.toast(text, level, ms)      level: info|good|warning|serious|critical
     HD.popup({title, body, actions:[{label, onclick}]})   modal card (air-quality nudges, alarm ringing, ...)
     HD.openApp(id) / HD.showIdle()
     HD.fmtTime(date) / HD.units()  respect the clock and unit settings
     HD.isGuest()                   guest mode flag from general config
     HD.icon(name[, cls])           inline monoline SVG icon (see ICONS); app "icon" fields are icon names
     HD.KIOSK                       true when running on the device's own screen (/?kiosk=1); apps may set
                                    kioskHidden: true to exist only on phones (camera privacy, presence)
*/
window.HD = (() => {
  const apps = {};
  // Monoline SVG icon set (24x24, 1.75px stroke, round caps) so the UI never needs emoji.
  const ICONS = {
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "sun-max": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7z"/>',
    "moon-stars": '<path d="M18.5 15.2A7 7 0 0 1 8.8 5.5a7 7 0 1 0 9.7 9.7z"/><path d="M18 3v3M16.5 4.5h3M21 8v2M20 9h2"/>',
    "cloud": '<path d="M7.5 18.5h9.3a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 6.9 9.3a4.6 4.6 0 0 0 .6 9.2z"/>',
    "cloud-sun": '<path d="M9.5 19.5h8a3.5 3.5 0 0 0 .4-6.98A4.8 4.8 0 0 0 8.9 11.6a4 4 0 0 0 .6 7.9z"/><path d="M6 10.5A3.8 3.8 0 0 1 10 6.6M6.5 3v1.5M2.5 7h1.5M4 4.5l1 1"/>',
    "cloud-moon": '<path d="M9.5 19.5h8a3.5 3.5 0 0 0 .4-6.98A4.8 4.8 0 0 0 8.9 11.6a4 4 0 0 0 .6 7.9z"/><path d="M10.2 6.6A3 3 0 0 1 6.9 2.6a3.4 3.4 0 0 0 1 6.5"/>',
    "rain": '<path d="M7.5 15.5h9.3a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 6.9 6.3a4.6 4.6 0 0 0 .6 9.2z"/><path d="M9 18l-1 3M13 18l-1 3M17 18l-1 3"/>',
    "drizzle": '<path d="M7.5 15.5h9.3a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 6.9 6.3a4.6 4.6 0 0 0 .6 9.2z"/><path d="M9.5 18.5v1.5M13.5 18.5v1.5M17.5 18.5v1.5"/>',
    "snow": '<path d="M7.5 15.5h9.3a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 6.9 6.3a4.6 4.6 0 0 0 .6 9.2z"/><circle cx="9" cy="19.5" r=".6"/><circle cx="13" cy="19.5" r=".6"/><circle cx="17" cy="19.5" r=".6"/>',
    "fog": '<path d="M7.5 14h9.3a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 6.9 4.8a4.6 4.6 0 0 0 .6 9.2z"/><path d="M6 17.5h12M8 20.5h8"/>',
    "thunder": '<path d="M7.5 15.5h9.3a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 6.9 6.3a4.6 4.6 0 0 0 .6 9.2z"/><path d="M13 14l-2.5 4.5H13L11.5 22"/>',
    "wind": '<path d="M3 8h10.5a2.5 2.5 0 1 0-2.5-2.5M3 13h14.5a2.5 2.5 0 1 1-2.5 2.5M3 18h7a2 2 0 1 1-2 2"/>',
    "bike": '<circle cx="5.5" cy="17" r="3.5"/><circle cx="18.5" cy="17" r="3.5"/><path d="M5.5 17l4-8h6l3 8M9.5 9l2.5 5h4M13 5h3l1.5 4"/>',
    "bolt": '<path d="M13 2L5 13.5h6L10 22l9-11.5h-6z"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "timer": '<circle cx="12" cy="13.5" r="7.5"/><path d="M12 9.5v4l2.5 2M10 2h4M12 2v2"/>',
    "bell": '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5H4.5zM10 21a2 2 0 0 0 4 0"/>',
    "alarm": '<circle cx="12" cy="13" r="7.5"/><path d="M12 9v4l2.5 1.5M4 5l2.5-2M20 5l-2.5-2"/>',
    "note": '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M9 21h6"/>',
    "mic-off": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M9 21h6M4 4l16 16"/>',
    "camera": '<path d="M4 8.5h3l1.5-2.5h7L17 8.5h3a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 20 19.5H4A1.5 1.5 0 0 1 2.5 18v-8A1.5 1.5 0 0 1 4 8.5z"/><circle cx="12" cy="13.5" r="3.5"/>',
    "camera-off": '<path d="M4 8.5h3l1.5-2.5h7L17 8.5h3a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 20 19.5H4A1.5 1.5 0 0 1 2.5 18v-8A1.5 1.5 0 0 1 4 8.5z"/><circle cx="12" cy="13.5" r="3.5"/><path d="M3 3l18 18"/>',
    "bulb": '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M8.5 14.5A6 6 0 1 1 15.5 14.5c-.6.6-1 1.5-1 2.5h-5c0-1-.4-1.9-1-2.5z"/>',
    "news": '<path d="M4 5h13v14H6a2 2 0 0 1-2-2z"/><path d="M17 9h3v8a2 2 0 0 1-2 2"/><path d="M7 9h6M7 12h6M7 15h4"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6h.01M4 12h.01M4 18h.01"/>',
    "leaf": '<path d="M5 19c0-8 5-13 14-14-1 9-6 14-14 14z"/><path d="M5 19l8-8"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
    "chevron-left": '<path d="M15 5l-7 7 7 7"/>',
    "chevron-right": '<path d="M9 5l7 7-7 7"/>',
    "chevron-down": '<path d="M5 9l7 7 7-7"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 018 0v4"/>',
    "spotify": '<path fill="currentColor" stroke="none" d="M12 1.5C6.2 1.5 1.5 6.2 1.5 12S6.2 22.5 12 22.5 22.5 17.8 22.5 12 17.8 1.5 12 1.5zm4.8 15.2a.65.65 0 01-.9.22c-2.47-1.51-5.58-1.85-9.24-1.01a.65.65 0 11-.29-1.27c4-.92 7.44-.52 10.2 1.17.31.19.41.6.23.89zm1.29-2.86a.82.82 0 01-1.12.27c-2.83-1.74-7.14-2.24-10.49-1.22a.82.82 0 11-.47-1.57c3.82-1.16 8.57-.6 11.82 1.4.38.24.5.74.26 1.12zm.11-2.98C14.8 8.86 9.22 8.68 5.98 9.66a.98.98 0 11-.57-1.88c3.72-1.13 9.9-.91 13.8 1.4a.98.98 0 01-1.01 1.68z"/>',
    "youtube": '<path fill="currentColor" stroke="none" d="M22.6 6.9a2.8 2.8 0 00-1.95-1.98C18.9 4.4 12 4.4 12 4.4s-6.9 0-8.65.52A2.8 2.8 0 001.4 6.9 29 29 0 001 12a29 29 0 00.4 5.1 2.8 2.8 0 001.95 1.98c1.75.52 8.65.52 8.65.52s6.9 0 8.65-.52a2.8 2.8 0 001.95-1.98A29 29 0 0023 12a29 29 0 00-.4-5.1zM9.8 15.3V8.7l5.8 3.3-5.8 3.3z"/>',
    "wifi": '<path d="M2 8.5a16 16 0 0120 0M5.5 12a11 11 0 0113 0M9 15.5a5.5 5.5 0 016 0M12 19h.01"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "play": '<path d="M7 4.5v15l12-7.5z" fill="currentColor" stroke="none"/>',
    "pause": '<rect x="6" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none"/><rect x="14" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none"/>',
    "skip-back": '<path d="M6 5v14M19 5.5v13L9 12z" fill="currentColor" stroke="none"/><path d="M6 5v14"/>',
    "skip-forward": '<path d="M18 5v14M5 5.5v13L15 12z" fill="currentColor" stroke="none"/><path d="M18 5v14"/>',
    "shuffle": '<path d="M3 7h3.5l9 10H21M21 7h-5.5l-2 2.2M3 17h3.5l2-2.2M18.5 4.5L21 7l-2.5 2.5M18.5 14.5L21 17l-2.5 2.5"/>',
    "volume": '<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z"/><path d="M15.5 9a4.5 4.5 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11"/>',
    "volume-low": '<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z"/><path d="M15.5 9a4.5 4.5 0 0 1 0 6"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "home": '<path d="M3.5 11L12 4l8.5 7V20a1 1 0 0 1-1 1h-5v-6h-5v6h-5a1 1 0 0 1-1-1z"/>',
    "person": '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>',
    "map-pin": '<path d="M12 21.5s7-6.5 7-11.5a7 7 0 0 0-14 0c0 5 7 11.5 7 11.5z"/><circle cx="12" cy="10" r="2.5"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5"/>',
    "trash": '<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l.8 13h9.4l.8-13M10 11v6M14 11v6"/>',
    "waveform": '<path d="M4 12v1M8 8v8M12 5v14M16 8v8M20 11v2"/>',
    "drop": '<path d="M12 3.5s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    "thermometer": '<path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a3.5 3.5 0 1 1-4 0z"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "power": '<path d="M12 3v8M6.3 6.5a8 8 0 1 0 11.4 0"/>',
    "cloud-off": '<path d="M7.5 18.5h9.3a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 6.9 9.3a4.6 4.6 0 0 0 .6 9.2z"/><path d="M4 4l16 16"/>',
  };
  function icon(name, cls = "ic") {
    const d = ICONS[name] || ICONS["cloud"];
    return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  }
  // kiosk = the device's own screen (Chromium on the Pi loads /?kiosk=1). Apps with kioskHidden never show there.
  const KIOSK = new URLSearchParams(location.search).has("kiosk");
  const DEMO_MUSIC = new URLSearchParams(location.search).get("demo") === "music";   // visual check of the player, no Spotify needed
  const DEMO_ART = "data:image/svg+xml;utf8," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#e0703a"/><stop offset="1" stop-color="#3a2a5e"/></linearGradient></defs><rect width="400" height="400" fill="url(#g)"/><circle cx="200" cy="200" r="120" fill="none" stroke="rgba(255,255,255,.35)" stroke-width="18"/><circle cx="200" cy="200" r="28" fill="rgba(255,255,255,.85)"/></svg>');
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (KIOSK) document.documentElement.classList.add("kiosk");
  // never start a native image/link drag or a text selection on the panel: a drag is always a scroll
  document.addEventListener("dragstart", e => e.preventDefault(), true);
  document.addEventListener("selectstart", e => { if (!e.target.closest("input, textarea")) e.preventDefault(); }, true);
  const NODIM = new URLSearchParams(location.search).has("nodim");   // bench/testing: never apply the CSS dimmer
  let openedFromApps = false;
  let state = {}, config = {}, current = null, idleTimer = null, lastTouch = Date.now();
  const $ = (s, r = document) => r.querySelector(s);

  function setText(el, text) { if (el && el.textContent !== text) el.textContent = text; }
  function setHtml(el, html) { if (el && el.dataset.h !== html) { el.innerHTML = html; el.dataset.h = html; } }
  function registerApp(a) { apps[a.id] = a; if (document.readyState !== "loading") buildGrid(); }

  async function api(module, action, params = {}) {
    const r = await fetch(`/api/${module}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params) });
    return r.json();
  }
  async function saveConfig(partial) {
    const r = await fetch(`/api/config`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(partial) });
    const j = await r.json(); if (j.config) config = j.config; return j;
  }
  function isGuest() { return !!(config.general && config.general.guest_mode); }
  function units() { return (config.general && config.general.units) || "imperial"; }
  function fmtTime(d = new Date(), withSeconds = false) {
    const h24 = config.general && config.general.clock_24h;
    return d.toLocaleTimeString([], { hour: h24 ? "2-digit" : "numeric", minute: "2-digit", second: withSeconds ? "2-digit" : undefined, hour12: !h24 });
  }

  function toast(text, level = "info", ms = 4000) {
    const t = document.createElement("div"); t.className = `toast ${level}`; t.textContent = text;
    $("#toasts").appendChild(t); setTimeout(() => t.remove(), ms);
  }
  function popup({ title, body, actions = [{ label: "OK" }], level = "info" }) {
    const wrap = document.createElement("div"); wrap.className = "popup-wrap";
    wrap.innerHTML = `<div class="popup ${level}"><h3></h3><div class="pbody"></div><div class="pactions${actions.length === 2 ? "" : " stack"}"></div></div>`;
    $("h3", wrap).textContent = title; $(".pbody", wrap).innerHTML = body;
    for (const a of actions) { const b = document.createElement("button"); b.textContent = a.label; b.onclick = () => { wrap.remove(); a.onclick && a.onclick(); }; $(".pactions", wrap).appendChild(b); }
    document.body.appendChild(wrap); return wrap;
  }

  // iOS-style app colours: each app owns one calm solid; used for its switcher squircle, page icon and primary buttons
  const APP_COLORS = { weather: "#4aa3ff", sensors: "#34c759", spotify: "#1db954", youtube: "#ff0033", games: "#ff2d55", flights: "#64d2ff", countdowns: "#af52de", guest: "#a2845e", transit: "#ff375f", sleep: "#5e5ce6", leds: "#ffb020", alarms: "#ff9f0a", timers: "#ff6b35",
    calendar: "#ff3b30", reminders: "#5e5ce6", lists: "#5ac8fa", bikes: "#2bb0a0", news: "#8e8e93", fan: "#30b0c7", camera: "#1c1c1e",
    presence: "#6e6e73", settings: "#8e8e93", voice: "#0a84ff" };
  const appColor = a => (a && (a.color || APP_COLORS[a.id])) || "#636366";
  function appIcon(a, cls = "ic") { return `<span class="${cls}" style="--app:${appColor(a)}">${ICONS[a.icon] ? icon(a.icon, "") : (a.icon || "")}</span>`; }
  function buildGrid() {
    const g = $("#appgrid"); if (!g) return; g.innerHTML = "";
    Object.values(apps).filter(a => !a.hidden && !(isGuest() && a.guestHidden) && !(KIOSK && a.kioskHidden)).sort((a, b) => (a.order || 99) - (b.order || 99)).forEach(a => {
      const b = document.createElement("button"); b.className = "appbtn"; b.innerHTML = `${appIcon(a)}<span>${a.title}</span>`;
      b.onclick = () => openApp(a.id); g.appendChild(b);
    });
  }
  // Sheet + page motion helpers (transforms/opacity only). body.in-app tells the home style to darken its backdrop.
  function sheetOpen() { const s = $("#apps"); s.classList.remove("hidden", "closing"); document.body.classList.add("in-app"); requestAnimationFrame(() => requestAnimationFrame(() => s.classList.add("in"))); }
  function sheetClose(then) { const s = $("#apps"); if (s.classList.contains("hidden")) { then && then(); return; }
    s.classList.remove("in"); s.classList.add("closing"); setTimeout(() => { s.classList.add("hidden"); s.classList.remove("closing"); then && then(); }, 230); }
  function pageClose(then) { const v = $("#appview"); if (v.classList.contains("hidden")) { then && then(); return; }
    v.classList.add("leaving"); setTimeout(() => { v.classList.add("hidden"); v.classList.remove("leaving"); v.innerHTML = ""; then && then(); }, 190); }
  function openApp(id) {
    undismissNowPlaying();
    openedFromApps = !$("#apps").classList.contains("hidden");   // back returns to wherever we came from
    const a = apps[id]; if (!a || (KIOSK && a.kioskHidden) || (isGuest() && a.guestHidden)) return;
    current = id; $("#idle").classList.add("hidden"); $("#apps").classList.add("hidden"); $("#apps").classList.remove("in"); document.body.classList.add("in-app");
    const v = $("#appview"); v.classList.remove("hidden"); v.style.setProperty("--app-accent", appColor(a));
    v.innerHTML = `<header class="apphead"><button class="back" id="backbtn" aria-label="Back">${icon("chevron-left", "")}</button>${appIcon(a, "appic")}<h2>${a.title}</h2></header><div class="appbody" id="appbody"></div>`;
    $("#backbtn").onclick = () => { if (openedFromApps) showApps(); else showIdle(); };
    try { a.render($("#appbody")); a.update && a.update(state); } catch (e) { $("#appbody").innerHTML = `<p class="err">${e}</p>`; console.error(e); }
  }
  function showApps() { current = null; undismissNowPlaying(); buildGrid(); const fromPage = !$("#appview").classList.contains("hidden");
    $("#idle").classList.remove("hidden"); renderIdle();          // the sheet slides up over the home screen
    if (fromPage) pageClose(() => sheetOpen()); else sheetOpen(); }
  function showIdle() { current = null; document.body.classList.remove("in-app"); $("#idle").classList.remove("hidden"); renderIdle(); pageClose(); sheetClose(); }

  // ---- Now-playing home screen: while music plays (or paused < 2 min) the idle screen becomes a player.
  let npLastPlaying = 0, npKey = "", npVolDrag = false;
  const npMmss = ms => { if (ms == null) return "0:00"; const t = Math.max(0, Math.floor(ms / 1000)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
  const npEsc = v => String(v == null ? "" : v).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let npDismissed = false;   // owner left the music screen; comes back automatically when playback resumes
  function musicMode() {
    const now = state.spotify && state.spotify.now;
    if (now && now.playing) { if (!npWasPlaying) npDismissed = false; npLastPlaying = Date.now(); }
    npWasPlaying = !!(now && now.playing);
    if (npDismissed) return false;
    return !!now && (now.playing || (npLastPlaying && Date.now() - npLastPlaying < 120000));
  }
  let npWasPlaying = false;
  // leaving the player is temporary: the home screen is the player whenever music plays, so the dismissal ends when an
  // app is opened, the switcher is shown, or 60 s pass
  let npDismissTimer = null;
  function dismissNowPlaying() { npDismissed = true; clearTimeout(npDismissTimer); npDismissTimer = setTimeout(() => { npDismissed = false; if (!current && $("#apps").classList.contains("hidden")) renderIdle(); }, 60000); const np = $("#nowplaying"); if (np) np.remove(); $("#idle").classList.remove("music"); renderIdle(); }
  function undismissNowPlaying() { npDismissed = false; clearTimeout(npDismissTimer); }
  function renderNowPlaying(idle) {
    let np = $("#nowplaying");
    const on = musicMode();
    idle.classList.toggle("music", on);
    if (!on) { if (np) np.remove(); npKey = ""; return; }
    const now = state.spotify.now, vol = state.audio && state.audio.music_pct;
    if (!np) {
      np = document.createElement("div"); np.id = "nowplaying"; np.className = "np";
      np.innerHTML = `<div class="np-top"><button class="np-x" data-x="home" aria-label="Back to home">${icon("chevron-left", "")}</button><button class="np-x" data-x="apps" aria-label="Apps">${icon("home", "")}</button></div><div class="np-art"><img alt="" src=""><div class="np-noart">${icon("note", "")}</div></div>
        <div class="np-title"></div><div class="np-artist"></div>
        <div class="np-prog"><div class="np-bar"></div></div><div class="np-times"><span class="np-t1">0:00</span><span class="np-t2">-0:00</span></div>
        <div class="np-ctl"><button class="np-btn" data-a="prev" aria-label="Previous">${icon("skip-back", "")}</button><button class="np-btn np-play" data-a="play" aria-label="Play or pause">${icon("play", "")}</button><button class="np-btn" data-a="next" aria-label="Next">${icon("skip-forward", "")}</button></div>
        <div class="np-vol">${icon("volume-low", "")}<input type="range" min="0" max="100" value="${vol == null ? 55 : vol}" aria-label="Volume">${icon("volume", "")}</div>`;
      $("#idlewidgets").before(np);
      np.querySelectorAll(".np-x").forEach(b => b.onclick = e => { e.stopPropagation(); if (b.dataset.x === "home") dismissNowPlaying(); else { dismissNowPlaying(); showApps(); } });
      np.querySelectorAll(".np-btn").forEach(b => b.onclick = async e => { e.stopPropagation(); const a = b.dataset.a; const n = state.spotify && state.spotify.now;
        if (a === "play") await api("spotify", n && n.playing ? "pause" : "play", {}); else await api("spotify", a); poll(); });
      const vr = np.querySelector(".np-vol input");
      vr.addEventListener("pointerdown", e => { e.stopPropagation(); npVolDrag = true; });
      vr.addEventListener("input", e => e.stopPropagation());
      vr.addEventListener("change", e => { e.stopPropagation(); npVolDrag = false; api("audio", "set_volume", { pct: +e.target.value, target: "music" }); });
      np.querySelector(".np-prog").onclick = e => { e.stopPropagation(); const n = state.spotify && state.spotify.now; if (!n || !n.duration_ms) return; const r = e.currentTarget.getBoundingClientRect(); api("spotify", "seek", { ms: Math.round((e.clientX - r.left) / r.width * n.duration_ms) }); };
      requestAnimationFrame(() => np.classList.add("in"));
    }
    const key = [now.uri, now.playing, now.art_url].join("|");
    if (key !== npKey) {
      npKey = key;
      const img = np.querySelector(".np-art img"), noart = np.querySelector(".np-noart");
      if (now.art_url) { img.src = now.art_url; img.style.display = ""; noart.style.display = "none"; } else { img.style.display = "none"; noart.style.display = ""; }
      np.querySelector(".np-title").textContent = now.title || "";
      np.querySelector(".np-artist").textContent = now.artist || "";
      np.querySelector(".np-play").innerHTML = icon(now.playing ? "pause" : "play", "");
    }
    if (now.duration_ms) {
      np.querySelector(".np-bar").style.width = (100 * (now.progress_ms || 0) / now.duration_ms).toFixed(1) + "%";
      np.querySelector(".np-t1").textContent = npMmss(now.progress_ms);
      np.querySelector(".np-t2").textContent = "-" + npMmss(now.duration_ms - (now.progress_ms || 0));
    }
    if (!npVolDrag && vol != null) { const vr = np.querySelector(".np-vol input"); if (+vr.value !== vol) vr.value = vol; }
  }

  // Home styles: a theme file (web/themes/<name>.js) calls HD.registerHome(name, {render(idleEl, state, apps, helpers)})
  // and ships its CSS as web/themes/<name>.css; the shell loads the active one from config.general.home_style.
  const homes = {}; let loadedStyle = "";
  function registerHome(name, impl) { homes[name] = impl; }
  function activeHome() { const n = (config.general && config.general.home_style) || "board"; return n !== "board" && homes[n] ? { name: n, impl: homes[n] } : null; }
  function ensureHomeAssets() {
    const n = (config.general && config.general.home_style) || "board";
    if (n === loadedStyle) return; loadedStyle = n;
    document.querySelectorAll("[data-home-asset]").forEach(e => e.remove()); document.documentElement.dataset.home = n;
    const w = $("#idlewidgets"); if (w) w.innerHTML = "";
    if (n === "board") return;
    const css = document.createElement("link"); css.rel = "stylesheet"; css.href = `/web/themes/${n}.css`; css.dataset.homeAsset = "1"; document.head.appendChild(css);
    const js = document.createElement("script"); js.src = `/web/themes/${n}.js`; js.dataset.homeAsset = "1"; js.onload = () => renderIdle(); document.head.appendChild(js);
  }
  function renderIdle() {
    ensureHomeAssets();
    const home = activeHome();
    if (home) { const idle = $("#idle"); renderNowPlaying(idle); try { home.impl.render(idle, state, apps, { icon, fmtTime, units, isGuest, openApp, showApps, setText, setHtml, isHidden: id => new Set((config.general || {}).home_hidden || ["lists", "fan", "transit", "flights"]).has(id) }); } catch (e) { console.error("home style", e); } renderControls();
      { const t = fmtTime(); const m = t.match(/^(.*?)(\s*[AP]M)$/i); $("#clock").innerHTML = m ? `${m[1]}<span class="ampm">${m[2].trim()}</span>` : t; }
      $("#date").textContent = new Date().toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" }); return; }
    renderIdleBoard();
  }
  function renderIdleBoard() {
    const w = $("#idlewidgets"); if (!w) return;
    renderNowPlaying($("#idle"));
    // Home-screen editor (Settings > Home screen): general.home_hidden = [ids], general.home_order = [ids]
    const g = config.general || {}, hidden = new Set(g.home_hidden || ["lists", "fan", "transit", "flights"]), order = g.home_order || [];
    // idleAppend tiles (mic-off badge, lights, fan, reminders) always take the next free slot after the ordered ones
    const rank = a => { if (a.idleAppend && !order.includes(a.id)) return 5000 + (a.order || 99); const i = order.indexOf(a.id); return i < 0 ? 1000 + (a.order || 99) : i; };
    // Widget board: each app declares idleSize ("1x1" | "2x1" | "2x2"); idleWidget may return a size string to override
    // it for the current state (e.g. a running timer grows to 2x1). Tiles that render nothing collapse away.
    let n = 0;
    for (const a of Object.values(apps).sort((x, y) => rank(x) - rank(y))) {
      if (!a.idleWidget || (isGuest() && a.guestHidden) || (KIOSK && a.kioskHidden)) continue;
      let el = $(`#iw-${a.id}`);
      if (hidden.has(a.id)) { if (el) el.remove(); continue; }
      const fresh = !el;
      if (!el) { el = document.createElement("div"); el.id = `iw-${a.id}`; el.className = "iw"; el.onclick = () => openApp(a.id); }
      if (el.parentNode !== w || el.nextSibling === null && w.lastChild !== el) w.appendChild(el);
      else if (w.children[n] !== el) w.insertBefore(el, w.children[n] || null);   // keep DOM order == configured order without reflowing every tick
      let size = null;
      try { size = a.idleWidget(el, state) || a.idleSize || "1x1"; } catch (e) { console.error(a.id, e); size = a.idleSize || "1x1"; }
      const cls = `iw iw-${size}` + (el.classList.contains("warn") ? " warn" : "") + (el.classList.contains("iw-quiet") ? " iw-quiet" : "");
      if (el.className !== cls) el.className = cls;
      if (fresh && !reducedMotion) { el.style.animationDelay = `${Math.min(n, 8) * 30}ms`; el.classList.add("iw-in"); el.addEventListener("animationend", () => el.classList.remove("iw-in"), { once: true }); }
      if (el.innerHTML !== "" && el.style.display !== "none") n++;
    }
    renderControls();
    { const t = fmtTime(); const m = t.match(/^(.*?)(\s*[AP]M)$/i);   // big digits, small AM/PM
      $("#clock").innerHTML = m ? `${m[1]}<span class="ampm">${m[2].trim()}</span>` : t; }
    $("#date").textContent = new Date().toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  }

  // Mic and camera quick toggles in the bottom corner of the home screen. The camera one only exists on phones:
  // the device's own screen never shows camera state (owner's rule). Camera "off" here = privacy mode (security recording stays armed).
  function renderControls() {
    const c = $("#idlecontrols"); if (!c) return;
    const v = state.voice || {}, cam = state.camera || {};
    const micOn = v.mic_enabled !== false, camOn = cam.mode === "on";
    let html = `<button class="ctlbtn ${micOn ? "on" : "off"}" data-act="mic" title="Microphone" aria-label="Microphone ${micOn ? "on" : "off"}">${icon(micOn ? "mic" : "mic-off", "")}<span>${micOn ? "Mic on" : "Mic off"}</span></button>`;
    if (state.camera) html += `<button class="ctlbtn ${camOn ? "on" : "off"}" data-act="cam" title="Camera" aria-label="Camera">${icon(camOn ? "camera" : "camera-off", "")}<span>${camOn ? "Camera on" : "Camera off"}</span></button>`;
    // volume: a round speaker button that opens a small slider popover (system-wide ALSA softvol via the audio module)
    const au = state.audio || {}, muted = au.volume_pct === 0 && au.music_pct === 0;
    html += `<button class="ctlbtn ${muted ? "off" : "on"}" data-act="vol" title="Volume" aria-label="Volume">${icon("volume", "")}<span>Volume</span></button>`;
    if (KIOSK) html += `<button class="ctlbtn" data-act="bright" title="Brightness" aria-label="Brightness">${icon("sun", "")}<span>Brightness</span></button>`;
    if (KIOSK) html += `<button class="ctlbtn" data-act="screen" title="Screen off" aria-label="Screen off">${icon("moon", "")}<span>Screen</span></button>`;
    if (c.dataset.sig !== html) { c.innerHTML = html; c.dataset.sig = html;
      c.querySelectorAll(".ctlbtn").forEach(b => b.onclick = async (e) => { e.stopPropagation();
        if (b.dataset.act === "screen") { await api("display", "screen_off", { toggle: true }); return; }
        if (b.dataset.act === "mic") { await api("voice", "set_mic", { enabled: !micOn }); toast(micOn ? "Microphone off" : "Microphone on"); }
        else if (b.dataset.act === "cam") { await api("camera", "set_mode", { mode: camOn ? "privacy" : "on" }); toast(camOn ? "Camera off" : "Camera on"); }
        else if (b.dataset.act === "vol") { toggleVolumePop(); return; }
        else if (b.dataset.act === "bright") { toggleBrightPop(); return; }
        poll(); }); }
  }
  // brightness: same popover as volume; "Auto" hands control back to the light sensor, the slider sets a 10-minute override
  function toggleBrightPop() {
    let pop = $("#volpop"); const wasBright = pop && pop.dataset.kind === "bright";
    if (pop) pop.remove();
    if (wasBright) return;
    const d = state.display || {}; const v = d.brightness_pct == null ? 60 : d.brightness_pct;
    pop = document.createElement("div"); pop.id = "volpop"; pop.className = "volpop"; pop.dataset.kind = "bright";
    pop.innerHTML = `<button class="volmute" id="brauto" aria-label="Automatic brightness">${icon("sun", "")}<span>Auto</span></button><input type="range" min="5" max="100" value="${v}" id="brrange" aria-label="Brightness"><span class="volval" id="brval">${v}%</span>`;
    pop.onclick = e => e.stopPropagation(); pop.onpointerdown = e => e.stopPropagation();
    document.body.appendChild(pop);
    const r = $("#brrange"), lbl = $("#brval"); let t = null;
    r.oninput = () => { lbl.textContent = r.value + "%"; clearTimeout(t); t = setTimeout(() => api("display", "set_brightness", { pct: +r.value }).then(poll), 120); };
    $("#brauto").onclick = async () => { await api("display", "clear_override", {}); toast("Auto brightness", "good", 1500); await poll(); const nv = (state.display || {}).brightness_pct; if (nv != null) { r.value = nv; lbl.textContent = nv + "%"; } };
    const close = e => { if (!pop.contains(e.target) && !e.target.closest('[data-act="bright"]')) { pop.remove(); document.removeEventListener("pointerdown", close, true); } };
    setTimeout(() => document.addEventListener("pointerdown", close, true), 50);
    setTimeout(() => { const p2 = $("#volpop"); if (p2 && p2.dataset.kind === "bright") { p2.remove(); document.removeEventListener("pointerdown", close, true); } }, 8000);
  }
  function toggleVolumePop() {
    let pop = $("#volpop");
    if (pop) { pop.remove(); return; }
    // two independent levels: Music (Spotify, YouTube; ducked while Jarvis talks) and Jarvis (speech, timers, alarms)
    const au = state.audio || {}; const v = au.volume_pct == null ? 50 : au.volume_pct, mv = au.music_pct == null ? 70 : au.music_pct;
    const allMuted = v === 0 && mv === 0;
    pop = document.createElement("div"); pop.id = "volpop"; pop.className = "volpop volpop2";
    const row = (id, label, val) => `<div class="volrow2"><span class="vollbl">${label}</span><input type="range" min="0" max="100" value="${val}" id="${id}" aria-label="${label} volume"><span class="volval" id="${id}v">${val}%</span></div>`;
    pop.innerHTML = `<button class="volmute" id="volmute" aria-label="Mute">${icon("volume", "")}<span>${allMuted ? "Unmute" : "Mute"}</span></button><div class="volrows">${row("volmusic", "Music", mv)}${row("voljarvis", "Jarvis", v)}</div>`;
    pop.onclick = e => e.stopPropagation(); pop.onpointerdown = e => e.stopPropagation();
    document.body.appendChild(pop);
    const bind = (id, target) => { const r = $("#" + id), lbl = $("#" + id + "v"); let t = null;
      r.oninput = () => { lbl.textContent = r.value + "%"; clearTimeout(t); t = setTimeout(() => api("audio", "set_volume", { pct: +r.value, target }).then(poll), 120); }; return r; };
    const rm = bind("volmusic", "music"), rj = bind("voljarvis", "jarvis");
    $("#volmute").onclick = async () => { const a = state.audio || {}; const mutedNow = (a.volume_pct === 0 && a.music_pct === 0); await api("audio", mutedNow ? "unmute" : "mute", { target: "all" }); await poll(); const b = state.audio || {};
      rm.value = b.music_pct || 0; $("#volmusicv").textContent = (b.music_pct || 0) + "%"; rj.value = b.volume_pct || 0; $("#voljarvisv").textContent = (b.volume_pct || 0) + "%"; $("#volmute span").textContent = (b.volume_pct === 0 && b.music_pct === 0) ? "Unmute" : "Mute"; };
    const close = e => { if (!pop.contains(e.target) && !e.target.closest('[data-act="vol"]')) { pop.remove(); document.removeEventListener("pointerdown", close, true); } };
    setTimeout(() => document.addEventListener("pointerdown", close, true), 50);
    setTimeout(() => { const p2 = $("#volpop"); if (p2) { p2.remove(); document.removeEventListener("pointerdown", close, true); } }, 8000);
  }

  let lastEvent = null;   // null until the first poll: events that happened before the page opened are not replayed
  async function poll() {
    try {
      const r = await fetch("/api/state"); state = await r.json();
      if (DEMO_MUSIC) { state.spotify = state.spotify || {}; state.spotify.now = { title: "Some Jazz To Make Love On", artist: "Bellaire", playing: true, progress_ms: 61000, duration_ms: 344000, art_url: DEMO_ART, shuffle: false }; }
      // deployed web files changed since this page loaded: reload (kiosk and phones alike)
      if (state.web_version) { if (window.__webv == null) window.__webv = state.web_version; else if (state.web_version !== window.__webv) location.reload(); }
      document.body.classList.toggle("offline", false); pollFails = 0;
      if (current && apps[current].update) apps[current].update(state);
      if (!$("#idle").classList.contains("hidden")) renderIdle();
      // server-pushed events: state.events = [{t, name, data}] ring buffer from the "events" module
      const ring = (state.events && state.events.ring) || [];
      if (lastEvent === null) lastEvent = ring.length ? ring[ring.length - 1].t : 0;
      for (const ev of ring) {
        if (ev.t > lastEvent && ev.name === "ui_home") { dismissNowPlaying(); showIdle(); }
        if (ev.t > lastEvent) { lastEvent = ev.t; for (const a of Object.values(apps)) a.onEvent && a.onEvent(ev.name, ev.data); document.dispatchEvent(new CustomEvent("hd-event", { detail: ev })); }
      }
      applyDisplay();
      offlineSince = 0;
    } catch (e) {
      // one missed 2 s poll is normal (busy server); cover the screen only after ~6 s without an answer
      pollFails = (typeof pollFails === "number" ? pollFails : 0) + 1;
      if (pollFails >= 3) document.body.classList.toggle("offline", true);
      // a page that has lost the server for a minute reloads itself once the server answers a plain request again
      offlineSince = offlineSince || Date.now();
      if (Date.now() - offlineSince > 60000) { offlineSince = Date.now(); fetch("/web/icon.svg", { cache: "no-store" }).then(r => { if (r.ok) location.reload(); }).catch(() => {}); }
    }
  }
  let offlineSince = 0, pollFails = 0;
  async function loadConfig() { try { config = await (await fetch("/api/config")).json(); } catch (e) {} }

  // Background: {mode: "live"|"solid"|"gradient", color, gradient:[c1,c2]} from Settings. Themes read html[data-bg].
  function applyBackground() {
    const bg = (config.general && config.general.background) || { mode: "live" };
    const root = document.documentElement, mode = bg.mode || "live";
    if (root.dataset.bg !== mode) root.dataset.bg = mode;
    let css = "";
    if (mode === "solid") css = bg.color || "#1c1c1e";
    else if (mode === "gradient") { const g = bg.gradient || ["#1b2735", "#090a0f"]; css = `linear-gradient(180deg, ${g[0]}, ${g[1]})`; }
    if (root.style.getPropertyValue("--bg-custom") !== css) root.style.setProperty("--bg-custom", css);
  }
  function applyDisplay() {
    applyBackground();
    const d = state.display || {};
    // Dimming is for the device's own panel only. When the real backlight exists the hardware does it;
    // otherwise (panel driver missing) the CSS dimmer stands in. Phones are never dimmed.
    const cssDim = KIOSK && !NODIM && !d.backlight_present && d.brightness_pct != null ? (100 - Math.max(8, d.brightness_pct)) / 100 : 0;
    document.documentElement.style.setProperty("--dim", cssDim);
    document.body.classList.toggle("night", KIOSK && !!d.night);
    document.body.classList.toggle("screen-off", KIOSK && !!d.screen_off);
    document.body.classList.toggle("guest", isGuest());
  }

  // 2 min without a touch returns to the home screen, except while the music player is open
  function touched() { lastTouch = Date.now(); if (idleTimer) clearTimeout(idleTimer); idleTimer = setTimeout(() => { if (current === "spotify") { touched(); return; } showIdle(); }, 120000); fetch("/api/display/touch", { method: "POST", body: "{}" }).catch(() => {}); }

  function reportViewport() { if (!KIOSK) return; fetch("/api/display/viewport", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ w: innerWidth, h: innerHeight, dpr: devicePixelRatio, ua: navigator.userAgent.slice(0, 80) }) }).catch(() => {}); }
  // Device panel: the compositor hands Chromium touch as pointer drags, which do not scroll by themselves.
  // Drag-to-scroll with a small dead zone so taps still click; suppress the click that would follow a drag.
  if (KIOSK) (() => {
    let y0 = null, sy0 = 0, moved = false, vy = 0, lastY = 0, lastT = 0, raf = null;
    const scroller = () => document.scrollingElement || document.documentElement;
    addEventListener("pointerdown", e => { if (raf) { cancelAnimationFrame(raf); raf = null; } y0 = e.clientY; lastY = e.clientY; lastT = e.timeStamp; sy0 = scroller().scrollTop; moved = false; vy = 0; }, { passive: true });
    addEventListener("pointermove", e => { if (y0 == null) return; const dy = e.clientY - y0; if (!moved && Math.abs(dy) < 8) return; moved = true;
      scroller().scrollTop = sy0 - dy; const dt = e.timeStamp - lastT; if (dt > 0) vy = (e.clientY - lastY) / dt; lastY = e.clientY; lastT = e.timeStamp; }, { passive: true });
    const end = () => { if (y0 == null) return; y0 = null; if (!moved) return;
      let v = vy * 16; const step = () => { if (Math.abs(v) < 0.5) { raf = null; return; } scroller().scrollTop -= v; v *= 0.94; raf = requestAnimationFrame(step); }; raf = requestAnimationFrame(step); };
    addEventListener("pointerup", end, { passive: true }); addEventListener("pointercancel", end, { passive: true });
    addEventListener("click", e => { if (moved) { e.stopPropagation(); e.preventDefault(); moved = false; } }, true);
  })();
  // popover styles (kept here so the volume control needs no stylesheet change)
  document.addEventListener("DOMContentLoaded", async () => {
    reportViewport(); setInterval(reportViewport, 60000); addEventListener("resize", reportViewport);
    await loadConfig(); buildGrid(); ensureHomeAssets();   // the home style's backdrop must exist even when a page opens first
    const q = new URLSearchParams(location.search), want = q.get("app");   // /?app=weather opens that app directly, /?view=apps the grid
    if (want && apps[want]) openApp(want); else if (q.get("view") === "apps") showApps(); else showIdle();
    poll(); setInterval(poll, 2000); setInterval(() => { if (!$("#idle").classList.contains("hidden")) renderIdle(); }, 1000);
    ["pointerdown", "keydown"].forEach(ev => document.addEventListener(ev, touched, { passive: true }));
    $("#idle").addEventListener("click", e => { if (e.target.closest(".iw, #nowplaying, #idlecontrols")) return; if ($("#apps").classList.contains("hidden")) showApps(); });
    // switcher sheet: tap outside or drag down to close
    $("#apps").addEventListener("click", e => { if (!e.target.closest("#appsheet")) showIdle(); });
    { const sh = $("#appsheet"); let y0 = null, dy = 0;
      sh.addEventListener("pointerdown", e => { y0 = e.clientY; dy = 0; sh.style.transition = "none"; }, { passive: true });
      sh.addEventListener("pointermove", e => { if (y0 == null) return; dy = Math.max(0, e.clientY - y0); sh.style.transform = `translateY(${dy}px)`; }, { passive: true });
      const done = () => { if (y0 == null) return; y0 = null; sh.style.transition = ""; sh.style.transform = ""; if (dy > 60) showIdle(); dy = 0; };
      sh.addEventListener("pointerup", done); sh.addEventListener("pointercancel", done); document.addEventListener("pointerup", done); }
    // hidden guest-mode gesture: press and hold the clock for 3 s
    // Robust long-press: pointerleave/cancel (touch jitter, long-press context menu) must not abort it.
    let hold = null, holdStart = 0;
    const clockEl = $("#clock");
    clockEl.addEventListener("contextmenu", e => e.preventDefault());
    const endHold = () => { if (hold) { clearTimeout(hold); hold = null; } clockEl.style.opacity = ""; };
    clockEl.addEventListener("pointerdown", e => { e.stopPropagation(); holdStart = Date.now(); clockEl.style.opacity = ".55";
      hold = setTimeout(async () => { hold = null; clockEl.style.opacity = ""; await saveConfig({ general: { guest_mode: !isGuest() } }); buildGrid(); renderIdle(); toast(isGuest() ? "Guest mode" : "Welcome home", "good", 1500); }, 3000); }, { passive: true });
    ["pointerup", "pointercancel"].forEach(ev => clockEl.addEventListener(ev, endHold));
    document.addEventListener("pointerup", endHold);
    setInterval(loadConfig, 30000);
    const demo = q.get("demo");   // visual checks only
    if (demo === "popup") popup({ title: "Fresh air time", body: "CO₂ is 1,180 ppm. Crack a window for a few minutes.", level: "serious", actions: [{ label: "Later" }, { label: "Got it" }] });
    if (demo === "alarm") popup({ title: "Wake up", level: "warning", body: `<div class="ring-time">${fmtTime()}</div><p>The light is still off. Up and at it.</p>`, actions: [{ label: "Snooze" }, { label: "Stop" }] });
    if (demo === "listen") document.dispatchEvent(new CustomEvent("hd-demo-listen"));
  });

  return { setText, setHtml, registerApp, registerHome, appColor, applyBackground, api, saveConfig, toast, popup, openApp, showIdle, showApps, fmtTime, units, isGuest, KIOSK, icon,
           get state() { return state; }, get config() { return config; }, get apps() { return apps; } };
})();
