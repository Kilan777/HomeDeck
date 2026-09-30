/* Timers app: countdowns with quick presets. Backend: modules/timers.py */
(() => {
  const mmss = s => { const m = Math.floor(s / 60), r = s % 60; return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`; };
  const add = async (seconds, label) => { const r = await HD.api("timers", "add", { seconds, label }); if (r.ok) HD.toast(`Timer set: ${label || mmss(seconds)}`, "good"); else HD.toast(r.error || "Could not add timer", "serious"); };

  HD.registerApp({
    id: "timers", title: "Timers", icon: "timer", order: 30,
    idleSize: "1x1",
    idleWidget(el, s) {
      const t = ((s.timers || {}).timers || [])[0];
      if (!t) { el.classList.add("iw-quiet"); HD.setHtml(el, `<div class="iw-label">Timer</div><div class="iw-mid" style="color:var(--fg2)">None</div><div class="iw-sub">Set one</div>`); return "1x1"; }
      el.classList.remove("iw-quiet");
      HD.setHtml(el, `<div class="iw-label">Timer</div><div class="iw-big" style="font-variant-numeric:tabular-nums">${mmss(t.remaining)}</div><div class="iw-sub">${t.label || "Ends " + HD.fmtTime(new Date(t.ends_at * 1000))}</div>`);
      return "2x1";
    },
    render(el) {
      el.innerHTML = `<div class="card"><h2>Quick start</h2><div class="grid2" style="grid-template-columns:repeat(4,1fr);gap:8px">${[1, 5, 10, 30].map(m => `<button class="btn secondary" data-m="${m}" style="min-height:56px;font-size:17px;display:flex;flex-direction:column;gap:0;line-height:1.1"><b style="font-size:22px;font-weight:600">${m}</b><span style="font-size:12px;color:var(--fg2)">min</span></button>`).join("")}</div>
        <div class="inline" style="margin-top:12px;flex-wrap:wrap">
          <input id="tmin" type="number" min="1" inputmode="numeric" placeholder="Minutes" style="flex:0 0 110px">
          <input id="tlabel" type="text" placeholder="Label (pasta, laundry…)" style="flex:1;min-width:140px">
          <button class="btn primary" id="tadd">Start</button></div></div>
        <div class="card"><h2>Running</h2><div class="rows" id="trun"></div></div>`;
      el.querySelectorAll("[data-m]").forEach(b => b.onclick = () => add(+b.dataset.m * 60, ""));
      el.querySelector("#tadd").onclick = () => { const m = +el.querySelector("#tmin").value; if (m > 0) { add(Math.round(m * 60), el.querySelector("#tlabel").value.trim()); el.querySelector("#tmin").value = ""; el.querySelector("#tlabel").value = ""; } };
    },
    update(s) {
      const box = document.getElementById("trun"); if (!box) return;
      const ts = (s.timers || {}).timers || [];
      box.innerHTML = ts.map(t => `<div class="row"><span style="flex:1">${t.label || "Timer"}<div class="hint">Ends ${HD.fmtTime(new Date(t.ends_at * 1000))}</div></span>
        <span style="font-size:26px;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-.02em">${mmss(t.remaining)}</span><button class="btn small danger" data-id="${t.id}">Cancel</button></div>`).join("") || `<div class="hint">No timers running.</div>`;
      box.querySelectorAll("[data-id]").forEach(b => b.onclick = () => HD.api("timers", "cancel", { id: +b.dataset.id }));
    },
    onEvent(name, d) {
      if (name === "ringing" && d && d.kind === "timer") HDRing.show({ kind: "timer", label: d.label || "Timer" });
      if (name === "ringing_stopped") HDRing.hide();
    },
  });

  // Full-screen ringing sheet used by timers and alarms: big label, elapsed time, Stop (and Snooze for alarms).
  const css = document.createElement("style"); css.textContent = `
    #ringsheet { position: fixed; inset: 0; z-index: 70; display: flex; align-items: flex-end; justify-content: center; background: rgba(0,0,0,.45); animation: fadein .2s var(--ease); }
    #ringsheet .rs { width: 100%; max-width: 620px; margin: 0 16px 18px; padding: 22px 24px 20px; border-radius: 24px; background: rgba(28,30,38,.97); box-shadow: 0 24px 70px rgba(0,0,0,.55), inset 0 0 0 1px rgba(255,255,255,.14); text-align: center; }
    #ringsheet .rs-kind { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
    #ringsheet .rs-label { font-size: 34px; font-weight: 700; letter-spacing: -.02em; margin: 6px 0 2px; }
    #ringsheet .rs-time { font-size: 15px; color: var(--fg2); font-variant-numeric: tabular-nums; }
    #ringsheet .rs-btns { display: flex; gap: 12px; margin-top: 18px; }
    #ringsheet .rs-btns button { flex: 1; min-height: 60px; border: 0; border-radius: 16px; font: inherit; font-size: 20px; font-weight: 600; color: #fff; background: rgba(255,255,255,.12); }
    #ringsheet .rs-btns button.stop { background: var(--accent); flex: 2; }
    @media (orientation: landscape) and (max-height: 600px) { #ringsheet { align-items: center; } #ringsheet .rs { margin: 0 16px; } #ringsheet .rs-label { font-size: 30px; } }`;
  document.head.appendChild(css);
  let sheet = null, tick = null, since = 0;
  window.HDRing = {
    show(o) {
      HDRing.hide(); since = Date.now();
      sheet = document.createElement("div"); sheet.id = "ringsheet";
      const snooze = o.kind === "alarm" ? `<button class="snooze">Snooze</button>` : "";
      sheet.innerHTML = `<div class="rs"><div class="rs-kind">${o.kind === "alarm" ? "Alarm" : "Timer"}</div><div class="rs-label">${o.label || (o.kind === "alarm" ? "Wake up" : "Time's up")}</div><div class="rs-time">ringing for 0:00</div><div class="rs-btns">${snooze}<button class="stop">Stop</button></div></div>`;
      const stop = async () => { HDRing.hide(); await HD.api("ringer", "stop", {}); if (o.kind === "alarm") HD.api("alarms", "dismiss", {}); else HD.api("timers", "stop", {}); };
      sheet.querySelector(".stop").onclick = stop;
      const sn = sheet.querySelector(".snooze"); if (sn) sn.onclick = async () => { HDRing.hide(); await HD.api("alarms", "snooze", { min: 9 }); };
      sheet.addEventListener("click", e => { if (e.target === sheet) stop(); });
      document.body.appendChild(sheet);
      const t = sheet.querySelector(".rs-time");
      tick = setInterval(() => { const s = Math.round((Date.now() - since) / 1000); t.textContent = `ringing for ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }, 1000);
    },
    hide() { if (tick) clearInterval(tick); tick = null; if (sheet) sheet.remove(); sheet = null; },
    visible() { return !!sheet; },
  };
  // state is the fallback when the event was missed (page loaded while ringing)
  setInterval(() => { const r = HD.state && HD.state.ringer; if (!r) return; if (r.ringing && !HDRing.visible()) HDRing.show({ kind: r.kind, label: r.label }); if (!r.ringing && HDRing.visible()) HDRing.hide(); }, 1500);
})();
