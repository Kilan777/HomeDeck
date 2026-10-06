/* Air quality app: hero CO2 tile + comfort tiles with zone meters, sparklines and nudge popups. */
(() => {
  const fmt = (v, d) => v == null ? "–" : Number(v).toFixed(d);
  const tempOut = (c) => HD.units() === "metric" ? [c, "°C"] : [c == null ? null : c * 9 / 5 + 32, "°F"];

  function meter(m) {
    const span = m.hi - m.lo, pct = v => Math.max(0, Math.min(100, (v - m.lo) / span * 100));
    const segs = m.zones.map(([a, b, l, t]) => `<div class="seg-z ${l}" style="flex:${b - a} ${b - a} 0" title="${t}"></div>`).join("");
    const mark = m.value == null ? "" : `<div class="mark" style="left:${pct(m.value)}%"></div>`;
    const edges = [...new Set(m.zones.flatMap(([a, b]) => [a, b]))].filter(e => e > m.lo && e < m.hi);
    const lbl = e => m.key === "temp" && HD.units() !== "metric" ? Math.round(e * 9 / 5 + 32) : e;
    return `<div class="meter"><div class="track">${segs}</div>${mark}</div><div class="ticks">${edges.map(e => `<span style="left:${pct(e)}%">${lbl(e)}</span>`).join("")}</div>`;
  }
  function spark(h) {
    if (!h || h.length < 2) return "";
    const w = 300, ht = 40, min = Math.min(...h), max = Math.max(...h), r = (max - min) || 1;
    const pts = h.map((v, i) => `${(i / (h.length - 1) * w).toFixed(1)},${(ht - 4 - (v - min) / r * (ht - 8)).toFixed(1)}`).join(" ");
    return `<svg class="spark" viewBox="0 0 ${w} ${ht}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg><div class="hint" style="color:var(--muted)">Last ${Math.max(1, Math.round(h.length / 2))} min</div>`;
  }
  function chip(s) { return `<span class="chip"><span class="dot ${s.level}"></span>${s.text}</span>`; }
  function tile(m) {
    let v = m.value, u = m.unit, d = m.key === "co2" ? 0 : 1;
    if (m.key === "temp") [v, u] = tempOut(v);
    return `<div class="card"><div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px"><div><h3>${m.label}</h3><div class="big">${fmt(v, d)}<span style="font-size:17px;font-weight:500;color:var(--fg2);margin-left:4px">${u}</span></div></div>${chip(m.status)}</div>${meter(m)}${spark(m.history)}<div class="hint" style="margin-top:8px">${m.hint}</div></div>`;
  }

  // ---------- history chart (canvas, comfort bands, min/max/avg)
  const CSS = `
  .aq-hist{column-span:all;-webkit-column-span:all}
  .aq-hist .aq-top{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px}
  .aq-hist .seg{min-width:150px}
  .aq-hist .chips{margin:2px 0 8px}
  .aq-hist .chip{cursor:pointer;border:0;font:inherit}
  .aq-hist .chip.on{background:var(--app-accent,var(--accent));color:#fff}
  .aq-canvas{width:100%;height:190px;display:block;border-radius:10px}
  .aq-stats{display:flex;gap:22px;margin-top:8px;font-variant-numeric:tabular-nums;flex-wrap:wrap}
  .aq-stats div{display:flex;flex-direction:column;gap:1px}
  .aq-stats b{font-size:17px;font-weight:600;letter-spacing:-.01em}
  .aq-stats span{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
  .aq-empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:14px;pointer-events:none}
  @media (orientation: landscape) and (max-height: 600px){ .aq-canvas{height:170px} }`;
  if (!document.getElementById("aq-css")) { const st = document.createElement("style"); st.id = "aq-css"; st.textContent = CSS; document.head.appendChild(st); }

  const METRICS = [["co2", "CO₂"], ["temp", "Temperature"], ["hum", "Humidity"], ["voc", "VOC"], ["press", "Pressure"]];
  const ZONE_RGB = { good: "52,199,89", warning: "255,214,10", serious: "255,159,10", critical: "255,69,58" };
  const hist = { metric: "co2", hours: 24, data: null, busy: false, timer: null };
  const toUnit = (m, v) => v == null ? null : (m === "temp" && HD.units() !== "metric" ? v * 9 / 5 + 32 : v);
  const unitLbl = (m, u) => m === "temp" ? (HD.units() === "metric" ? "°C" : "°F") : u;
  const fmtV = (m, v) => v == null ? "–" : (m === "co2" || m === "temp" ? Math.round(v).toLocaleString() : Number(v).toFixed(m === "press" ? 1 : 0));
  const fmtT = (t, hours) => { const d = new Date(t * 1000); return hours > 48 ? d.toLocaleDateString([], { weekday: "short" }) : d.toLocaleTimeString([], { hour: "numeric" }).replace(" ", "").toLowerCase(); };

  async function loadHistory() {
    if (hist.busy) return; hist.busy = true;
    try { const r = await HD.api("sensors", "history", { hours: hist.hours, metric: hist.metric }); if (r && r.ok) hist.data = r; }
    catch (e) { console.error("air history", e); }
    hist.busy = false; drawHistory(); updateStats();
  }
  function updateStats() {
    const box = document.getElementById("aq-stats"); if (!box) return;
    const d = hist.data, m = hist.metric, u = d ? unitLbl(m, d.unit) : "";
    const cell = (l, v) => `<div><b>${v}${v !== "–" && u ? `<small style="font-size:12px;font-weight:500;color:var(--fg2);margin-left:2px">${u}</small>` : ""}</b><span>${l}</span></div>`;
    box.innerHTML = d && d.n ? cell("Low", fmtV(m, toUnit(m, d.min))) + cell("High", fmtV(m, toUnit(m, d.max))) + cell("Average", fmtV(m, toUnit(m, d.avg))) + cell("Peak at", d.max_t ? new Date(d.max_t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "–") : cell("Low", "–") + cell("High", "–") + cell("Average", "–");
  }
  function drawHistory() {
    const c = document.getElementById("aq-canvas"); if (!c) return;
    const dpr = Math.max(1, Math.min(3, window.devicePixelRatio || 1));
    const W = c.clientWidth || 600, H = c.clientHeight || 190;
    if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
    const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const empty = document.getElementById("aq-empty");
    const d = hist.data, m = hist.metric, pts = (d && d.points) || [];
    const cs = getComputedStyle(document.body), fg2 = cs.getPropertyValue("--fg2").trim() || "rgba(255,255,255,.7)", muted = cs.getPropertyValue("--muted").trim() || "rgba(255,255,255,.45)";
    const padL = 44, padR = 10, padT = 10, padB = 22, x0 = padL, x1 = W - padR, y0 = padT, y1 = H - padB;
    const since = d ? d.since : Date.now() / 1000 - hist.hours * 3600, until = d ? d.until : Date.now() / 1000;
    const vals = pts.map(p => toUnit(m, p.v));
    // y range: the data plus a little air, clamped inside the metric's own scale
    let lo = vals.length ? Math.min(...vals) : 0, hi = vals.length ? Math.max(...vals) : 1;
    if (!vals.length) { lo = toUnit(m, d && d.lo != null ? d.lo : 0); hi = toUnit(m, d && d.hi != null ? d.hi : 1); }
    let span = hi - lo || (m === "co2" ? 100 : m === "press" ? 4 : 2); lo -= span * .18; hi += span * .18;
    if (m === "co2") lo = Math.max(350, lo); if (m === "hum" || m === "voc") { lo = Math.max(0, lo); hi = Math.min(100, hi); }
    const X = t => x0 + (t - since) / Math.max(1, until - since) * (x1 - x0), Y = v => y1 - (v - lo) / (hi - lo) * (y1 - y0);
    // comfort bands: only when a zone boundary is in view (a single zone across the whole plot is just a tinted box)
    const zones = ((d && d.zones) || []).map(([a, b, level]) => [toUnit(m, a), toUnit(m, b), level]);
    const visible = zones.filter(([a, b]) => Math.max(a, lo) < Math.min(b, hi));
    if (visible.length > 1) for (const [a, b, level] of visible) {
      const ya = Y(a), yb = Y(b); const top = Math.max(y0, Math.min(ya, yb)), bot = Math.min(y1, Math.max(ya, yb));
      if (bot <= top) continue; g.fillStyle = `rgba(${ZONE_RGB[level] || "255,255,255"},.07)`; g.fillRect(x0, top, x1 - x0, bot - top);
      g.strokeStyle = `rgba(${ZONE_RGB[level] || "255,255,255"},.35)`; g.lineWidth = 1; g.beginPath(); g.moveTo(x0, Math.round(bot) + .5); g.lineTo(x1, Math.round(bot) + .5); g.stroke();
    }
    // grid + y labels (4 lines on nice steps)
    g.font = "500 11px Inter, system-ui, sans-serif"; g.textBaseline = "middle"; g.textAlign = "right";
    const rawStep = (hi - lo) / 4, mag = Math.pow(10, Math.floor(Math.log10(rawStep || 1))), step = [1, 2, 2.5, 5, 10].map(k => k * mag).find(k => k >= rawStep) || mag;
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
      const y = Y(v); if (y < y0 - 1 || y > y1 + 1) continue;
      g.strokeStyle = "rgba(255,255,255,.08)"; g.lineWidth = 1; g.beginPath(); g.moveTo(x0, Math.round(y) + .5); g.lineTo(x1, Math.round(y) + .5); g.stroke();
      g.fillStyle = muted; g.fillText(fmtV(m, v), x0 - 8, y);
    }
    // x labels
    g.textAlign = "center"; g.textBaseline = "top"; g.fillStyle = muted;
    const nx = hist.hours > 48 ? 7 : 6;
    for (let i = 0; i <= nx; i++) { const t = since + (until - since) * i / nx; const x = X(t); if (i === 0) g.textAlign = "left"; else if (i === nx) g.textAlign = "right"; else g.textAlign = "center"; g.fillText(fmtT(t, hist.hours), x, y1 + 6); }
    // axis baseline
    g.strokeStyle = "rgba(255,255,255,.16)"; g.beginPath(); g.moveTo(x0, y1 + .5); g.lineTo(x1, y1 + .5); g.stroke();
    if (empty) empty.style.display = vals.length ? "none" : "";
    if (!vals.length) return;
    // area + line, broken across gaps longer than 15 minutes
    const gapS = Math.max(900, (until - since) / 120);
    const accent = cs.getPropertyValue("--app-accent").trim() || cs.getPropertyValue("--accent").trim() || "#34c759";
    g.lineJoin = "round"; g.lineCap = "round";
    let segs = [], cur = [];
    pts.forEach((p, i) => { if (i && p.t - pts[i - 1].t > gapS) { if (cur.length) segs.push(cur); cur = []; } cur.push(p); }); if (cur.length) segs.push(cur);
    for (const sg of segs) {
      if (sg.length === 1) { g.fillStyle = accent; g.beginPath(); g.arc(X(sg[0].t), Y(toUnit(m, sg[0].v)), 2.5, 0, 6.283); g.fill(); continue; }
      g.beginPath(); sg.forEach((p, i) => { const x = X(p.t), y = Y(toUnit(m, p.v)); i ? g.lineTo(x, y) : g.moveTo(x, y); });
      g.lineTo(X(sg[sg.length - 1].t), y1); g.lineTo(X(sg[0].t), y1); g.closePath();
      const grad = g.createLinearGradient(0, y0, 0, y1); grad.addColorStop(0, "rgba(255,255,255,.16)"); grad.addColorStop(1, "rgba(255,255,255,0)"); g.fillStyle = grad; g.fill();
      g.beginPath(); sg.forEach((p, i) => { const x = X(p.t), y = Y(toUnit(m, p.v)); i ? g.lineTo(x, y) : g.moveTo(x, y); });
      g.strokeStyle = "#fff"; g.lineWidth = 2; g.stroke();
    }
    // last value marker
    const lp = pts[pts.length - 1]; g.fillStyle = "#fff"; g.beginPath(); g.arc(X(lp.t), Y(toUnit(m, lp.v)), 3.5, 0, 6.283); g.fill();
    g.strokeStyle = "rgba(0,0,0,.5)"; g.lineWidth = 1.5; g.stroke();
  }
  function historyCard() {
    return `<div class="card aq-hist"><div class="aq-top"><h3 style="margin:0">History</h3><div class="seg" id="aq-range">${[[24, "24 h"], [168, "7 d"]].map(([h, l]) => `<button class="segbtn ${hist.hours === h ? "on" : ""}" data-h="${h}">${l}</button>`).join("")}</div></div>
      <div class="chips" id="aq-metrics">${METRICS.map(([k, l]) => `<button class="chip ${hist.metric === k ? "on" : ""}" data-m="${k}">${l}</button>`).join("")}</div>
      <div style="position:relative"><canvas class="aq-canvas" id="aq-canvas"></canvas><div class="aq-empty" id="aq-empty" style="display:none">Collecting readings, the line will fill in over the next hours.</div></div>
      <div class="aq-stats" id="aq-stats"></div></div>`;
  }
  function wireHistory(el) {
    el.querySelectorAll("#aq-range .segbtn").forEach(b => b.onclick = () => { hist.hours = +b.dataset.h; el.querySelectorAll("#aq-range .segbtn").forEach(x => x.classList.toggle("on", x === b)); loadHistory(); });
    el.querySelectorAll("#aq-metrics .chip").forEach(b => b.onclick = () => { hist.metric = b.dataset.m; el.querySelectorAll("#aq-metrics .chip").forEach(x => x.classList.toggle("on", x === b)); loadHistory(); });
    loadHistory();
    clearInterval(hist.timer); hist.timer = setInterval(() => { if (document.getElementById("aq-canvas")) loadHistory(); else clearInterval(hist.timer); }, 60000);
  }
  let _ro = null;
  if (!_ro && window.ResizeObserver) { _ro = new ResizeObserver(() => drawHistory()); }

  HD.registerApp({
    id: "sensors", title: "Air", icon: "leaf", order: 8,
    render(el) {
      el.innerHTML = `<div id="aq"><div id="aq-tiles" style="display:contents"></div>${historyCard()}</div>`;
      wireHistory(el);
      const c = el.querySelector("#aq-canvas"); if (_ro && c) { _ro.disconnect(); _ro.observe(c); }
    },
    update(s) {
      const el = document.getElementById("aq-tiles"); if (!el) return;
      const ms = (s.sensors && s.sensors.metrics) || [];
      if (!ms.length) { el.innerHTML = `<div class="card hint">Waiting for the sensors… ${(s.sensors && s.sensors.scd40 && s.sensors.scd40.error) || ""}</div>`; return; }
      el.innerHTML = ms.map(tile).join("");
    },
    idleSize: "2x2",
    idleWidget(el, s) {
      const ms = (s.sensors && s.sensors.metrics) || []; const co2 = ms.find(m => m.key === "co2"), t = ms.find(m => m.key === "temp"), h = ms.find(m => m.key === "hum");
      if (!co2) { HD.setHtml(el, ""); return "2x2"; }
      const [tv, tu] = t ? tempOut(t.value) : [null, ""];
      const span = co2.hi - co2.lo, pct = v => Math.max(0, Math.min(100, (v - co2.lo) / span * 100));
      const segs = co2.zones.map(([a, b, l]) => `<div class="seg-z ${l}" style="flex:${b - a} ${b - a} 0"></div>`).join("");
      const mark = co2.value == null ? "" : `<div class="mark" style="left:${pct(co2.value)}%"></div>`;
      const hh = (co2.history || []).slice(-40); let sp = "";
      if (hh.length > 2) { const w = 200, ht = 28, mn = Math.min(...hh), mx = Math.max(...hh), r = (mx - mn) || 1;
        sp = `<svg class="iw-spark" viewBox="0 0 ${w} ${ht}" preserveAspectRatio="none"><polyline points="${hh.map((v, i) => `${(i / (hh.length - 1) * w).toFixed(1)},${(ht - 3 - (v - mn) / r * (ht - 6)).toFixed(1)}`).join(" ")}" fill="none" stroke="var(--fg2)" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`; }
      HD.setHtml(el, `<div class="iw-label">Air</div><div class="iw-big">${fmt(co2.value, 0)}<span class="iw-unit">ppm</span></div>
        <div class="iw-sub"><span class="dot ${co2.status.level}"></span>${co2.status.text} · ${fmt(tv, 0)}${tu}${h ? " · " + fmt(h.value, 0) + "%" : ""}</div>
        <div class="iw-meter">${segs}${mark}</div>${sp}`);
      return "2x2";
    },
    onEvent(name, data) {
      if (["co2_high", "co2_ok", "humidity_low", "humidity_high"].includes(name) && data && data.text) {
        if (name === "co2_ok") HD.toast(data.text, "good", 5000);
        else HD.popup({ title: name === "co2_high" ? "Fresh air time" : "Humidity", body: data.text, level: data.level || "warning", actions: [{ label: "Got it", onclick: () => HD.api("sensors", "clear_nudge") }] });
      }
    }
  });
})();
