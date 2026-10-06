/* Alarms app: list, add/edit, ringing overlay, morning-routine popup, idle widget with the next alarm. */
(() => {
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  let root = null, editing = null, ringPopup = null;

  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") el.className = v; else if (k.startsWith("on")) el[k] = v; else if (k === "html") el.innerHTML = v; else el.setAttribute(k, v);
    }
    for (const k of kids) el.append(k);
    return el;
  };
  const fmtHM = t => { const [hh, mm] = t.split(":").map(Number); const d = new Date(); d.setHours(hh, mm, 0, 0); return HD.fmtTime(d); };
  const dayStr = days => !days || !days.length ? "Once" : days.length === 7 ? "Every day" : days.length === 5 && days.every(d => d < 5) ? "Weekdays" : days.map(d => DAYS[d]).join(" ");

  function list(el, st) {
    const alarms = (st.alarms && st.alarms.alarms) || [];
    const box = el.querySelector("#al-list"); box.innerHTML = "";
    if (!alarms.length) box.append(h("p", { class: "hint", style: "padding:16px" }, "No alarms yet. Tap + to add one."));
    for (const a of alarms) {
      const row = h("div", { class: "row al-row" + (a.enabled ? "" : " off"), style: "padding:10px 16px" },
        h("div", { class: "al-main", style: "flex:1;cursor:pointer", onclick: () => edit(el, a) },
          h("div", { class: "al-time", style: "font-size:44px;font-weight:200;letter-spacing:-.02em;line-height:1.05;font-variant-numeric:tabular-nums" + (a.enabled ? "" : ";color:var(--muted)") }, fmtHM(a.time)),
          h("div", { class: "al-sub hint", style: "font-size:15px" }, `${a.label || "Alarm"} · ${dayStr(a.days)}${a.sunrise_min ? " · sunrise " + a.sunrise_min + " min" : ""}${a.light_retry && a.light_retry.enabled ? " · light check" : ""}`)),
        h("label", { class: "switch" }, Object.assign(h("input", { type: "checkbox" }), { checked: !!a.enabled, onchange: async e => { await HD.api("alarms", "toggle", { id: a.id, enabled: e.target.checked }); } }), h("span")));
      box.append(row);
    }
  }

  function edit(el, a) {
    editing = a ? JSON.parse(JSON.stringify(a)) : { time: "07:00", days: [0, 1, 2, 3, 4], label: "Wake up", sound: "default", sunrise_min: 20,
      light_retry: { enabled: true, lux_threshold: 30, retry_after_min: 3, max_retries: 5 }, routine: true, enabled: true };
    const f = el.querySelector("#al-form"); f.innerHTML = ""; f.classList.remove("hidden"); el.querySelector("#al-list").classList.add("hidden"); el.querySelector("#al-add").classList.add("hidden");
    const lr = editing.light_retry || {};
    const days = h("div", { class: "chips" }, ...DAYS.map((d, i) => h("button", { class: "chip" + (editing.days.includes(i) ? " on" : ""), onclick: e => { e.preventDefault(); const s = new Set(editing.days); s.has(i) ? s.delete(i) : s.add(i); editing.days = [...s].sort(); e.target.classList.toggle("on"); } }, d)));
    const timeIn = h("input", { type: "time", value: editing.time, onchange: e => editing.time = e.target.value });
    const labelIn = h("input", { type: "text", value: editing.label, placeholder: "Label", onchange: e => editing.label = e.target.value });
    const sunIn = h("input", { type: "number", min: 0, max: 60, value: editing.sunrise_min, onchange: e => editing.sunrise_min = +e.target.value });
    const soundSel = h("select", { onchange: e => editing.sound = e.target.value === "spotify" ? (editing.sound.startsWith("spotify:") ? editing.sound : "spotify:") : e.target.value },
      h("option", { value: "default" }, "Alarm tone"), h("option", { value: "spotify" }, "Spotify playlist / track"));
    soundSel.value = editing.sound.startsWith("spotify:") ? "spotify" : "default";
    const spotIn = h("input", { type: "text", placeholder: "spotify:playlist:… (paste a Spotify URI)", value: editing.sound.startsWith("spotify:") ? editing.sound : "", oninput: e => editing.sound = e.target.value });
    const lrOn = Object.assign(h("input", { type: "checkbox" }), { checked: lr.enabled !== false, onchange: e => (editing.light_retry = editing.light_retry || {}).enabled = e.target.checked });
    const lrMin = h("input", { type: "number", min: 1, max: 30, value: lr.retry_after_min || 3, onchange: e => editing.light_retry.retry_after_min = +e.target.value });
    const lrMax = h("input", { type: "number", min: 1, max: 20, value: lr.max_retries || 5, onchange: e => editing.light_retry.max_retries = +e.target.value });
    const lrLux = h("input", { type: "number", min: 1, max: 500, value: lr.lux_threshold || 30, onchange: e => editing.light_retry.lux_threshold = +e.target.value });
    const routine = Object.assign(h("input", { type: "checkbox" }), { checked: editing.routine !== false, onchange: e => editing.routine = e.target.checked });
    timeIn.style.cssText = "font-size:44px;font-weight:200;background:transparent;padding:0;text-align:center;width:100%;letter-spacing:-.02em";
    sunIn.style.width = lrMin.style.width = lrMax.style.width = lrLux.style.width = "84px"; sunIn.style.textAlign = lrMin.style.textAlign = lrMax.style.textAlign = lrLux.style.textAlign = "right";
    labelIn.style.cssText = "text-align:right;background:transparent;padding:0;width:60%";
    soundSel.style.cssText = "width:auto;background:transparent;padding:0;text-align:right;color:var(--fg2)";
    const rowOf = (label, ctl) => h("div", { class: "row" }, h("span", { class: "k" }, label), ctl);
    f.append(
      h("div", { style: "padding:8px 0 4px" }, timeIn),
      h("div", { class: "rows" },
        rowOf("Label", labelIn),
        h("div", { class: "row", style: "flex-direction:column;align-items:stretch;gap:8px" }, h("span", { class: "k" }, "Repeat"), days),
        rowOf("Sound", soundSel),
        (editing.sound.startsWith("spotify:") ? h("div", { class: "row" }, spotIn) : h("div", { class: "row hidden", id: "al-spot" }, spotIn)),
        rowOf("Sunrise on the light bar, minutes before", sunIn),
        rowOf("Keep ringing until the light is on", lrOn),
        rowOf("Retry every, minutes", lrMin),
        rowOf("Maximum retries", lrMax),
        rowOf("Light threshold, lux", lrLux),
        rowOf("Morning briefing after dismiss", routine)),
      h("div", { class: "actions", style: "margin-top:12px" },
        h("button", { class: "primary", style: "flex:1", onclick: async () => { await HD.api("alarms", "save", { alarm: editing }); close(el); HD.toast("Alarm saved", "good"); } }, "Save"),
        h("button", { style: "flex:1", onclick: () => close(el) }, "Cancel"),
        editing.id ? h("button", { class: "danger", onclick: async () => { await HD.api("alarms", "delete", { id: editing.id }); close(el); } }, "Delete") : ""),
      h("div", { class: "actions minor", style: "margin-top:8px" },
        h("button", { onclick: () => HD.api("alarms", "test") }, "Test sound"),
        h("button", { onclick: () => HD.api("alarms", "sunrise_test", { progress: 0.6 }) }, "Test sunrise")));
    soundSel.addEventListener("change", () => { const r = f.querySelector("#al-spot"); if (r) r.classList.toggle("hidden", soundSel.value !== "spotify"); });
  }
  function close(el) { editing = null; el.querySelector("#al-form").classList.add("hidden"); el.querySelector("#al-list").classList.remove("hidden"); el.querySelector("#al-add").classList.remove("hidden"); }

  function showRinging(data) {
    if (window.HDRing) { if (!HDRing.visible()) HDRing.show({ kind: "alarm", label: data.label || "Alarm" }); return; }
    if (ringPopup) return;
    ringPopup = HD.popup({ title: data.label || "Alarm", level: "warning",
      body: `<div class="ring-time">${HD.fmtTime()}</div>${data.retry ? "<p>The light is still off. Up and at it.</p>" : ""}`,
      actions: [{ label: "Snooze", onclick: () => { HD.api("alarms", "snooze", { min: 9 }); ringPopup = null; } },
                { label: "Stop", onclick: () => { HD.api("alarms", "dismiss"); ringPopup = null; } }] });
  }

  HD.registerApp({
    id: "alarms", title: "Alarms", icon: "alarm", order: 15, guestHidden: true,
    render(el) {
      root = el;
      el.innerHTML = `<div id="al-list" class="group"></div><div id="al-form" class="card hidden"></div><div class="fab-row"><button id="al-add" class="fab" aria-label="Add alarm">${HD.icon("plus", "")}</button></div><div class="hint" id="al-next" style="text-align:center;color:var(--muted)"></div>`;
      el.querySelector("#al-add").onclick = () => edit(el, null);
      if (new URLSearchParams(location.search).get("edit") === "new") edit(el, null);
    },
    update(st) {
      if (!root || editing) return;
      list(root, st);
      const n = st.alarms && st.alarms.next_alarm;
      root.querySelector("#al-next").textContent = n ? `Next: ${n.label} at ${n.at_str}` : "";
      if (st.alarms && st.alarms.ringing && !ringPopup && !(window.HDRing && HDRing.visible())) showRinging({ label: "Alarm" });
      if (st.alarms && !st.alarms.ringing && ringPopup) { ringPopup.remove(); ringPopup = null; }
    },
    idleSize: "1x1",
    idleWidget(el, st) {
      const n = st.alarms && st.alarms.next_alarm;
      const s = st.alarms || {};
      const timeOnly = str => str.replace(/^\w+ /, "");
      HD.setHtml(el, s.ringing ? `<div class="iw-label">Alarm</div><div class="iw-big">Ringing</div>` :
        s.snoozed_until ? `<div class="iw-label">Snoozed</div><div class="iw-big">${HD.fmtTime(new Date(s.snoozed_until * 1000))}</div>` :
        n ? `<div class="iw-label">Alarm</div><div class="iw-big"><span class="iw-icon">${HD.icon("alarm")}</span>${timeOnly(n.at_str)}</div><div class="iw-sub">${isTomorrow(n.at) ? "Tomorrow" : n.at_str.split(" ")[0]}${n.label ? " · " + n.label : ""}</div>` :
        `<div class="iw-label">Alarm</div><div class="iw-mid" style="color:var(--fg2)">None</div><div class="iw-sub">Add one</div>`);
    },
    onEvent(name, data) {
      if (name === "alarm_ringing") showRinging(data || {});
      if (name === "alarm_stopped") { if (ringPopup) { ringPopup.remove(); ringPopup = null; } if (window.HDRing) HDRing.hide(); }
      if (name === "routine" && data && data.text) HD.popup({ title: "Good morning", body: `<p>${data.text}</p>`, actions: [{ label: "Thanks" }] });
    }
  });
  function isTomorrow(ts) { const d = new Date(ts * 1000), t = new Date(); t.setDate(t.getDate() + 1); return d.toDateString() === t.toDateString(); }
})();
