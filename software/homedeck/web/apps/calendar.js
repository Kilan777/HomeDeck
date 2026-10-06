/* Calendar app: private iCal URLs (Google Calendar "secret address" etc). Backend: modules/calendar.py */
(() => {
  const t = iso => HD.fmtTime(new Date(iso));
  const when = e => (e.all_day ? "All day" : `${t(e.start)} – ${t(e.end)}`);
  const dayLabel = iso => { const d = new Date(iso + "T12:00:00"); const tm = new Date(); tm.setDate(tm.getDate() + 1); return d.toDateString() === tm.toDateString() ? "Tomorrow" : d.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" }); };
  const evRow = e => `<div class="row"><span style="flex:1">${e.title}${e.location ? `<div class="hint">${e.location}</div>` : ""}</span><span class="v" style="font-size:15px">${when(e)}</span></div>`;

  HD.registerApp({
    id: "calendar", title: "Calendar", icon: "calendar", order: 25, guestHidden: true,
    idleSize: "2x1",
    idleWidget(el, s) {
      const c = s.calendar || {}, n = c.next_event;
      if (c.configured === false) { HD.setHtml(el, `<div class="iw-label">Calendar</div><div class="iw-mid" style="color:var(--fg2)">Not set up</div><div class="iw-sub">Add a calendar</div>`); return; }
      if (!n) { HD.setHtml(el, `<div class="iw-label">Calendar</div><div class="iw-mid" style="color:var(--fg2)">Clear</div><div class="iw-sub">${c.today && c.today.length ? "No more events today" : "Nothing scheduled"}</div>`); return; }
      const sameDay = n.start.slice(0, 10) === new Date().toISOString().slice(0, 10) || new Date(n.start).toDateString() === new Date().toDateString();
      HD.setHtml(el, `<div class="iw-label">Next up</div><div class="iw-mid">${n.title}</div><div class="iw-sub">${sameDay ? "" : dayLabel(n.start.slice(0, 10)) + " · "}${t(n.start)}${n.location ? " · " + n.location : ""}</div>`);
    },
    render(el) {
      el.innerHTML = `<div class="card"><h2>Today</h2><div class="rows" id="ctoday"></div></div><div class="card"><h2>Coming up</h2><div id="cupcoming"></div></div>
        <details class="card disclose"><summary><span>Calendar settings</span>${HD.icon("chevron-down", "")}</summary><div class="hint">Paste private iCal (.ics) URLs, one per line. In Google Calendar: Settings → your calendar → "Secret address in iCal format".</div>
        <textarea id="curls" rows="3" style="font-size:13px;font-family:ui-monospace,Menlo,monospace;margin:10px 0"></textarea>
        <div class="actions"><button class="btn primary" id="csave">Save</button><button class="btn" id="crefresh">Refresh</button></div><div class="hint" id="cerr" style="margin-top:8px"></div></details>`;
      el.querySelector("#curls").value = ((HD.config.calendar || {}).ics_urls || []).join("\n");
      el.querySelector("#csave").onclick = async () => { const urls = el.querySelector("#curls").value.split("\n").map(u => u.trim()).filter(Boolean); await HD.api("calendar", "set_urls", { urls }); HD.toast("Calendars saved, refreshing", "good"); };
      el.querySelector("#crefresh").onclick = () => HD.api("calendar", "refresh", {});
    },
    update(s) {
      const c = s.calendar || {}, today = document.getElementById("ctoday"); if (!today) return;
      today.innerHTML = (c.today || []).map(evRow).join("") || `<div class="hint">${c.configured === false ? "No calendar added yet." : "Nothing today."}</div>`;
      document.getElementById("cupcoming").innerHTML = (c.upcoming || []).map(d => `<div class="cday"><div class="sec" style="margin:12px 0 4px">${dayLabel(d.date)}</div><div class="rows">${d.events.map(evRow).join("")}</div></div>`).join("") || `<div class="hint">Nothing in the next 7 days.</div>`;
      document.getElementById("cerr").textContent = c.error ? `Problem: ${c.error}` : (c.refreshed_at ? `Updated ${HD.fmtTime(new Date(c.refreshed_at * 1000))}` : "");
    },
    onEvent(name, d) { if (name === "event_soon") HD.toast(`${d.title} in ${d.minutes} min${d.location ? " · " + d.location : ""}`, "info", 10000); },
  });
})();
