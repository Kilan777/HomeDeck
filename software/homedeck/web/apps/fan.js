/* Fan: CM4 cooling fan on J21. Auto follows the CM4 temperature with hysteresis; On uses a manual speed. */
(() => {
  const tempOut = c => c == null ? "–" : HD.units() === "metric" ? `${c.toFixed(1)} °C` : `${Math.round(c * 9 / 5 + 32)} °F`;
  let last = "";
  function draw(s) {
    const el = document.getElementById("fanapp"); if (!el) return;
    const f = (s && s.fan) || {}, cfg = HD.config.fan || {}, a = cfg.auto || {};
    const pwm = f.driver === "gpiozero-pwm";
    const fanText = f.running ? (pwm ? `Running · ${f.pct}%` : "Running") : "Stopped";
    // the page is only rebuilt when the mode, driver or an error changes; live readings are patched in place so a
    // tap never lands on a button that was just replaced
    const sig = JSON.stringify([f.mode, f.driver, f.error]);
    if (sig === last && el.children.length) {
      const t = el.querySelector("#f_temp"), r = el.querySelector("#f_run");
      if (t) t.textContent = tempOut(f.temp_c);
      if (r) r.textContent = fanText;
      return;
    }
    last = sig;
    el.innerHTML = `
      <div class="card"><div class="rows">
        <div class="row"><span class="k">CM4 temperature</span><span class="v" id="f_temp">${tempOut(f.temp_c)}</span></div>
        <div class="row"><span class="k">Fan</span><span class="v" id="f_run">${fanText}</span></div>
        <div class="row"><span class="k">Driver</span><span class="v">${f.driver === "gpiozero-pwm" ? "PWM speed control" : f.driver === "pinctrl-onoff" ? "On/off only" : "None"}</span></div>
        ${f.error ? `<div class="hint err">${f.error}</div>` : ""}
      </div></div>
      <div class="card"><h3>Mode</h3>
        <div class="seg">${["auto", "on", "off"].map(m => `<button class="segbtn ${(f.mode || "auto") === m ? "on" : ""}" data-m="${m}">${m === "auto" ? "Auto" : m === "on" ? "On" : "Off"}</button>`).join("")}</div>
        <div class="hint" style="margin-top:8px">Auto starts the fan when the CM4 warms up and stops it once it cools. At night the speed is capped to stay quiet.</div>
      </div>
      ${pwm ? `<div class="card"><h3>Manual speed</h3>
        <input type="range" min="${cfg.min_pct || 35}" max="100" value="${cfg.manual_pct || 60}" id="f_pct">
        <div class="hint">Used in On mode. Fans stall below about ${cfg.min_pct || 35}%.</div>
      </div>` : ""}
      <details class="card disclose"><summary><span>Fan settings</span>${HD.icon("chevron-down", "")}</summary>
        <div class="rows">
          <div class="row"><span class="k">Start at</span><span class="v"><input type="number" id="f_on" value="${a.on_c ?? 58}" style="width:88px;text-align:right"> °C</span></div>
          <div class="row"><span class="k">Stop below</span><span class="v"><input type="number" id="f_off" value="${a.off_c ?? 50}" style="width:88px;text-align:right"> °C</span></div>
          <div class="row"><span class="k">Full speed at</span><span class="v"><input type="number" id="f_full" value="${a.full_c ?? 70}" style="width:88px;text-align:right"> °C</span></div>
        </div>
        <div style="margin-top:10px"><button class="btn primary" id="f_save">Save thresholds</button></div>
      </details>`;
    el.querySelectorAll(".segbtn").forEach(b => b.onclick = async () => {
      el.querySelectorAll(".segbtn").forEach(x => x.classList.toggle("on", x === b));   // respond on the tap, before the round trip
      await HD.api("fan", "set_mode", { mode: b.dataset.m }); last = "";
    });
    const pct = el.querySelector("#f_pct"); if (pct) pct.onchange = e => HD.api("fan", "set_pct", { pct: +e.target.value });
    el.querySelector("#f_save").onclick = async () => {
      const on = +el.querySelector("#f_on").value, off = +el.querySelector("#f_off").value, full = +el.querySelector("#f_full").value;
      if (!(off < on && on <= full)) { HD.toast("Needs stop < start ≤ full", "warning"); return; }
      await HD.saveConfig({ fan: { auto: { on_c: on, off_c: off, full_c: full } } }); HD.toast("Saved", "good");
    };
  }
  HD.registerApp({
    id: "fan", idleAppend: true, title: "Fan", icon: "wind", order: 16,
    render(el) { el.innerHTML = `<div id="fanapp"></div>`; last = ""; draw(HD.state); },
    update(s) { if (!document.activeElement || !document.activeElement.matches("input")) draw(s); },
    idleWidget(el, s) {
      const f = s.fan || {};
      if (!f.running) { HD.setHtml(el, ""); return; }
      HD.setHtml(el, `<div class="iw-label">Fan</div><div class="iw-big">${f.driver === "gpiozero-pwm" ? f.pct + "%" : "On"}</div><div class="iw-sub">${tempOut(f.temp_c)}</div>`);
    }
  });
})();
