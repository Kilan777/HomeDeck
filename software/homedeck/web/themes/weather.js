/* Home style "weather": animated weather scene (one cheap 2D canvas, ~15 fps), left-aligned clock, temperature
   headline, next-hours strip, and a tile board that reuses the apps' own idle widgets on translucent cards. Registered with HD.registerHome("weather"). */
(() => {
  const qs = new URLSearchParams(location.search);
  const forcedCode = qs.has("wx") ? parseInt(qs.get("wx"), 10) : null;   // ?wx=61 previews rain, ?night=1 previews night
  const forcedNight = qs.has("night");

  // ---------------------------------------------------------------- scene classification (WMO weather codes)
  function kind(code) {
    if (code == null) return "clear";
    if (code === 0 || code === 1) return "clear";
    if (code === 2) return "partly";
    if (code === 3) return "cloudy";
    if (code === 45 || code === 48) return "fog";
    if (code >= 51 && code <= 57) return "drizzle";
    if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return "rain";
    if ((code >= 71 && code <= 77) || code === 85 || code === 86) return "snow";
    if (code >= 95) return "thunder";
    return "cloudy";
  }
  const PAL = {   // [top, bottom] gradients per scene, day / night
    clear:   { day: ["#2a63ad", "#7db3e3"], night: ["#070f24", "#1b2a52"] },
    partly:  { day: ["#3a6fae", "#93b2cf"], night: ["#0b1430", "#28365a"] },
    cloudy:  { day: ["#48586e", "#8590a0"], night: ["#161c28", "#2b3443"] },
    fog:     { day: ["#6b7380", "#a7adb5"], night: ["#1c2129", "#3a414c"] },
    drizzle: { day: ["#3f4f63", "#71818f"], night: ["#141b26", "#2a3441"] },
    rain:    { day: ["#2c3a4d", "#556577"], night: ["#0f1620", "#25303e"] },
    snow:    { day: ["#5d6b80", "#b5bdc6"], night: ["#1a2230", "#414c5c"] },
    thunder: { day: ["#232c3a", "#4a5262"], night: ["#0b0f18", "#1f2531"] },
  };

  // ---------------------------------------------------------------- canvas scene
  let canvas, ctx2d, W = 0, H = 0, scene = "", isDay = true, parts = [], clouds = [], stars = [], last = 0, flash = 0, raf = null;
  const rnd = (a, b) => a + Math.random() * (b - a);
  function ensureCanvas(idle) {
    if (canvas && canvas.isConnected) return;
    // The sky is a fixed backdrop for the whole UI: home, the app switcher sheet and every app page draw on top of it.
    canvas = document.createElement("canvas"); canvas.id = "wxbg"; document.body.prepend(canvas); ctx2d = canvas.getContext("2d", { alpha: false });
    if (!document.getElementById("skydim")) { const d = document.createElement("div"); d.id = "skydim"; canvas.after(d); }
    const fit = () => { W = Math.max(300, innerWidth); H = Math.max(400, innerHeight); canvas.width = W; canvas.height = H; };
    fit(); addEventListener("resize", fit);
    if (!raf) raf = requestAnimationFrame(tick);
  }
  function buildScene(k) {
    scene = k; parts = []; clouds = []; stars = [];
    const n = 40;
    if (k === "rain" || k === "drizzle" || k === "thunder") for (let i = 0; i < n; i++) parts.push({ x: rnd(0, W), y: rnd(0, H), v: rnd(k === "drizzle" ? 3 : 6, k === "drizzle" ? 5 : 10), l: rnd(k === "drizzle" ? 6 : 12, k === "drizzle" ? 10 : 22), a: rnd(.18, .38) });
    if (k === "snow") for (let i = 0; i < n; i++) parts.push({ x: rnd(0, W), y: rnd(0, H), v: rnd(.6, 1.6), r: rnd(1.2, 3), d: rnd(0, 6.28), a: rnd(.35, .8) });
    if (k === "partly" || k === "cloudy" || k === "fog" || k === "rain" || k === "drizzle" || k === "thunder" || k === "snow") {
      const cn = k === "partly" ? 3 : k === "fog" ? 0 : 5;
      for (let i = 0; i < cn; i++) clouds.push({ x: rnd(-200, W), y: rnd(40, H * .45), s: rnd(.8, 1.5), v: rnd(.12, .3), a: k === "partly" ? .16 : .12 });
    }
    if (!isDay) for (let i = 0; i < (k === "clear" ? 40 : k === "partly" ? 18 : 0); i++) stars.push({ x: rnd(0, W), y: rnd(0, H * .6), r: rnd(.6, 1.6), p: rnd(0, 6.28), s: rnd(.4, 1.2) });
  }
  function drawCloud(c) {
    const s = c.s * 34;
    ctx2d.fillStyle = `rgba(255,255,255,${c.a})`;
    for (const [dx, dy, r] of [[0, 0, 1], [.9, -.35, .8], [1.9, 0, .95], [.6, .45, .75], [1.5, .5, .7], [-.6, .3, .7]]) {
      ctx2d.beginPath(); ctx2d.arc(c.x + dx * s, c.y + dy * s, r * s, 0, 6.28); ctx2d.fill();
    }
  }
  function tick(t) {
    raf = requestAnimationFrame(tick);
    if (t - last < 66) return; const dt = Math.min(3, (t - last) / 66); last = t;           // ~15 fps, cheap on the Pi
    const bgMode = document.documentElement.dataset.bg || "live";                       // Settings > Background: solid/gradient stop the scene
    if (!ctx2d || document.documentElement.dataset.home !== "weather" || bgMode !== "live" || document.body.classList.contains("screen-off") || document.hidden) return;
    const p = (PAL[scene] || PAL.clear)[isDay ? "day" : "night"];
    const g = ctx2d.createLinearGradient(0, 0, 0, H); g.addColorStop(0, p[0]); g.addColorStop(1, p[1]);
    ctx2d.fillStyle = g; ctx2d.fillRect(0, 0, W, H);
    const sec = t / 1000;
    if (isDay && (scene === "clear" || scene === "partly")) {                       // slow sun glow, top right
      const pulse = .55 + .1 * Math.sin(sec * .35);
      const sx = W > H ? W * .4 : W * .82;
      const sg = ctx2d.createRadialGradient(sx, H * .12, 10, sx, H * .12, W * .75);
      sg.addColorStop(0, `rgba(255,236,190,${pulse})`); sg.addColorStop(.25, `rgba(255,214,150,${pulse * .35})`); sg.addColorStop(1, "rgba(255,200,120,0)");
      ctx2d.fillStyle = sg; ctx2d.fillRect(0, 0, W, H);
    }
    if (isDay && scene === "clear") {
      const hz = ctx2d.createLinearGradient(0, H * .55, 0, H);
      hz.addColorStop(0, "rgba(255,225,170,0)"); hz.addColorStop(1, "rgba(255,214,150,.28)");
      ctx2d.fillStyle = hz; ctx2d.fillRect(0, H * .55, W, H * .45);
    }
    if (!isDay) {
      for (const s of stars) { const a = .35 + .55 * (.5 + .5 * Math.sin(sec * s.s + s.p)); ctx2d.fillStyle = `rgba(255,255,255,${a.toFixed(2)})`; ctx2d.beginPath(); ctx2d.arc(s.x, s.y, s.r, 0, 6.28); ctx2d.fill(); }
      if (scene === "clear" || scene === "partly") {                                 // moon with a soft crescent
        const mx = W > H ? W * .4 : W * .8, my = W > H ? H * .12 : H * .14, mr = 26;
        const mg = ctx2d.createRadialGradient(mx, my, mr, mx, my, mr * 4); mg.addColorStop(0, "rgba(255,250,230,.28)"); mg.addColorStop(1, "rgba(255,250,230,0)");
        ctx2d.fillStyle = mg; ctx2d.fillRect(mx - mr * 4, my - mr * 4, mr * 8, mr * 8);
        ctx2d.fillStyle = "#f6f1df"; ctx2d.beginPath(); ctx2d.arc(mx, my, mr, 0, 6.28); ctx2d.fill();
        ctx2d.fillStyle = p[0]; ctx2d.beginPath(); ctx2d.arc(mx - mr * .45, my - mr * .2, mr * .92, 0, 6.28); ctx2d.fill();
      }
    }
    for (const c of clouds) { c.x += c.v * dt; if (c.x > W + 160) c.x = -260; drawCloud(c); }
    if (scene === "fog") for (let i = 0; i < 5; i++) { const y = H * (.25 + i * .14) + Math.sin(sec * .2 + i) * 10; const fg = ctx2d.createLinearGradient(0, y, 0, y + 70); fg.addColorStop(0, "rgba(255,255,255,0)"); fg.addColorStop(.5, "rgba(255,255,255,.1)"); fg.addColorStop(1, "rgba(255,255,255,0)"); ctx2d.fillStyle = fg; ctx2d.fillRect(0, y, W, 70); }
    if (scene === "rain" || scene === "drizzle" || scene === "thunder") {
      ctx2d.lineWidth = 1.2; ctx2d.lineCap = "round";
      for (const r of parts) { r.y += r.v * dt; r.x -= .6 * dt; if (r.y > H) { r.y = -20; r.x = rnd(0, W + 40); } ctx2d.strokeStyle = `rgba(210,225,245,${r.a})`; ctx2d.beginPath(); ctx2d.moveTo(r.x, r.y); ctx2d.lineTo(r.x - 2, r.y + r.l); ctx2d.stroke(); }
    }
    if (scene === "snow") for (const f of parts) { f.y += f.v * dt; f.d += .02 * dt; f.x += Math.sin(f.d) * .5; if (f.y > H) { f.y = -6; f.x = rnd(0, W); } ctx2d.fillStyle = `rgba(255,255,255,${f.a})`; ctx2d.beginPath(); ctx2d.arc(f.x, f.y, f.r, 0, 6.28); ctx2d.fill(); }
    if (scene === "thunder") { if (flash > 0) { ctx2d.fillStyle = `rgba(255,255,255,${(flash * .28).toFixed(2)})`; ctx2d.fillRect(0, 0, W, H); flash = Math.max(0, flash - .18 * dt); } else if (Math.random() < .004) flash = 1; }
    // darkening so white type stays readable everywhere
    const dg = ctx2d.createLinearGradient(0, 0, 0, H); dg.addColorStop(0, "rgba(0,0,0,.24)"); dg.addColorStop(.5, "rgba(0,0,0,.08)"); dg.addColorStop(1, "rgba(0,0,0,.42)");
    ctx2d.fillStyle = dg; ctx2d.fillRect(0, 0, W, H);
  }

  // ---------------------------------------------------------------- DOM
  const deg = (units) => units === "metric" ? "°C" : "°F";
  const r0 = v => v == null ? "–" : Math.round(v);
  function shortStation(n) { return (n || "").replace(/\bStreet\b/g, "St").replace(/ at /, " & ").replace(/\bSt\b/g, "St"); }
  function fmtWhen(iso, h) {
    const d = new Date(iso); if (isNaN(d)) return "";
    const now = new Date(), sameDay = d.toDateString() === now.toDateString();
    const tm = new Date(); tm.setDate(now.getDate() + 1);
    const day = sameDay ? "Today" : d.toDateString() === tm.toDateString() ? "Tomorrow" : d.toLocaleDateString([], { weekday: "short" });
    return `${day} · ${h.fmtTime(d)}`;
  }
  function mmss(s) { s = Math.max(0, Math.round(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }

  // tile board (lower half): reuses every app's idleWidget so tiles match the widget-board style, on translucent cards
  const ORDER = ["sensors", "bikes", "alarms", "calendar", "timers"];      // fixed leaders; append-tiles follow by their order
  function build(w, h) {
    w.innerHTML = `
      <div class="wx-hero">
        <div class="wx-temp"><span class="ic" id="wx-ic"></span><span class="t" id="wx-t">–</span><span class="c" id="wx-c"></span></div>
        <div class="wx-sub" id="wx-sub"></div>
        <div class="wx-hours" id="wx-hours"></div>
      </div>
      <div class="wx-board" id="wx-board"></div>`;
  }
  function renderBoard(board, state, apps, h) {
    const list = Object.values(apps).filter(a => a.idleWidget && !(HD.KIOSK && a.kioskHidden) && !(h.isGuest() && a.guestHidden) && !h.isHidden(a.id) && a.id !== "weather");
    const rank = a => { const i = ORDER.indexOf(a.id); return i >= 0 ? i : 100 + (a.order || 99); };
    list.sort((x, y) => rank(x) - rank(y));
    for (const a of list) {
      let el = board.querySelector(`#wx-iw-${a.id}`);
      if (!el) { el = document.createElement("div"); el.id = `wx-iw-${a.id}`; el.className = "iw"; el.addEventListener("click", e => { e.stopPropagation(); h.openApp(a.id); }); }
      let size = "1x1";
      try { size = a.idleWidget(el, state) || a.idleSize || "1x1"; } catch (e) { console.error("wx tile", a.id, e); }
      if (!el.innerHTML.trim()) { if (el.isConnected) el.remove(); continue; }      // nothing to say (mic on, lights off, ...)
      const cls = `iw iw-${size}` + (el.classList.contains("iw-quiet") ? " iw-quiet" : "");
      if (el.className !== cls) el.className = cls;
      board.appendChild(el);                                                        // re-append keeps DOM order == rank order
    }
    fitBoard(board);
  }

  // Landscape: pick the column count and row height from the tiles' real footprint so every tile fits the board
  // whatever combination is showing (a timer and a wide bike tile at once, a now-playing tile, ...).
  const LAND = matchMedia("(orientation: landscape) and (max-height: 600px)");
  function fitBoard(board) {
    if (!LAND.matches || document.getElementById("idle").classList.contains("music")) {
      board.style.removeProperty("--wx-cols"); board.style.removeProperty("--wx-row"); return;
    }
    const tiles = [...board.querySelectorAll(".iw")];
    const cells = tiles.reduce((n, el) => n + (el.classList.contains("iw-2x2") ? 4 : el.classList.contains("iw-2x1") ? 2 : 1), 0);
    let cols = 3;
    while (cols < 6 && Math.ceil(cells / cols) > 4) cols++;                     // never more than four rows
    if (cols === 3 && Math.ceil(cells / 3) === 4 && cells <= 12) cols = 4;      // prefer three roomy rows over four thin ones
    const h = board.clientHeight || 440, gap = 10;
    const place = (c) => {
      board.style.setProperty("--wx-cols", String(c));
      const rows = Math.max(1, Math.ceil(cells / c));
      let rowH = Math.max(88, Math.min(150, Math.floor((h - gap * (rows - 1)) / rows)));
      board.style.setProperty("--wx-row", rowH + "px");
      // dense packing can need one more row than the count suggests: measure and shrink once if so
      if (board.scrollHeight > board.clientHeight + 2) {
        rowH = Math.max(88, Math.floor(rowH * board.clientHeight / board.scrollHeight));
        board.style.setProperty("--wx-row", rowH + "px");
      }
    };
    place(cols);
    if (board.scrollHeight > board.clientHeight + 2 && cols < 5) place(cols + 1);
  }
  LAND.addEventListener("change", () => { const b = document.getElementById("wx-board"); if (b) fitBoard(b); });
  addEventListener("resize", () => { const b = document.getElementById("wx-board"); if (b) fitBoard(b); });

  function render(idle, state, apps, h) {
    ensureCanvas(idle);
    const w = document.getElementById("idlewidgets"); if (!w) return;
    if (!w.querySelector("#wx-board")) build(w, h);
    const wx = state.weather || {}, cur = wx.current || {};
    const code = forcedCode != null ? forcedCode : cur.code;
    const day = forcedNight ? false : (cur.is_day !== false);
    const k = kind(code);
    if (k !== scene || day !== isDay) { isDay = day; buildScene(k); }
    document.documentElement.dataset.sky = day ? "day" : "night";
    // hero
    h.setHtml(document.getElementById("wx-ic"), h.icon(cur.icon || (day ? "sun" : "moon"), ""));
    h.setText(document.getElementById("wx-t"), cur.temp == null ? "–" : r0(cur.temp) + "°");
    h.setText(document.getElementById("wx-c"), cur.text || "");
    const d0 = (wx.daily || [])[0] || {};
    const subParts = [];
    if (cur.apparent != null) subParts.push(`Feels like ${r0(cur.apparent)}°`);
    if (d0.hi != null) subParts.push(`H ${r0(d0.hi)}° L ${r0(d0.lo)}°`);
    if (d0.rain_pct != null && d0.rain_pct > 0) subParts.push(`Rain ${d0.rain_pct}%`);
    h.setText(document.getElementById("wx-sub"), subParts.join("  ·  "));
    const hours = (wx.hourly || []).slice(0, 5);
    h.setHtml(document.getElementById("wx-hours"), hours.map(x => `<div class="wx-hour"><span>${x.label || ""}</span>${h.icon(x.icon || "cloud", "")}<b>${r0(x.temp)}°</b></div>`).join(""));
    renderBoard(document.getElementById("wx-board"), state, apps, h);
  }

  // Keep the sky in sync even when no home screen has rendered yet (an app opened directly): classify from HD.state.
  function syncScene() {
    const cur = ((HD.state || {}).weather || {}).current || {};
    const code = forcedCode != null ? forcedCode : cur.code;
    const day = forcedNight ? false : (cur.is_day !== false);
    const k = kind(code);
    if (k !== scene || day !== isDay) { isDay = day; buildScene(k); }
    document.documentElement.dataset.sky = day ? "day" : "night";
  }
  HD.registerHome("weather", { render });
  ensureCanvas(); syncScene(); setInterval(syncScene, 5000);
})();
