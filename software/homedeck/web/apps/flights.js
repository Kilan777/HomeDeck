/* Flight radar: live aircraft around home on a canvas radar (range rings, compass, airports, altitude-coloured planes
   with short trails), a distance-sorted list patched in place, a detail panel for the selected aircraft, and a quiet
   home tile when something is within 3 nm. Backend: modules/flights.py (adsb.lol + adsbdb). */
(() => {
  const CSS = `
  .fl-wrap { display: flex; gap: 14px; align-items: stretch; min-height: 0; }
  .fl-left { flex: 0 0 auto; display: flex; flex-direction: column; gap: 10px; }
  .fl-radar { position: relative; width: 392px; height: 392px; border-radius: 50%; background: radial-gradient(circle at 50% 50%, rgba(80,140,255,.10), rgba(10,14,24,.55) 70%); box-shadow: inset 0 0 0 1px rgba(255,255,255,.14); overflow: hidden; touch-action: none; }
  .fl-radar canvas { width: 100%; height: 100%; display: block; }
  .fl-right { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
  .fl-top { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
  .fl-top .seg { flex: 0 0 auto; }
  .fl-stat { font-size: 13px; color: var(--fg2); white-space: nowrap; }
  .fl-detail { border-radius: 14px; background: rgba(255,255,255,.08); box-shadow: inset 0 0 0 1px var(--hair); padding: 12px 14px; }
  .fl-detail .fl-h { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
  .fl-detail .fl-flight { font-size: 21px; font-weight: 650; letter-spacing: -.01em; }
  .fl-detail .fl-air { font-size: 14px; color: var(--fg2); }
  .fl-detail .fl-route { font-size: 16px; margin-top: 4px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .fl-detail .fl-route b { font-weight: 650; }
  .fl-detail .fl-route span { color: var(--fg2); }
  .fl-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px 12px; margin-top: 10px; }
  .fl-grid .k { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
  .fl-grid .v { font-size: 16px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .fl-grid .v small { font-size: 12px; font-weight: 500; color: var(--fg2); margin-left: 3px; }
  .fl-sq { color: #ff453a; font-weight: 700; }
  .fl-list { flex: 1 1 0; min-height: 0; overflow-y: auto; border-radius: 14px; background: rgba(255,255,255,.05); box-shadow: inset 0 0 0 1px var(--hair); }
  .fl-row { display: grid; grid-template-columns: 12px 1.4fr 1.6fr .8fr .7fr; gap: 10px; align-items: center; padding: 9px 12px; min-height: 46px; border-bottom: 1px solid var(--sep); font-size: 14px; cursor: pointer; }
  .fl-row:last-child { border-bottom: 0; }
  .fl-row.sel { background: rgba(255,255,255,.10); }
  .fl-row .dot { width: 10px; height: 10px; border-radius: 50%; }
  .fl-row .fl-f { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .fl-row .fl-f small { display: block; font-weight: 400; font-size: 12px; color: var(--fg2); }
  .fl-row .fl-r { color: var(--fg2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 13px; }
  .fl-row .fl-a, .fl-row .fl-d { font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
  .fl-row .fl-d { color: var(--fg2); }
  .fl-empty { padding: 18px 14px; color: var(--fg2); font-size: 14px; }
  .fl-legend { display: flex; gap: 12px; justify-content: center; font-size: 12px; color: var(--muted); }
  .fl-legend i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }
  #flights-card { column-span: all; }
  @media (max-width: 760px) { .fl-wrap { flex-direction: column; } .fl-radar { width: min(92vw, 360px); height: min(92vw, 360px); margin: 0 auto; } .fl-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (orientation: landscape) and (max-height: 600px) { .fl-radar { width: 372px; height: 372px; } .fl-list { max-height: 372px; } .fl-detail + .fl-list { max-height: 214px; } }`;
  if (!document.getElementById("fl-style")) { const st = document.createElement("style"); st.id = "fl-style"; st.textContent = CSS; document.head.appendChild(st); }

  const NM_PER_FT = 1 / 6076.12;
  let root = null, canvas = null, ctx2d = null, data = null, sel = null, range = 15, raf = null, pokeTimer = null, lastSig = "", dirty = true;
  const rows = new Map();   // hex -> row element

  const isMetric = () => HD.units() === "metric";
  const fmtDist = nm => isMetric() ? `${(nm * 1.852).toFixed(1)} km` : `${(nm * 1.15078).toFixed(1)} mi`;
  const fmtAlt = ft => ft == null ? "–" : ft <= 0 ? "Ground" : isMetric() ? `${Math.round(ft * 0.3048).toLocaleString()} m` : `${Math.round(ft).toLocaleString()} ft`;
  const fmtSpd = kt => kt == null ? "–" : isMetric() ? `${Math.round(kt * 1.852)} km/h` : `${Math.round(kt * 1.15078)} mph`;
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  // altitude colour: low = warm, high = cool
  function altColor(ft) {
    if (ft == null) return "#a0a4ad";
    if (ft <= 0) return "#8e8e93";
    if (ft < 3000) return "#ff9f0a";
    if (ft < 8000) return "#ffd60a";
    if (ft < 15000) return "#30d158";
    if (ft < 28000) return "#5ac8fa";
    return "#7d8cff";
  }
  const routeText = a => { const r = a.route; if (!r || !(r.from || r.to)) return ""; const f = r.from && (r.from.iata || r.from.city), t = r.to && (r.to.iata || r.to.city); return f && t ? `${f} → ${t}` : t ? `to ${t}` : ""; };
  const vArrow = v => v == null || Math.abs(v) < 300 ? "" : v > 0 ? " ↑" : " ↓";

  // ------------------------------------------------------------- radar drawing
  function project(a, home, R, cx, cy) {
    // equirectangular around home: nm east/north
    const dLat = (a.lat - home.lat) * 60, dLon = (a.lon - home.lon) * 60 * Math.cos(home.lat * Math.PI / 180);
    return [cx + dLon / range * R, cy - dLat / range * R];
  }
  function draw() {
    raf = null;
    if (!canvas || !canvas.isConnected || !data) return;
    const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    const c = ctx2d; c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, h);
    const cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2 - 16, home = data.home || { lat: 37.7749, lon: -122.4194 };
    // rings
    c.lineWidth = 1; c.strokeStyle = "rgba(255,255,255,.14)"; c.fillStyle = "rgba(255,255,255,.45)"; c.font = "11px Inter, system-ui, sans-serif"; c.textAlign = "left";
    for (let i = 1; i <= 3; i++) { const r = R * i / 3; c.beginPath(); c.arc(cx, cy, r, 0, Math.PI * 2); c.stroke(); const nm = range * i / 3; c.fillText(`${Number.isInteger(nm) ? nm : nm.toFixed(1)} nm`, cx + 4, cy - r + 12); }
    // compass
    c.strokeStyle = "rgba(255,255,255,.08)"; c.beginPath(); c.moveTo(cx - R, cy); c.lineTo(cx + R, cy); c.moveTo(cx, cy - R); c.lineTo(cx, cy + R); c.stroke();
    c.fillStyle = "rgba(255,255,255,.5)"; c.font = "600 11px Inter, system-ui, sans-serif"; c.textAlign = "center";
    c.fillText("N", cx, cy - R - 4); c.fillText("S", cx, cy + R + 12); c.fillText("E", cx + R + 8, cy + 4); c.fillText("W", cx - R - 8, cy + 4);
    // airports
    for (const ap of data.airports || []) {
      const [x, y] = project(ap, home, R, cx, cy); if (Math.hypot(x - cx, y - cy) > R) continue;
      c.fillStyle = "rgba(255,255,255,.55)"; c.fillRect(x - 3, y - 3, 6, 6);
      c.fillStyle = "rgba(255,255,255,.6)"; c.font = "600 10px Inter, system-ui, sans-serif"; c.textAlign = "left"; c.fillText(ap.iata, x + 6, y + 4);
    }
    // home
    c.fillStyle = "#fff"; c.beginPath(); c.arc(cx, cy, 3.5, 0, Math.PI * 2); c.fill();
    c.strokeStyle = "rgba(255,255,255,.35)"; c.beginPath(); c.arc(cx, cy, 7, 0, Math.PI * 2); c.stroke();
    // aircraft
    const placed = [];
    for (const a of data.aircraft) {
      const [x, y] = project(a, home, R, cx, cy);
      if (Math.hypot(x - cx, y - cy) > R + 6) continue;
      const col = altColor(a.alt_ft), isSel = sel === a.hex;
      const onGround = (a.alt_ft || 0) <= 0;
      if (onGround && !isSel) { c.fillStyle = "rgba(255,255,255,.28)"; c.beginPath(); c.arc(x, y, 2.2, 0, Math.PI * 2); c.fill(); continue; }
      // trail
      if (a.trail && a.trail.length > 1) {
        c.lineWidth = 1.5; c.lineCap = "round";
        for (let i = 1; i < a.trail.length; i++) {
          const [x0, y0] = project({ lat: a.trail[i - 1][0], lon: a.trail[i - 1][1] }, home, R, cx, cy), [x1, y1] = project({ lat: a.trail[i][0], lon: a.trail[i][1] }, home, R, cx, cy);
          c.strokeStyle = col; c.globalAlpha = 0.12 + 0.5 * (i / a.trail.length); c.beginPath(); c.moveTo(x0, y0); c.lineTo(x1, y1); c.stroke();
        }
        c.globalAlpha = 1;
      }
      c.save(); c.translate(x, y); c.rotate(((a.track || 0)) * Math.PI / 180);
      if (isSel) { c.strokeStyle = "rgba(255,255,255,.9)"; c.lineWidth = 1.5; c.beginPath(); c.arc(0, 0, 13, 0, Math.PI * 2); c.stroke(); }
      const s = isSel ? 1.25 : 1;
      c.fillStyle = a.emergency ? "#ff453a" : col;
      c.beginPath();                              // small plane silhouette pointing up
      c.moveTo(0, -8 * s); c.lineTo(1.6 * s, -3 * s); c.lineTo(8 * s, 1 * s); c.lineTo(8 * s, 2.6 * s); c.lineTo(1.6 * s, 1.2 * s); c.lineTo(1.4 * s, 5.5 * s); c.lineTo(3.6 * s, 7.2 * s); c.lineTo(3.6 * s, 8.2 * s);
      c.lineTo(0, 7 * s); c.lineTo(-3.6 * s, 8.2 * s); c.lineTo(-3.6 * s, 7.2 * s); c.lineTo(-1.4 * s, 5.5 * s); c.lineTo(-1.6 * s, 1.2 * s); c.lineTo(-8 * s, 2.6 * s); c.lineTo(-8 * s, 1 * s); c.lineTo(-1.6 * s, -3 * s); c.closePath(); c.fill();
      c.restore();
      const crowded = !isSel && placed.some(p => Math.abs(p[0] - x) < 60 && Math.abs(p[1] - y) < 14);
      if (!crowded) { c.fillStyle = isSel ? "#fff" : "rgba(255,255,255,.78)"; c.font = `${isSel ? "600 " : ""}11px Inter, system-ui, sans-serif`; c.textAlign = "left"; c.fillText(a.flight || a.callsign || "", x + 11, y + 4); placed.push([x, y]); }
    }
    // updated stamp
    if (data.updated_at) { c.fillStyle = "rgba(255,255,255,.35)"; c.font = "10px Inter, system-ui, sans-serif"; c.textAlign = "right"; c.fillText(`${data.source || ""} · ${Math.max(0, Math.round(Date.now() / 1000 - data.updated_at))} s ago`, w - 10, h - 8); }
  }
  const schedule = () => { if (!raf) raf = requestAnimationFrame(draw); };

  function hitTest(px, py) {
    if (!data || !canvas) return null;
    const w = canvas.clientWidth, h = canvas.clientHeight, cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2 - 16, home = data.home;
    let best = null, bd = 22;
    for (const a of data.aircraft) { const [x, y] = project(a, home, R, cx, cy); const d = Math.hypot(x - px, y - py); if (d < bd) { bd = d; best = a.hex; } }
    return best;
  }

  // ------------------------------------------------------------- list & detail
  function rowHtml(a) {
    return `<span class="dot" style="background:${altColor(a.alt_ft)}"></span><span class="fl-f">${esc(a.flight)}<small>${esc(a.airline || a.type_name || a.type || a.reg || "")}</small></span><span class="fl-r">${esc(routeText(a) || (a.type_name || a.type || ""))}</span><span class="fl-a">${fmtAlt(a.alt_ft)}${vArrow(a.vrate)}</span><span class="fl-d">${fmtDist(a.dist_nm)}</span>`;
  }
  function patchList() {
    const list = root.querySelector("#fl-list"); if (!list) return;
    const seen = new Set();
    const empty = list.querySelector(".fl-empty"); if (empty) empty.remove();
    data.aircraft.forEach((a, i) => {
      seen.add(a.hex);
      let r = rows.get(a.hex);
      if (!r) { r = document.createElement("div"); r.className = "fl-row"; r.dataset.hex = a.hex; r.onclick = () => select(a.hex); rows.set(a.hex, r); }
      const html = rowHtml(a); if (r.dataset.h !== html) { r.innerHTML = html; r.dataset.h = html; }
      r.classList.toggle("sel", sel === a.hex);
      if (list.children[i] !== r) list.insertBefore(r, list.children[i] || null);
    });
    for (const [hx, r] of rows) if (!seen.has(hx)) { r.remove(); rows.delete(hx); }
    if (!data.aircraft.length) list.innerHTML = `<div class="fl-empty">${data.error ? "Flight data unavailable: " + esc(data.error) : "Nothing in range right now."}</div>`;
  }
  function detailHtml(a) {
    const r = a.route || {}, f = r.from || {}, t = r.to || {};
    const route = f.city || t.city ? `<b>${esc(f.iata || "?")}</b><span>${esc(f.city || "")}</span> → <b>${esc(t.iata || "?")}</b><span>${esc(t.city || "")}</span>` : `<span>${a.callsign ? "Route not known" : "No callsign"}</span>`;
    const sqBad = a.emergency;
    return `<div class="fl-h"><span class="fl-flight">${esc(a.flight)}</span><span class="fl-air">${esc(a.airline || "")}${a.reg ? (a.airline ? " · " : "") + esc(a.reg) : ""}</span></div>
      <div class="fl-route">${route}</div>
      <div class="fl-grid">
        <div><div class="k">Type</div><div class="v" style="white-space:normal;font-size:14px">${esc(a.type_name || a.type || "–")}</div></div>
        <div><div class="k">Altitude</div><div class="v">${fmtAlt(a.alt_ft)}${vArrow(a.vrate)}</div></div>
        <div><div class="k">Speed</div><div class="v">${fmtSpd(a.gs_kt)}</div></div>
        <div><div class="k">Heading</div><div class="v">${a.track == null ? "–" : a.track + "°"}<small>${esc(a.track == null ? "" : compass(a.track))}</small></div></div>
        <div><div class="k">Distance</div><div class="v">${fmtDist(a.dist_nm)}<small>${esc(a.compass)}</small></div></div>
        <div><div class="k">Bearing</div><div class="v">${a.bearing}°</div></div>
        <div><div class="k">Squawk</div><div class="v ${sqBad ? "fl-sq" : ""}">${esc(a.squawk || "–")}${sqBad ? "<small>emergency</small>" : ""}</div></div>
        <div><div class="k">Vertical</div><div class="v">${a.vrate == null ? "–" : (a.vrate > 0 ? "+" : "") + a.vrate}<small>${a.vrate == null ? "" : "ft/min"}</small></div></div>
      </div>`;
  }
  const compass = d => ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(((d % 360) + 360) % 360 / 45) % 8];
  function renderDetail() {
    const box = root.querySelector("#fl-detail"); if (!box) return;
    const a = data && data.aircraft.find(x => x.hex === sel);
    if (!a) { box.classList.add("hidden"); box.innerHTML = ""; return; }
    const html = detailHtml(a); if (box.dataset.h !== html) { box.innerHTML = html; box.dataset.h = html; }
    box.classList.remove("hidden");
  }
  function select(hx) { sel = sel === hx ? null : hx; renderDetail(); patchList(); schedule(); const r = rows.get(sel); if (r) r.scrollIntoView({ block: "nearest" }); }

  function apply(state) {
    const st = state.flights; if (!st || !root || !root.isConnected) return;
    data = st; range = st.radius_nm || range;
    const stat = root.querySelector("#fl-stat"); if (stat) stat.textContent = st.error && !st.aircraft.length ? "No data" : `${st.count} aircraft within ${range} nm`;
    root.querySelectorAll("[data-nm]").forEach(b => b.classList.toggle("on", +b.dataset.nm === range));
    if (sel && !st.aircraft.some(a => a.hex === sel)) { sel = null; }
    patchList(); renderDetail(); schedule();
  }

  // ------------------------------------------------------------- app
  HD.registerApp({
    id: "flights", title: "Flights", order: 27, idleAppend: true, idleSize: "2x1",
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.5 13.5L4 11l1.2-1.2 6.3 1.2 4.6-4.6a1.6 1.6 0 012.3 2.3l-4.6 4.6 1.2 6.3L13.8 21l-2.5-6.5-3 3 .2 2.4-1.3 1.3-1.5-3.2-3.2-1.5 1.3-1.3 2.4.2 3-3z"/></svg>',
    render(el) {
      root = el; rows.clear(); sel = null;
      el.innerHTML = `<div class="card" id="flights-card">
        <div class="fl-wrap">
          <div class="fl-left"><div class="fl-radar"><canvas id="fl-canvas"></canvas></div>
            <div class="fl-legend"><span><i style="background:#ff9f0a"></i>under 3k ft</span><span><i style="background:#ffd60a"></i>3 to 8k</span><span><i style="background:#30d158"></i>8 to 15k</span><span><i style="background:#5ac8fa"></i>15 to 28k</span><span><i style="background:#7d8cff"></i>above</span></div></div>
          <div class="fl-right">
            <div class="fl-top"><span class="fl-stat" id="fl-stat">Loading…</span><div class="seg">${[5, 15, 30, 60].map(n => `<button class="segbtn" data-nm="${n}">${n} nm</button>`).join("")}</div></div>
            <div class="fl-detail hidden" id="fl-detail"></div>
            <div class="fl-list" id="fl-list"><div class="fl-empty">Loading…</div></div>
          </div>
        </div></div>`;
      canvas = el.querySelector("#fl-canvas"); ctx2d = canvas.getContext("2d");
      const radar = el.querySelector(".fl-radar");
      radar.addEventListener("pointerdown", e => { const rc = canvas.getBoundingClientRect(); const hx = hitTest(e.clientX - rc.left, e.clientY - rc.top); if (hx) select(hx); else if (sel) select(sel); });
      el.querySelectorAll("[data-nm]").forEach(b => b.onclick = async () => { range = +b.dataset.nm; el.querySelectorAll("[data-nm]").forEach(x => x.classList.toggle("on", x === b)); schedule(); await HD.api("flights", "set_range", { nm: range }); });
      const poke = () => { if (!el.isConnected) { clearInterval(pokeTimer); pokeTimer = null; return; } HD.api("flights", "poke", {}); };
      clearInterval(pokeTimer); poke(); pokeTimer = setInterval(poke, 8000);
      const tick = () => { if (!el.isConnected) return; schedule(); setTimeout(tick, 1000); }; setTimeout(tick, 1000);
      window.addEventListener("resize", schedule);
      apply(HD.state);
    },
    update(s) { apply(s); },
    idleWidget(el, s) {
      const st = s.flights; const within = st && st.aircraft ? st.aircraft.filter(a => a.dist_nm <= (3)) : [];
      if (!within.length) { HD.setHtml(el, ""); return; }
      within.sort((a, b) => a.dist_nm - b.dist_nm);
      const a = within[0]; const r = a.route || {}; const to = r.to && (r.to.city || r.to.iata);
      HD.setHtml(el, `<div class="iw-label">Flights</div><div class="iw-mid">${esc(a.flight)}${to ? " to " + esc(to) : ""}</div><div class="iw-sub">${st.count} nearby · ${fmtAlt(a.alt_ft)} · ${fmtDist(a.dist_nm)} ${esc(a.compass)}</div>`);
      return "2x1";
    },
  });
})();
