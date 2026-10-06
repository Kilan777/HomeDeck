/* Weather app: Open-Meteo forecast + RainViewer radar animation. Backend: modules/weather.py */
(() => {
  const ICON = { sun: "sun", moon: "moon", partly: "cloud-sun", "partly-night": "cloud-moon", cloud: "cloud", fog: "fog", drizzle: "drizzle", rain: "rain", sleet: "snow", snow: "snow", storm: "thunder" };
  const ic = (k, cls = "") => HD.icon(ICON[k] || "cloud", cls);
  const deg = () => (HD.units() === "imperial" ? "°F" : "°C");
  const r0 = v => (v == null ? "–" : Math.round(v));
  const dayName = iso => { const d = new Date(iso + "T12:00:00"); const today = new Date(); return d.toDateString() === today.toDateString() ? "Today" : d.toLocaleDateString([], { weekday: "short" }); };

  // ---- radar: 3x3 slippy tiles at zoom Z around the configured location, animated RainViewer overlays
  const Z = 7;   // RainViewer's free tiles stop at zoom 7 (8 returns a 'not supported' tile)
  let radar = { timer: null, frame: 0, playing: true, built: null };
  function tileXY(lat, lon, z) {
    const n = 2 ** z, fx = (lon + 180) / 360 * n;
    const la = lat * Math.PI / 180, fy = (1 - Math.log(Math.tan(la) + 1 / Math.cos(la)) / Math.PI) / 2 * n;
    return { x: Math.floor(fx), y: Math.floor(fy), fx, fy };
  }
  const SCALE = 1.7;   // the 3x3 tile grid is scaled up so the view is ~500 km wide instead of ~900 km
  function buildRadar(el, w) {
    const loc = (HD.config.general || {}).location || { lat: 37.75, lon: -122.42 };
    const frames = (w.radar && w.radar.frames) || [];
    const key = frames.map(f => f.path).join(",") + loc.lat + loc.lon;
    if (radar.built === key) return;            // frames unchanged: keep the DOM and the animation
    radar.built = key; clearInterval(radar.timer);
    const { x, y, fx, fy } = tileXY(loc.lat, loc.lon, Z), host = (w.radar && w.radar.host) || "https://tilecache.rainviewer.com";
    // shift the grid so the exact location (not just its tile) sits in the middle of the box, then scale about the centre
    const sx = (0.5 - (fx - x)) / 3 * 100, sy = (0.5 - (fy - y)) / 3 * 100;
    const gridStyle = `position:absolute;inset:0;display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(3,1fr);transform:scale(${SCALE}) translate(${sx.toFixed(3)}%,${sy.toFixed(3)}%);transform-origin:50% 50%`;
    let html = `<div class="radar">`;
    const grid = layerHtml => `<div style="${gridStyle}">${layerHtml}</div>`;
    let base = "";
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) base += `<img src="https://tile.openstreetmap.org/${Z}/${x + dx}/${y + dy}.png" style="width:100%;height:100%;display:block;filter:invert(.9) hue-rotate(180deg) saturate(.35) brightness(.85)" alt="">`;
    html += grid(base);
    frames.forEach((f, i) => {
      let ov = "";
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) ov += `<img src="${host}${f.path}/256/${Z}/${x + dx}/${y + dy}/2/1_1.png" style="width:100%;height:100%;display:block;opacity:.8" alt="">`;
      html += `<div class="rframe" data-i="${i}" style="${gridStyle};display:${i === frames.length - 1 ? "grid" : "none"}">${ov}</div>`;
    });
    html += `<div style="position:absolute;left:50%;top:50%;width:12px;height:12px;margin:-6px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 3px #fff"></div>`;
    html += `<div class="rstamp"></div></div>`;
    html += `<div style="display:flex;gap:12px;margin-top:10px;align-items:center"><button class="btn" id="rplay" style="width:44px;padding:0;display:flex;align-items:center;justify-content:center">${HD.icon(radar.playing ? "pause" : "play", "")}</button><span class="hint">Past ${frames.length * 10} minutes. The dot is home.</span></div>`;
    el.innerHTML = html;
    const fr = el.querySelectorAll(".rframe"), stamp = el.querySelector(".rstamp");
    const show = i => { fr.forEach((f, j) => f.style.display = j === i ? "grid" : "none"); if (frames[i]) stamp.textContent = HD.fmtTime(new Date(frames[i].time * 1000)); };
    radar.frame = Math.max(0, frames.length - 1); show(radar.frame);
    const tick = () => { if (!frames.length) return; radar.frame = (radar.frame + 1) % frames.length; show(radar.frame); };
    const run = () => { clearInterval(radar.timer); if (radar.playing) radar.timer = setInterval(tick, 600); };
    el.querySelector("#rplay").onclick = e => { radar.playing = !radar.playing; e.currentTarget.innerHTML = HD.icon(radar.playing ? "pause" : "play", ""); run(); };
    run();
  }

  HD.registerApp({
    id: "weather", title: "Weather", icon: "cloud-sun", order: 10,
    idleSize: "2x2",
    idleWidget(el, s) {
      const w = s.weather || {}, c = w.current;
      if (!c) { HD.setHtml(el, `<div class="iw-label">Weather</div><div class="hint">${w.error ? "offline" : "loading…"}</div>`); return "2x2"; }
      const d0 = (w.daily || [])[0] || {};
      const hrs = (w.hourly || []).slice(1, 6).map(h => `<div><span>${new Date(h.time).toLocaleTimeString([], { hour: "numeric" }).replace(" ", "").toLowerCase()}</span>${ic(h.icon)}<b>${r0(h.temp)}°</b></div>`).join("");
      HD.setHtml(el, `<div class="iw-label">Weather</div>
        <div class="iw-big"><span class="iw-icon">${ic(c.icon)}</span>${r0(c.temp)}°</div>
        <div class="iw-sub">${c.text} · H ${r0(d0.hi)}° L ${r0(d0.lo)}°${d0.rain_pct >= 20 ? ` · ${d0.rain_pct}% rain` : ""}</div>
        <div class="iw-hours">${hrs}</div>`);
      return "2x2";
    },
    render(el) {
      el.innerHTML = `<div class="card" id="wnow"></div><div class="card"><h2>Hourly</h2><div class="hstrip" id="whourly"></div></div>
        <div class="card"><h2>7-day forecast</h2><div id="wdaily"></div></div><div class="card"><h2>Radar</h2><div id="wradar"></div></div>`;
      radar.built = null;
    },
    update(s) {
      const w = s.weather || {}, c = w.current, now = document.getElementById("wnow"); if (!now) return;
      if (!c) { now.innerHTML = `<div class="hint">${w.error ? "Weather offline: " + w.error : "Loading forecast…"}</div>`; return; }
      const wind = HD.units() === "imperial" ? "mph" : "km/h";
      const loc = (HD.config.general || {}).location || {};
      now.innerHTML = `<div class="wnow">${ic(c.icon)}<div><div class="wtemp">${r0(c.temp)}<small>${deg()}</small></div><div style="margin-top:6px">${c.text} · feels like ${r0(c.apparent)}°</div>
        <div class="hint">${loc.city ? loc.city + " · " : ""}Humidity ${c.humidity}% · Wind ${r0(c.wind)} ${wind}</div></div></div>${w.advice ? `<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--sep);font-size:15px;color:var(--fg2)">${w.advice}</div>` : ""}`;
      document.getElementById("whourly").innerHTML = (w.hourly || []).map(h => `<div><span class="t">${h.label}</span>${ic(h.icon)}<b>${r0(h.temp)}°</b><span class="p">${h.rain_pct >= 20 ? h.rain_pct + "%" : ""}</span></div>`).join("");
      const days = w.daily || [], allLo = Math.min(...days.map(d => d.lo)), allHi = Math.max(...days.map(d => d.hi)), span = (allHi - allLo) || 1;
      document.getElementById("wdaily").innerHTML = days.map((d, i) => {
        const l = (d.lo - allLo) / span * 100, r = (d.hi - allLo) / span * 100;
        const nowDot = i === 0 && c.temp != null ? `<b style="left:${Math.max(0, Math.min(100, (c.temp - allLo) / span * 100))}%"></b>` : "";
        return `<div class="wday"><span>${dayName(d.date)}</span>${ic(d.icon)}<span class="txt">${d.text}${d.rain_pct ? ` · ${d.rain_pct}%` : ""}</span><span class="lo">${r0(d.lo)}°</span><span class="wbar"><i style="left:${l}%;right:${100 - r}%"></i>${nowDot}</span><span class="hi">${r0(d.hi)}°</span></div>`; }).join("");
      buildRadar(document.getElementById("wradar"), w);
    },
  });
})();
