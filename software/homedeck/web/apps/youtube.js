/* YouTube app: search (server side via yt-dlp), results, watch history, and an ad-free native player: the server remuxes
   the video into a fragmented MP4 (/youtube/stream) and this page plays it in a <video> with its own controls. If a video
   cannot be streamed directly, it falls back to YouTube's own embedded player. Voice and the phone start videos through
   the "youtube_play" event. Backend: modules/youtube.py */
(() => {
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const CSS = `
  #ytapp { column-span: all; }
  #ytapp .card { margin-bottom: 12px; }
  #ytapp .yt-search { display: flex; gap: 8px; }
  #ytapp .yt-search input { flex: 1; }
  #ytapp .yt-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  @media (orientation: landscape) and (max-height: 600px) { #ytapp .yt-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; } }
  #ytapp .yt-item { display: flex; flex-direction: column; gap: 6px; border: 0; padding: 0; margin: 0; background: transparent !important; color: var(--fg) !important; text-align: left; font: inherit; min-width: 0; min-height: 0; cursor: pointer; border-radius: 12px; box-shadow: none; width: 100%; }
  #ytapp .yt-item * { color: inherit; }
  #ytapp .yt-item:active { opacity: .7; }
  #ytapp .yt-thumb { position: relative; width: 100%; aspect-ratio: 16 / 9; border-radius: 10px; overflow: hidden; background: rgba(255,255,255,.08); }
  #ytapp .yt-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  #ytapp .yt-dur { position: absolute; right: 6px; bottom: 6px; background: rgba(0,0,0,.75); color: #fff; font-size: 11px; font-weight: 600; padding: 2px 5px; border-radius: 4px; font-variant-numeric: tabular-nums; }
  #ytapp .yt-dur.live { background: #e0245e; }
  #ytapp .yt-title { font-size: 14px; font-weight: 600; line-height: 1.25; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; color: var(--fg) !important; }
  #ytapp .yt-ch { font-size: 12px; color: var(--fg2) !important; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #ytapp .yt-row { display: flex; gap: 8px; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  /* player */
  #ytapp .yt-player { display: flex; flex-direction: column; gap: 8px; max-width: 760px; margin: 0 auto; width: 100%; }
  #ytapp .yt-stage { position: relative; width: 100%; aspect-ratio: 16 / 9; background: #000; border-radius: 12px; overflow: hidden; }
  #ytapp .yt-stage video, #ytapp .yt-stage iframe, #ytapp .yt-stage .yt-host { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; background: #000; }
  #ytapp .yt-stage .yt-poster { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .35; }
  #ytapp .yt-ctl { position: absolute; inset: 0; display: flex; flex-direction: column; justify-content: space-between; transition: opacity .25s; }
  #ytapp .yt-ctl.hide { opacity: 0; pointer-events: none; }
  #ytapp .yt-ctl .yt-top { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; background: linear-gradient(rgba(0,0,0,.55), rgba(0,0,0,0)); }
  #ytapp .yt-ctl .yt-top b { font-size: 15px; font-weight: 600; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  #ytapp .yt-ctl .yt-top span { font-size: 12px; color: rgba(255,255,255,.7); }
  #ytapp .yt-ctl .yt-mid { flex: 1; display: flex; align-items: center; justify-content: center; gap: 34px; }
  #ytapp .yt-ctl .yt-bot { padding: 6px 12px 10px; background: linear-gradient(rgba(0,0,0,0), rgba(0,0,0,.6)); display: flex; flex-direction: column; gap: 4px; }
  #ytapp .yt-btn { width: 46px; height: 46px; border-radius: 50%; border: 0; background: rgba(0,0,0,.35) !important; color: #fff !important; display: flex; align-items: center; justify-content: center; padding: 0; margin: 0; min-height: 0; box-shadow: none; }
  #ytapp .yt-btn svg { width: 24px; height: 24px; }
  #ytapp .yt-btn.big { width: 68px; height: 68px; background: rgba(255,255,255,.92) !important; color: #000 !important; }
  #ytapp .yt-btn.big svg { width: 34px; height: 34px; }
  #ytapp .yt-btn.sm { width: 38px; height: 38px; background: transparent !important; }
  #ytapp .yt-btn:active { opacity: .7; }
  #ytapp .yt-scrub { display: flex; align-items: center; gap: 10px; color: #fff; font-size: 12px; font-variant-numeric: tabular-nums; }
  #ytapp .yt-scrub input[type=range] { flex: 1; height: 34px; margin: 0; accent-color: #ff3b30; background: transparent; }
  #ytapp .yt-bar2 { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  #ytapp .yt-bar2 .l, #ytapp .yt-bar2 .r { display: flex; align-items: center; gap: 4px; }
  #ytapp .yt-vol { display: flex; align-items: center; gap: 6px; color: #fff; }
  #ytapp .yt-vol input[type=range] { width: 110px; height: 34px; margin: 0; accent-color: #fff; background: transparent; }
  #ytapp .yt-note { font-size: 12px; color: var(--fg2); text-align: center; min-height: 14px; }
  #ytapp .yt-next { display: flex; gap: 10px; overflow-x: auto; scrollbar-width: none; padding-bottom: 4px; }
  #ytapp .yt-next::-webkit-scrollbar { display: none; }
  #ytapp .yt-next .yt-item { flex: 0 0 150px; }
  #ytapp .yt-next .yt-item.on .yt-thumb { box-shadow: 0 0 0 2px #fff; }
  #ytapp .yt-spin { position: absolute; left: 50%; top: 50%; width: 42px; height: 42px; margin: -21px 0 0 -21px; border-radius: 50%; border: 3px solid rgba(255,255,255,.25); border-top-color: #fff; animation: ytspin .9s linear infinite; }
  @keyframes ytspin { to { transform: rotate(360deg); } }
  body.yt-full #appview .apphead { display: none !important; }
  body.yt-full #ytapp .yt-stage { position: fixed; inset: 0; z-index: 55; border-radius: 0; aspect-ratio: auto; }
  body.yt-full #ytapp .yt-stage video { object-fit: contain; }
  `;
  if (!document.getElementById("yt-style")) { const st = document.createElement("style"); st.id = "yt-style"; st.textContent = CSS; document.head.appendChild(st); }
  const SVG = {
    play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l12-7.5z"/></svg>',
    pause: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>',
    prev: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h2v14H6zM20 5v14L9 12z"/></svg>',
    next: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 5h2v14h-2zM4 5v14l11-7z"/></svg>',
    back10: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/></svg>',
    fwd10: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/></svg>',
    full: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></svg>',
    shrink: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h5V3M21 8h-5V3M3 16h5v5M21 16h-5v5"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    vol: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5L6 9H2v6h4l5 4zM15.5 8.5a5 5 0 0 1 0 7M19 5a9 9 0 0 1 0 14"/></svg>',
  };

  let root = null, view = "search", results = [], lastQuery = "", current = null, watchdog = null, lastHistKey = "";
  // player state
  let video = null, tOffset = 0, duration = 0, dragging = false, hideTimer = null, lastReport = "", tick = null, iframeMode = false, ytPlayer = null, apiLoading = null, seq = 0;
  const fmtDur = s => { if (s == null || isNaN(s)) return ""; s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60; return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(x).padStart(2, "0"); };
  const fmtViews = n => n == null ? "" : n >= 1e9 ? (n / 1e9).toFixed(1) + "B views" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M views" : n >= 1e3 ? Math.round(n / 1e3) + "K views" : n + " views";
  const listFor = () => (results.length ? results : ((HD.state.youtube || {}).history || [])).filter(x => !x.live);

  // ---------- search / results
  function item(v, on) {
    return `<button class="yt-item${on ? " on" : ""}" data-id="${esc(v.id)}"><div class="yt-thumb"><img src="${esc(v.thumb || `https://i.ytimg.com/vi/${v.id}/mqdefault.jpg`)}" alt="" loading="lazy">${v.live ? `<span class="yt-dur live">LIVE</span>` : v.duration != null ? `<span class="yt-dur">${fmtDur(v.duration)}</span>` : ""}</div><div class="yt-title">${esc(v.title)}</div><div class="yt-ch">${esc(v.channel)}${v.views != null ? " · " + fmtViews(v.views) : ""}</div></button>`;
  }
  function drawSearch() {
    if (!root) return;
    const st = (HD.state && HD.state.youtube) || {}, hist = st.history || [];
    root.innerHTML = `<div class="card"><h3>Search</h3><div class="yt-search"><input type="search" id="yt-q" placeholder="Search YouTube" autocomplete="off" value="${esc(lastQuery)}"><button class="btn primary" id="yt-go">Search</button></div><div class="hint" id="yt-msg" style="margin-top:8px">${st.available === false ? esc(st.error || "Search unavailable") : ""}</div></div>
      <div class="card" id="yt-results" ${results.length ? "" : "hidden"}><div class="yt-row"><h3 style="margin:0">Results</h3></div><div class="yt-grid">${results.map(v => item(v)).join("")}</div></div>
      <div class="card" ${hist.length ? "" : "hidden"}><div class="yt-row"><h3 style="margin:0">Recently watched</h3><button class="btn small" id="yt-clear">Clear</button></div><div class="yt-grid">${hist.map(v => item(v)).join("")}</div></div>`;
    const q = root.querySelector("#yt-q"), go = async () => { const s = q.value.trim(); if (!s) return; lastQuery = s; const msg = root.querySelector("#yt-msg"); msg.textContent = "Searching…";
      const r = await HD.api("youtube", "search", { q: s }); if (!root) return;
      if (!r || !r.ok) { msg.textContent = (r && r.error) || "Search failed"; return; }
      results = r.results || []; msg.textContent = results.length ? "" : "No videos found"; drawSearch(); };
    root.querySelector("#yt-go").onclick = go; q.onkeydown = e => { if (e.key === "Enter") go(); };
    root.querySelectorAll(".yt-item").forEach(b => b.onclick = () => { const v = results.find(x => x.id === b.dataset.id) || hist.find(x => x.id === b.dataset.id); if (v) HD.api("youtube", "play", { id: v.id }); });
    const cl = root.querySelector("#yt-clear"); if (cl) cl.onclick = async () => { await HD.api("youtube", "clear_history"); drawSearch(); };
  }

  // ---------- native player
  const streamUrl = (id, t) => `/youtube/stream?id=${encodeURIComponent(id)}&t=${Math.max(0, Math.floor(t || 0))}&n=${Date.now()}`;
  function drawPlayer(v) {
    if (!root) return;
    const vol = (HD.state.audio && HD.state.audio.music_pct) != null ? HD.state.audio.music_pct : 70;
    root.innerHTML = `<div class="yt-player">
      <div class="yt-stage" id="yt-stage"><img class="yt-poster" src="${esc(v.thumb || `https://i.ytimg.com/vi/${v.id}/mqdefault.jpg`)}" alt=""><div class="yt-spin" id="yt-spin"></div>
        <div class="yt-ctl" id="yt-ctl">
          <div class="yt-top"><div style="min-width:0"><b>${esc(v.title || "YouTube")}</b><br><span>${esc(v.channel || "")}</span></div><div class="inline" style="gap:4px"><button class="yt-btn sm" id="yt-fullbtn" aria-label="Full screen">${SVG.full}</button><button class="yt-btn sm" id="yt-close" aria-label="Close">${SVG.close}</button></div></div>
          <div class="yt-mid"><button class="yt-btn" id="yt-b10" aria-label="Back 10 seconds">${SVG.back10}</button><button class="yt-btn big" id="yt-play" aria-label="Play or pause">${SVG.pause}</button><button class="yt-btn" id="yt-f10" aria-label="Forward 10 seconds">${SVG.fwd10}</button></div>
          <div class="yt-bot"><div class="yt-scrub"><span id="yt-t1">0:00</span><input type="range" id="yt-seek" min="0" max="1000" value="0" aria-label="Position"><span id="yt-t2">${fmtDur(v.duration) || "–:––"}</span></div>
            <div class="yt-bar2"><div class="l"><button class="yt-btn sm" id="yt-prev" aria-label="Previous">${SVG.prev}</button><button class="yt-btn sm" id="yt-next" aria-label="Next">${SVG.next}</button></div><div class="yt-vol">${SVG.vol}<input type="range" id="yt-vol" min="0" max="100" value="${vol}" aria-label="Volume"></div></div></div>
        </div></div>
      <div class="yt-note" id="yt-note"></div>
      <div class="yt-next" id="yt-upnext"></div></div>`;
    drawUpNext(v);
    const stage = root.querySelector("#yt-stage"), ctl = root.querySelector("#yt-ctl");
    stage.addEventListener("click", e => { if (e.target === stage || e.target === video || e.target.classList.contains("yt-poster")) { ctl.classList.contains("hide") ? showCtl() : hideCtl(); } });
    root.querySelector("#yt-play").onclick = () => togglePlay();
    root.querySelector("#yt-b10").onclick = () => seekTo(curTime() - 10);
    root.querySelector("#yt-f10").onclick = () => seekTo(curTime() + 10);
    root.querySelector("#yt-prev").onclick = () => step(-1);
    root.querySelector("#yt-next").onclick = () => step(1);
    root.querySelector("#yt-close").onclick = () => { stopPlayer(true); view = "search"; drawSearch(); };
    root.querySelector("#yt-fullbtn").onclick = () => { document.body.classList.toggle("yt-full"); root.querySelector("#yt-fullbtn").innerHTML = document.body.classList.contains("yt-full") ? SVG.shrink : SVG.full; showCtl(); };
    const seek = root.querySelector("#yt-seek");
    seek.addEventListener("pointerdown", () => { dragging = true; });
    seek.addEventListener("input", () => { root.querySelector("#yt-t1").textContent = fmtDur(seek.value / 1000 * duration); });
    seek.addEventListener("change", () => { dragging = false; seekTo(seek.value / 1000 * duration); });
    let volT = null; root.querySelector("#yt-vol").oninput = e => { clearTimeout(volT); volT = setTimeout(() => HD.api("audio", "set_volume", { pct: +e.target.value, target: "music" }), 150); };
  }
  function drawUpNext(v) {
    const box = root && root.querySelector("#yt-upnext"); if (!box) return;
    const list = listFor();
    box.innerHTML = list.length > 1 ? list.map(x => item(x, x.id === v.id)).join("") : "";
    box.querySelectorAll(".yt-item").forEach(b => b.onclick = () => { const x = list.find(y => y.id === b.dataset.id); if (x && x.id !== (current || {}).id) HD.api("youtube", "play", { id: x.id }); });
    const on = box.querySelector(".yt-item.on"); if (on) on.scrollIntoView({ inline: "center", block: "nearest" });
  }
  const curTime = () => (iframeMode ? (ytPlayer && ytPlayer.getCurrentTime ? ytPlayer.getCurrentTime() : 0) : tOffset + (video ? video.currentTime : 0));
  function showCtl() { const c = root && root.querySelector("#yt-ctl"); if (!c) return; c.classList.remove("hide"); clearTimeout(hideTimer); if (video && !video.paused) hideTimer = setTimeout(hideCtl, 3000); }
  function hideCtl() { const c = root && root.querySelector("#yt-ctl"); if (c && video && !video.paused) c.classList.add("hide"); }
  function setPlayIcon() { const b = root && root.querySelector("#yt-play"); if (b) b.innerHTML = (video && !video.paused && !video.ended) ? SVG.pause : SVG.play; }
  let lastHb = 0;
  function report(state) { if (!current) return; const k = state + current.id; if (k === lastReport) return; lastReport = k; lastHb = Date.now(); HD.api("youtube", "playing", { id: current.id, title: current.title, channel: current.channel, state }); }
  function heartbeat() { if (!current || Date.now() - lastHb < 5000) return; const on = iframeMode ? (ytPlayer && ytPlayer.getPlayerState && ytPlayer.getPlayerState() === 1) : (video && !video.paused && !video.ended); if (on) { lastHb = Date.now(); HD.api("youtube", "playing", { id: current.id, title: current.title, channel: current.channel, state: "playing" }); } }
  function updateTime() {
    if (!root || !current) return;
    const t = curTime(), t1 = root.querySelector("#yt-t1"), sk = root.querySelector("#yt-seek");
    if (!dragging) { if (t1) t1.textContent = fmtDur(t); if (sk && duration) sk.value = Math.round(t / duration * 1000); }
    heartbeat();
  }
  async function playNative(v, t) {
    const my = ++seq;
    tOffset = t || 0; iframeMode = false;
    const stage = root.querySelector("#yt-stage"); if (!stage) return;
    if (video) { try { video.pause(); video.removeAttribute("src"); video.load(); } catch (e) {} video.remove(); video = null; }
    video = document.createElement("video");
    video.setAttribute("playsinline", ""); video.autoplay = true; video.preload = "auto"; video.volume = 1;
    video.src = streamUrl(v.id, tOffset);
    stage.insertBefore(video, stage.querySelector("#yt-ctl"));
    const spin = root.querySelector("#yt-spin"), note = root.querySelector("#yt-note");
    video.addEventListener("playing", () => { if (my !== seq) return; if (spin) spin.style.display = "none"; const p = root.querySelector(".yt-poster"); if (p) p.style.display = "none"; setPlayIcon(); report("playing"); showCtl(); });
    video.addEventListener("waiting", () => { if (spin) spin.style.display = ""; });
    video.addEventListener("pause", () => { if (my !== seq) return; setPlayIcon(); showCtl(); report("paused"); });
    video.addEventListener("ended", () => { if (my !== seq) return; report("ended"); if (!step(1)) { setPlayIcon(); showCtl(); } });
    video.addEventListener("error", () => { if (my !== seq) return; if (video.error && video.error.code === 4 && tOffset === 0) fallbackEmbed(v, "Playing through YouTube's player"); else if (note) note.textContent = "Playback stopped (network). Tap play to retry."; });
    if (!tick) tick = setInterval(updateTime, 250);
    try { await video.play(); } catch (e) {}
  }
  function seekTo(t) {
    if (!current) return;
    t = Math.max(0, Math.min(duration ? duration - 1 : t, t));
    if (iframeMode) { ytPlayer && ytPlayer.seekTo && ytPlayer.seekTo(t, true); return; }
    playNative(current, t); updateTime();
  }
  function togglePlay() {
    if (iframeMode) { if (!ytPlayer) return; const s = ytPlayer.getPlayerState(); s === 1 ? ytPlayer.pauseVideo() : ytPlayer.playVideo(); return; }
    if (!video) return;
    if (video.paused || video.ended) { if (video.ended) { playNative(current, 0); return; } video.play().catch(() => {}); } else video.pause();
    setPlayIcon();
  }
  function step(dir) {
    const list = listFor(); if (!current || list.length < 2) return false;
    const i = list.findIndex(x => x.id === current.id); if (i < 0) return false;
    const n = list[i + dir]; if (!n) return false;
    HD.api("youtube", "play", { id: n.id }); return true;
  }
  async function playVideo(v) {
    current = v; view = "player"; lastReport = "";
    if (!root || !root.isConnected) return;
    drawPlayer(v);
    duration = v.duration || 0;
    const note = root.querySelector("#yt-note");
    const my = ++seq;
    const r = await HD.api("youtube", "resolve", { id: v.id });
    if (!root || my !== seq || !current || current.id !== v.id) return;
    if (r && r.ok) {
      if (r.duration) { duration = r.duration; const t2 = root.querySelector("#yt-t2"); if (t2) t2.textContent = fmtDur(duration); }
      if (r.title && !v.title) { v.title = r.title; v.channel = r.channel; const b = root.querySelector(".yt-top b"); if (b) b.textContent = r.title; }
    }
    if (r && r.ok && r.stream_ok) { if (note) note.textContent = r.height ? `${r.height}p · direct stream` : ""; playNative(v, 0); }
    else fallbackEmbed(v, (r && r.error) ? `${r.error}. Playing through YouTube's player` : "Playing through YouTube's player");
    if (!watchdog) watchdog = setInterval(() => { if (!root || !root.isConnected) { stopPlayer(true); root = null; clearInterval(watchdog); watchdog = null; } }, 1000);
  }

  // ---------- fallback: YouTube's own embedded player
  function loadApi() {
    if (window.YT && window.YT.Player) return Promise.resolve();
    if (apiLoading) return apiLoading;
    apiLoading = new Promise((ok, fail) => {
      const prev = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => { prev && prev(); ok(); };
      const s = document.createElement("script"); s.src = "https://www.youtube.com/iframe_api"; s.onerror = () => { apiLoading = null; fail(new Error("YouTube player failed to load")); };
      document.head.appendChild(s);
      setTimeout(() => { if (!(window.YT && window.YT.Player)) { apiLoading = null; fail(new Error("YouTube player timed out")); } }, 15000);
    });
    return apiLoading;
  }
  async function fallbackEmbed(v, why) {
    iframeMode = true;
    const note = root && root.querySelector("#yt-note"); if (note) note.textContent = why;
    if (video) { try { video.pause(); video.removeAttribute("src"); video.load(); } catch (e) {} video.remove(); video = null; }
    const stage = root && root.querySelector("#yt-stage"); if (!stage) return;
    const spin = root.querySelector("#yt-spin"); if (spin) spin.style.display = "none";
    const ctl = root.querySelector("#yt-ctl"); if (ctl) ctl.classList.add("hide");         // YouTube's player has its own controls
    let host = stage.querySelector(".yt-host"); if (!host) { host = document.createElement("div"); host.className = "yt-host"; stage.insertBefore(host, ctl); }
    try { await loadApi(); } catch (e) { if (note) note.textContent = e.message; return; }
    if (ytPlayer) { try { ytPlayer.destroy(); } catch (e) {} ytPlayer = null; }
    if (!tick) tick = setInterval(updateTime, 250);
    ytPlayer = new YT.Player(host, {
      host: "https://www.youtube-nocookie.com", videoId: v.id, width: "100%", height: "100%",
      playerVars: { playsinline: 1, autoplay: 1, rel: 0, modestbranding: 1, controls: 1, iv_load_policy: 3, origin: location.origin },
      events: {
        onReady: e => { try { e.target.setPlaybackQuality("small"); e.target.playVideo(); } catch (x) {} },
        onStateChange: e => { const s = e.data === 1 ? "playing" : e.data === 2 ? "paused" : e.data === 0 ? "ended" : null; if (s) report(s); if (s === "ended") step(1); },
        onError: () => { if (note) note.textContent = "This video can't be played here (embedding blocked or unavailable)."; report("stopped"); },
      },
    });
    // the close and full-screen buttons live in our overlay, which is hidden in this mode: give a small row instead
    const bar = root.querySelector(".yt-player"); if (bar && !bar.querySelector("#yt-fbrow")) { const d = document.createElement("div"); d.id = "yt-fbrow"; d.className = "yt-row"; d.style.marginTop = "4px"; d.innerHTML = `<button class="btn" id="yt-fclose">Close</button><button class="btn" id="yt-ffull">Full screen</button>`; bar.insertBefore(d, root.querySelector("#yt-note")); d.querySelector("#yt-fclose").onclick = () => { stopPlayer(true); view = "search"; drawSearch(); }; d.querySelector("#yt-ffull").onclick = () => document.body.classList.toggle("yt-full"); }
  }

  function stopPlayer(tellServer) {
    seq++;
    document.body.classList.remove("yt-full");
    clearTimeout(hideTimer); if (tick) { clearInterval(tick); tick = null; }
    if (video) { try { video.pause(); video.removeAttribute("src"); video.load(); } catch (e) {} video.remove(); video = null; }
    if (ytPlayer) { try { ytPlayer.stopVideo(); ytPlayer.destroy(); } catch (e) {} ytPlayer = null; }
    if (tellServer) { const id = current && current.id; fetch("/api/youtube/stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }), keepalive: true }).catch(() => {}); }
    current = null; iframeMode = false; lastReport = "";
  }

  HD.registerApp({
    id: "youtube", title: "YouTube", icon: "youtube", order: 13,
    render(el) {
      el.innerHTML = `<div id="ytapp"></div>`; root = el.querySelector("#ytapp");
      if (view === "player" && current) playVideo(current); else { view = "search"; drawSearch(); }
      if (!watchdog) watchdog = setInterval(() => { if (!root || !root.isConnected) { stopPlayer(true); root = null; clearInterval(watchdog); watchdog = null; } }, 1000);
    },
    update(s) {
      if (!root) return;
      if (view === "search" && !(document.activeElement && document.activeElement.matches("input"))) { const h = JSON.stringify((s.youtube || {}).history || []); if (h !== lastHistKey) { lastHistKey = h; drawSearch(); } }
      if (view === "player") { const vs = root.querySelector("#yt-vol"), av = s.audio && s.audio.music_pct; if (vs && av != null && document.activeElement !== vs) vs.value = av; }
    },
    idleSize: "2x1",
    idleWidget(el, s) {
      const y = s.youtube || {};
      if (!y.playing || !y.current) { HD.setHtml(el, ""); return; }
      HD.setHtml(el, `<div class="iw-label">YouTube</div><div class="iw-mid">${esc(y.current.title || "Playing")}</div><div class="iw-sub">${esc(y.current.channel || "")}</div>`);
      return "2x1";
    },
    onEvent(name, data) {
      if (name === "youtube_play" && data && data.id) {
        const known = results.find(x => x.id === data.id) || ((HD.state.youtube || {}).history || []).find(x => x.id === data.id);
        const v = { id: data.id, title: data.title || (known && known.title) || "", channel: data.channel || (known && known.channel) || "", thumb: `https://i.ytimg.com/vi/${data.id}/mqdefault.jpg`, duration: known && known.duration };
        if (!root || !root.isConnected) { current = v; view = "player"; HD.openApp("youtube"); }
        else playVideo(v);
      }
      if (name === "youtube_stop" && root && view === "player") { stopPlayer(false); view = "search"; drawSearch(); }
    },
  });
})();
