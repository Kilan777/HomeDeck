/* HomeDeck home style "Ambient": black screen, huge clock, one quiet status line, one attention pill at most.
   A tap on the empty area slides the standard tiles up; they hide again after 12 s without a touch.
   Registered through HD.registerHome; the shell owns #clock/#date, the corner controls and the now-playing player. */
(() => {
  const SHEET_MS = 12000;
  let built = false, sheetOpen = false, hideTimer = null, els = {};

  const deg = (h) => "°";
  const short = (s, n) => (s || "").length > n ? (s || "").slice(0, n - 1).trimEnd() + "…" : (s || "");

  function fmtClock(ts, h) {
    const d = new Date(ts * 1000), now = new Date();
    const time = h.fmtTime(d).replace(/\s*(AM|PM)$/i, m => "\u2009" + m.trim().toUpperCase());
    const sameDay = d.toDateString() === now.toDateString();
    const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
    if (sameDay) return time;
    if (d.toDateString() === tomorrow.toDateString()) return "tomorrow " + time;
    return d.toLocaleDateString([], { weekday: "short" }) + " " + time;
  }
  const mmss = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

  function statusLines(state, h) {
    const parts = [], parts2 = [];
    const w = state.weather || {}, c = w.current;
    if (c && c.temp != null) parts.push(`${Math.round(c.temp)}${deg()} ${(c.text || "").toLowerCase()}`.trim());
    const ms = (state.sensors && state.sensors.metrics) || [];
    const co2 = ms.find(m => m.key === "co2");
    if (co2 && co2.value != null) parts.push("air " + (co2.status && co2.status.text ? co2.status.text.split(",")[0].toLowerCase() : "ok"));
    const st = (state.bikes && state.bikes.stations && state.bikes.stations[0]);
    if (st && st.ebikes != null && !h.isHidden("bikes")) parts.push(`${st.ebikes} e-bike${st.ebikes === 1 ? "" : "s"}`);

    const ev = state.calendar && state.calendar.next_event;
    if (ev && ev.title && !h.isHidden("calendar")) {
      const at = typeof ev.start === "number" ? ev.start : (ev.start ? Date.parse(ev.start) / 1000 : null);
      parts2.push(short(ev.title, 22) + (at ? " " + fmtClock(at, h) : ""));
    }
    const al = state.alarms && state.alarms.next_alarm;
    if (al && al.at && !h.isHidden("alarms")) parts2.push("alarm " + fmtClock(al.at, h));
    const tm = ((state.timers && state.timers.timers) || [])[0];
    if (tm) parts2.push("timer " + mmss(tm.remaining));
    return [parts.join(" · "), parts2.join(" · ")];
  }

  function pill(state) {
    const ms = (state.sensors && state.sensors.metrics) || [];
    const co2 = ms.find(m => m.key === "co2");
    if (co2 && co2.status && (co2.status.level === "serious" || co2.status.level === "critical"))
      return { level: co2.status.level, text: `${co2.status.level === "critical" ? "Bad air" : "Ventilate"} · ${Math.round(co2.value)} ppm` };
    const tm = ((state.timers && state.timers.timers) || []).find(t => t.remaining <= 60);
    if (tm) return { level: "warning", text: `Timer ${mmss(tm.remaining)}${tm.label ? " · " + tm.label : ""}` };
    const rem = state.reminders && state.reminders.next;
    if (rem && rem.at && rem.at - Date.now() / 1000 < 300) return { level: "warning", text: "Reminder · " + short(rem.text, 28) };
    if (state.voice && state.voice.mic_enabled === false) return { level: "unknown", text: "Mic off" };
    return null;
  }

  function build(idleEl, h) {
    const w = document.getElementById("idlewidgets");
    w.innerHTML = `<div class="amb"><div class="amb-line" id="amb-l1"></div><div class="amb-line" id="amb-l2"></div><div class="amb-pill" id="amb-pill"></div></div>`;
    const sheet = document.createElement("div"); sheet.className = "amb-sheet"; sheet.id = "amb-sheet";
    sheet.innerHTML = `<div class="amb-sheet-head"><span>At a glance</span><button class="amb-apps" id="amb-apps">${h.icon("home", "")}Apps</button></div><div class="amb-grid" id="amb-grid"></div>`;
    idleEl.appendChild(sheet);
    els = { l1: w.querySelector("#amb-l1"), l2: w.querySelector("#amb-l2"), pill: w.querySelector("#amb-pill"), sheet, grid: sheet.querySelector("#amb-grid") };
    sheet.querySelector("#amb-apps").addEventListener("click", e => { e.stopPropagation(); closeSheet(); h.showApps(); });
    sheet.addEventListener("click", e => { e.stopPropagation(); armHide(); });
    sheet.addEventListener("pointerdown", armHide, { passive: true });
    // Capture-phase click on #idle: the shell's own (bubbling) click opens the app grid; we turn a tap into reveal/hide instead.
    idleEl.addEventListener("click", e => {
      if (e.target.closest("#idlecontrols, #nowplaying, .amb-sheet")) return;
      e.stopPropagation();
      sheetOpen ? closeSheet() : openSheet();
    }, true);
    built = true;
  }

  function armHide() { if (hideTimer) clearTimeout(hideTimer); hideTimer = setTimeout(closeSheet, SHEET_MS); }
  function openSheet() { sheetOpen = true; els.sheet.classList.add("open"); armHide(); }
  function closeSheet() { sheetOpen = false; if (els.sheet) els.sheet.classList.remove("open"); if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; } }

  function renderTiles(state, apps, h) {
    const grid = els.grid; let n = 0;
    for (const a of Object.values(apps).sort((x, y) => (x.order || 99) - (y.order || 99))) {
      if (!a.idleWidget || h.isHidden(a.id) || (h.isGuest() && a.guestHidden) || (HD.KIOSK && a.kioskHidden)) continue;
      let el = grid.querySelector(`#amb-iw-${a.id}`);
      if (!el) { el = document.createElement("div"); el.id = `amb-iw-${a.id}`; el.className = "iw"; el.onclick = e => { e.stopPropagation(); closeSheet(); h.openApp(a.id); }; grid.appendChild(el); }
      try { a.idleWidget(el, state); } catch (err) { console.error(a.id, err); }
      if (el.innerHTML !== "") n++;
    }
    return n;
  }

  HD.registerHome("ambient", {
    render(idleEl, state, apps, h) {
      if (!built || !document.getElementById("amb-l1")) build(idleEl, h);
      const [l1, l2] = statusLines(state, h);
      h.setText(els.l1, l1); h.setText(els.l2, l2);
      const p = pill(state);
      h.setHtml(els.pill, p ? `<span class="dot ${p.level}"></span>${p.text}` : "");
      els.pill.className = "amb-pill" + (p ? " " + p.level : "");
      document.documentElement.classList.toggle("amb-night", !!(state.display && state.display.night));
      if (sheetOpen) renderTiles(state, apps, h);
    }
  });
})();
