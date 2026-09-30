/* Spotify app: a Spotify Connect client for the HomeDeck. Player, search, library (liked songs, albums, artists,
   podcasts, playlists), drill-down pages, queue, devices, like, repeat, add to playlist.
   Backend: modules/spotify.py (state under HD.state.spotify, actions via HD.api("spotify", ...)). */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const mmss = ms => { if (ms == null) return "–:––"; const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  const longer = ms => { if (ms == null) return ""; const m = Math.round(ms / 60000); return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`; };
  const api = (a, p) => HD.api("spotify", a, p || {});
  const ART = (url, cls = "") => url ? `<img class="${cls}" src="${esc(url)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'plph ${cls}',innerHTML:HD.icon('note','')}))">` : `<div class="plph ${cls}">${HD.icon("note", "")}</div>`;
  const HEART = on => `<svg viewBox="0 0 24 24" fill="${on ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M20.8 4.6a5.5 5.5 0 00-7.8 0L12 5.6l-1-1a5.5 5.5 0 00-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 000-7.8z"/></svg>`;
  const REPEAT = mode => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M17 2l4 4-4 4"/><path d="M3 11V9a4 4 0 014-4h14"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v2a4 4 0 01-4 4H3"/>${mode === "track" ? '<text x="9.2" y="15.5" font-size="8" font-weight="700" fill="currentColor" stroke="none">1</text>' : ""}</svg>`;
  const DOTS = `<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>`;
  const CHEV = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7"/></svg>`;
  let root = null, lastNowKey = "", volDragging = false, lastPlaylistsKey = "", seekDrag = null;
  const stack = [];            // sub views: {kind, uri, title, ...}
  let subState = null;         // data of the current sub view

  // ---------------------------------------------------------------- setup / player (home view)
  function setupCard(sp) {
    const redirect = location.origin + "/spotify/callback";
    const cid = (HD.config.spotify && HD.config.spotify.client_id) || "";
    if (!sp.configured) {
      return `<div class="card home">
        <h3>Connect Spotify</h3>
        <p style="font-size:15px;color:var(--fg2)">Playback needs Spotify Premium. Control needs a free developer app.</p>
        <ol class="steps">
          <li>Go to <b>developer.spotify.com/dashboard</b> and create an app.</li>
          <li>Add this redirect URI exactly:<br><code class="sel">${esc(redirect)}</code></li>
          <li>Enable the Web API, save, and paste the Client ID here.</li>
        </ol>
        <div class="row"><input id="sp-cid" class="input" placeholder="Client ID" value="${esc(cid)}" autocomplete="off"><button id="sp-save" class="btn primary">Save</button></div>
        <p class="hint">Then tap Connect Spotify and approve on Spotify's page.</p>
      </div>`;
    }
    if (!sp.authenticated) {
      return `<div class="card home">
        <h3>Connect Spotify</h3>
        <p style="font-size:15px;color:var(--fg2)">Client ID saved. Sign in to let HomeDeck control playback.</p>
        <div class="row">${HD.KIOSK ? `<button id="sp-devlogin" class="btn primary">Connect on this screen</button>` : `<a class="btn primary" href="/spotify/login" style="display:inline-flex;align-items:center">Connect Spotify</a>`}<button id="sp-edit" class="btn">Change Client ID</button></div>
        ${sp.error ? `<p class="err">${esc(sp.error)}</p>` : ""}
      </div>`;
    }
    return "";
  }

  function playerCard() {
    return `<div class="card player home">
      <div class="art-wrap"><img id="sp-art" class="art" alt="" src=""><div id="sp-noart" class="noart">${HD.icon("note", "")}</div></div>
      <div class="meta"><div class="metarow"><div id="sp-title" class="title">Not Playing</div><button class="ctl small heart" id="sp-like" aria-label="Like">${HEART(false)}</button></div><div id="sp-artist" class="artist">Choose a playlist, or send music here from your phone</div></div>
      <div class="progress" id="sp-prog"><div class="bar" id="sp-bar"></div></div>
      <div class="times"><span id="sp-t1">0:00</span><span id="sp-t2">0:00</span></div>
      <div class="controls">
        <button class="ctl small" id="sp-shuffle" aria-label="Shuffle">${HD.icon("shuffle", "")}</button>
        <button class="ctl" id="sp-prev" aria-label="Previous">${HD.icon("skip-back", "")}</button>
        <button class="ctl big" id="sp-play" aria-label="Play or pause">${HD.icon("play", "")}</button>
        <button class="ctl" id="sp-next" aria-label="Next">${HD.icon("skip-forward", "")}</button>
        <button class="ctl small" id="sp-repeat" aria-label="Repeat">${REPEAT("off")}</button>
      </div>
      <div class="volrow">${HD.icon("volume-low", "")}<input id="sp-vol" type="range" min="0" max="100" value="50" aria-label="Volume">${HD.icon("volume", "")}</div>
      <div class="subrow"><button class="pill" id="sp-queue-btn">${HD.icon("list", "")}<span>Queue</span></button><button class="pill" id="sp-devices-btn">${HD.icon("volume", "")}<span id="sp-devname">Devices</span></button><span id="sp-dev" class="hint"></span></div>
      <div id="sp-err" class="hint"></div>
    </div>`;
  }

  async function deviceLogin() {
    const r = await api("device_login");
    if (r && r.ok) HD.toast("Opening Spotify sign-in", "good"); else HD.toast((r && r.error) || "Could not open sign-in", "warning");
  }

  function wireHome(el) {
    const on = (id, ev, fn) => { const n = $(id, el); if (n) n.addEventListener(ev, fn); };
    on("#sp-save", "click", async () => { const v = $("#sp-cid", el).value.trim(); if (!v) return HD.toast("Paste the Client ID first", "warning"); await HD.saveConfig({ spotify: { client_id: v } }); HD.toast("Saved. Now tap Connect Spotify.", "good"); render(el); });
    on("#sp-devlogin", "click", deviceLogin);
    on("#sp-edit", "click", async () => { await HD.saveConfig({ spotify: { client_id: "" } }); await api("logout"); render(el); });
    on("#sp-play", "click", togglePlay);
    on("#sp-prev", "click", () => api("prev"));
    on("#sp-next", "click", () => api("next"));
    on("#sp-shuffle", "click", () => { const now = nowState(); api("shuffle", { on: !(now && now.shuffle) }); });
    on("#sp-repeat", "click", async () => { const now = nowState(); const cur = (now && now.repeat) || "off"; const next = cur === "off" ? "context" : cur === "context" ? "track" : "off"; const r = await api("repeat", { mode: next }); if (r && r.ok) { if (now) now.repeat = next; patchPlayer(HD.state, true); } });
    on("#sp-like", "click", async () => { const now = nowState(); if (!now || !now.uri || now.kind !== "track") return; const r = await api("like", { uri: now.uri, on: !now.liked }); if (r && r.ok) { now.liked = !now.liked; patchPlayer(HD.state, true); HD.toast(now.liked ? "Saved to Liked Songs" : "Removed from Liked Songs", "good", 1500); } else HD.toast((r && r.error) || "Couldn't change that", "warning"); });
    // seek: tap or drag along the bar
    const prog = $("#sp-prog", el);
    if (prog) {
      const frac = e => { const r = prog.getBoundingClientRect(); return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)); };
      prog.addEventListener("pointerdown", e => { const now = nowState(); if (!now || !now.duration_ms) return; seekDrag = { f: frac(e) }; prog.setPointerCapture(e.pointerId); $("#sp-bar", el).style.width = (seekDrag.f * 100).toFixed(1) + "%"; $("#sp-t1", el).textContent = mmss(seekDrag.f * now.duration_ms); });
      prog.addEventListener("pointermove", e => { if (!seekDrag) return; const now = nowState(); seekDrag.f = frac(e); $("#sp-bar", el).style.width = (seekDrag.f * 100).toFixed(1) + "%"; if (now) $("#sp-t1", el).textContent = mmss(seekDrag.f * now.duration_ms); });
      const done = e => { if (!seekDrag) return; const now = nowState(); const f = seekDrag.f; seekDrag = null; if (now && now.duration_ms) { now.progress_ms = Math.round(f * now.duration_ms); api("seek", { ms: now.progress_ms }); } };
      prog.addEventListener("pointerup", done); prog.addEventListener("pointercancel", done);
    }
    on("#sp-vol", "pointerdown", () => volDragging = true);
    on("#sp-vol", "change", e => { volDragging = false; HD.api("audio", "set_volume", { pct: +e.target.value, target: "music" }); });
    on("#sp-queue-btn", "click", () => openSub({ kind: "queue", title: "Queue" }));
    on("#sp-devices-btn", "click", () => openSub({ kind: "devices", title: "Devices" }));
    on("#sp-refresh", "click", async () => { await api("playlists"); HD.toast("Playlists refreshed", "good", 1200); });
    const doSearch = async () => { const q = $("#sp-q", el).value.trim(); if (!q) return; openSub({ kind: "search", title: `Results for "${q}"`, q }); };
    on("#sp-go", "click", doSearch); on("#sp-q", "keydown", e => { if (e.key === "Enter") doSearch(); });
    el.querySelectorAll(".libbtn").forEach(b => b.onclick = () => openSub({ kind: b.dataset.lib, title: b.textContent.trim() }));
    const rec = $("#sp-recent", el);
    if (rec) api("recent").then(r => { rec.innerHTML = (r.items || []).map(it => `<button class="pl" data-uri="${esc(it.uri)}">${ART(it.art_url)}<span>${esc(it.name)}</span><small>${esc(it.artist || "")}</small></button>`).join("") || `<p class="hint">Nothing played recently.</p>`;
      rec.querySelectorAll(".pl").forEach(b => b.onclick = () => playItem(b.dataset.uri, "track")); });
  }
  const nowState = () => HD.state.spotify && HD.state.spotify.now;
  async function togglePlay() { const now = nowState(); const r = now && now.playing ? await api("pause") : await api("play", {}); if (r && r.error) HD.toast(r.error, "warning"); }
  async function playItem(uri, type) { const r = await api("play", type === "track" || type === "episode" ? { uri } : { context_uri: uri }); if (r && !r.ok) HD.toast(r.error || "Could not start playback", "warning"); }

  // ---------------------------------------------------------------- home render
  // ---------------------------------------------------------------- sound: tone controls + room calibration (audio module)
  function soundCard() {
    const eq = ((HD.state && HD.state.audio) || {}).eq || {};
    const cal = eq.calibration || {}, res = cal.result;
    const slider = (id, val) => `<div class="jv-slider"><input type="range" id="${id}" min="-8" max="8" step="1" value="${val}"><div class="jv-ends"><span>Less</span><span>More</span></div></div>`;
    return `<div class="card home" id="sp-sound"><h3>Sound</h3>
      ${eq.available === false ? `<div class="hint">The equaliser is not installed on this device (install/audio_setup.sh).</div>` : ""}
      <div class="jv-field"><span class="jv-label">Bass <span class="jv-val" id="sp-bassv">${fmtDb(eq.bass)}</span></span>${slider("sp-bass", eq.bass || 0)}</div>
      <div class="jv-field"><span class="jv-label">Treble <span class="jv-val" id="sp-trebv">${fmtDb(eq.treble)}</span></span>${slider("sp-treb", eq.treble || 0)}</div>
      <div class="jv-field"><span class="jv-label">Room correction <span class="jv-val" id="sp-roomv">${roomText(eq)}</span></span>
        <div class="inline"><button class="btn" id="sp-cal">${cal.running ? (cal.step || "Measuring…") : "Calibrate with the microphone"}</button><button class="btn small" id="sp-eqreset">Reset</button></div>
        <div class="hint" id="sp-calhint">${cal.running ? "Keep quiet for about fifteen seconds. A short burst of noise plays." : (cal.error ? cal.error : (res ? res.text : "Put the USB microphone where you usually listen, then calibrate: a short burst of noise is played and the speakers are evened out for that spot. Bass and treble sit on top of it."))}</div></div>
    </div>`;
  }
  const fmtDb = v => `${v > 0 ? "+" : ""}${Math.round(v || 0)} dB`;
  function roomText(eq) {
    const room = eq.room || [], on = eq.room_enabled !== false;
    const active = room.some(x => Math.abs(x) >= 0.5);
    return !active ? "Off" : on ? "On" : "Off (measured)";
  }
  let lastCalKey = "";
  function wireSound(el) {
    const on = (id, ev, fn) => { const n = $(id, el); if (n) n.addEventListener(ev, fn); };
    const debounced = (id, lbl, key) => { const r = $(id, el), l = $(lbl, el); if (!r) return; let t = null;
      r.oninput = () => { l.textContent = fmtDb(+r.value); clearTimeout(t); t = setTimeout(async () => { const res = await HD.api("audio", "set_eq", { [key]: +r.value }); if (!res || !res.ok) HD.toast((res && res.error) || "Could not set the equaliser", "warning"); }, 250); }; };
    debounced("#sp-bass", "#sp-bassv", "bass");
    debounced("#sp-treb", "#sp-trebv", "treble");
    on("#sp-cal", "click", async () => { const r = await HD.api("audio", "calibrate", {}); HD.toast(r && r.ok ? "Calibrating: keep quiet for a moment" : ((r && r.error) || "Could not start"), r && r.ok ? "good" : "warning"); });
    on("#sp-eqreset", "click", async () => { await HD.api("audio", "reset_eq", {}); HD.toast("Sound reset to flat", "good"); lastCalKey = ""; });
  }
  function updateSound(state) {
    const eq = ((state && state.audio) || {}).eq; if (!eq || !root) return;
    const key = JSON.stringify([eq.calibration, eq.room, eq.room_enabled, eq.available]);
    if (key === lastCalKey) return;
    lastCalKey = key;
    const card = $("#sp-sound", root); if (!card) return;
    const tmp = document.createElement("div"); tmp.innerHTML = soundCard();
    // keep the sliders the user may be dragging: only swap the calibration part and the room label
    HD.setText($("#sp-roomv", card), roomText(eq));
    const b = $("#sp-cal", card), nb = $("#sp-cal", tmp); if (b && nb) b.textContent = nb.textContent;
    const h = $("#sp-calhint", card), nh = $("#sp-calhint", tmp); if (h && nh) h.textContent = nh.textContent;
  }

  function render(el) {
    root = el;
    const sp = (HD.state && HD.state.spotify) || {};
    const setup = setupCard(sp);
    const auth = sp.authenticated && !setup;
    el.innerHTML = `<div class="spotify">${setup || playerCard()}
      ${auth ? `<div class="card home"><h3>Search</h3><div class="row"><input id="sp-q" class="input" type="search" placeholder="Songs, artists, albums, podcasts" autocomplete="off"><button id="sp-go" class="btn primary">Search</button></div></div>` : ""}
      ${auth && !HD.isGuest() ? `<div class="card home"><h3>Library</h3><div class="libgrid">
          <button class="libbtn" data-lib="liked"><span class="libic liked">${HEART(true)}</span>Liked Songs</button>
          <button class="libbtn" data-lib="albums"><span class="libic">${HD.icon("note", "")}</span>Albums</button>
          <button class="libbtn" data-lib="artists"><span class="libic">${HD.icon("mic", "")}</span>Artists</button>
          <button class="libbtn" data-lib="shows"><span class="libic">${HD.icon("volume", "")}</span>Podcasts</button>
        </div></div>` : ""}
      ${auth && !HD.isGuest() ? `<div class="card home"><h3>Recently played</h3><div id="sp-recent" class="plgrid"></div></div>` : ""}
      ${auth && !HD.isGuest() ? `<div class="card home"><div class="row between"><h3>Playlists</h3><span class="inline"><button class="btn small" id="sp-refresh">Refresh</button><button class="btn small libbtn" data-lib="playlists">See all</button></span></div><div class="hint" id="sp-rl" style="display:none"></div><div id="sp-pls" class="plgrid"></div></div>` : ""}
      ${soundCard()}
      <div id="sp-sub" class="sub hidden"></div>
      <div id="sp-sheet" class="sheetwrap hidden"></div>
    </div>`;
    lastNowKey = ""; lastPlaylistsKey = ""; stack.length = 0; subState = null; lastCalKey = "";
    wireHome(el);
    wireSound(el);
    update(HD.state);
  }

  // progress as of right now: the server stamps each snapshot with fetched_at, so the bar keeps moving between the
  // 2 s state polls (a 1 Hz ticker below calls this while the app is open)
  function liveProgress(now) {
    if (!now) return 0;
    let p = now.progress_ms || 0;
    if (now.playing && now.fetched_at) p += (Date.now() / 1000 - now.fetched_at) * 1000;
    return Math.max(0, Math.min(now.duration_ms || p, p));
  }
  let ticker = null;
  function startTicker() {
    if (ticker) return;
    ticker = setInterval(() => {
      if (!root || !root.isConnected) { clearInterval(ticker); ticker = null; return; }
      const now = nowState(); if (!now || !now.playing || !now.duration_ms || seekDrag) return;
      const pr = liveProgress(now), bar = $("#sp-bar", root), t1 = $("#sp-t1", root);
      if (bar) bar.style.width = (100 * pr / now.duration_ms).toFixed(1) + "%";
      if (t1) t1.textContent = mmss(pr);
    }, 1000);
  }
  function patchPlayer(state, force) {
    startTicker();
    const sp = (state && state.spotify) || {}, now = sp.now;
    const key = JSON.stringify([now && now.uri, now && now.playing, now && now.shuffle, now && now.repeat, now && now.liked, now && now.volume, now && now.device, sp.device_online, sp.error, sp.needs_reauth]);
    if (key !== lastNowKey || force) {
      lastNowKey = key;
      const art = $("#sp-art", root), noart = $("#sp-noart", root);
      if (!art) return;
      if (now && now.art_url) { art.src = now.art_url; art.style.display = ""; noart.style.display = "none"; } else { art.style.display = "none"; noart.style.display = ""; }
      $("#sp-title", root).textContent = now ? now.title || "" : "Not Playing";
      $("#sp-artist", root).textContent = now ? [now.artist, now.album].filter(Boolean).join(" · ") : "Choose a playlist, or send music here from your phone";
      $("#sp-play", root).innerHTML = HD.icon(now && now.playing ? "pause" : "play", "");
      $("#sp-shuffle", root).classList.toggle("on", !!(now && now.shuffle));
      const rep = $("#sp-repeat", root); rep.innerHTML = REPEAT(now && now.repeat); rep.classList.toggle("on", !!(now && now.repeat && now.repeat !== "off"));
      const like = $("#sp-like", root); like.innerHTML = HEART(!!(now && now.liked)); like.classList.toggle("on", !!(now && now.liked)); like.style.visibility = now && now.kind === "track" ? "" : "hidden";
      const av = state.audio && state.audio.music_pct; if (!volDragging && av != null) $("#sp-vol", root).value = av;
      $("#sp-devname", root).textContent = now && now.device ? now.device : "Devices";
      $("#sp-dev", root).textContent = sp.device_online ? "" : "HomeDeck isn't in Spotify Connect yet. Open Spotify on your phone, tap the speaker icon, choose HomeDeck.";
      const errBox = $("#sp-err", root);
      if (sp.needs_reauth || (sp.error && /scope/i.test(sp.error))) {
        errBox.innerHTML = HD.KIOSK ? `Reconnect Spotify to enable the library features. <button class="relink" id="sp-relogin" type="button">Connect on this screen</button>` : `Reconnect Spotify to enable the library features. <a class="relink" href="/spotify/login">Reconnect</a>`;
        const rb = $("#sp-relogin", root); if (rb) rb.onclick = deviceLogin;
      } else errBox.textContent = sp.error || "";
    }
    if (now && now.duration_ms && !seekDrag) {
      const pr = liveProgress(now);
      $("#sp-bar", root).style.width = (100 * pr / now.duration_ms).toFixed(1) + "%";
      $("#sp-t1", root).textContent = mmss(pr); $("#sp-t2", root).textContent = mmss(now.duration_ms);
    }
    // mini bar inside sub views
    const mini = $("#sp-mini", root);
    if (mini) {
      mini.querySelector(".mt").textContent = now ? now.title || "" : "Not playing";
      mini.querySelector(".ma").textContent = now ? now.artist || "" : "";
      mini.querySelector(".mp").innerHTML = HD.icon(now && now.playing ? "pause" : "play", "");
      const mi = mini.querySelector("img"); if (mi && now && now.art_url && mi.src !== now.art_url) mi.src = now.art_url;
      root.querySelectorAll(".trk").forEach(r => r.classList.toggle("playing", !!(now && now.uri && r.dataset.uri === now.uri)));
    }
  }

  function update(state) {
    if (!root || !root.isConnected) return;
    const sp = (state && state.spotify) || {};
    const wantSetup = !!setupCard(sp);
    if (wantSetup !== !!$(".spotify .steps, .spotify a[href='/spotify/login'], .spotify #sp-devlogin", root)) return render(root);
    if (wantSetup) return;
    updateSound(state);
    const rl = $("#sp-rl", root); if (rl) { const u = sp.rate_limited_until; rl.style.display = u ? "" : "none";
      if (u) rl.textContent = `Spotify is limiting requests from this device; playlists and history refresh again at ${new Date(u * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}. Playback still works.`; }
    patchPlayer(state);
    const pls = $("#sp-pls", root);
    if (pls) {
      const pk = (sp.playlists || []).map(p => p.uri).join(",");
      if (pk !== lastPlaylistsKey) {
        lastPlaylistsKey = pk;
        pls.innerHTML = (sp.playlists || []).slice(0, 12).map(p => `<button class="pl" data-uri="${esc(p.uri)}">${ART(p.art_url)}<span>${esc(p.name)}</span><small>${p.tracks != null ? p.tracks + " songs" : ""}</small></button>`).join("") || `<p class="hint">No playlists yet. Tap Refresh.</p>`;
        pls.querySelectorAll(".pl").forEach(b => b.onclick = () => openSub({ kind: "detail", uri: b.dataset.uri, title: b.querySelector("span").textContent }));
      }
    }
  }

  // ---------------------------------------------------------------- sub views (in-app stack)
  function openSub(view) { stack.push(view); showSub(); }
  function back() { stack.pop(); if (stack.length) showSub(); else closeSub(); }
  function closeSub() { stack.length = 0; subState = null; const sub = $("#sp-sub", root); sub.classList.add("hidden"); sub.innerHTML = ""; $(".spotify", root).classList.remove("insub"); lastNowKey = ""; patchPlayer(HD.state, true); window.scrollTo(0, 0); }

  function miniBar() {
    const now = nowState();
    return `<div class="mini" id="sp-mini">${ART(now && now.art_url, "mimg")}<div class="mm"><div class="mt">${esc(now ? now.title : "Not playing")}</div><div class="ma">${esc(now ? now.artist : "")}</div></div><button class="ctl mp" aria-label="Play or pause">${HD.icon(now && now.playing ? "pause" : "play", "")}</button><button class="ctl mn" aria-label="Next">${HD.icon("skip-forward", "")}</button></div>`;
  }
  function header(view, subtitle, actions) {
    return `<div class="subhead"><button class="ctl backb" id="sp-back" aria-label="Back">${HD.icon("chevron-left", "")}</button>
      <div class="ht"><div class="t">${esc(view.title || "")}</div>${subtitle ? `<div class="s">${esc(subtitle)}</div>` : ""}</div>${actions || ""}</div>`;
  }

  async function showSub() {
    const view = stack[stack.length - 1];
    const sub = $("#sp-sub", root); $(".spotify", root).classList.add("insub"); sub.classList.remove("hidden");
    sub.innerHTML = miniBar() + header(view) + `<div class="hint" style="padding:12px 4px">Loading…</div>`;
    wireMini(sub); $("#sp-back", sub).onclick = back;
    window.scrollTo(0, 0);
    try {
      if (view.kind === "detail") await renderDetail(sub, view);
      else if (view.kind === "search") await renderSearch(sub, view);
      else if (view.kind === "queue") await renderQueue(sub, view);
      else if (view.kind === "devices") await renderDevices(sub, view);
      else await renderLibrary(sub, view);
    } catch (e) { console.error(e); sub.querySelector(".hint") && (sub.querySelector(".hint").textContent = "Something went wrong: " + e); }
  }
  function wireMini(sub) {
    const m = $("#sp-mini", sub); if (!m) return;
    m.querySelector(".mp").onclick = e => { e.stopPropagation(); togglePlay(); };
    m.querySelector(".mn").onclick = e => { e.stopPropagation(); api("next"); };
    m.onclick = () => closeSub();
  }

  // track rows -------------------------------------------------------------
  function trackRow(t, i, ctx) {
    const now = nowState(); const playing = now && now.uri === t.uri;
    const sub = [t.artist, ctx && ctx.showAlbum && t.album].filter(Boolean).join(" · ");
    return `<div class="trk ${playing ? "playing" : ""}" data-uri="${esc(t.uri)}" data-i="${i}">
      ${ctx && ctx.numbers ? `<span class="num">${i + 1}</span>` : ART(t.art_url, "timg")}
      <span class="tt"><b>${esc(t.name)}${t.explicit ? ' <i class="ex">E</i>' : ""}</b><small>${esc(sub)}${t.type === "episode" && t.release_date ? " · " + esc(t.release_date) : ""}</small></span>
      ${t.type === "track" && t.liked ? `<span class="lk">${HEART(true)}</span>` : ""}
      <span class="dur">${t.type === "episode" ? longer(t.duration_ms) : mmss(t.duration_ms)}</span>
      <button class="more" aria-label="More">${DOTS}</button></div>`;
  }
  function wireTracks(box, items, playFn, ctx) {
    box.querySelectorAll(".trk").forEach(r => {
      const t = items[+r.dataset.i]; if (!t) return;
      r.onclick = () => playFn(t, +r.dataset.i);
      r.querySelector(".more").onclick = e => { e.stopPropagation(); openMenu(t, ctx); };
    });
  }
  function gridItem(it) {
    const sub = it.type === "artist" ? "Artist" : it.type === "album" ? [it.artist, it.year].filter(Boolean).join(" · ") : it.type === "show" ? it.artist || "Podcast" : it.type === "playlist" ? (it.tracks != null ? `${it.tracks} songs` : it.artist || "Playlist") : it.artist || "";
    return `<button class="pl ${it.type === "artist" ? "round" : ""}" data-uri="${esc(it.uri)}" data-type="${esc(it.type)}">${ART(it.art_url)}<span>${esc(it.name)}</span><small>${esc(sub)}</small></button>`;
  }
  function wireGrid(box) {
    box.querySelectorAll(".pl").forEach(b => b.onclick = () => {
      const type = b.dataset.type;
      if (type === "track" || type === "episode") return playItem(b.dataset.uri, type);
      openSub({ kind: "detail", uri: b.dataset.uri, title: b.querySelector("span").textContent });
    });
  }

  // library -----------------------------------------------------------------
  async function renderLibrary(sub, view) {
    const kind = view.kind; let offset = 0, after = null, items = [];
    const body = document.createElement("div"); body.className = "subbody";
    const load = async () => {
      const r = await api("library", { kind, offset, after });
      if (!r || !r.ok) { body.innerHTML = `<p class="hint">${esc((r && r.error) || "Couldn't load")}${r && r.needs_reauth ? " (reconnect Spotify to enable this)" : ""}</p>`; return; }
      items = items.concat(r.items || []);
      const more = r.next ? `<button class="btn morebtn" id="sp-more">Show more</button>` : "";
      if (kind === "liked") {
        body.innerHTML = `<div class="tracks">${items.map((t, i) => trackRow(t, i, { showAlbum: true })).join("") || `<p class="hint">No liked songs yet.</p>`}</div>${more}`;
        wireTracks(body, items, t => api("play_liked", { uri: t.uri }).then(rr => { if (!rr.ok) HD.toast(rr.error || "Couldn't play", "warning"); }), { liked: true });
      } else {
        body.innerHTML = `<div class="grid">${items.map(gridItem).join("") || `<p class="hint">Nothing here yet.</p>`}</div>${more}`;
        wireGrid(body);
      }
      const mb = $("#sp-more", body); if (mb) mb.onclick = () => { offset += 50; after = r.after || null; mb.textContent = "Loading…"; load(); };
      sub.querySelector(".subhead .s") && (sub.querySelector(".subhead .s").textContent = r.total != null ? `${r.total} ${kind === "liked" ? "songs" : kind}` : "");
    };
    const actions = kind === "liked" ? `<span class="hact"><button class="btn primary" id="sp-playall">${HD.icon("play", "")} Play</button><button class="btn" id="sp-shuf">${HD.icon("shuffle", "")} Shuffle</button></span>` : "";
    sub.innerHTML = miniBar() + header(view, "", actions); wireMini(sub); $("#sp-back", sub).onclick = back;
    sub.appendChild(body); body.innerHTML = `<p class="hint">Loading…</p>`;
    const pa = $("#sp-playall", sub); if (pa) pa.onclick = async () => { const r = await api("play_liked"); if (!r.ok) HD.toast(r.error || "Couldn't play", "warning"); };
    const sh = $("#sp-shuf", sub); if (sh) sh.onclick = async () => { await api("shuffle", { on: true }); const r = await api("play_liked"); if (!r.ok) HD.toast(r.error || "Couldn't play", "warning"); };
    await load();
  }

  // detail: playlist / album / artist / show ----------------------------------
  async function renderDetail(sub, view) {
    let offset = 0, items = [];
    const r0 = await api("detail", { uri: view.uri, offset });
    if (!r0 || !r0.ok) { sub.querySelector(".hint").textContent = (r0 && r0.error) || "Couldn't load"; return; }
    const info = r0.info || {}, kind = r0.kind;
    view.title = info.name || view.title;
    const subtitle = kind === "playlist" ? [info.owner ? "by " + info.owner : "", info.total != null ? `${info.total} songs` : ""].filter(Boolean).join(" · ")
      : kind === "album" ? [info.artist, info.year, info.total != null ? `${info.total} songs` : ""].filter(Boolean).join(" · ")
      : kind === "artist" ? [info.followers != null ? `${info.followers.toLocaleString()} followers` : "", (info.genres || []).slice(0, 2).join(", ")].filter(Boolean).join(" · ")
      : [info.artist, info.total != null ? `${info.total} episodes` : ""].filter(Boolean).join(" · ");
    const actions = `<span class="hact"><button class="btn primary" id="sp-playall">${HD.icon("play", "")} Play</button>${kind !== "show" ? `<button class="btn" id="sp-shuf">${HD.icon("shuffle", "")} Shuffle</button>` : ""}</span>`;
    sub.innerHTML = miniBar() + `<div class="hero">${ART(info.art_url, "himg " + (kind === "artist" ? "round" : ""))}${header(view, subtitle, actions)}</div>`;
    wireMini(sub); $("#sp-back", sub).onclick = back;
    const body = document.createElement("div"); body.className = "subbody"; sub.appendChild(body);
    const ctxUri = kind === "artist" ? null : view.uri;
    const playAt = (t) => {
      const p = t.type === "episode" && t.resume_ms ? api("play_context", { context_uri: view.uri, uri: t.uri, position_ms: t.resume_ms })
        : ctxUri ? api("play_context", { context_uri: ctxUri, uri: t.uri }) : api("play", { uri: t.uri });
      p.then(rr => { if (!rr.ok) HD.toast(rr.error || "Couldn't play", "warning"); });
    };
    const draw = (r) => {
      items = offset ? items.concat(r.items || []) : (r.items || []);
      const more = r.next ? `<button class="btn morebtn" id="sp-more">Show more</button>` : "";
      let html = `<div class="tracks">${items.map((t, i) => trackRow(t, i, { numbers: kind === "album", showAlbum: kind === "playlist" })).join("") || `<p class="hint">Nothing here.</p>`}</div>${more}`;
      if (kind === "artist" && (r.albums || []).length) html = `<div class="sec">Popular</div>` + html + `<div class="sec">Albums and singles</div><div class="grid">${r.albums.map(gridItem).join("")}</div>`;
      body.innerHTML = html;
      wireTracks(body, items, playAt, { playlist: kind === "playlist" && info.editable ? view.uri : null });
      wireGrid(body);
      const mb = $("#sp-more", body); if (mb) mb.onclick = async () => { offset += 50; mb.textContent = "Loading…"; const rn = await api("detail", { uri: view.uri, offset }); if (rn && rn.ok) draw(rn); };
    };
    draw(r0);
    $("#sp-playall", sub).onclick = async () => { const r = await api("play", { context_uri: view.uri }); if (!r.ok) HD.toast(r.error || "Couldn't play", "warning"); };
    const sh = $("#sp-shuf", sub); if (sh) sh.onclick = async () => { await api("shuffle", { on: true }); const r = await api("play", { context_uri: view.uri }); if (!r.ok) HD.toast(r.error || "Couldn't play", "warning"); };
  }

  // search --------------------------------------------------------------------
  async function renderSearch(sub, view) {
    const r = await api("search_full", { q: view.q });
    const body = document.createElement("div"); body.className = "subbody";
    sub.innerHTML = miniBar() + header(view, ""); wireMini(sub); $("#sp-back", sub).onclick = back; sub.appendChild(body);
    if (!r || !r.ok) { body.innerHTML = `<p class="hint">${esc((r && r.error) || "Search failed")}</p>`; return; }
    const groups = [["Songs", "tracks"], ["Artists", "artists"], ["Albums", "albums"], ["Playlists", "playlists"], ["Podcasts", "shows"]].filter(([, k]) => (r[k] || []).length);
    if (!groups.length) { body.innerHTML = `<p class="hint">Nothing found for "${esc(view.q)}".</p>`; return; }
    body.innerHTML = groups.map(([label, k]) => k === "tracks"
      ? `<div class="sec">${label}</div><div class="tracks">${r.tracks.slice(0, 6).map((t, i) => trackRow(t, i, { showAlbum: true })).join("")}</div>`
      : `<div class="sec">${label}</div><div class="grid">${r[k].slice(0, 8).map(gridItem).join("")}</div>`).join("");
    wireTracks(body, r.tracks || [], t => playItem(t.uri, "track"), {});
    wireGrid(body);
  }

  // queue ---------------------------------------------------------------------
  async function renderQueue(sub, view) {
    const r = await api("queue_list");
    const body = document.createElement("div"); body.className = "subbody";
    sub.innerHTML = miniBar() + header(view, "What plays next on the HomeDeck"); wireMini(sub); $("#sp-back", sub).onclick = back; sub.appendChild(body);
    if (!r || !r.ok) { body.innerHTML = `<p class="hint">${esc((r && r.error) || "Couldn't load the queue")}</p>`; return; }
    const items = r.items || [];
    body.innerHTML = (r.current ? `<div class="sec">Now playing</div><div class="tracks">${trackRow(r.current, 0, { showAlbum: true })}</div>` : "")
      + `<div class="sec">Next up</div><div class="tracks" id="sp-qlist">${items.map((t, i) => trackRow(t, i, { showAlbum: true })).join("") || `<p class="hint">The queue is empty. Add songs with the … menu on any track.</p>`}</div>`;
    // jump: skip forward N times until that track (Spotify has no direct "play from queue" call)
    const ql = $("#sp-qlist", body);
    ql.querySelectorAll(".trk").forEach(row => { const t = items[+row.dataset.i]; row.onclick = async () => { const n = +row.dataset.i + 1; HD.toast(`Skipping to ${t.name}`, "good", 1500); for (let k = 0; k < n; k++) { await api("next"); await new Promise(ok => setTimeout(ok, 250)); } }; row.querySelector(".more").onclick = e => { e.stopPropagation(); openMenu(t, {}); }; });
    if (r.current) { const cur = body.querySelector(".tracks .trk"); cur.onclick = () => {}; cur.querySelector(".more").onclick = e => { e.stopPropagation(); openMenu(r.current, {}); }; }
  }

  // devices -------------------------------------------------------------------
  async function renderDevices(sub, view) {
    const r = await api("devices");
    const body = document.createElement("div"); body.className = "subbody";
    sub.innerHTML = miniBar() + header(view, "Where the music plays"); wireMini(sub); $("#sp-back", sub).onclick = back; sub.appendChild(body);
    if (!r || !r.ok) { body.innerHTML = `<p class="hint">${esc((r && r.error) || "Couldn't list devices")}</p>`; return; }
    const devs = r.devices || [];
    body.innerHTML = `<div class="tracks">${devs.map(d => `<div class="trk dev ${d.active ? "playing" : ""}" data-id="${esc(d.id)}"><span class="dic">${HD.icon(d.homedeck ? "home" : d.type === "Smartphone" ? "mic" : "volume", "")}</span><span class="tt"><b>${esc(d.name)}${d.homedeck ? " (this device)" : ""}</b><small>${esc(d.type)}${d.active ? " · playing here" : ""}</small></span>${d.active ? `<span class="lk on">${HD.icon("check", "")}</span>` : ""}</div>`).join("") || `<p class="hint">No devices found. Open Spotify on your phone once.</p>`}</div>
      <p class="hint">Tap a device to move the music there. Playback continues from the same spot.</p>`;
    body.querySelectorAll(".dev").forEach(row => row.onclick = async () => { const rr = await api("transfer", { device_id: row.dataset.id, play: true }); if (rr.ok) { HD.toast("Moved playback", "good", 1500); setTimeout(() => renderDevices(sub, view), 1200); } else HD.toast(rr.error || "Couldn't transfer", "warning"); });
  }

  // track menu (bottom sheet) --------------------------------------------------
  function openMenu(t, ctx) {
    const wrap = $("#sp-sheet", root); if (!wrap) return;
    const isTrack = t.type === "track";
    wrap.classList.remove("hidden");
    wrap.innerHTML = `<div class="sheet"><div class="shead">${ART(t.art_url, "simg")}<div class="tt"><b>${esc(t.name)}</b><small>${esc(t.artist || "")}</small></div></div>
      <div class="sitems">
        ${isTrack ? `<button data-m="queue">${HD.icon("plus", "")}Add to queue</button>` : ""}
        ${isTrack ? `<button data-m="playlist">${HD.icon("list", "")}Add to playlist${CHEV}</button>` : ""}
        ${isTrack ? `<button data-m="like">${HEART(!!t.liked)}${t.liked ? "Remove from Liked Songs" : "Save to Liked Songs"}</button>` : ""}
        ${ctx && ctx.playlist ? `<button data-m="remove">${HD.icon("trash", "")}Remove from this playlist</button>` : ""}
        ${t.album_uri ? `<button data-m="album">${HD.icon("note", "")}Go to ${t.type === "episode" ? "podcast" : "album"}${CHEV}</button>` : ""}
        ${t.artist_uri ? `<button data-m="artist">${HD.icon("mic", "")}Go to artist${CHEV}</button>` : ""}
      </div><button class="scancel" data-m="cancel">Cancel</button></div>`;
    const close = () => { wrap.classList.add("hidden"); wrap.innerHTML = ""; };
    wrap.onclick = e => { if (e.target === wrap) close(); };
    wrap.querySelectorAll("[data-m]").forEach(b => b.onclick = async () => {
      const m = b.dataset.m;
      if (m === "cancel") return close();
      if (m === "queue") { const r = await api("queue", { uri: t.uri }); HD.toast(r.ok ? "Added to queue" : (r.error || "Couldn't queue"), r.ok ? "good" : "warning"); return close(); }
      if (m === "like") { const r = await api("like", { uri: t.uri, on: !t.liked }); if (r.ok) { t.liked = !t.liked; HD.toast(t.liked ? "Saved to Liked Songs" : "Removed from Liked Songs", "good", 1500); root.querySelectorAll(`.trk[data-uri="${CSS.escape(t.uri)}"] .lk`).forEach(n => n.remove()); } else HD.toast(r.error || "Couldn't change that", "warning"); return close(); }
      if (m === "remove") { const r = await api("remove_from_playlist", { playlist_uri: ctx.playlist, uri: t.uri }); HD.toast(r.ok ? "Removed" : (r.error || "Couldn't remove"), r.ok ? "good" : "warning"); if (r.ok) root.querySelectorAll(`.trk[data-uri="${CSS.escape(t.uri)}"]`).forEach(n => n.remove()); return close(); }
      if (m === "album") { close(); return openSub({ kind: "detail", uri: t.album_uri, title: t.album || "" }); }
      if (m === "artist") { close(); return openSub({ kind: "detail", uri: t.artist_uri, title: (t.artist || "").split(",")[0] }); }
      if (m === "playlist") {
        const r = await api("library", { kind: "playlists" });
        const pls = ((r && r.items) || []).filter(p => p.editable);
        wrap.querySelector(".sitems").innerHTML = pls.length ? pls.map(p => `<button data-pl="${esc(p.uri)}">${ART(p.art_url, "simg2")}${esc(p.name)}</button>`).join("") : `<p class="hint" style="padding:12px">You have no playlists you can edit.</p>`;
        wrap.querySelector(".shead .tt small").textContent = "Add to playlist";
        wrap.querySelectorAll("[data-pl]").forEach(pb => pb.onclick = async () => { const rr = await api("add_to_playlist", { playlist_uri: pb.dataset.pl, uri: t.uri }); HD.toast(rr.ok ? `Added to ${pb.textContent.trim()}` : (rr.error || "Couldn't add"), rr.ok ? "good" : "warning"); close(); });
      }
    });
  }

  function idleWidget(el, state) {
    const sp = (state && state.spotify) || {}, now = sp.now;
    if (!now || !now.playing) { el.style.display = "none"; return; }
    el.style.display = "";
    const key = now.uri;
    if (el.dataset.key === key) return;
    el.dataset.key = key;
    el.innerHTML = `<div class="iw-music">${now.art_url ? `<img src="${esc(now.art_url)}" alt="">` : `<span class="iw-icon">${HD.icon("note")}</span>`}<div><div class="iw-label">Now Playing</div><div class="iw-title">${esc(now.title)}</div><div class="iw-sub">${esc(now.artist)}</div></div></div>`;
  }

  HD.registerApp({ id: "spotify", title: "Spotify", icon: "note", order: 12, guestHidden: false, idleSize: "2x1", render, update, idleWidget });

  // ---------------------------------------------------------------- styles (scoped by .spotify / .iw-music)
  const css = document.createElement("style");
  css.textContent = `
  .spotify .steps{padding-left:20px;line-height:1.6;font-size:15px;color:var(--fg2);margin:8px 0}.spotify code.sel{user-select:all;background:var(--card2);padding:2px 6px;border-radius:6px;word-break:break-all;font-size:13px;color:var(--fg)}
  .spotify .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:8px;border:0;padding:0;min-height:0}.spotify .row.between{justify-content:space-between}
  .spotify .inline{display:flex;gap:8px;align-items:center}
  .spotify .input{flex:1;min-width:200px}
  .spotify .player{text-align:center;padding-top:22px}
  .spotify .art-wrap{position:relative;width:min(64vw,280px);aspect-ratio:1;margin:0 auto 18px}
  .spotify .art{width:100%;height:100%;object-fit:cover;border-radius:12px;box-shadow:0 18px 40px rgba(0,0,0,.5)}
  .spotify .noart{width:100%;height:100%;border-radius:12px;background:var(--card2);display:flex;align-items:center;justify-content:center;color:var(--muted)}.spotify .noart svg{width:64px;height:64px}
  .spotify .metarow{display:flex;align-items:center;justify-content:center;gap:6px;min-width:0}
  .spotify .title{font-size:20px;font-weight:600;margin-top:4px;letter-spacing:-.01em;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.spotify .artist{color:var(--fg2);font-size:15px;margin-top:2px;min-height:1.4em}
  .spotify .heart{color:var(--fg2)}.spotify .heart.on{color:var(--app-accent,var(--accent))}.spotify .heart svg{width:22px;height:22px}
  .spotify .progress{height:18px;padding:7px 0;margin-top:12px;cursor:pointer;touch-action:none}.spotify .progress .bar{height:4px;border-radius:2px;background:var(--fg);width:0;position:relative}
  .spotify .progress{background:linear-gradient(rgba(255,255,255,.18),rgba(255,255,255,.18)) center/100% 4px no-repeat}
  .spotify .progress .bar::after{content:"";position:absolute;right:-6px;top:-4px;width:12px;height:12px;border-radius:50%;background:#fff}
  .spotify .times{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums;margin-top:0}
  .spotify .controls{display:flex;justify-content:center;align-items:center;gap:10px;margin:10px 0 6px}
  .spotify .ctl{width:52px;height:52px;border-radius:50%;border:0;background:transparent;color:var(--fg);display:flex;align-items:center;justify-content:center;padding:0;transition:transform .12s;flex:none}.spotify .ctl svg{width:30px;height:30px}
  .spotify .ctl:active{transform:scale(.92)}
  .spotify .ctl.big{width:76px;height:76px;background:rgba(255,255,255,.12)}.spotify .ctl.big svg{width:40px;height:40px}
  .spotify .ctl.on{color:var(--app-accent,var(--accent))}.spotify .ctl.small{width:44px;height:44px;color:var(--fg2)}.spotify .ctl.small.on{color:var(--app-accent,var(--accent))}
  .spotify #sp-shuffle svg,.spotify #sp-prev svg,.spotify #sp-next svg,.spotify #sp-repeat svg{width:26px;height:26px}
  .spotify .volrow{display:flex;align-items:center;gap:12px;margin:6px auto 0;max-width:360px;color:var(--fg2)}.spotify .volrow svg{width:20px;height:20px;flex:none}.spotify .volrow input{flex:1;height:44px}
  .spotify .subrow{display:flex;gap:8px;align-items:center;justify-content:center;flex-wrap:wrap;margin-top:8px}
  .spotify .pill{display:inline-flex !important;align-items:center;justify-content:center;gap:6px;min-height:36px !important;height:36px;line-height:1 !important;padding:0 14px !important;border-radius:999px !important;border:0;background:rgba(255,255,255,.1) !important;color:var(--fg) !important;font:inherit;font-size:14px !important;font-weight:500;overflow:hidden;white-space:nowrap}.spotify .pill svg{width:18px;height:18px}
  .spotify .pill span{max-width:160px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .spotify .relink{color:var(--app-accent,var(--accent));font-weight:600;text-decoration:none;margin-left:6px}
  .spotify button.relink{background:transparent;border:0;padding:0;font:inherit;font-weight:600;min-height:0;display:inline}
  .spotify .libgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
  .spotify .libbtn{display:flex !important;align-items:center;gap:12px;min-height:56px;padding:8px 12px !important;border:0;border-radius:12px !important;background:rgba(255,255,255,.07) !important;color:var(--fg) !important;font:inherit;font-size:16px !important;font-weight:500;text-align:left}
  .spotify .libbtn:active{background:rgba(255,255,255,.14)}
  .spotify .libic{width:40px;height:40px;border-radius:10px;background:rgba(255,255,255,.12);display:flex;align-items:center;justify-content:center;flex:none;color:var(--fg)}.spotify .libic svg{width:22px;height:22px}
  .spotify .libic.liked{background:linear-gradient(135deg,#4a3aff,#c4efd9);color:#fff}
  .spotify .btn.libbtn{min-height:34px;padding:0 12px;font-size:14px;gap:0;background:rgba(255,255,255,.1)}
  .spotify .plgrid,.spotify .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:10px}
  @media(min-width:700px){.spotify .plgrid{grid-template-columns:repeat(4,1fr)}.spotify .grid{grid-template-columns:repeat(6,1fr)}}
  .spotify .pl{border:0;background:transparent;color:inherit;border-radius:12px;padding:0;text-align:left;cursor:pointer;min-height:44px;overflow:hidden;transition:transform .12s;min-width:0}.spotify .pl:active{transform:scale(.97)}
  .spotify .pl img,.spotify .pl .plph{width:100%;aspect-ratio:1;object-fit:cover;display:flex;align-items:center;justify-content:center;background:var(--card2);border-radius:12px;color:var(--muted)}.spotify .pl .plph svg{width:40px;height:40px}
  .spotify .pl.round img,.spotify .pl.round .plph{border-radius:50%}
  .spotify .pl span{display:block;padding:8px 2px 0;font-size:15px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .spotify .pl small{display:block;padding:1px 2px 0;font-size:12.5px;color:var(--fg2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .spotify .hint{color:var(--fg2);font-size:13px;margin-top:8px}.spotify .err{color:var(--critical);font-size:13px;min-height:1em}
  .spotify #sp-err:empty,.spotify #sp-dev:empty{display:none}
  /* sub views */
  .spotify.insub .home{display:none}
  .spotify .sub{column-span:all;-webkit-column-span:all;break-inside:avoid}
  .spotify .sub.hidden{display:none}
  .spotify .mini{display:flex;align-items:center;gap:12px;padding:8px 8px 8px 10px;border-radius:14px;background:rgba(255,255,255,.08);box-shadow:inset 0 0 0 1px var(--hair);margin-bottom:12px;cursor:pointer}
  .spotify .mini .mimg,.spotify .mini .plph.mimg{width:44px;height:44px;border-radius:8px;object-fit:cover;flex:none;display:flex;align-items:center;justify-content:center;background:var(--card2);color:var(--muted)}.spotify .mini .plph svg{width:22px;height:22px}
  .spotify .mini .mm{min-width:0;flex:1}.spotify .mini .mt{font-weight:600;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.spotify .mini .ma{font-size:13px;color:var(--fg2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .spotify .mini .ctl{width:44px;height:44px;background:rgba(255,255,255,.1)}.spotify .mini .ctl svg{width:22px;height:22px}
  .spotify .subhead{display:flex;align-items:center;gap:10px;margin:2px 0 10px;min-width:0}
  .spotify .backb{width:40px;height:40px;background:rgba(255,255,255,.12)}.spotify .backb svg{width:22px;height:22px}
  .spotify .subhead .ht{min-width:0;flex:1}.spotify .subhead .t{font-size:22px;font-weight:700;letter-spacing:-.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.spotify .subhead .s{font-size:13px;color:var(--fg2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .spotify .hact{display:flex;gap:8px;flex:none}.spotify .hact .btn{display:inline-flex;align-items:center;gap:6px;min-height:40px;padding:0 14px}.spotify .hact .btn svg{width:18px;height:18px}
  .spotify .hero{display:flex;align-items:center;gap:14px}.spotify .hero .himg,.spotify .hero .plph.himg{width:92px;height:92px;border-radius:12px;object-fit:cover;flex:none;box-shadow:0 10px 30px rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;background:var(--card2);color:var(--muted);margin-bottom:10px}.spotify .hero .round{border-radius:50%}
  .spotify .hero .subhead{flex:1;min-width:0}
  .spotify .subbody{display:flex;flex-direction:column;gap:4px}
  .spotify .sec{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--fg2);margin:14px 4px 6px}
  .spotify .tracks{display:flex;flex-direction:column;gap:3px}
  .spotify .trk{display:flex;align-items:center;gap:12px;min-height:56px;padding:6px 4px 6px 8px;border-radius:12px;cursor:pointer;background:rgba(255,255,255,.04)}
  .spotify .trk:active{background:rgba(255,255,255,.12)}
  .spotify .trk.playing b{color:var(--app-accent,var(--accent))}
  .spotify .trk .timg,.spotify .trk .plph.timg{width:44px;height:44px;border-radius:8px;object-fit:cover;flex:none;display:flex;align-items:center;justify-content:center;background:var(--card2);color:var(--muted)}.spotify .trk .plph svg{width:22px;height:22px}
  .spotify .trk .num{width:28px;text-align:center;color:var(--muted);font-variant-numeric:tabular-nums;font-size:14px;flex:none}
  .spotify .trk .tt{display:flex;flex-direction:column;min-width:0;flex:1}.spotify .trk b{font-weight:600;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.spotify .trk small{color:var(--fg2);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .spotify .ex{display:inline-block;font-style:normal;font-size:9px;font-weight:700;line-height:1;padding:2px 3px;border-radius:3px;background:rgba(255,255,255,.3);color:#000;vertical-align:middle;margin-left:4px}
  .spotify .lk{color:var(--app-accent,var(--accent));display:inline-flex;flex:none}.spotify .lk svg{width:16px;height:16px}.spotify .lk.on svg{width:20px;height:20px}
  .spotify .dur{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums;flex:none;min-width:38px;text-align:right}
  .spotify .more{width:40px;height:40px;min-height:0 !important;border-radius:50% !important;border:0;background:transparent !important;color:var(--fg2) !important;display:flex !important;align-items:center;justify-content:center;padding:0 !important;flex:none}.spotify .more svg{width:20px;height:20px}
  .spotify .dic{width:40px;height:40px;border-radius:10px;background:rgba(255,255,255,.1);display:flex;align-items:center;justify-content:center;flex:none;color:var(--fg)}.spotify .dic svg{width:22px;height:22px}
  .spotify .morebtn{align-self:center;margin:10px 0 4px}
  /* bottom sheet */
  .spotify .sheetwrap{position:fixed;inset:0;z-index:40;background:rgba(0,0,0,.45);display:flex;align-items:flex-end;justify-content:center}
  .spotify .sheetwrap.hidden{display:none}
  .spotify .sheet{width:min(560px,100%);background:#1d1f26;border-radius:18px 18px 0 0;padding:14px 14px calc(14px + env(safe-area-inset-bottom));box-shadow:0 -1px 0 rgba(255,255,255,.12),0 -20px 60px rgba(0,0,0,.45)}
  .spotify .shead{display:flex;align-items:center;gap:12px;padding:2px 4px 12px;border-bottom:1px solid var(--sep)}.spotify .shead .tt{display:flex;flex-direction:column;min-width:0}.spotify .shead b{font-size:16px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.spotify .shead small{color:var(--fg2);font-size:13px}
  .spotify .simg,.spotify .plph.simg{width:52px;height:52px;border-radius:8px;object-fit:cover;flex:none;display:flex;align-items:center;justify-content:center;background:var(--card2);color:var(--muted)}
  .spotify .simg2,.spotify .plph.simg2{width:36px;height:36px;border-radius:6px;object-fit:cover;flex:none;display:inline-flex;align-items:center;justify-content:center;background:var(--card2);color:var(--muted)}
  .spotify .sitems{display:flex;flex-direction:column;padding:6px 0;max-height:50vh;overflow-y:auto}
  .spotify .sitems button{display:flex !important;align-items:center;gap:14px;width:100%;min-height:50px;padding:6px 8px !important;border:0;background:transparent !important;color:var(--fg) !important;font:inherit;font-size:16px !important;text-align:left;border-radius:10px !important}
  .spotify .sitems button svg{width:22px;height:22px;flex:none;color:var(--fg2)}.spotify .sitems button svg:last-child:not(:first-child){margin-left:auto;width:18px;height:18px}
  .spotify .sitems button:active{background:rgba(255,255,255,.08)}
  .spotify .scancel{width:100%;min-height:46px;margin-top:6px;border:0;border-radius:12px !important;background:rgba(255,255,255,.1) !important;color:var(--fg) !important;font:inherit;font-size:16px !important;font-weight:600;padding:8px !important}
  @media (orientation: landscape) and (max-height: 600px){
    .spotify .player{display:grid;grid-template-columns:132px minmax(0,1fr);column-gap:18px;row-gap:0;text-align:left;padding:14px 16px 12px;align-items:center}
    .spotify .art-wrap{grid-column:1;grid-row:1/span 8;width:132px;margin:0}
    .spotify .meta,.spotify .progress,.spotify .times,.spotify .controls,.spotify .volrow,.spotify .subrow,.spotify #sp-dev,.spotify #sp-err{grid-column:2;min-width:0}
    .spotify .metarow{justify-content:flex-start}
    .spotify .meta .title{font-size:18px}.spotify .meta .artist{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .spotify .progress{margin-top:6px}
    .spotify .controls{justify-content:flex-start;gap:2px;margin:2px 0 0}
    .spotify .ctl{width:44px;height:44px}.spotify .ctl svg{width:24px;height:24px}
    .spotify .ctl.big{width:54px;height:54px}.spotify .ctl.big svg{width:28px;height:28px}
    .spotify .ctl.small{width:38px;height:38px}
    .spotify .volrow{margin:0;max-width:none}.spotify .volrow input{height:34px}
    .spotify .subrow{justify-content:flex-start;margin-top:4px}.spotify .pill{height:32px;font-size:13px}
    .spotify #sp-dev,.spotify #sp-err{font-size:12px}
    .spotify .plgrid{grid-template-columns:repeat(4,1fr);gap:10px}
    .spotify .grid{grid-template-columns:repeat(6,1fr);gap:10px}
    .spotify .libgrid{grid-template-columns:repeat(2,1fr)}
    .spotify .tracks{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px 10px}
    .spotify .sheet{border-radius:18px;margin-bottom:8px;width:min(520px,96%)}
  }`;
  document.head.appendChild(css);
})();
