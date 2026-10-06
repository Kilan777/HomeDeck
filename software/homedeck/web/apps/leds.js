/* Lights: use the LED bar as a lamp. Colour swatches, a brightness slider, and an on/off switch.
   Patterns (alarm, listening, timers) play over the top and return to the lamp colour afterwards. */
(() => {
  const PRESETS = [["Warm", [255, 160, 70]], ["Soft", [255, 200, 140]], ["Daylight", [255, 245, 230]], ["Cool", [200, 225, 255]],
                   ["Night", [120, 20, 0]], ["Amber", [255, 120, 0]], ["Ocean", [0, 140, 255]], ["Forest", [30, 200, 90]], ["Rose", [255, 60, 120]]];
  const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;
  const hex = c => "#" + c.map(x => x.toString(16).padStart(2, "0")).join("");
  const fromHex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  // hue (0-360) -> fully saturated rgb, and rgb -> hue for placing the thumb
  const hueRgb = h => { const f = n => { const k = (n + h / 60) % 6; return Math.round(255 * (1 - Math.max(0, Math.min(k, 4 - k, 1)))); }; return [f(5), f(3), f(1)]; };
  const rgbHue = ([r, g, b]) => { r /= 255; g /= 255; b /= 255; const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn; if (!d) return null;
    let h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; h = Math.round(h * 60); return h < 0 ? h + 360 : h; };
  const same = (a, b) => a && b && a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
  let lamp = { on: false, color: [255, 170, 90], brightness: 60 };
  // strip setup: which LEDs of the chain actually show through the enclosure
  const setup = { open: false, index: 10, start: null, end: null, name: "", chasing: false, segs: [], count: 70 };
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function set(part) { lamp = { ...lamp, ...part }; HD.api("leds", "lamp", part); draw(); }

  async function saveSegs(segs, note) {
    const r = await HD.api("leds", "set_segments", { segments: segs });
    if (r && r.ok) { setup.segs = r.segments; setup.chasing = false; HD.toast(note || (r.segments.length ? `${r.segments.length} segment${r.segments.length > 1 ? "s" : ""} saved` : "Segments cleared"), "good"); }
    else HD.toast("Could not save the segments", "warning");
    draw();
  }
  function identify(i) {
    setup.index = Math.max(0, Math.min(setup.count - 1, i));
    setup.chasing = false;
    HD.api("leds", "identify", { index: setup.index, seconds: 120 });
    const v = document.getElementById("l_idxv"); if (v) v.textContent = setup.index;
    const s = document.getElementById("l_idx"); if (s) s.value = setup.index;
  }
  function parseRanges(text) {
    // "12-35, 41-64r" -> segments; a trailing r/R means the strip runs the other way
    const out = [];
    for (const part of String(text).split(/[,;]/)) {
      const m = part.trim().match(/^(\d+)\s*(?:-|to|\.\.)\s*(\d+)\s*([rR])?$/);
      if (!m) continue;
      out.push({ name: ["Left", "Right", "Third", "Fourth"][out.length] || `Run ${out.length + 1}`,
                 start: +m[1], end: +m[2], reverse: !!m[3] });
    }
    return out;
  }
  function setupCard() {
    const segs = setup.segs, n = setup.count;
    const rows = segs.length
      ? segs.map((s, i) => `<div class="row"><span class="k">${esc(s.name)}<div class="hint">LED ${s.start} to ${s.end}${s.reverse ? " · reversed" : ""}</div></span>
          <span class="inline" style="gap:8px"><button class="btn small" data-segrev="${i}">${s.reverse ? "Normal" : "Reverse"}</button><button class="btn small secondary" data-segdel="${i}">Remove</button></span></div>`).join("")
      : `<div class="hint">No segments yet, so the whole external strip is used and the hidden onboard LEDs stay dark.</div>`;
    return `<details class="card disclose" id="l_setup"${setup.open ? " open" : ""}>
      <summary><span>Strip setup</span>${HD.icon("chevron-down", "")}</summary>
      <div class="hint">Light one LED at a time to see which ones show through the case, then save those stretches. Everything outside them stays dark.</div>
      <div class="sec" style="margin-top:14px">1 · Find a visible LED</div>
      <div class="inline" style="gap:10px"><button class="btn" id="l_dec">−</button>
        <input type="range" min="0" max="${n - 1}" value="${setup.index}" id="l_idx" style="flex:1">
        <button class="btn" id="l_inc">+</button></div>
      <div class="hint">Lighting LED <b id="l_idxv">${setup.index}</b> of ${n}. Drag or step until you see it move.</div>
      <div class="inline" style="gap:8px;margin-top:8px"><button class="btn" id="l_chase">${setup.chasing ? "Chasing…" : "Run a chase"}</button><button class="btn secondary" id="l_stopmap">Stop</button></div>
      <div class="sec" style="margin-top:16px">2 · Mark the ends of a strip</div>
      <div class="inline" style="gap:8px;flex-wrap:wrap"><input type="text" id="l_name" placeholder="Left" value="${esc(setup.name)}" style="flex:1;min-width:110px">
        <button class="btn" id="l_ms">Mark start</button><button class="btn" id="l_me">Mark end</button></div>
      <div class="hint">Start ${setup.start == null ? "–" : `<b>${setup.start}</b>`} · End ${setup.end == null ? "–" : `<b>${setup.end}</b>`}</div>
      <div style="margin-top:8px"><button class="btn primary" id="l_add"${setup.start == null || setup.end == null ? " disabled" : ""}>Add this segment</button></div>
      <div class="sec" style="margin-top:16px">3 · Visible segments</div>
      <div class="rows">${rows}</div>
      <div class="inline" style="gap:8px;margin-top:10px;flex-wrap:wrap"><button class="btn" id="l_test">Test segments</button><button class="btn secondary" id="l_clearsegs">Clear all</button></div>
      <div class="sec" style="margin-top:16px">Or type the ranges</div>
      <div class="inline" style="gap:8px"><input type="text" id="l_ranges" placeholder="12-35, 41-64" value="${segs.map(s => `${s.start}-${s.end}${s.reverse ? "r" : ""}`).join(", ")}" style="flex:1">
        <button class="btn" id="l_applyranges">Apply</button></div>
      <div class="hint">Add an r after a range if that strip runs the other way, like 41-64r.</div>
    </details>`;
  }
  function wireSetup(el) {
    const d = el.querySelector("#l_setup");
    if (!d) return;
    d.addEventListener("toggle", () => {
      setup.open = d.open;
      if (!d.open) { setup.chasing = false; HD.api("leds", "manual_off", {}); }
    });
    const slider = el.querySelector("#l_idx");
    slider.oninput = e => { const v = document.getElementById("l_idxv"); if (v) v.textContent = e.target.value; };
    slider.onchange = e => identify(+e.target.value);
    el.querySelector("#l_dec").onclick = () => identify(setup.index - 1);
    el.querySelector("#l_inc").onclick = () => identify(setup.index + 1);
    el.querySelector("#l_chase").onclick = async () => { setup.chasing = true; await HD.api("leds", "chase", { on: true, ms: 400 }); draw(); };
    el.querySelector("#l_stopmap").onclick = async () => { setup.chasing = false; await HD.api("leds", "manual_off", {}); draw(); };
    el.querySelector("#l_name").oninput = e => { setup.name = e.target.value; };
    el.querySelector("#l_ms").onclick = () => { setup.start = setup.index; draw(); };
    el.querySelector("#l_me").onclick = () => { setup.end = setup.index; draw(); };
    el.querySelector("#l_add").onclick = () => {
      if (setup.start == null || setup.end == null) return;
      const name = setup.name.trim() || ["Left", "Right", "Third", "Fourth"][setup.segs.length] || `Run ${setup.segs.length + 1}`;
      const segs = setup.segs.concat([{ name, start: setup.start, end: setup.end, reverse: false }]);
      setup.start = setup.end = null; setup.name = "";
      saveSegs(segs, `${name} added`);
    };
    el.querySelectorAll("[data-segdel]").forEach(b => b.onclick = () => saveSegs(setup.segs.filter((_, i) => i !== +b.dataset.segdel), "Segment removed"));
    el.querySelectorAll("[data-segrev]").forEach(b => b.onclick = () => saveSegs(setup.segs.map((s, i) => i === +b.dataset.segrev ? { ...s, reverse: !s.reverse } : s), "Direction changed"));
    el.querySelector("#l_test").onclick = async () => {
      const r = await HD.api("leds", "test_segments", { seconds: 4 });
      if (r && r.ok) HD.toast(r.segments.length ? r.segments.map(s => s.name).join(" then ") + ", each in its own colour" : "No segments to test", "info");
    };
    el.querySelector("#l_clearsegs").onclick = () => HD.popup({ title: "Clear the segments?", body: "The whole external strip will be used again.", actions: [{ label: "Cancel" }, { label: "Clear", onclick: () => saveSegs([], "Segments cleared") }] });
    el.querySelector("#l_applyranges").onclick = () => {
      const segs = parseRanges(el.querySelector("#l_ranges").value);
      if (!segs.length) { HD.toast("Type ranges like 12-35, 41-64", "warning"); return; }
      saveSegs(segs);
    };
  }
  function draw() {
    const el = document.getElementById("lights"); if (!el) return;
    const opts = HD.config.leds || {};
    const tf = opts.timer_fill !== false, mr = opts.music_reactive !== false;
    el.innerHTML = `
      <div class="card"><div class="row" style="display:flex;justify-content:space-between;align-items:center">
        <div><h3 style="margin:0">Light bar</h3><div class="hint">${lamp.on ? "On" : "Off"} · ${lamp.brightness}%</div></div>
        <button class="switch ${lamp.on ? "on" : ""}" id="l_sw" aria-label="Light on or off"></button></div></div>
      <div class="card"><h3>Brightness</h3><input type="range" min="1" max="100" value="${lamp.brightness}" id="l_br"></div>
      <div class="card"><h3>Colour</h3><div class="swatches">
        ${PRESETS.map(([n, c]) => `<button class="swatch ${same(c, lamp.color) ? "on" : ""}" style="background:${rgb(c)}" data-c="${c.join(",")}" aria-label="${n}"></button>`).join("")}
      </div>
      <div class="huewrap"><div class="huebar" id="l_hue" role="slider" aria-label="Custom colour"><div class="huethumb" id="l_thumb" style="left:${(rgbHue(lamp.color) ?? 30) / 3.6}%;background:${rgb(lamp.color)}"></div></div>
        <input type="color" id="l_custom" value="${hex(lamp.color)}" class="huefallback" aria-hidden="true" tabindex="-1"></div>
      <div class="hint" style="margin-top:10px">Tap a preset or drag along the bar for any colour. Alarms, timers and Jarvis flash over the top, then the bar returns to this colour.</div></div>
      <div class="card"><h3>Effect brightness</h3><div class="hint">How bright the flashes and the sunrise are.</div>
        <input type="range" min="5" max="100" value="${(HD.config.leds && HD.config.leds.brightness) || 60}" id="l_fx"></div>
      <div class="card"><h3>Effects</h3><div class="rows">
        <label class="row"><span class="k">Show timers on the strip<div class="hint">The strip fills up as a timer runs and breathes in the last stretch.</div></span><button class="switch ${tf ? "on" : ""}" id="l_tf" aria-label="Show timers on the strip"></button></label>
        <label class="row"><span class="k">React to music<div class="hint">A quiet light show from the centre outward while Spotify plays.</div></span><button class="switch ${mr ? "on" : ""}" id="l_mr" aria-label="React to music"></button></label>
      </div></div>
      ${setupCard()}`;
    wireSetup(el);
    el.querySelector("#l_tf").onclick = async () => { await HD.api("leds", "set_options", { timer_fill: !tf }); await HD.saveConfig({ leds: { timer_fill: !tf } }); draw(); };
    el.querySelector("#l_mr").onclick = async () => { await HD.api("leds", "set_options", { music_reactive: !mr }); await HD.saveConfig({ leds: { music_reactive: !mr } }); draw(); };
    el.querySelector("#l_sw").onclick = () => set({ on: !lamp.on });
    el.querySelector("#l_br").onchange = e => set({ brightness: +e.target.value, on: true });
    el.querySelectorAll(".swatch[data-c]").forEach(s => s.onclick = () => set({ color: s.dataset.c.split(",").map(Number), on: true }));
    el.querySelector("#l_custom").onchange = e => set({ color: fromHex(e.target.value), on: true });
    // hue bar: pointer down/drag picks a hue; the thumb follows live, the lamp updates on release (and on tap)
    const bar = el.querySelector("#l_hue"), thumb = el.querySelector("#l_thumb");
    let dragging = false, lastHue = null;
    const pick = (e, commit) => { const r = bar.getBoundingClientRect(); const x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)); const h = Math.round(x * 360) % 360;
      lastHue = h; thumb.style.left = (x * 100) + "%"; thumb.style.background = rgb(hueRgb(h)); if (commit) set({ color: hueRgb(h), on: true }); };
    bar.addEventListener("pointerdown", e => { e.stopPropagation(); dragging = true; bar.setPointerCapture(e.pointerId); pick(e, false); });
    bar.addEventListener("pointermove", e => { if (dragging) { e.stopPropagation(); pick(e, false); } });
    const end = e => { if (!dragging) return; dragging = false; e.stopPropagation(); pick(e, true); };
    bar.addEventListener("pointerup", end); bar.addEventListener("pointercancel", end);
    el.querySelector("#l_fx").onchange = e => { HD.api("leds", "set_brightness", { pct: +e.target.value }); HD.api("leds", "test"); };
  }
  HD.registerApp({
    id: "leds", idleAppend: true, title: "Lights", icon: "bulb", order: 14,
    render(el) {
      el.innerHTML = `<div id="lights"></div>`;
      const st = HD.state.leds || {};
      if (st.lamp) lamp = { ...lamp, ...st.lamp };
      setup.segs = st.segments || []; setup.count = st.count || (HD.config.leds && HD.config.leds.count) || 70;
      setup.index = Math.min(setup.index, setup.count - 1);
      draw();
    },
    update(s) {
      const st = s.leds || {}, l = st.lamp;
      if (st.count) setup.count = st.count;
      if (document.activeElement && document.activeElement.matches("input")) return;   // don't fight a slider or field
      const segsChanged = JSON.stringify(st.segments || []) !== JSON.stringify(setup.segs);
      if (segsChanged) setup.segs = st.segments || [];
      if (l) { const changed = JSON.stringify(l) !== JSON.stringify(lamp); lamp = { ...lamp, ...l }; if (changed || segsChanged) draw(); }
      else if (segsChanged) draw();
    },
    idleSize: "1x1",
    idleWidget(el, s) { const l = s.leds && s.leds.lamp; if (!l || !l.on) { HD.setHtml(el, ""); return; }
      HD.setHtml(el, `<div class="iw-label">Lights</div><div class="iw-big"><span class="dot" style="width:14px;height:14px;background:${rgb(l.color)}"></span>${l.brightness}%</div><div class="iw-sub">${(PRESETS.find(([, c]) => same(c, l.color)) || ["Custom"])[0]}</div>`); }
  });
})();
