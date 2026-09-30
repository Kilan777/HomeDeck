/* Home style "Clock-first": big clock, one row of three glance tiles, the remaining tiles one swipe to the left.
   Registered with the shell via HD.registerHome; the shell owns #clock, #date, the bottom controls and now-playing. */
(() => {
  const PAGE2 = ["calendar", "alarms", "timers", "leds", "reminders", "fan", "lists", "voice"];
  let root = null, track = null, dots = null, p1 = null, p2 = null, page = 0, scratch = null;
  const fmt = (v, d = 0) => (v == null ? "–" : Number(v).toFixed(d));

  function build(idle, apps, h) {
    root = document.createElement("div"); root.className = "cf";
    root.innerHTML = `<div class="cf-track"><div class="cf-page cf-p1"></div><div class="cf-page cf-p2"></div></div><div class="cf-dots"><i class="on"></i><i></i></div>`;
    track = root.querySelector(".cf-track"); dots = root.querySelector(".cf-dots"); p1 = root.querySelector(".cf-p1"); p2 = root.querySelector(".cf-p2");
    scratch = document.createElement("div");
    for (const id of ["weather", "sensors", "bikes"]) {
      const t = document.createElement("div"); t.className = "cf-tile"; t.dataset.id = id;
      t.innerHTML = `<div class="cf-lbl"></div><div class="cf-val"></div><div class="cf-sub"></div>`;
      t.addEventListener("click", e => { e.stopPropagation(); if (!moved) h.openApp(id); });
      p1.appendChild(t);
    }
    for (const id of PAGE2) {
      if (!apps[id] || !apps[id].idleWidget) continue;
      const el = document.createElement("div"); el.className = "iw"; el.dataset.id = id;
      el.addEventListener("click", e => { e.stopPropagation(); if (!moved) h.openApp(id); });
      p2.appendChild(el);
    }
    const empty = document.createElement("div"); empty.className = "cf-empty"; empty.textContent = "Nothing else right now"; empty.hidden = true; p2.appendChild(empty);
    swipe(root); try { HD.__cfGo = swipe.go; } catch (e) {}
    root.addEventListener("click", e => { if (moved) { e.stopPropagation(); moved = false; } });
    return root;
  }

  // Horizontal swipe with pointer events (touch reaches the page as pointer drags on the panel).
  let moved = false;
  function swipe(el) {
    let x0 = null, y0 = 0, dx = 0, horiz = null;
    const go = n => { page = Math.max(0, Math.min(1, n)); track.style.transform = `translateX(${-page * 50}%)`;
      dots.querySelectorAll("i").forEach((d, i) => d.classList.toggle("on", i === page)); };
    swipe.go = go;   // exposed for testing (HD.__cfGo)
    el.addEventListener("pointerdown", e => { x0 = e.clientX; y0 = e.clientY; dx = 0; horiz = null; moved = false; }, { passive: true });
    el.addEventListener("pointermove", e => {
      if (x0 == null) return;
      dx = e.clientX - x0; const dy = e.clientY - y0;
      if (horiz === null && (Math.abs(dx) > 10 || Math.abs(dy) > 10)) horiz = Math.abs(dx) > Math.abs(dy);
      if (!horiz) return;
      moved = true; el.classList.add("dragging");
      const w = el.clientWidth || 1; const pct = Math.max(-1, Math.min(1, dx / w));
      track.style.transform = `translateX(calc(${-page * 50}% + ${pct * 50}%))`;
    }, { passive: true });
    const end = () => { if (x0 == null) return; el.classList.remove("dragging");
      if (horiz && Math.abs(dx) > 30) go(page + (dx < 0 ? 1 : -1)); else go(page);
      x0 = null; setTimeout(() => { moved = false; }, 50); };
    el.addEventListener("pointerup", end, { passive: true }); el.addEventListener("pointercancel", end, { passive: true });
    document.addEventListener("pointerup", end, { passive: true });
  }

  // Pull the weather icon SVG the weather app would draw, so both styles agree on iconography.
  function weatherIcon(apps, state) {
    try { const sc = document.createElement("div"); apps.weather.idleWidget(sc, state); const ic = sc.querySelector(".iw-icon"); return ic ? ic.innerHTML : ""; } catch (e) { return ""; }
  }

  function update(state, apps, h) {
    const tiles = {}; p1.querySelectorAll(".cf-tile").forEach(t => { tiles[t.dataset.id] = t; });
    // weather
    { const t = tiles.weather; const w = state.weather || {}, c = w.current; t.hidden = h.isHidden("weather");
      h.setText(t.querySelector(".cf-lbl"), "Weather");
      if (c) { h.setHtml(t.querySelector(".cf-val"), `${weatherIcon(apps, state)}<span>${fmt(c.temp)}°</span>`);
        const d0 = (w.daily || [])[0] || {}; h.setText(t.querySelector(".cf-sub"), `${c.text || ""}${d0.hi != null ? ` · ${fmt(d0.hi)}° / ${fmt(d0.lo)}°` : ""}`); }
      else { h.setHtml(t.querySelector(".cf-val"), "–"); h.setText(t.querySelector(".cf-sub"), w.error ? "Offline" : "Loading…"); } }
    // air
    { const t = tiles.sensors; const ms = (state.sensors && state.sensors.metrics) || []; const co2 = ms.find(m => m.key === "co2"); t.hidden = h.isHidden("sensors");
      h.setText(t.querySelector(".cf-lbl"), "Air");
      if (co2 && co2.value != null) { h.setHtml(t.querySelector(".cf-val"), `<span>${fmt(co2.value)}</span><span class="cf-unit">ppm</span>`);
        h.setHtml(t.querySelector(".cf-sub"), `<span class="dot ${co2.status.level}"></span><span>${co2.status.text}</span>`); }
      else { h.setHtml(t.querySelector(".cf-val"), "–"); h.setText(t.querySelector(".cf-sub"), "Waiting for sensors"); } }
    // bikes
    { const t = tiles.bikes; const b = state.bikes || {}, st = (b.stations || [])[0]; t.hidden = h.isHidden("bikes");
      h.setText(t.querySelector(".cf-lbl"), "E-bikes");
      if (st) { const parts = st.name.split(/\s+at\s+/i); const short = (parts[1] || parts[0]).replace(/\b(St|Street|Ave|Avenue|Blvd|Rd)\b\.?\s*$/i, "").trim();
        h.setHtml(t.querySelector(".cf-val"), `${h.icon("bolt")}<span>${st.ebikes ?? "–"}</span>`); h.setText(t.querySelector(".cf-sub"), b.low ? "Running low" : short); }
      else { h.setHtml(t.querySelector(".cf-val"), "–"); h.setText(t.querySelector(".cf-sub"), b.error ? "Offline" : "Loading…"); } }
    // page 2: reuse each app's own idle widget
    let shown = 0;
    p2.querySelectorAll(".iw").forEach(el => {
      const id = el.dataset.id, a = apps[id];
      if (!a || h.isHidden(id) || (h.isGuest() && a.guestHidden)) { el.hidden = true; return; }
      try { a.idleWidget(el, state); } catch (e) { el.innerHTML = ""; }
      el.hidden = !el.innerHTML.trim(); if (!el.hidden) shown++;
    });
    p2.querySelector(".cf-empty").hidden = shown > 0;
  }

  HD.registerHome("clockfirst", {
    render(idle, state, apps, h) {
      const host = idle.querySelector("#idlewidgets"); if (!host) return;
      if (!root || !host.contains(root)) { host.innerHTML = ""; host.appendChild(build(idle, apps, h)); }
      update(state, apps, h);
    }
  });
})();
