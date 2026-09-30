/* HomeDeck Remote: phone app that controls the device. Talks to the same /api as the device UI. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const ICON = {
    mic: '<path d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>',
    micoff: '<path d="M9 9v3a3 3 0 0 0 5.1 2.1"/><path d="M15 9.3V6a3 3 0 0 0-5.7-1.3"/><path d="M5 11a7 7 0 0 0 11 5.7"/><path d="M19 11a7 7 0 0 1-.6 2.8"/><path d="M12 18v3"/><path d="M4 4l16 16"/>',
    cam: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7l1.5-3h5L16 7"/><circle cx="12" cy="13.5" r="3.5"/>',
    camoff: '<path d="M4 4l16 16"/><path d="M9 7h-4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h12"/><path d="M21 16V9a2 2 0 0 0-2-2h-3l-1.5-3h-5"/>',
    vol: '<path d="M4 10v4h4l5 4V6L8 10z"/><path d="M16 9a4 4 0 0 1 0 6"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    bolt: '<path d="M13 3L5 13h6l-1 8 8-10h-6z"/>',
    bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    cal: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    play: '<path d="M8 5v14l11-7z" fill="currentColor" stroke="none"/>',
    pause: '<rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor" stroke="none"/><rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor" stroke="none"/>',
    back: '<path d="M6 5v14"/><path d="M19 5l-11 7 11 7z" fill="currentColor"/>',
    fwd: '<path d="M18 5v14"/><path d="M5 5l11 7-11 7z" fill="currentColor"/>',
    shuffle: '<path d="M3 7h3l9 10h6"/><path d="M3 17h3l3-3.3"/><path d="M13.5 9.7L15 7h6"/><path d="M19 4l3 3-3 3M19 14l3 3-3 3"/>',
    cloud: '<path d="M7 18a4 4 0 0 1-.5-8 6 6 0 0 1 11.4 1.5A3.5 3.5 0 0 1 17.5 18z"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    bulb: '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M8.5 14.5A6 6 0 1 1 15.5 14.5c-.6.6-1 1.5-1 2.5h-5c0-1-.4-1.9-1-2.5z"/>',
    timer: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2"/><path d="M9 2h6"/>',
    chat: '<path d="M4 5h16v11H9l-5 4z"/>',
    house: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
    leaf: '<path d="M5 19c0-8 5-13 14-14-1 9-6 14-14 14z"/><path d="M5 19l8-8"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  };
  const icon = (n, cls = "i") => `<svg class="${cls}" viewBox="0 0 24 24">${ICON[n] || ""}</svg>`;
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (v, d = 0) => v == null || isNaN(v) ? "–" : Number(v).toFixed(d);
  const fmtTime = (ts) => { const d = ts instanceof Date ? ts : new Date(typeof ts === "number" ? ts * 1000 : ts); return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); };
  const fmtDay = (ts) => { const d = new Date(typeof ts === "number" ? ts * 1000 : ts); return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" }); };
  const mmss = ms => { const s = Math.floor((ms || 0) / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  const tempOut = c => (R.config.general && R.config.general.units) === "metric" ? `${fmt(c, 0)}°C` : `${fmt(c * 9 / 5 + 32, 0)}°F`;

  const R = { state: {}, config: {}, tab: "home", rendered: {}, search: null };

  // ---------------------------------------------------------------- transport
  async function api(module, action, params = {}) {
    const r = await fetch(`/api/${module}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params) });
    if (r.status === 401) { location.href = "/auth/login"; return {}; }
    return r.json().catch(() => ({}));
  }
  async function saveConfig(partial) {
    const r = await fetch("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(partial) });
    if (r.status === 401) { location.href = "/auth/login"; return {}; }
    const j = await r.json().catch(() => ({})); if (j.config) R.config = j.config; return j;
  }
  function toast(text, level = "") { const t = document.createElement("div"); t.className = "toast " + level; t.textContent = text; $("#toasts").appendChild(t); setTimeout(() => t.remove(), 2600); }
  function banner(text) { const b = $("#banner"); if (!text) { b.hidden = true; return; } b.textContent = text; b.hidden = false; }
  function setText(el, t) { if (el && el.textContent !== t) el.textContent = t; }
  function setHtml(el, h) { if (el && el.dataset.h !== h) { el.innerHTML = h; el.dataset.h = h; } }

  async function poll() {
    if (document.hidden) return;
    try {
      const r = await fetch("/api/state");
      if (r.status === 401) { location.href = "/auth/login"; return; }
      R.state = await r.json(); banner("");
      render();
    } catch (e) { banner("Can't reach HomeDeck. Retrying…"); }
  }
  async function loadConfig() { try { const r = await fetch("/api/config"); if (r.status === 401) { location.href = "/auth/login"; return; } R.config = await r.json(); } catch (e) {} }

  // ---------------------------------------------------------------- tabs
  function showTab(name) {
    R.tab = name;
    document.querySelectorAll(".view").forEach(v => v.hidden = v.id !== "v-" + name);
    document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === name));
    window.scrollTo(0, 0);
    if (!R.rendered[name]) { BUILD[name](); R.rendered[name] = true; }
    render();
    try { history.replaceState(null, "", "?remote=1&tab=" + name); } catch (e) {}
  }

  // ---------------------------------------------------------------- HOME
  function buildHome() {
    $("#v-home").innerHTML = `
      <h1>HomeDeck<small id="h-sub">connecting…</small></h1>
      <div class="card" id="h-device">
        <div class="row"><span class="ic" style="background:#6e6e73">${icon("house")}</span><div class="k">Presence<small id="h-pres-sub"></small></div><div class="seg" id="h-pres" style="width:170px"><button data-v="home">Home</button><button data-v="away">Away</button><button data-v="auto">Auto</button></div></div>
        <div class="row"><span class="ic" style="background:#0a84ff">${icon("mic")}</span><div class="k">Microphone<small id="h-mic-sub"></small></div><button class="switch" id="h-mic"></button></div>
        <div class="row"><span class="ic" style="background:#1c1c1e">${icon("cam")}</span><div class="k">Camera<small id="h-cam-sub"></small></div><div class="seg" id="h-cam" style="width:170px"><button data-v="on">On</button><button data-v="privacy">Private</button><button data-v="off">Off</button></div></div>
        <div class="row"><span class="ic" style="background:#8e8e93">${icon("vol")}</span><div class="k"><input type="range" id="h-vol" min="0" max="100" aria-label="Volume"></div><div class="v" id="h-vol-v" style="width:38px"></div><button class="btn small" id="h-mute">Mute</button></div>
        <div class="row"><span class="ic" style="background:#5e5ce6">${icon("moon")}</span><div class="k">Screen<small id="h-scr-sub"></small></div><button class="btn small" id="h-screen">Turn off</button></div>
        <div class="row"><span class="ic" style="background:#4aa3ff">${icon("sun")}</span><div class="k">Brightness<small id="h-br-sub"></small></div><button class="btn small" id="h-br-auto">Auto</button></div>
        <div class="pad" style="padding-top:0"><input type="range" id="h-br" min="5" max="100" aria-label="Screen brightness"></div>
        <div class="row"><span class="ic" style="background:#ff9f0a">${icon("bell")}</span><div class="k">Guest mode<small>Hides personal apps on the device</small></div><button class="switch" id="h-guest"></button></div>
      </div>
      <h2>Room</h2>
      <div class="tiles" id="h-tiles"></div>
      <div class="card" style="margin-top:12px"><div class="row"><span class="ic" style="background:#4aa3ff">${icon("sun")}</span><div class="k" id="h-weather">Weather</div></div></div>
      <h2>Lights</h2>
      <div class="card"><div class="row"><span class="ic" style="background:#ffb020">${icon("bulb")}</span><div class="k">Light bar<small id="h-lamp-sub"></small></div><button class="switch" id="h-lamp"></button></div>
        <div class="pad"><div class="swatches" id="h-swatches"></div><input type="range" id="h-lamp-br" min="1" max="100" style="margin-top:12px" aria-label="Light brightness"></div></div>
      <h2>Quick actions</h2>
      <div class="card">
        <div class="pad"><label class="field" style="margin-top:0">Send a timer to the device</label><div class="inline"><input type="number" id="h-timer-min" value="5" min="1" max="600" style="width:90px"><span class="hint">minutes</span><button class="btn" id="h-timer-go">Start</button></div></div>
        <div class="pad" style="border-top:1px solid var(--line)"><label class="field" style="margin-top:0">Ask Jarvis</label><div class="inline"><input type="text" id="h-ask" placeholder="Type a question"><button class="btn primary" id="h-ask-go">Ask</button></div><div class="hint" id="h-ask-out" style="margin-top:8px"></div><div class="btnrow" id="h-ask-actions" style="margin-top:8px" hidden><button class="btn small" id="h-ask-say">Say it on HomeDeck</button></div></div>
      </div>
      <h2>Up next</h2>
      <div class="card"><div class="row"><span class="ic" style="background:#ff9f0a">${icon("bell")}</span><div class="k">Next alarm</div><div class="v" id="h-alarm"></div></div>
        <div class="row"><span class="ic" style="background:#ff3b30">${icon("cal")}</span><div class="k">Next event<small id="h-event-sub"></small></div><div class="v" id="h-event"></div></div>
        <div class="row"><span class="ic" style="background:#2bb0a0">${icon("bolt")}</span><div class="k">E-bikes<small id="h-bikes-sub"></small></div><div class="v" id="h-bikes"></div></div></div>
      <h2>Notifications</h2>
      <div class="card" id="h-notify"></div>`;
    const v = $("#v-home");
    v.querySelectorAll("#h-pres button").forEach(b => b.onclick = () => api("presence", "set_mode", { mode: b.dataset.v }).then(poll));
    $("#h-mic").onclick = () => api("voice", "set_mic", { enabled: !(R.state.voice && R.state.voice.mic_enabled !== false) }).then(poll);
    v.querySelectorAll("#h-cam button").forEach(b => b.onclick = () => api("camera", "set_mode", { mode: b.dataset.v }).then(poll));
    $("#h-vol").oninput = e => setText($("#h-vol-v"), e.target.value + "%");
    $("#h-vol").onchange = e => api("audio", "set_volume", { pct: +e.target.value }).then(poll);
    $("#h-mute").onclick = () => api("audio", (R.state.audio && R.state.audio.muted) ? "unmute" : "mute", { target: "all" }).then(poll);
    $("#h-screen").onclick = () => api("display", "screen_off", { toggle: true }).then(poll);
    let brT = null;
    $("#h-br").oninput = e => { setText($("#h-br-sub"), e.target.value + "%"); clearTimeout(brT); brT = setTimeout(() => api("display", "set_brightness", { pct: +e.target.value }).then(poll), 150); };
    $("#h-br-auto").onclick = () => api("display", "clear_override", {}).then(() => { toast("Auto brightness", "good"); poll(); });
    $("#h-guest").onclick = () => saveConfig({ general: { guest_mode: !(R.config.general && R.config.general.guest_mode) } }).then(() => { toast("Saved", "good"); render(); });
    $("#h-lamp").onclick = () => api("leds", "lamp", { on: !(R.state.leds && R.state.leds.lamp && R.state.leds.lamp.on) }).then(poll);
    $("#h-lamp-br").onchange = e => api("leds", "lamp", { on: true, brightness: +e.target.value }).then(poll);
    const presets = [["Warm", [255, 160, 70]], ["Soft", [255, 200, 140]], ["Daylight", [255, 245, 230]], ["Cool", [200, 225, 255]], ["Night", [120, 20, 0]], ["Amber", [255, 120, 0]], ["Ocean", [0, 140, 255]], ["Forest", [30, 200, 90]], ["Rose", [255, 60, 120]]];
    $("#h-swatches").innerHTML = presets.map(([n, c]) => `<button class="swatch" title="${n}" data-c="${c.join(",")}" style="background:rgb(${c.join(",")})"></button>`).join("");
    v.querySelectorAll("#h-swatches .swatch").forEach(b => b.onclick = () => api("leds", "lamp", { on: true, color: b.dataset.c.split(",").map(Number) }).then(poll));
    $("#h-timer-go").onclick = async () => { const m = +$("#h-timer-min").value || 5; const r = await api("timers", "add", { seconds: m * 60, label: `${m} min` }); toast(r.ok ? `Timer set for ${m} min` : "Couldn't set timer", r.ok ? "good" : "warning"); };
    const ask = async () => { const q = $("#h-ask").value.trim(); if (!q) return; setText($("#h-ask-out"), "Thinking…"); const r = await api("voice", "ask", { text: q }); setText($("#h-ask-out"), r.answer || r.error || "No answer"); $("#h-ask-actions").hidden = !r.answer; $("#h-ask-say").onclick = () => api("voice", "say", { text: r.answer }); };
    $("#h-ask-go").onclick = ask; $("#h-ask").onkeydown = e => { if (e.key === "Enter") ask(); };
  }
  function renderHome() {
    const s = R.state, g = R.config.general || {};
    const online = s.time ? "online · " + (s.display && s.display.night ? "night mode" : "day") : "offline";
    setText($("#h-sub"), `${online} · ${s.presence && s.presence.home === false ? "away" : "home"}`);
    const p = s.presence || {}; document.querySelectorAll("#h-pres button").forEach(b => b.classList.toggle("on", b.dataset.v === (p.mode || "auto")));
    setText($("#h-pres-sub"), p.home === false ? "Nobody home · security armed" : (p.phones || []).length ? "Someone is home" : "Set phones in Settings");
    const mic = !(s.voice && s.voice.mic_enabled === false); $("#h-mic").classList.toggle("on", mic); setText($("#h-mic-sub"), mic ? "Listening for “Hey Jarvis”" : "Off, nothing is captured");
    // no camera module (it is optional, and left out of the public source): hide its row and tab
    const hasCam = !!s.camera; const camTab = document.querySelector('[data-tab="camera"]'); if (camTab) camTab.hidden = !hasCam;
    const camRow = $("#h-cam") && $("#h-cam").closest(".row"); if (camRow) camRow.hidden = !hasCam;
    const cm = (s.camera || {}).mode || "privacy"; document.querySelectorAll("#h-cam button").forEach(b => b.classList.toggle("on", b.dataset.v === cm));
    setText($("#h-cam-sub"), cm === "on" ? "Live view available" : cm === "privacy" ? (((R.config.camera || {}).security || {}).enabled ? "No live view · motion clips on" : "No live view") : "Completely off");
    const a = s.audio || {}; if (document.activeElement !== $("#h-vol")) { $("#h-vol").value = a.volume_pct ?? 50; setText($("#h-vol-v"), (a.volume_pct ?? "–") + "%"); } setText($("#h-mute"), a.muted ? "Unmute" : "Mute");
    const d = s.display || {}; setText($("#h-screen"), d.screen_off ? "Turn on" : "Turn off"); setText($("#h-scr-sub"), d.screen_off ? "Off" : `On · ${d.brightness_pct ?? "?"}% brightness`);
    if (document.activeElement !== $("#h-br") && d.brightness_pct != null) { $("#h-br").value = d.brightness_pct; setText($("#h-br-sub"), `${d.brightness_pct}%${d.override_pct != null ? " · manual" : " · auto"}`); }
    $("#h-guest").classList.toggle("on", !!g.guest_mode);
    const ms = (s.sensors || {}).metrics || [];
    setHtml($("#h-tiles"), ms.filter(m => ["co2", "temp", "hum", "voc"].includes(m.key)).map(m => { let val = m.value, unit = m.unit; if (m.key === "temp") { val = null; } return `<div class="tile"><div class="lbl">${m.label}</div><div class="val">${m.key === "temp" ? tempOut(m.value) : fmt(val, m.key === "co2" ? 0 : 1)}<small>${m.key === "temp" ? "" : unit}</small></div><div class="sub"><span class="dot ${m.status.level}"></span>${m.status.text}</div></div>`; }).join(""));
    const w = (s.weather || {}).current, d0 = ((s.weather || {}).daily || [])[0];
    setText($("#h-weather"), w ? `${fmt(w.temp, 0)}° ${w.text}${d0 ? ` · H ${fmt(d0.hi, 0)} L ${fmt(d0.lo, 0)}` : ""}${w.humidity != null ? ` · ${w.humidity}% humidity` : ""}` : "Weather unavailable");
    const l = (s.leds || {}).lamp || {}; $("#h-lamp").classList.toggle("on", !!l.on); setText($("#h-lamp-sub"), l.on ? `On · ${l.brightness}%` : "Off");
    if (document.activeElement !== $("#h-lamp-br")) $("#h-lamp-br").value = l.brightness ?? 60;
    document.querySelectorAll("#h-swatches .swatch").forEach(b => b.classList.toggle("on", !!l.on && b.dataset.c === (l.color || []).join(",")));
    const na = (s.alarms || {}).next_alarm; setText($("#h-alarm"), na ? `${fmtDay(na.at)} ${fmtTime(na.at)}` : "None");
    const ne = (s.calendar || {}).next_event; setText($("#h-event"), ne ? (ne.all_day ? fmtDay(ne.start) : `${fmtDay(ne.start)} ${fmtTime(ne.start)}`) : "None"); setText($("#h-event-sub"), ne ? ne.title : "");
    const st = ((s.bikes || {}).stations || [])[0]; setText($("#h-bikes"), st ? `${st.ebikes}` : "–"); setText($("#h-bikes-sub"), st ? st.name : "");
    const n = s.notify || {}; const rec = (n.recent || []).slice(-5).reverse();
    setHtml($("#h-notify"), rec.length ? rec.map(r => `<div class="row"><div class="k">${esc(r.title)}<small>${esc(r.body || "")}</small></div><div class="v">${fmtTime(r.t)}</div></div>`).join("") : `<div class="pad hint">No alerts yet. Install the free ntfy app and subscribe to <b>${esc(n.topic || "")}</b> to get motion, reminder and alarm alerts on this phone.</div>`);
  }

  // ---------------------------------------------------------------- CAMERA
  let clipsCache = { t: 0, clips: [] }, cloudDays = null;
  function buildCamera() {
    $("#v-camera").innerHTML = `
      <h1>Camera<small id="c-sub"></small></h1>
      <div class="live" id="c-live"></div>
      <div class="btnrow" style="margin-top:12px"><a class="btn" id="c-snap" href="/camera/snapshot.jpg" target="_blank">Snapshot</a><button class="btn" id="c-refresh">Refresh clips</button></div>
      <h2>Intercom</h2>
      <div class="card"><div class="pad">
        <div class="btnrow"><button class="btn" id="ic-listen">Listen</button><button class="btn primary ic-talk" id="ic-talk">Hold to talk</button></div>
        <div class="hint" id="ic-status" style="margin-top:8px">Listen plays the room's microphone here. Hold to talk plays your voice on the HomeDeck.</div>
        <div class="ic-say"><input type="text" id="ic-say" placeholder="Type something for Jarvis to say" autocomplete="off"><button class="btn small" id="ic-say-go">Say</button></div>
      </div></div>
      <h2>Mode</h2>
      <div class="card"><div class="pad"><div class="seg" id="c-mode"><button data-v="on">On</button><button data-v="privacy">Privacy</button><button data-v="off">Off</button></div><div class="hint" id="c-mode-hint" style="margin-top:10px"></div></div></div>
      <h2>Security</h2>
      <div class="card">
        <div class="row"><div class="k">Motion recording</div><button class="switch" id="c-sec"></button></div>
        <div class="row"><div class="k">Only when I'm away</div><button class="switch" id="c-away"></button></div>
        <div class="row"><div class="k">Notify on every clip</div><button class="switch" id="c-notify"></button></div>
        <div class="row"><div class="k">Sensitivity<small id="c-sens-v"></small></div><input type="range" id="c-sens" min="1" max="10" style="width:140px"></div>
        <div class="row"><div class="k">Cloud<small id="c-cloud-sub"></small></div><button class="btn small" id="c-cloud-test">Test</button></div>
      </div>
      <h2>Clips</h2>
      <div class="card" id="c-clips"><div class="pad hint">Loading…</div></div>
      <div id="c-player" style="margin-top:12px" hidden><video id="c-video" controls playsinline></video><div class="btnrow" style="margin-top:8px"><button class="btn" id="c-close">Close</button><button class="btn danger" id="c-del">Delete clip</button></div></div>
      <h2>Archive in the cloud</h2>
      <div class="card" id="c-archive"><div class="pad hint">Loading…</div></div>`;
    const v = $("#v-camera");
    v.querySelectorAll("#c-mode button").forEach(b => b.onclick = () => api("camera", "set_mode", { mode: b.dataset.v }).then(poll));
    const cfg = () => (R.config.camera || {});
    $("#c-sec").onclick = () => saveConfig({ camera: { security: { enabled: !cfg().security.enabled } } }).then(render);
    $("#c-away").onclick = () => saveConfig({ camera: { security: { only_when_away: !cfg().security.only_when_away } } }).then(render);
    $("#c-notify").onclick = () => saveConfig({ camera: { security: { notify_always: !cfg().security.notify_always } } }).then(render);
    $("#c-sens").onchange = e => saveConfig({ camera: { motion: { sensitivity: +e.target.value } } }).then(render);
    $("#c-cloud-test").onclick = async () => { const r = await api("camera", "cloud_test"); toast(r.ok ? "Cloud upload works" : "Cloud: " + (r.error || "failed"), r.ok ? "good" : "warning"); };
    $("#c-refresh").onclick = () => { clipsCache.t = 0; cloudDays = null; loadClips(); };
    $("#c-close").onclick = () => { $("#c-player").hidden = true; $("#c-video").pause(); $("#c-video").removeAttribute("src"); };
    wireIntercom(v);
    loadClips();
  }
  // ---------------------------------------------------------------- INTERCOM (listen / hold to talk / say)
  let icAudio = null, icRec = null, icChunks = [], icStart = 0, icTimer = null;
  function icStatus(t, cls) { const el = $("#ic-status"); if (!el) return; el.textContent = t; el.className = "hint" + (cls ? " " + cls : ""); }
  function icStopListen() {
    if (icAudio) { try { icAudio.pause(); icAudio.removeAttribute("src"); icAudio.load(); } catch (e) {} icAudio = null; }
    const b = $("#ic-listen"); if (b) { b.textContent = "Listen"; b.classList.remove("on"); }
  }
  async function icToggleListen() {
    if (icAudio) { icStopListen(); icStatus("Stopped listening."); return; }
    const st = await api("intercom", "status").catch(() => null);
    if (st && st.mic_enabled === false) { icStatus("The microphone is muted on the HomeDeck, so listening is off.", "err"); return; }
    const a = new Audio(); a.setAttribute("playsinline", ""); a.playsInline = true; a.preload = "none";
    a.src = "/intercom/listen?fmt=mp3&t=" + Date.now();
    icAudio = a;
    a.onerror = () => { if (icAudio === a) { icStopListen(); icStatus("Could not open the room audio.", "err"); } };
    a.onplaying = () => { if (icAudio === a) icStatus("Listening to the room…"); };
    try { await a.play(); } catch (e) { icStopListen(); icStatus("Playback blocked: " + (e.message || e), "err"); return; }
    const b = $("#ic-listen"); b.textContent = "Stop listening"; b.classList.add("on");
    icStatus("Connecting…");
  }
  function icMime() {
    if (!window.MediaRecorder) return null;
    for (const m of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) if (MediaRecorder.isTypeSupported(m)) return m;
    return "";
  }
  async function icTalkStart(ev) {
    ev.preventDefault();
    if (icRec) return;
    const mime = icMime();
    if (mime === null || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { icStatus("This browser can't record audio. Use the Say box instead.", "err"); return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
    catch (e) { icStatus("Microphone permission is needed to talk.", "err"); return; }
    icChunks = []; icStart = Date.now();
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 32000 } : undefined);
    icRec = rec;
    rec.ondataavailable = e => { if (e.data && e.data.size) icChunks.push(e.data); };
    rec.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const secs = (Date.now() - icStart) / 1000; icRec = null; $("#ic-talk").classList.remove("live");
      if (secs < 0.4 || !icChunks.length) { icStatus("Hold the button while you speak."); return; }
      const blob = new Blob(icChunks, { type: rec.mimeType || mime || "audio/webm" });
      if (blob.size > 700 * 1024) { icStatus("That was too long to send. Keep it under 20 seconds.", "err"); return; }
      icStatus(`Sending ${secs.toFixed(1)} s…`);
      const b64 = await new Promise(ok => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1] || ""); r.readAsDataURL(blob); });
      try {
        const res = await fetch("/intercom/talk", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ audio: b64, type: blob.type, seconds: secs }) });
        const j = await res.json().catch(() => ({}));
        icStatus(j.ok ? "Playing on the HomeDeck." : "Could not send: " + (j.error || res.status), j.ok ? "" : "err");
      } catch (e) { icStatus("Could not send: " + (e.message || e), "err"); }
    };
    rec.start(250);
    $("#ic-talk").classList.add("live"); icStatus("Recording… release to send.");
    clearTimeout(icTimer); icTimer = setTimeout(() => icTalkStop(), 20000);
  }
  function icTalkStop(ev) {
    if (ev) ev.preventDefault();
    clearTimeout(icTimer);
    if (icRec && icRec.state !== "inactive") { try { icRec.stop(); } catch (e) {} }
  }
  function wireIntercom(v) {
    const listen = v.querySelector("#ic-listen"), talk = v.querySelector("#ic-talk"), say = v.querySelector("#ic-say"), go = v.querySelector("#ic-say-go");
    if (!listen) return;
    listen.onclick = icToggleListen;
    talk.addEventListener("pointerdown", icTalkStart); talk.addEventListener("pointerup", icTalkStop); talk.addEventListener("pointercancel", icTalkStop); talk.addEventListener("pointerleave", icTalkStop);
    talk.addEventListener("contextmenu", e => e.preventDefault());
    const doSay = async () => { const t = say.value.trim(); if (!t) return; await api("voice", "say", { text: t }); say.value = ""; icStatus("Said it on the HomeDeck."); };
    go.onclick = doSay; say.onkeydown = e => { if (e.key === "Enter") doSay(); };
    document.addEventListener("visibilitychange", () => { if (document.hidden) { icStopListen(); icTalkStop(); } });
  }
  async function loadClips() {
    if (Date.now() - clipsCache.t < 20000) return;
    const r = await api("camera", "list_clips"); clipsCache = { t: Date.now(), clips: r.clips || [] };
    if (cloudDays === null) { const c = await api("camera", "cloud_status"); cloudDays = c; }
    renderClips();
  }
  function renderClips() {
    const box = $("#c-clips"); if (!box) return;
    const byDay = {}; for (const c of clipsCache.clips) (byDay[c.date] = byDay[c.date] || []).push(c);
    const days = Object.keys(byDay).sort().reverse();
    if (!days.length) { setHtml(box, `<div class="pad hint">No clips yet. Clips appear here when motion is detected.</div>`); return; }
    setHtml(box, days.map(d => `<div class="row" style="min-height:40px"><div class="k">${esc(fmtDay(d + "T12:00:00"))}</div><div class="v">${byDay[d].length} clip${byDay[d].length === 1 ? "" : "s"}</div></div><div class="clipgrid">${byDay[d].sort((a, b) => b.start - a.start).map(c => `<button class="clip" data-url="${esc(c.url)}" data-file="${esc(c.file)}">${c.thumb_url ? `<img src="${esc(c.thumb_url)}" alt="">` : ""}<span class="t">${fmtTime(c.start)}</span>${c.uploaded ? `<span class="cloud" title="In the cloud">${icon("cloud", "")}</span>` : ""}</button>`).join("")}</div>`).join(""));
    box.querySelectorAll(".clip").forEach(b => b.onclick = () => { const p = $("#c-player"); p.hidden = false; const vid = $("#c-video"); vid.src = b.dataset.url; vid.play().catch(() => {}); p.scrollIntoView({ behavior: "smooth", block: "center" });
      $("#c-del").onclick = async () => { if (!confirm("Delete this clip from the device?")) return; await api("camera", "delete_clip", { file: b.dataset.file }); clipsCache.t = 0; $("#c-player").hidden = true; loadClips(); }; });
  }
  function renderCamera() {
    const s = R.state, c = s.camera || {}, cfg = R.config.camera || {}, armed = !!(cfg.security || {}).enabled;
    setText($("#c-sub"), c.recording ? "Recording motion now" : c.last_motion_ts ? `Last motion ${fmtTime(c.last_motion_ts)} · ${c.clips_today || 0} clips today` : `${c.clips_today || 0} clips today`);
    const live = $("#c-live");
    if (c.mode === "on") { if (!live.querySelector("img")) live.innerHTML = `<img src="/camera/stream" alt="Live view">`; }
    else setHtml(live, `<div class="overlay"><div>${icon("camoff")}</div><div>${c.mode === "off" ? "Camera is off" : "Live view is off in privacy mode"}<br><span class="hint" style="color:#bbb">${c.mode === "off" ? "Nothing is captured" : armed ? "Motion clips still record" : "Motion recording is off"}</span></div><button class="btn primary" onclick="HDR.api('camera','set_mode',{mode:'on'}).then(HDR.poll)">Turn on live view</button></div>`);
    document.querySelectorAll("#c-mode button").forEach(b => b.classList.toggle("on", b.dataset.v === (c.mode || "privacy")));
    setText($("#c-mode-hint"), c.mode === "on" ? (armed ? "Live view on this phone. Motion clips record." : "Live view on this phone. Motion recording is off.") : c.mode === "privacy" ? (armed ? "No live view anywhere. Motion clips still record." : "No live view anywhere. Motion recording is off.") : "Camera fully stopped. Nothing records.");
    const sec = cfg.security || {}; $("#c-sec").classList.toggle("on", !!sec.enabled); $("#c-away").classList.toggle("on", !!sec.only_when_away); $("#c-notify").classList.toggle("on", !!sec.notify_always);
    const sens = (cfg.motion || {}).sensitivity ?? 5; if (document.activeElement !== $("#c-sens")) $("#c-sens").value = sens; setText($("#c-sens-v"), `${sens} of 10`);
    const cl = c.cloud || {}; setText($("#c-cloud-sub"), cl.enabled ? (cl.last_error ? "Error: " + cl.last_error : cl.queue_len ? `${cl.queue_len} waiting to upload` : cl.last_upload_ts ? `Last upload ${fmtTime(cl.last_upload_ts)}` : "Ready") : "Off");
    if (cloudDays && cloudDays.configured !== undefined) renderArchive();
    if (R.tab === "camera") loadClips();
  }
  async function renderArchive() {
    const box = $("#c-archive"); if (!box || box.dataset.done) return; box.dataset.done = "1";
    const days = [...new Set(clipsCache.clips.map(c => c.date))].sort().reverse().slice(0, 7);
    const parts = [];
    for (const d of days) { const r = await api("camera", "cloud_list", { date: d }); const vids = (r.entries || []).filter(e => e.name.endsWith(".mp4")); if (vids.length) parts.push(`<div class="row" style="min-height:40px"><div class="k">${esc(fmtDay(d + "T12:00:00"))}</div><div class="v">${vids.length} in Drive</div></div><div class="clipgrid">${vids.map(v => `<button class="clip" data-url="/camera/cloud_clip?f=${encodeURIComponent(d + "/" + v.name)}"><img src="/camera/thumb?f=${encodeURIComponent(d + "/" + v.name.replace(".mp4", ".jpg"))}" alt=""><span class="t">${esc(v.name.slice(0, 2))}:${esc(v.name.slice(2, 4))}</span></button>`).join("")}</div>`); }
    setHtml(box, parts.length ? parts.join("") : `<div class="pad hint">${cloudDays.configured ? "Nothing in the archive yet." : "Cloud archive isn't connected."}</div>`);
    box.querySelectorAll(".clip").forEach(b => b.onclick = () => { const p = $("#c-player"); p.hidden = false; const vid = $("#c-video"); vid.src = b.dataset.url; vid.play().catch(() => {}); $("#c-del").onclick = () => toast("Cloud clips are managed in Drive"); p.scrollIntoView({ behavior: "smooth", block: "center" }); });
  }

  // ---------------------------------------------------------------- MUSIC
  let plCache = null, recentCache = null;
  function buildMusic() {
    $("#v-music").innerHTML = `
      <h1>Music<small id="m-sub"></small></h1>
      <div class="card" id="m-np"><div class="np"><img class="art" id="m-art" alt=""><div class="title" id="m-title">Not playing</div><div class="artist" id="m-artist">Choose something below</div>
        <div class="prog" id="m-prog"><i id="m-bar"></i></div><div class="times"><span id="m-t1">0:00</span><span id="m-t2">0:00</span></div>
        <div class="transport"><button class="sm" id="m-shuffle" aria-label="Shuffle">${icon("shuffle", "")}</button><button id="m-prev" aria-label="Previous">${icon("back", "")}</button><button class="play" id="m-play" aria-label="Play or pause">${icon("play", "")}</button><button id="m-next" aria-label="Next">${icon("fwd", "")}</button><span style="width:48px"></span></div>
        <div class="volrow">${icon("vol")}<input type="range" id="m-vol" min="0" max="100" aria-label="Volume"></div></div>
        <div class="pad hint" id="m-hint" style="border-top:1px solid var(--line)"></div></div>
      <h2>Search</h2>
      <div class="card"><div class="pad"><div class="inline"><input type="text" id="m-q" placeholder="Song, album or playlist"><button class="btn primary" id="m-go">${icon("search", "")}</button></div></div><div id="m-results"></div></div>
      <h2>Playlists</h2>
      <div class="card" id="m-playlists"><div class="pad hint">Loading…</div></div>
      <h2>Recently played</h2>
      <div class="card" id="m-recent"><div class="pad hint">Loading…</div></div>
      <h2>YouTube on the HomeDeck</h2>
      <div class="card"><div class="pad"><div class="inline"><input type="text" id="yt-q" placeholder="Paste a link or search" autocomplete="off"><button class="btn primary" id="yt-go">Play</button></div><div class="hint" id="yt-msg" style="margin-top:8px">Plays on the HomeDeck screen.</div></div></div>`;
    const ytGo = async () => { const q = $("#yt-q").value.trim(); if (!q) return; setText($("#yt-msg"), "Sending…"); const r = await api("youtube", "play", { q }); setText($("#yt-msg"), r && r.ok ? `Playing: ${(r.video && r.video.title) || q}` : (r && r.error) || "Could not play that"); if (r && r.ok) $("#yt-q").value = ""; };
    $("#yt-go").onclick = ytGo; $("#yt-q").onkeydown = e => { if (e.key === "Enter") ytGo(); };
    $("#m-play").onclick = () => { const n = (R.state.spotify || {}).now; api("spotify", n && n.playing ? "pause" : "play", {}).then(poll); };
    $("#m-prev").onclick = () => api("spotify", "prev").then(poll); $("#m-next").onclick = () => api("spotify", "next").then(poll);
    $("#m-shuffle").onclick = () => { const n = (R.state.spotify || {}).now; api("spotify", "shuffle", { on: !(n && n.shuffle) }).then(poll); };
    $("#m-vol").onchange = e => api("audio", "set_volume", { pct: +e.target.value, target: "music" }).then(poll);
    $("#m-prog").onclick = e => { const n = (R.state.spotify || {}).now; if (!n || !n.duration_ms) return; const r = e.currentTarget.getBoundingClientRect(); api("spotify", "seek", { ms: Math.round((e.clientX - r.left) / r.width * n.duration_ms) }).then(poll); };
    const go = async () => { const q = $("#m-q").value.trim(); if (!q) return; setHtml($("#m-results"), `<div class="pad hint">Searching…</div>`); const r = await api("spotify", "search", { q }); const items = r.items || [];
      const groups = [["track", "Tracks"], ["album", "Albums"], ["playlist", "Playlists"]];
      setHtml($("#m-results"), items.length ? groups.map(([t, lbl]) => { const g = items.filter(i => i.type === t); return g.length ? `<div class="row" style="min-height:36px;border-top:1px solid var(--line)"><div class="k hint">${lbl}</div></div>` + g.map(i => `<div class="trackrow"><img src="${esc(i.art_url || "")}" alt=""><div class="meta"><div>${esc(i.name)}</div><small>${esc(i.artist || i.owner || "")}</small></div><button class="btn small" data-play="${esc(i.uri)}">Play</button>${t === "track" ? `<button class="btn small" data-queue="${esc(i.uri)}">Queue</button>` : ""}</div>`).join("") : ""; }).join("") : `<div class="pad hint">${r.error || "Nothing found."}</div>`);
      $("#m-results").querySelectorAll("[data-play]").forEach(b => b.onclick = () => api("spotify", "play", { uri: b.dataset.play }).then(r => { toast(r.ok ? "Playing on HomeDeck" : (r.error || "Couldn't play"), r.ok ? "good" : "warning"); poll(); }));
      $("#m-results").querySelectorAll("[data-queue]").forEach(b => b.onclick = () => api("spotify", "queue", { uri: b.dataset.queue }).then(r => toast(r.ok ? "Added to queue" : (r.error || "Couldn't queue"), r.ok ? "good" : "warning"))); };
    $("#m-go").onclick = go; $("#m-q").onkeydown = e => { if (e.key === "Enter") go(); };
    loadMusicLists();
  }
  async function loadMusicLists() {
    const sp = R.state.spotify || {};
    if (!sp.authenticated) { const why = !sp.configured ? "Set up Spotify in Settings to see your playlists." : "Connect Spotify to see your playlists."; setHtml($("#m-playlists"), `<div class="pad hint">${why}</div>`); setHtml($("#m-recent"), `<div class="pad hint">${!sp.configured ? "Set up Spotify in Settings first." : "Connect Spotify first."}</div>`); return; }
    if (!plCache) { const r = await api("spotify", "playlists"); plCache = r.playlists || []; }
    if (!recentCache) { const r = await api("spotify", "recent"); recentCache = r.items || []; }
    const grid = (items, empty) => items.length ? `<div class="artgrid">${items.map(p => `<button data-uri="${esc(p.uri)}"><img src="${esc(p.art_url || "")}" alt=""><div class="n">${esc(p.name)}</div></button>`).join("")}</div>` : `<div class="pad hint">${empty}</div>`;
    setHtml($("#m-playlists"), grid(plCache, "No playlists found."));
    setHtml($("#m-recent"), grid(recentCache, sp.needs_reauth ? "Reconnect Spotify in Settings to show recently played." : "Nothing played recently."));
    document.querySelectorAll("#m-playlists [data-uri], #m-recent [data-uri]").forEach(b => b.onclick = () => api("spotify", "play", { context_uri: b.dataset.uri, uri: b.dataset.uri }).then(r => { toast(r.ok ? "Playing on HomeDeck" : (r.error || "Couldn't play"), r.ok ? "good" : "warning"); poll(); }));
  }
  function renderMusic() {
    const s = R.state, sp = s.spotify || {}, n = sp.now, a = s.audio || {};
    setText($("#m-sub"), !sp.configured ? "Not set up" : !sp.authenticated ? "Not connected" : sp.device_online ? "HomeDeck speaker online" : "Speaker offline");
    if (n && n.title) { const art = $("#m-art"); if (art.src !== n.art_url) art.src = n.art_url || ""; setText($("#m-title"), n.title); setText($("#m-artist"), n.artist || ""); }
    else { setText($("#m-title"), "Not playing"); setText($("#m-artist"), "Pick a playlist or search below"); }
    const pct = n && n.duration_ms ? Math.min(100, n.progress_ms / n.duration_ms * 100) : 0; $("#m-bar").style.width = pct + "%";
    setText($("#m-t1"), mmss(n && n.progress_ms)); setText($("#m-t2"), n && n.duration_ms ? "-" + mmss(n.duration_ms - n.progress_ms) : "0:00");
    setHtml($("#m-play"), icon(n && n.playing ? "pause" : "play", "")); $("#m-shuffle").style.color = n && n.shuffle ? "var(--accent)" : "";
    if (document.activeElement !== $("#m-vol")) $("#m-vol").value = a.music_pct ?? 70;
    setHtml($("#m-hint"), !sp.configured ? "Spotify isn't set up yet. Add the Client ID in Settings › Music." : !sp.authenticated ? `<a href="/spotify/login" class="btn primary">Connect Spotify</a>` : sp.needs_reauth ? `Reconnect once to enable recently played. <a href="/spotify/login">Reconnect</a>` : sp.device_online ? "Playing through the HomeDeck speakers. Your phone's Spotify volume also controls them." : "Speaker not visible to Spotify right now.");
    if (!sp.authenticated || !plCache || !recentCache) loadMusicLists();
  }

  // ---------------------------------------------------------------- SETTINGS
  function field(label, inner) { return `<label class="field">${label}</label>${inner}`; }
  const swatchesSolid = [["Graphite", "#1c1c1e"], ["Midnight", "#0b1a33"], ["Ink", "#101418"], ["Forest", "#0f2a1f"], ["Plum", "#241633"], ["Slate", "#1f2933"], ["Sand", "#2b241c"], ["Rose", "#2a1620"]];
  const gradients = [["Dusk", ["#1b2735", "#090a0f"]], ["Ocean", ["#0f2027", "#2c5364"]], ["Moss", ["#0b2a24", "#0d3b36"]], ["Ember", ["#2b1b12", "#120c08"]], ["Steel", ["#1f2933", "#0b0f14"]], ["Night", ["#0b1a33", "#000000"]]];
  function buildSettings() {
    const c = R.config, g = c.general || {}, loc = g.location || {}, bg = g.background || { mode: "live" }, au = c.audio || {}, vo = c.voice || {}, llm = vo.llm || {}, vad = vo.vad || {}, no = c.notify || {}, pr = c.presence || {}, cal = c.calendar || {}, fan = c.fan || {}, cam = c.camera || {}, auth = c.auth || {}, sp = c.spotify || {};
    $("#v-settings").innerHTML = `
      <h1>Settings<small>${esc(g.name || "HomeDeck")}</small></h1>
      <h2>Location & format</h2>
      <div class="card"><div class="pad">
        ${field("Home address", `<div class="inline"><input type="text" id="s-addr" value="${esc(loc.address || "")}"><button class="btn" id="s-geo">Look up</button></div>`)}<div class="hint" id="s-geo-out"></div>
        <div class="inline" style="margin-top:12px"><div style="flex:1"><label class="field" style="margin-top:0">Clock</label><div class="seg" data-cfg="clock_24h"><button data-v="false" class="${g.clock_24h ? "" : "on"}">12 h</button><button data-v="true" class="${g.clock_24h ? "on" : ""}">24 h</button></div></div>
        <div style="flex:1"><label class="field" style="margin-top:0">Units</label><div class="seg" data-cfg="units"><button data-v="imperial" class="${g.units !== "metric" ? "on" : ""}">°F</button><button data-v="metric" class="${g.units === "metric" ? "on" : ""}">°C</button></div></div></div>
        <div class="btnrow" style="margin-top:12px"><button class="btn primary" id="s-loc-save">Save location</button></div></div></div>
      <h2>Device screen</h2>
      <div class="card"><div class="pad">
        <label class="field" style="margin-top:0">Home style</label><div class="seg" id="s-style">${[["weather", "Weather"], ["board", "Board"], ["clockfirst", "Clock"], ["ambient", "Ambient"]].map(([v, l]) => `<button data-v="${v}" class="${(g.home_style || "board") === v ? "on" : ""}">${l}</button>`).join("")}</div>
        <label class="field">Background</label><div class="seg" id="s-bg"><button data-v="live" class="${bg.mode === "live" || !bg.mode ? "on" : ""}">Live sky</button><button data-v="solid" class="${bg.mode === "solid" ? "on" : ""}">Solid</button><button data-v="gradient" class="${bg.mode === "gradient" ? "on" : ""}">Gradient</button></div>
        <div class="swatches" id="s-bg-solid" style="margin-top:10px" ${bg.mode === "solid" ? "" : "hidden"}>${swatchesSolid.map(([n, h]) => `<button class="swatch ${bg.color === h ? "on" : ""}" data-c="${h}" title="${n}" style="background:${h}"></button>`).join("")}<input type="color" id="s-bg-custom" value="${esc(bg.color || "#1c1c1e")}" style="width:34px;height:34px;padding:0;border:0;background:none"></div>
        <div class="swatches" id="s-bg-grad" style="margin-top:10px" ${bg.mode === "gradient" ? "" : "hidden"}>${gradients.map(([n, gg]) => `<button class="swatch ${JSON.stringify(bg.gradient) === JSON.stringify(gg) ? "on" : ""}" data-g="${gg.join(",")}" title="${n}" style="background:linear-gradient(180deg,${gg[0]},${gg[1]})"></button>`).join("")}</div>
      </div>
      <div id="s-tiles"></div></div>
      <h2>Audio</h2>
      <div class="card"><div class="row"><div class="k">Volume at startup</div><input type="range" id="s-vol" min="5" max="100" value="${au.default_volume ?? 55}" style="width:140px"><div class="v" id="s-vol-v" style="width:40px">${au.default_volume ?? 55}%</div></div>
        <div class="row"><div class="k">Night maximum</div><input type="range" id="s-nvol" min="5" max="100" value="${au.night_max_pct ?? 35}" style="width:140px"><div class="v" id="s-nvol-v" style="width:40px">${au.night_max_pct ?? 35}%</div></div></div>
      <h2>Jarvis</h2>
      <div class="card"><div class="pad">
        ${field("Answers from", `<select id="s-prov"></select>`)}<div id="s-prov-fields"></div>
        ${field("Voice", `<div class="inline"><select id="s-voice"></select><button class="btn" id="s-voice-prev">Preview</button></div>`)}
        ${field("Silence before answering (seconds)", `<input type="number" id="s-sil" step="0.1" min="0.3" max="3" value="${vad.silence_s ?? 0.65}">`)}
        <div class="btnrow" style="margin-top:12px"><button class="btn primary" id="s-jarvis-save">Save</button><button class="btn" id="s-jarvis-test">Test</button></div><div class="hint" id="s-jarvis-out" style="margin-top:8px"></div></div></div>
      <h2>Notifications</h2>
      <div class="card"><div class="row"><div class="k">ntfy topic<small>Subscribe in the ntfy app to get alerts here</small></div><div class="v" style="font-family:ui-monospace,monospace;white-space:normal">${esc(no.ntfy_topic || "")}</div></div>
        <div class="row"><div class="k">Attach motion snapshots</div><button class="switch ${no.attach_images ? "on" : ""}" id="s-attach"></button></div>
        <div class="pad"><button class="btn" id="s-ntest">Send a test notification</button></div></div>
      <h2>Presence</h2>
      <div class="card"><div class="pad"><div class="hint">Phones on the home Wi-Fi mean someone is home. Enter each phone's IP or MAC address.</div><div id="s-phones" style="margin-top:8px"></div><div class="btnrow" style="margin-top:10px"><button class="btn" id="s-phone-add">Add phone</button><button class="btn primary" id="s-phone-save">Save</button></div></div></div>
      <h2>Calendar</h2>
      <div class="card"><div class="pad">${field("Private iCal links, one per line", `<textarea id="s-ics" rows="3">${esc((cal.ics_urls || []).join("\n"))}</textarea>`)}<div class="btnrow" style="margin-top:10px"><button class="btn primary" id="s-ics-save">Save</button></div></div></div>
      <h2>Bay Wheels stations</h2>
      <div class="card" id="s-bikes"><div class="pad hint">Loading nearby stations…</div></div>
      <h2>Fan</h2>
      <div class="card"><div class="pad"><div class="inline">${["on_c", "off_c", "full_c"].map(k => `<div style="flex:1"><label class="field" style="margin-top:0">${{ on_c: "On above", off_c: "Off below", full_c: "Full at" }[k]} °C</label><input type="number" id="s-fan-${k}" value="${(fan.auto || {})[k] ?? ""}"></div>`).join("")}</div><div class="btnrow" style="margin-top:10px"><button class="btn primary" id="s-fan-save">Save</button></div></div></div>
      <h2>Music</h2>
      <div class="card"><div class="pad">${field("Spotify Client ID", `<input type="text" id="s-spid" value="${esc(sp.client_id || "")}">`)}<div class="btnrow" style="margin-top:10px"><button class="btn primary" id="s-sp-save">Save</button><a class="btn" href="/spotify/login">Connect / Reconnect</a></div></div></div>
      <h2>Camera cloud</h2>
      <div class="card"><div class="pad">${field("rclone remote and folder", `<input type="text" id="s-cloud" value="${esc((cam.cloud || {}).rclone_remote || "")}">`)}<div class="row" style="padding:8px 0"><div class="k">Delete local copy after upload</div><button class="switch ${(cam.cloud || {}).delete_local_after_upload ? "on" : ""}" id="s-cloud-del"></button></div><div class="btnrow"><button class="btn primary" id="s-cloud-save">Save</button></div></div></div>
      <h2>Remote access</h2>
      <div class="card"><div class="row"><div class="k">Sign-in required</div><div class="v ${auth.enabled ? "good" : ""}">${auth.enabled ? "On" : "Off"}</div></div>
        <div class="row"><div class="k">Address</div><div class="v">${esc(auth.public_host || "")}</div></div>
        <div class="row"><div class="k">Allowed accounts</div><div class="v" style="white-space:normal">${esc((auth.allowed_emails || []).join(", "))}</div></div>
        <div class="row"><div class="k">Stay signed in for</div><div class="v"><input type="number" id="s-sess" value="${auth.session_days ?? 30}" style="width:70px;min-height:36px;padding:6px 8px"> days</div></div>
        <div class="row"><div class="k">Device tokens<small id="s-tok-sub"></small></div><button class="btn small" id="s-tok-new">Create</button></div>
        <div class="pad btnrow"><button class="btn" id="s-signout-all">Sign out everywhere</button><a class="btn danger" href="/auth/logout">Sign out</a></div></div>
      <div class="hint" style="margin:20px 4px 0">HomeDeck Remote · everything runs on the device at home; this page only talks to it.</div>`;
    const v = $("#v-settings");
    v.querySelectorAll('.seg[data-cfg] button').forEach(b => b.onclick = async () => { const seg = b.parentElement; const val = b.dataset.v === "true" ? true : b.dataset.v === "false" ? false : b.dataset.v; await saveConfig({ general: { [seg.dataset.cfg]: val } }); seg.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); toast("Saved", "good"); });
    $("#s-geo").onclick = async () => { const r = await api("weather", "geocode", { address: $("#s-addr").value }); setText($("#s-geo-out"), r.ok ? "Found: " + r.display : (r.error || "Not found")); if (r.ok) R._geo = r; };
    $("#s-loc-save").onclick = async () => { const p = { general: { location: { address: $("#s-addr").value } } }; if (R._geo) Object.assign(p.general.location, { lat: R._geo.lat, lon: R._geo.lon, city: R._geo.city || loc.city, zip: R._geo.zip || loc.zip }); await saveConfig(p); toast("Location saved", "good"); api("weather", "refresh"); api("bikes", "refresh"); };
    v.querySelectorAll("#s-style button").forEach(b => b.onclick = async () => { await saveConfig({ general: { home_style: b.dataset.v } }); v.querySelectorAll("#s-style button").forEach(x => x.classList.toggle("on", x === b)); toast("Home style: " + b.textContent, "good"); });
    v.querySelectorAll("#s-bg button").forEach(b => b.onclick = async () => { await saveConfig({ general: { background: { mode: b.dataset.v } } }); v.querySelectorAll("#s-bg button").forEach(x => x.classList.toggle("on", x === b)); $("#s-bg-solid").hidden = b.dataset.v !== "solid"; $("#s-bg-grad").hidden = b.dataset.v !== "gradient"; });
    v.querySelectorAll("#s-bg-solid .swatch").forEach(b => b.onclick = async () => { await saveConfig({ general: { background: { mode: "solid", color: b.dataset.c } } }); v.querySelectorAll("#s-bg-solid .swatch").forEach(x => x.classList.toggle("on", x === b)); });
    $("#s-bg-custom").onchange = e => saveConfig({ general: { background: { mode: "solid", color: e.target.value } } });
    v.querySelectorAll("#s-bg-grad .swatch").forEach(b => b.onclick = async () => { await saveConfig({ general: { background: { mode: "gradient", gradient: b.dataset.g.split(",") } } }); v.querySelectorAll("#s-bg-grad .swatch").forEach(x => x.classList.toggle("on", x === b)); });
    renderTilesEditor();
    $("#s-vol").oninput = e => setText($("#s-vol-v"), e.target.value + "%"); $("#s-vol").onchange = e => saveConfig({ audio: { default_volume: +e.target.value } }).then(() => toast("Saved", "good"));
    $("#s-nvol").oninput = e => setText($("#s-nvol-v"), e.target.value + "%"); $("#s-nvol").onchange = e => saveConfig({ audio: { night_max_pct: +e.target.value } }).then(() => toast("Saved", "good"));
    loadJarvis();
    $("#s-jarvis-save").onclick = async () => { const part = { voice: { llm: { provider: $("#s-prov").value }, vad: { silence_s: +$("#s-sil").value || 0.65 } } }; v.querySelectorAll("#s-prov-fields input[data-key]").forEach(i => { const val = i.value.trim(); if (val && !val.startsWith("•")) part.voice.llm[i.dataset.key] = val; }); v.querySelectorAll("#s-prov-fields input[data-model]").forEach(i => { if (i.value.trim()) part.voice.llm[i.dataset.model] = i.value.trim(); }); await saveConfig(part); toast("Saved", "good"); loadJarvis(); };
    $("#s-jarvis-test").onclick = async () => { setText($("#s-jarvis-out"), "Testing…"); const r = await api("voice", "llm_test"); setText($("#s-jarvis-out"), r.ok ? `${r.answer} (${r.ms} ms via ${r.provider})` : (r.answer || r.error || "Failed")); };
    $("#s-voice").onchange = async e => { const r = await api("voice", "set_voice", { id: e.target.value }); toast(r.status === "downloading" ? "Downloading voice…" : "Voice set", "good"); };
    $("#s-voice-prev").onclick = () => api("voice", "preview");
    $("#s-attach").onclick = async () => { const on = !$("#s-attach").classList.contains("on"); await saveConfig({ notify: { attach_images: on } }); $("#s-attach").classList.toggle("on", on); };
    $("#s-ntest").onclick = async () => { const r = await api("notify", "test"); toast(r.ok ? "Sent" : "Failed: " + (r.error || ""), r.ok ? "good" : "warning"); };
    let phones = JSON.parse(JSON.stringify(pr.phones || []));
    const drawPhones = () => { setHtml($("#s-phones"), phones.map((p, i) => `<div class="inline" style="margin-top:6px"><input type="text" data-i="${i}" data-f="name" placeholder="Name" value="${esc(p.name || "")}"><input type="text" data-i="${i}" data-f="ip" placeholder="IP or MAC" value="${esc(p.ip || p.mac || "")}"><button class="btn small danger" data-del="${i}">${icon("trash", "")}</button></div>`).join("") || `<div class="hint">No phones yet.</div>`);
      $("#s-phones").querySelectorAll("input").forEach(i => i.onchange = e => { const p = phones[+e.target.dataset.i]; const val = e.target.value.trim(); if (e.target.dataset.f === "name") p.name = val; else if (/^([0-9a-f]{2}:){5}[0-9a-f]{2}$/i.test(val)) { p.mac = val; delete p.ip; } else { p.ip = val; delete p.mac; } });
      $("#s-phones").querySelectorAll("[data-del]").forEach(b => b.onclick = () => { phones.splice(+b.dataset.del, 1); drawPhones(); }); };
    drawPhones();
    $("#s-phone-add").onclick = () => { phones.push({ name: "My phone", ip: "" }); drawPhones(); };
    $("#s-phone-save").onclick = async () => { await api("presence", "set_phones", { phones: phones.filter(p => p.ip || p.mac) }); toast("Presence saved", "good"); };
    $("#s-ics-save").onclick = async () => { const urls = $("#s-ics").value.split("\n").map(x => x.trim()).filter(Boolean); const r = await api("calendar", "set_urls", { urls }); toast(r.ok ? "Calendar saved" : "Couldn't save", r.ok ? "good" : "warning"); };
    loadBikes();
    $("#s-fan-save").onclick = async () => { await saveConfig({ fan: { auto: { on_c: +$("#s-fan-on_c").value, off_c: +$("#s-fan-off_c").value, full_c: +$("#s-fan-full_c").value } } }); toast("Fan saved", "good"); };
    $("#s-sp-save").onclick = async () => { await saveConfig({ spotify: { client_id: $("#s-spid").value.trim() } }); toast("Saved", "good"); };
    $("#s-cloud-save").onclick = async () => { await saveConfig({ camera: { cloud: { rclone_remote: $("#s-cloud").value.trim(), delete_local_after_upload: $("#s-cloud-del").classList.contains("on") } } }); toast("Saved", "good"); };
    $("#s-cloud-del").onclick = () => $("#s-cloud-del").classList.toggle("on");
    $("#s-sess").onchange = e => saveConfig({ auth: { session_days: +e.target.value } }).then(() => toast("Saved", "good"));
    $("#s-tok-new").onclick = async () => { const name = prompt("Name this device token", "My phone"); if (!name) return; const r = await api("auth", "create_token", { name }); if (r.token) prompt("Copy this token now, it is shown once:", r.token); else toast(r.error || "Failed", "warning"); render(); };
    $("#s-signout-all").onclick = async () => { if (!confirm("Sign out every phone and browser?")) return; await api("auth", "logout_all"); location.href = "/auth/login"; };
  }
  function renderTilesEditor() {
    const box = $("#s-tiles"); if (!box) return;
    const g = R.config.general || {}, hidden = new Set(g.home_hidden || ["lists"]), order = g.home_order || [];
    const all = [["sensors", "Air"], ["weather", "Weather"], ["spotify", "Music"], ["leds", "Lights"], ["alarms", "Alarm"], ["fan", "Fan"], ["lists", "Shopping"], ["reminders", "Reminders"], ["bikes", "E-bikes"], ["calendar", "Next up"], ["timers", "Timer"]];
    const rank = id => { const i = order.indexOf(id); return i < 0 ? 1000 + all.findIndex(a => a[0] === id) : i; };
    const sorted = all.slice().sort((a, b) => rank(a[0]) - rank(b[0]));
    setHtml(box, `<div class="row" style="min-height:36px"><div class="k hint">Home screen tiles</div></div>` + sorted.map(([id, t], i) => `<div class="row"><div class="k">${t}</div><button class="btn small" data-mv="${id}" data-d="-1" ${i === 0 ? "disabled" : ""}>Up</button><button class="btn small" data-mv="${id}" data-d="1" ${i === sorted.length - 1 ? "disabled" : ""}>Down</button><button class="switch ${hidden.has(id) ? "" : "on"}" data-tg="${id}"></button></div>`).join(""));
    box.querySelectorAll("[data-tg]").forEach(b => b.onclick = async () => { const h = new Set(hidden); h.has(b.dataset.tg) ? h.delete(b.dataset.tg) : h.add(b.dataset.tg); await saveConfig({ general: { home_hidden: [...h] } }); renderTilesEditor(); });
    box.querySelectorAll("[data-mv]").forEach(b => b.onclick = async () => { const ids = sorted.map(a => a[0]); const i = ids.indexOf(b.dataset.mv), j = i + (+b.dataset.d); if (j < 0 || j >= ids.length) return; [ids[i], ids[j]] = [ids[j], ids[i]]; await saveConfig({ general: { home_order: ids } }); renderTilesEditor(); });
  }
  async function loadJarvis() {
    const r = await api("voice", "providers"); const sel = $("#s-prov"); if (!sel || !r.providers) return;
    sel.innerHTML = r.providers.map(p => `<option value="${p.id}" ${p.current ? "selected" : ""}>${esc(p.label)}${p.configured || !p.needs_key ? "" : " · needs key"}</option>`).join("");
    const draw = () => { const id = sel.value, llm = (R.config.voice || {}).llm || {}; const keyName = { groq: "groq_key", gemini: "gemini_key", anthropic: "api_key" }[id]; const modelName = { groq: "groq_fast_model", gemini: "gemini_model", anthropic: "model", local: "local_model" }[id];
      const notes = { groq: "Free key at console.groq.com", gemini: "Free key at aistudio.google.com/apikey", anthropic: "Paid, console.anthropic.com", local: "Runs on the device, slow", openai_compat: "Any OpenAI-compatible server" };
      setHtml($("#s-prov-fields"), `${keyName ? field("API key", `<input type="password" data-key="${keyName}" placeholder="${llm[keyName + "_set"] ? "Saved · paste to replace" : "Paste key"}">`) : ""}${modelName ? field("Model", `<input type="text" data-model="${modelName}" value="${esc(llm[modelName] || "")}">`) : ""}<div class="hint" style="margin-top:6px">${notes[id] || ""}</div>`); };
    sel.onchange = draw; draw();
    const vr = await api("voice", "voices"); const vs = $("#s-voice"); if (vs && vr.voices) vs.innerHTML = vr.voices.map(v => `<option value="${v.id}" ${v.current ? "selected" : ""}>${esc(v.label)}${v.status === "ready" ? "" : " · " + v.status}</option>`).join("");
  }
  async function loadBikes() {
    const box = $("#s-bikes"); const r = await api("bikes", "nearby"); const st = r.stations || []; const chosen = new Set(((R.config.bikes || {}).stations) || []);
    setHtml(box, st.length ? st.slice(0, 12).map(s => `<div class="row"><div class="k">${esc(s.name)}<small>${s.dist_m} m · ${s.ebikes} e-bikes now</small></div><button class="switch ${chosen.has(s.id) || s.chosen ? "on" : ""}" data-id="${s.id}"></button></div>`).join("") + `<div class="pad hint">The first switched-on station is the primary one on the home screen.</div>` : `<div class="pad hint">No stations found near the saved address.</div>`);
    box.querySelectorAll("[data-id]").forEach(b => b.onclick = async () => { b.classList.toggle("on"); const ids = [...box.querySelectorAll("[data-id].on")].map(x => x.dataset.id); await api("bikes", "set_stations", { ids }); toast("Stations saved", "good"); });
  }
  function renderSettings() { const a = R.state.auth || {}; setText($("#s-tok-sub"), `${(a.tokens || []).length} active · sessions ${a.sessions_active ?? 0}`); }

  // ---------------------------------------------------------------- boot
  const BUILD = { home: buildHome, camera: buildCamera, music: buildMusic, settings: buildSettings };
  const RENDER = { home: renderHome, camera: renderCamera, music: renderMusic, settings: renderSettings };
  function render() { try { if (R.rendered[R.tab]) RENDER[R.tab](); } catch (e) { console.error(e); } }
  window.HDR = { api, poll, saveConfig };
  document.addEventListener("DOMContentLoaded", async () => {
    document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
    await loadConfig();
    const want = new URLSearchParams(location.search).get("tab");
    await poll();
    showTab(["home", "camera", "music", "settings"].includes(want) ? want : "home");
    setInterval(poll, 3000); setInterval(loadConfig, 60000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
  });
})();
