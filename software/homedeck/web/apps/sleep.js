/* Sleep sounds: rain, ocean, noise colours and a fan hum with a sleep timer. Backend: modules/sleep.py */
(() => {
  const CSS = `
  .sl-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
  .appbody .sl-tile, .appbody button.sl-tile { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 92px; border: 0; border-radius: 16px;
    background: rgba(255,255,255,.07); box-shadow: inset 0 0 0 1px var(--hair); color: var(--fg) !important; font: inherit; font-size: 14px; font-weight: 500; padding: 12px 8px; cursor: pointer; transition: background .15s, transform .12s; }
  .appbody .sl-tile svg { width: 28px; height: 28px; stroke-width: 1.6; color: var(--fg2); }
  .appbody .sl-tile.on, .appbody button.sl-tile.on { background: var(--app-accent, var(--accent)) !important; color: #fff !important; box-shadow: none; }
  .appbody .sl-tile.on svg { color: #fff; }
  .appbody .sl-tile:active { transform: scale(.96); }
  .sl-status { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 44px; }
  .sl-status .sl-now { font-size: 20px; font-weight: 600; letter-spacing: -.015em; }
  .sl-status .sl-left { font-size: 15px; color: var(--fg2); font-variant-numeric: tabular-nums; }
  .sl-bar { height: 4px; border-radius: 2px; background: rgba(255,255,255,.12); overflow: hidden; margin: 10px 0 4px; }
  .sl-bar i { display: block; height: 100%; background: var(--app-accent, var(--accent)); width: 0; transition: width 1s linear; }
  .sl-vol { display: flex; align-items: center; gap: 10px; color: var(--fg2); margin-top: 6px; }
  .sl-vol svg { width: 20px; height: 20px; flex: none; }
  .sl-vol input { flex: 1; }
  .sl-chips .chip.on { background: var(--app-accent, var(--accent)); color: #fff; }
  .sl-chips .chip[disabled] { opacity: .4; }`;
  const ICON = { rain: "rain", ocean: "drop", white: "waveform", pink: "waveform", brown: "waveform", hum: "wind" };
  const TIMERS = [15, 30, 45, 60, 90];
  const mm = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return h ? `${h} h ${m} min` : `${m} min`; };
  let root = null, chosenMin = 45, chosenAlarm = false, volDrag = false, tick = null;

  function draw() {
    if (!root) return;
    const st = (HD.state && HD.state.sleep) || {};
    const sounds = st.sounds || [];
    const vol = (HD.state.audio && HD.state.audio.volume_pct);
    const hasAlarm = !!st.next_alarm_at;
    root.innerHTML = `<style>${CSS}</style>
      <div class="card">
        <div class="sl-status"><div><div class="sl-now" id="sl-now">${st.active ? st.label : "Nothing playing"}</div><div class="sl-left" id="sl-left">${st.active ? (st.remaining_s != null ? mm(st.remaining_s) + " left" + (st.fading ? " · fading out" : "") : "") : "Pick a sound below"}</div></div>
          ${st.active ? `<button class="btn" id="sl-stop">Stop</button>` : ""}</div>
        ${st.active ? `<div class="sl-bar"><i id="sl-bari" style="width:${st.started_at && st.ends_at ? (100 * (Date.now() / 1000 - st.started_at) / Math.max(1, st.ends_at - st.started_at)).toFixed(1) : 0}%"></i></div>` : ""}
        <div class="sl-vol">${HD.icon("volume-low", "")}<input type="range" min="0" max="100" value="${vol == null ? 40 : vol}" id="sl-vol" aria-label="Volume">${HD.icon("volume", "")}</div>
      </div>
      <div class="card"><h3>Sound</h3><div class="sl-grid">${sounds.map(s => `<button class="sl-tile ${st.active && st.sound === s.id ? "on" : ""}" data-s="${s.id}">${HD.icon(ICON[s.id] || "note", "")}<span>${s.label}</span></button>`).join("")}</div></div>
      <div class="card"><h3>Sleep timer</h3>
        <div class="chips sl-chips">${TIMERS.map(m => `<button class="chip ${!chosenAlarm && chosenMin === m ? "on" : ""}" data-m="${m}">${m} min</button>`).join("")}<button class="chip ${chosenAlarm ? "on" : ""}" data-m="alarm" ${hasAlarm ? "" : "disabled"}>Until alarm</button></div>
        <div class="hint" style="margin-top:8px">${hasAlarm ? `Next alarm ${HD.fmtTime(new Date(st.next_alarm_at * 1000))}. ` : "No alarm set, so \"Until alarm\" is off. "}The sound fades out over the last minute and the volume goes back to where it was.</div>
      </div>`;
    root.querySelectorAll(".sl-tile").forEach(b => b.onclick = async () => {
      root.querySelectorAll(".sl-tile").forEach(x => x.classList.toggle("on", x === b));
      const r = await HD.api("sleep", "start", chosenAlarm ? { sound: b.dataset.s, until_alarm: true } : { sound: b.dataset.s, minutes: chosenMin });
      if (!r || !r.ok) HD.toast((r && r.error) || "Could not start", "warning");
    });
    root.querySelectorAll(".sl-chips .chip").forEach(c => c.onclick = async () => {
      if (c.disabled) return;
      chosenAlarm = c.dataset.m === "alarm"; if (!chosenAlarm) chosenMin = +c.dataset.m;
      root.querySelectorAll(".sl-chips .chip").forEach(x => x.classList.toggle("on", x === c));
      if (st.active) { const r = await HD.api("sleep", "set_timer", chosenAlarm ? { until_alarm: true } : { minutes: chosenMin }); if (r && r.ok) HD.toast(chosenAlarm ? "Until the alarm" : `${chosenMin} minutes`, "good", 1500); }
    });
    const stop = root.querySelector("#sl-stop"); if (stop) stop.onclick = () => HD.api("sleep", "stop", {});
    const v = root.querySelector("#sl-vol"); let t;
    v.oninput = () => { volDrag = true; clearTimeout(t); t = setTimeout(() => HD.api("audio", "set_volume", { pct: +v.value }).then(() => { volDrag = false; }), 120); };
    v.onchange = () => { volDrag = false; };
  }
  function patch(st) {
    const now = root.querySelector("#sl-now"), left = root.querySelector("#sl-left"), bar = root.querySelector("#sl-bari"), v = root.querySelector("#sl-vol");
    if (now) now.textContent = st.active ? st.label : "Nothing playing";
    if (left) left.textContent = st.active ? (st.remaining_s != null ? mm(st.remaining_s) + " left" + (st.fading ? " · fading out" : "") : "") : "Pick a sound below";
    if (bar && st.started_at && st.ends_at) bar.style.width = (100 * (Date.now() / 1000 - st.started_at) / Math.max(1, st.ends_at - st.started_at)).toFixed(1) + "%";
    if (v && !volDrag && HD.state.audio && HD.state.audio.volume_pct != null && document.activeElement !== v) v.value = HD.state.audio.volume_pct;
  }
  HD.registerApp({
    id: "sleep", title: "Sleep", icon: "moon-stars", color: "#5e5ce6", order: 17, idleAppend: true,
    render(el) { root = el; this._sig = null; draw(); clearInterval(tick); tick = setInterval(() => { if (root && root.isConnected) patch((HD.state && HD.state.sleep) || {}); else clearInterval(tick); }, 1000); },
    update(s) {
      if (!root || !root.isConnected) return;
      const st = s.sleep || {};
      const sig = JSON.stringify([st.active, st.sound, !!st.next_alarm_at, (st.sounds || []).length]);
      if (sig !== this._sig) { this._sig = sig; draw(); } else patch(st);
    },
    idleSize: "2x1",
    idleWidget(el, s) {
      const st = s.sleep || {};
      if (!st.active) { HD.setHtml(el, ""); return; }
      HD.setHtml(el, `<div class="iw-label">Sleep</div><div class="iw-mid">${st.label}</div><div class="iw-sub">${st.remaining_s != null ? mm(st.remaining_s) + " left" : ""}${st.fading ? " · fading out" : ""}</div>`);
      return "2x1";
    },
    onEvent(name, d) { if (name === "sleep_stopped" && d && d.reason === "timer") HD.toast("Sleep sounds finished", "good", 4000); },
  });
})();
