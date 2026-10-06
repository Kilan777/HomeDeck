/* Jarvis app: everything about the assistant in one place — mic and live status, how it responds, the voice,
   where answers come from, personal memory and the conversation. Every control saves immediately.
   Also owns the listening sheet (wake / transcript / answer events) and the mic-off badge on the home screen. */
(() => {
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const PHASE = { idle: "Listening for “Hey Jarvis”", wake: "Heard you", listening: "Listening…", thinking: "Thinking…", speaking: "Speaking" };
  const V = () => HD.config.voice || {};
  let root = null, overlay = null, lastLog = "", lastMem = "", histTimer = null, lastOnline = null;
  if (!document.getElementById("jv-hist-style")) {
    const st = document.createElement("style"); st.id = "jv-hist-style";
    st.textContent = `.jv-hist { margin-top: 8px; max-height: 360px; overflow-y: auto; touch-action: pan-y; }
      .jv-hist .h { padding: 9px 0; border-bottom: 1px solid var(--sep); }
      .jv-hist .h:last-child { border-bottom: 0; }
      .jv-hist .m { font-size: 11px; color: var(--muted); letter-spacing: .06em; text-transform: uppercase; display: flex; justify-content: space-between; gap: 8px; }
      .jv-hist .q { font-weight: 600; margin-top: 2px; }
      .jv-hist .a { color: var(--fg2); font-size: 14px; line-height: 1.35; margin-top: 2px; }
      .jv-offline { display: inline-flex; align-items: center; gap: 6px; margin-top: 6px; padding: 3px 9px; border-radius: 999px; background: rgba(255,159,10,.18); color: #ffb340; font-size: 12px; font-weight: 600; }
      .jv-offline::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }`;
    document.head.appendChild(st);
  }

  const saveVoice = part => HD.saveConfig({ voice: part });
  const seg = (id, opts, cur) => `<div class="seg" data-seg="${id}">${opts.map(([v, l]) => `<button class="segbtn ${String(cur) === String(v) ? "on" : ""}" data-v="${v}">${l}</button>`).join("")}</div>`;
  const sw = (id, on, label, hint) => `<div class="row"><span class="k"><b class="jv-k">${label}</b>${hint ? `<span class="jv-hint">${hint}</span>` : ""}</span><button class="switch ${on ? "on" : ""}" data-sw="${id}" aria-label="${label}"></button></div>`;
  const slider = (id, min, max, step, val, left, right) => `<div class="jv-slider"><input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${val}"><div class="jv-ends"><span>${left}</span><span>${right}</span></div></div>`;

  // ---------------------------------------------------------------- cards
  function statusCard() {
    return `<div class="card jv-status">
      <div class="top"><div><h3>Microphone</h3><div class="jv-big" id="jv-phase">–</div><div class="hint" id="jv-sub"></div></div>
        <button class="switch" id="jv-mic" aria-label="Microphone"></button></div>
      <div class="jv-meter" aria-hidden="true"><div class="jv-meter-fill" id="jv-level"></div></div>
      <div class="jv-stats"><span id="jv-score">Wake score –</span><span id="jv-timing"></span></div>
      <div id="jv-online"></div>
      <div class="jv-field" style="margin-top:10px"><span class="jv-label">Microphones</span>
        <select id="jv-micdev"><option>Loading…</option></select>
        <div class="hint" id="jv-michint"></div></div>
    </div>`;
  }
  function respondCard() {
    const v = V(), tts = v.tts || {}, llm = v.llm || {}, vad = v.vad || {};
    return `<div class="card"><h3>How it responds</h3>
      <div class="rows">
        ${sw("led_feedback", v.led_feedback !== false, "Light bar reacts", "Glows while listening, thinking and answering")}
        ${sw("chirp", tts.chirp !== false, "Wake sound", "A soft blip after “Hey Jarvis”")}
        ${sw("web_search", llm.web_search !== false, "Search the web", "For questions that need fresh information")}
      </div>
      <div class="jv-field"><span class="jv-label">Follow-up window</span>${seg("follow_up_s", [[0, "Off"], [3, "3 s"], [5, "5 s"], [8, "8 s"]], v.follow_up_s ?? 5)}
        <div class="hint">After an answer, ask the next thing without the wake word.</div></div>
      <div class="jv-field"><span class="jv-label">Answer length</span>${seg("max_sentences", [[1, "Short"], [2, "Normal"], [4, "Detailed"]], llm.max_sentences ?? 2)}</div>
      <div class="jv-field"><span class="jv-label">Speech volume <span class="jv-val" id="jv-gainv">${tts.gain_db ?? -5} dB</span></span>${slider("jv-gain", -15, 0, 1, tts.gain_db ?? -5, "Quieter", "Louder")}</div>
      <div class="jv-field"><span class="jv-label">Wake sensitivity <span class="jv-val" id="jv-wakev">${(v.wake_threshold ?? 0.5).toFixed(2)}</span></span>${slider("jv-wake", 0.35, 0.7, 0.05, v.wake_threshold ?? 0.5, "More sensitive", "Less sensitive")}</div>
      <div class="jv-field"><span class="jv-label">Silence before answering <span class="jv-val" id="jv-silv">${(vad.silence_s ?? 0.65).toFixed(2)} s</span></span>${slider("jv-sil", 0.4, 1.5, 0.05, vad.silence_s ?? 0.65, "Quicker", "More patient")}</div>
      <div class="hint">Wake word: “Hey Jarvis”, or just “Jarvis” with a short pause after it. Custom wake words are a later feature.</div>
    </div>`;
  }
  function voiceCard() {
    return `<div class="card"><h3>Voice</h3>
      <div class="inline"><select id="jv-voice"><option>Loading…</option></select><button class="btn" id="jv-preview" style="flex:none">Preview</button></div>
      <div class="rows" style="margin-top:6px"><div class="row"><span class="k">Voice engine in use</span><span class="v" id="jv-engine">–</span></div><div class="row"><span class="k">Status</span><span class="v" id="jv-voicest">–</span></div></div>
      <div class="hint">Groq voices answer in about a second. Piper voices run on the device and are the offline fallback.</div>
    </div>`;
  }
  function providerCard() {
    return `<div class="card"><h3>Answers from</h3>
      ${seg("provider", [["local", "Local"], ["groq", "Groq"], ["gemini", "Gemini"], ["anthropic", "Anthropic"], ["openai_compat", "Custom"]], (V().llm || {}).provider || "")}
      <div id="jv-provfields" style="margin-top:10px"></div>
      <div class="hint" id="jv-provnote"></div>
      <div class="inline" style="margin-top:10px"><button class="btn primary" id="jv-provsave">Save</button><button class="btn" id="jv-provtest">Test</button></div>
      <div class="hint" id="jv-provres" style="margin-top:8px"></div>
    </div>`;
  }
  function memoryCard() {
    return `<div class="card"><h3>Memory</h3>
      <label class="field">Call me<div class="inline"><input type="text" id="jv-name" placeholder="Your name" autocomplete="off"><button class="btn" id="jv-namesave" style="flex:none">Save</button></div></label>
      <div class="hint">Things Jarvis remembers. Say “remember that …” or add one here.</div>
      <div class="rows" id="jv-facts" style="margin-top:6px"></div>
      <form class="inline" id="jv-factform" style="margin-top:8px"><input type="text" id="jv-fact" placeholder="Remember that…" autocomplete="off"><button class="btn" type="submit" style="flex:none">Add</button></form>
      <div style="margin-top:8px"><button class="btn small" id="jv-factclear">Clear all</button></div>
    </div>`;
  }
  function historyCard() {
    return `<div class="card"><h3>History</h3>
      <div class="inline"><input type="search" id="jv-hq" placeholder="Search past questions" autocomplete="off"><button class="btn small" id="jv-hclear" style="flex:none">Clear</button></div>
      <div class="jv-hist" id="jv-hist"><div class="hint">Loading…</div></div>
      <div class="hint" style="margin-top:8px">Everything Jarvis heard and answered, kept on the device only. Ask “what did I ask you yesterday” or “what did you tell me about …”.</div>
    </div>`;
  }
  function calibrationCard() {
    return `<div class="card"><h3>Voice calibration</h3>
      <div class="jv-cal-live"><div><div class="jv-cal-num" id="jv-erle">–</div><div class="hint">Echo reduction now</div></div>
        <div><div class="jv-cal-num" id="jv-aecst">–</div><div class="hint">Echo cancellation</div></div></div>
      <div class="jv-cal-res" id="jv-calres"></div>
      <div class="inline" style="margin-top:10px"><button class="btn primary" id="jv-cal">Calibrate</button><span class="hint" id="jv-calstep"></span></div>
      <div class="hint" style="margin-top:8px">Run this again after moving Jarvis or putting it in its case. It listens to the room for 3 seconds, then plays a soft 4-second hiss at the current volume to measure the speakers. Keep the room quiet while it runs.</div>
    </div>`;
  }
  function renderCal(res) {
    const box = root && root.querySelector("#jv-calres"); if (!box) return;
    if (!res) { box.innerHTML = `<div class="hint">Not calibrated yet.</div>`; return; }
    if (res.error) { box.innerHTML = `<div class="err">Calibration failed: ${res.error}</div>`; return; }
    const when = res.t ? new Date(res.t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
    box.innerHTML = `<div class="jv-cal-verdict ${String(res.verdict || "").toLowerCase()}">${res.verdict || ""}</div>
      <div class="jv-cal-sum">${res.summary || ""}</div>
      ${res.hint ? `<div class="hint jv-cal-hint">${res.hint}</div>` : ""}
      <div class="hint">Mic gain ${res.mic_gain}${res.mic_gain_suggested && Math.abs(res.mic_gain_suggested - res.mic_gain) > 1 ? ` · suggested ${res.mic_gain_suggested} <button class="btn small" id="jv-gainapply">Use it</button>` : " · fine"}${when ? ` · ${when}` : ""}</div>`;
    const g = box.querySelector("#jv-gainapply");
    if (g) g.onclick = async () => { await HD.saveConfig({ voice: { mic_gain: res.mic_gain_suggested } }); await HD.api("voice", "aec_reload", {}); HD.toast(`Mic gain ${res.mic_gain_suggested}`, "good"); };
  }
  function bindCal() {
    root.querySelector("#jv-cal").onclick = async () => {
      const r = await HD.api("voice", "calibrate", {});
      if (!r || !r.ok) { HD.toast((r && r.error) || "Could not start", "warning"); return; }
      const btn = root.querySelector("#jv-cal"); btn.disabled = true;
      for (let i = 0; i < 40; i++) {
        await new Promise(ok => setTimeout(ok, 500));
        const st = await HD.api("voice", "calibration_status", {});
        if (!root || !root.isConnected) return;
        HD.setText(root.querySelector("#jv-calstep"), st.running ? `${st.step}…` : "");
        if (st && !st.running) { renderCal(st.result); btn.disabled = false; return; }
      }
      btn.disabled = false;
    };
    const cs = document.createElement("style");
    cs.textContent = `.jv-cal-live{display:flex;gap:28px;margin-bottom:6px}.jv-cal-num{font-size:30px;font-weight:600;font-variant-numeric:tabular-nums}
      .jv-cal-verdict{font-size:20px;font-weight:600}.jv-cal-verdict.excellent,.jv-cal-verdict.good{color:var(--good)}.jv-cal-verdict.fair{color:var(--warning)}.jv-cal-verdict.poor{color:var(--critical)}
      .jv-cal-sum{font-size:15px;margin:2px 0 4px}.jv-cal-hint{margin-bottom:4px}`;
    root.appendChild(cs);
  }
  function chatCard() {
    return `<div class="card"><h3>Conversation</h3>
      <div id="jv-log" class="chat"></div>
      <form id="jv-form" class="inline" style="margin-top:8px"><input id="jv-text" placeholder="Ask by typing…" autocomplete="off"><button class="btn primary" type="submit" style="flex:none">Ask</button></form>
      <div class="inline" style="margin-top:8px"><button class="btn small" id="jv-clear">Clear history</button><button class="btn small" id="jv-stop">Stop speaking</button></div>
    </div>`;
  }

  // ---------------------------------------------------------------- render
  function render(el) {
    root = el; lastLog = ""; lastMem = "";   // fresh page, redraw memory + history on the next update
    el.innerHTML = statusCard() + respondCard() + voiceCard() + providerCard() + memoryCard() + calibrationCard() + chatCard() + historyCard();
    bindStatus(); bindRespond(); bindVoice(); bindProvider(); bindMemory(); bindCal(); bindChat(); bindHistory();
    renderCal(((HD.state.voice || {}).aec || {}).calibration || null);
  }

  function bindStatus() {
    root.querySelector("#jv-mic").onclick = async e => {
      const on = !e.currentTarget.classList.contains("on");
      e.currentTarget.classList.toggle("on", on);
      await HD.api("voice", "set_mic", { enabled: on }); HD.toast(on ? "Microphone on" : "Microphone off, nothing is captured", "info");
    };
  }
  function bindRespond() {
    root.querySelectorAll("[data-sw]").forEach(b => b.onclick = async () => {
      const on = !b.classList.contains("on"); b.classList.toggle("on", on);
      const k = b.dataset.sw;
      if (k === "led_feedback") await saveVoice({ led_feedback: on });
      else if (k === "chirp") await saveVoice({ tts: { chirp: on } });
      else if (k === "web_search") await saveVoice({ llm: { web_search: on } });
    });
    root.querySelectorAll("[data-seg]").forEach(s => s.querySelectorAll(".segbtn").forEach(b => b.onclick = async () => {
      s.querySelectorAll(".segbtn").forEach(x => x.classList.toggle("on", x === b));
      const k = s.dataset.seg, v = b.dataset.v;
      if (k === "follow_up_s") await saveVoice({ follow_up_s: +v });
      else if (k === "max_sentences") await saveVoice({ llm: { max_sentences: +v } });
      else if (k === "provider") { drawFields(v); }
    }));
    const debounced = (id, lblId, fmt, save) => { const r = root.querySelector(id), l = root.querySelector(lblId); let t = null;
      r.oninput = () => { l.textContent = fmt(+r.value); clearTimeout(t); t = setTimeout(() => save(+r.value), 250); }; };
    debounced("#jv-gain", "#jv-gainv", v => `${v} dB`, v => saveVoice({ tts: { gain_db: v } }));
    debounced("#jv-wake", "#jv-wakev", v => v.toFixed(2), v => saveVoice({ wake_threshold: v }));
    debounced("#jv-sil", "#jv-silv", v => `${v.toFixed(2)} s`, v => saveVoice({ vad: { silence_s: v } }));
  }

  async function loadMicDevices() {
    const sel = root && root.querySelector("#jv-micdev"); if (!sel) return;
    const r = await HD.api("voice", "capture_devices", {});
    if (!r || !r.ok) return;
    const cur = r.current || "";
    sel.innerHTML = r.devices.map(d => `<option value="${d.device}"${d.device === cur ? " selected" : ""}>${d.name}</option>`).join("");
    sel.onchange = async e => {
      const val = e.target.value;
      const res = await HD.api("voice", "set_capture_device", { device: val });
      HD.toast(res && res.ok ? (val === "onboard" ? "Built-in microphones only" : val ? "Built-in mics plus that USB microphone" : "Automatic: USB microphone joins in when plugged in") : "Could not switch microphone", res && res.ok ? "good" : "warning");
    };
  }
  let lastMics = "";
  function updateMics(v) {
    const m = v.mics || null, key = JSON.stringify(m);
    if (key === lastMics) return;
    lastMics = key;
    loadMicDevices();                                   // a mic was plugged in or removed: refresh the choices
    const hint = root.querySelector("#jv-michint"); if (!hint) return;
    if (!m) hint.textContent = "";
    else if (m.both) hint.textContent = `Listening through the built-in mics and ${m.usb}. Both hear “Hey Jarvis”; the music the speakers play is cancelled out of each.`;
    else if (m.usb) hint.textContent = `Listening through ${m.usb}.`;
    else hint.textContent = ((V().mic_device || "") === "onboard") ? "Built-in mics only." : "Built-in mics. Plug a USB microphone into the USB-A port and it joins in automatically.";
  }

  async function loadVoices() {
    const sel = root && root.querySelector("#jv-voice"); if (!sel) return;
    const r = await HD.api("voice", "voices"); if (!r.voices) return;
    sel.innerHTML = r.voices.map(v => `<option value="${esc(v.id)}" ${v.current ? "selected" : ""}>${esc(v.label)}${v.status === "ready" ? "" : v.status === "downloading" ? " (downloading…)" : " (downloads on select)"}</option>`).join("");
    const c = r.voices.find(v => v.current); HD.setText(root.querySelector("#jv-voicest"), c ? (c.status === "ready" ? "Ready" : c.status) : "–");
  }
  function bindVoice() {
    loadVoices();
    loadMicDevices();
    root.querySelector("#jv-voice").onchange = async e => { const r = await HD.api("voice", "set_voice", { id: e.target.value }); HD.toast(r.status === "downloading" ? "Downloading voice, about a minute" : "Voice set", "good"); setTimeout(loadVoices, 1500); };
    root.querySelector("#jv-preview").onclick = () => HD.api("voice", "preview");
  }

  const NOTES = { local: "Runs on the device, no account. Slow on this processor; install once with install/local_llm.sh.",
    groq: "Free tier and fast. Key from console.groq.com.", gemini: "Free tier. Key from aistudio.google.com/apikey.",
    anthropic: "Paid per use. Key from console.anthropic.com; uses Claude's own web search.",
    openai_compat: "Any OpenAI-compatible endpoint: OpenRouter, LM Studio, a home server." };
  function fieldsFor(pid) {
    const L = V().llm || {}, masked = set => set ? "••••••••" : "";
    const f = (lbl, type, key, val) => `<label class="field">${lbl}<input type="${type}" data-key="${key}" value="${esc(val)}" placeholder="${type === "password" ? (val ? "saved, paste to replace" : "paste key") : ""}" autocomplete="off"></label>`;
    return ({ local: [f("Model", "text", "local.model", (L.local || {}).model || "qwen2.5:1.5b"), f("Server", "text", "local.base_url", (L.local || {}).base_url || "http://127.0.0.1:11434/v1")],
      groq: [f("Groq API key", "password", "groq_key", masked(L.groq_key_set || L.groq_key)), f("Fast model", "text", "groq_fast_model", L.groq_fast_model || "openai/gpt-oss-20b"), f("Web-search model", "text", "groq_search_model", L.groq_search_model || "groq/compound")],
      gemini: [f("Gemini API key", "password", "gemini_key", masked(L.gemini_key_set || L.gemini_key)), f("Model", "text", "gemini_model", L.gemini_model || "gemini-2.0-flash")],
      anthropic: [f("Anthropic API key", "password", "api_key", masked(L.api_key_set || L.api_key)), f("Model", "text", "model", L.model || "claude-opus-5")],
      openai_compat: [f("Base URL", "text", "custom.base_url", (L.custom || {}).base_url || ""), f("API key", "password", "custom.key", masked((L.custom || {}).key_set || (L.custom || {}).key)), f("Model", "text", "custom.model", (L.custom || {}).model || "")] })[pid] || [];
  }
  function drawFields(pid) {
    const box = root.querySelector("#jv-provfields"); if (!box) return;
    box.innerHTML = fieldsFor(pid).join(""); box.dataset.pid = pid;
    HD.setText(root.querySelector("#jv-provnote"), NOTES[pid] || "");
  }
  function bindProvider() {
    const cur = (V().llm || {}).provider;
    HD.api("voice", "providers").then(r => {
      const pid = cur || (r && r.current) || "local";
      root.querySelectorAll('[data-seg="provider"] .segbtn').forEach(b => b.classList.toggle("on", b.dataset.v === pid));
      drawFields(pid);
    }).catch(() => drawFields(cur || "local"));
    root.querySelector("#jv-provsave").onclick = async () => {
      const pid = root.querySelector("#jv-provfields").dataset.pid || "local"; const llm = { provider: pid };
      root.querySelectorAll("#jv-provfields input").forEach(i => { const v = i.value.trim(); if (i.type === "password" && (!v || v.startsWith("•"))) return;
        const path = i.dataset.key.split("."); if (path.length === 2) llm[path[0]] = { ...(llm[path[0]] || {}), [path[1]]: v }; else llm[path[0]] = v; });
      await saveVoice({ llm }); HD.toast("Saved", "good");
    };
    root.querySelector("#jv-provtest").onclick = async () => { const o = root.querySelector("#jv-provres"); o.textContent = "Asking…";
      const r = await HD.api("voice", "llm_test"); o.textContent = (r.ok ? "" : "Failed: ") + (r.answer || r.error || "") + (r.ms ? ` · ${r.provider}, ${(r.ms / 1000).toFixed(1)} s` : ""); };
  }

  function bindMemory() {
    root.querySelector("#jv-namesave").onclick = async () => { const name = root.querySelector("#jv-name").value.trim(); await HD.api("memory", "set_name", { name }); HD.toast(name ? `Got it, ${name}` : "Name cleared", "good"); };
    root.querySelector("#jv-factform").onsubmit = async e => { e.preventDefault(); const i = root.querySelector("#jv-fact"); const t = i.value.trim(); if (!t) return; i.value = ""; await HD.api("memory", "add", { text: t }); lastMem = ""; };
    root.querySelector("#jv-factclear").onclick = () => HD.popup({ title: "Forget everything?", body: "All remembered facts are removed. Your name is kept.", actions: [{ label: "Cancel" }, { label: "Forget", onclick: async () => { await HD.api("memory", "clear"); lastMem = ""; } }] });
    root.querySelector("#jv-facts").addEventListener("click", async e => { const b = e.target.closest("[data-del]"); if (!b) return; await HD.api("memory", "remove", { index: +b.dataset.del }); lastMem = ""; });
  }
  function renderMemory(mem) {
    const box = root.querySelector("#jv-facts"); if (!box) return;
    const key = JSON.stringify(mem); if (key === lastMem) return; lastMem = key;
    const nm = root.querySelector("#jv-name"); if (document.activeElement !== nm) nm.value = mem.name || "";
    const facts = mem.facts || [];
    box.innerHTML = facts.length ? facts.map((f, i) => `<div class="row"><span class="k jv-fact">${esc(f.text)}</span><button class="btn small" data-del="${i}" aria-label="Forget">${HD.icon("trash", "")}</button></div>`).join("")
      : `<div class="hint">Nothing remembered yet.</div>`;
  }

  function bindChat() {
    root.querySelector("#jv-form").onsubmit = async e => {
      e.preventDefault(); const inp = root.querySelector("#jv-text"); const text = inp.value.trim(); if (!text) return;
      inp.value = ""; addBubble("user", text); const thinking = addBubble("bot", "…");
      try { const r = await HD.api("voice", "ask", { text }); const ans = r.answer || r.error || "no answer"; thinking.textContent = ans; if (HD.KIOSK && r.answer) HD.api("voice", "say", { text: r.answer }); loadHistory(); }
      catch (err) { thinking.textContent = "request failed: " + err; }
    };
    root.querySelector("#jv-clear").onclick = async () => { await HD.api("voice", "clear_history"); root.querySelector("#jv-log").innerHTML = ""; lastLog = ""; };
    root.querySelector("#jv-stop").onclick = () => HD.api("voice", "stop");
  }
  function addBubble(who, text) {
    const log = root && root.querySelector("#jv-log"); if (!log) return document.createElement("div");
    const b = document.createElement("div"); b.className = `bubble ${who}`; b.textContent = text; log.appendChild(b); log.scrollTop = log.scrollHeight; return b;
  }

  // ---------------------------------------------------------------- history (conversation log on the device)
  const SRC = { math: "Math", intent: "Built in", memory: "Memory", llm: "Model", search: "Web", local: "Local model", offline: "Offline", recall: "Recall" };
  function whenLabel(t) {
    const d = new Date(t * 1000), now = new Date(), y = new Date(); y.setDate(now.getDate() - 1);
    const tm = HD.fmtTime ? HD.fmtTime(d) : d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    if (d.toDateString() === now.toDateString()) return `Today ${tm}`;
    if (d.toDateString() === y.toDateString()) return `Yesterday ${tm}`;
    return `${d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })} ${tm}`;
  }
  async function loadHistory() {
    const box = root && root.querySelector("#jv-hist"); if (!box) return;
    const q = (root.querySelector("#jv-hq") || {}).value || "";
    const r = await HD.api("voice", "history", { limit: 60, q: q.trim() });
    if (!r || !r.ok) { box.innerHTML = `<div class="hint">History unavailable.</div>`; return; }
    if (!r.turns.length) { box.innerHTML = `<div class="hint">${q.trim() ? "Nothing matches." : "Nothing yet. Say “Hey Jarvis” and ask something."}</div>`; return; }
    box.innerHTML = r.turns.map(t => `<div class="h"><div class="m"><span>${whenLabel(t.t)}</span><span>${SRC[t.source] || esc(t.source || "")}</span></div><div class="q">${esc(t.heard)}</div>${t.answer ? `<div class="a">${esc(t.answer.length > 220 ? t.answer.slice(0, 220) + "…" : t.answer)}</div>` : ""}</div>`).join("");
  }
  function bindHistory() {
    loadHistory();
    const q = root.querySelector("#jv-hq"); q.oninput = () => { clearTimeout(histTimer); histTimer = setTimeout(loadHistory, 250); };
    q.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); loadHistory(); } };
    root.querySelector("#jv-hclear").onclick = () => HD.popup({ title: "Clear the history?", body: "Every past question and answer is deleted from the device. Remembered facts and your name are kept.",
      actions: [{ label: "Cancel" }, { label: "Clear", onclick: async () => { await HD.api("voice", "clear_conversations"); root.querySelector("#jv-log").innerHTML = ""; lastLog = ""; loadHistory(); HD.toast("History cleared", "good"); } }] });
  }

  // ---------------------------------------------------------------- live updates
  function update(state) {
    if (!root) return;
    const v = state.voice || {};
    const mic = root.querySelector("#jv-mic"); if (mic) mic.classList.toggle("on", v.mic_enabled !== false);
    HD.setText(root.querySelector("#jv-phase"), v.mic_enabled === false ? "Off" : (PHASE[v.phase] || "Idle"));
    HD.setText(root.querySelector("#jv-sub"), v.mic_enabled === false ? "Nothing is captured while the mic is off." : (v.listening ? "Say “Hey Jarvis”, then ask." : "Starting the microphone…"));
    if (v.online !== lastOnline) { lastOnline = v.online; const ob = root.querySelector("#jv-online"); if (ob) ob.innerHTML = v.online === false ? `<span class="jv-offline">Offline · timers, lights, music and math still work</span>` : ""; }
    const lvl = root.querySelector("#jv-level"); if (lvl) { const pct = Math.min(100, Math.round((v.mic_level || 0) / 40)); lvl.style.width = pct + "%"; }
    updateMics(v);
    HD.setText(root.querySelector("#jv-score"), `Wake score ${(v.wake_score_max ?? 0).toFixed(2)}`);
    const m = v.last_timings || {}; HD.setText(root.querySelector("#jv-timing"), m.total_to_speech != null ? `Last: ${m.total_to_speech}s to answer` : "");
    const eng = (v.deps || {}).tts_engine_active; HD.setText(root.querySelector("#jv-engine"), eng === "groq" ? "Groq Orpheus" : eng === "piper" ? "Piper on device" : "Not used yet");
    renderMemory(state.memory || {});
    const ae = v.aec || {};
    HD.setText(root.querySelector("#jv-aecst"), ae.active ? "On" : v.mic_enabled === false ? "Mic off" : "Off");
    HD.setText(root.querySelector("#jv-erle"), ae.active && ae.playing && ae.erle_db != null ? `${Math.round(ae.erle_db)} dB` : ae.active ? "Idle" : "–");
    const key = JSON.stringify(v.history || []);
    if (key !== lastLog) { lastLog = key; const log = root.querySelector("#jv-log"); log.innerHTML = ""; for (const h of v.history || []) addBubble(h.role === "user" ? "user" : "bot", h.content); }
  }

  function idleWidget(el, state) {
    const v = state.voice || {};
    if (v.mic_enabled === false) { el.style.display = ""; el.innerHTML = `<div class="iw-label">Microphone</div><div class="iw-mid" style="display:flex;align-items:center;gap:8px;color:var(--fg2)">${HD.icon("mic-off")} Off</div><div class="iw-sub">Nothing is captured</div>`; }
    else { el.style.display = "none"; }
  }

  function onEvent(name, data) {
    if (name === "wake") {
      hideCard();
      if (overlay) overlay.remove();
      overlay = document.createElement("div"); overlay.className = "listen-overlay"; overlay.innerHTML = `<div class="wave"><i></i><i></i><i></i><i></i><i></i></div><div>Listening…</div>`;
      document.body.appendChild(overlay); setTimeout(() => { overlay && overlay.remove(); overlay = null; }, 6000);
    } else if (name === "transcript" && overlay) {
      overlay.lastElementChild.textContent = `“${data && data.text}”`;
    } else if (name === "answer") {
      if (overlay) { overlay.remove(); overlay = null; }
      if (data && data.text) HD.toast(data.text, "info", 8000);
      if (root && root.isConnected) setTimeout(loadHistory, 400);
    } else if (name === "answer_card" && data) {
      showAnswerCard(data);
    }
  }

  // the answer, full screen, for a few seconds: a maths result, a dice roll, a coin, or the subject of a factual
  // answer with a picture. Tap a fact to open the article behind it (scrollable); tap the backdrop to dismiss.
  let cardEl = null, cardTimer = null, cardData = null, cardExpanded = false;
  const DIE = { 1: [4], 2: [0, 8], 3: [0, 4, 8], 4: [0, 2, 6, 8], 5: [0, 2, 4, 6, 8], 6: [0, 2, 3, 5, 6, 8] };
  function dieFace(n) {
    const pips = n >= 1 && n <= 6 ? DIE[n] : null;
    if (!pips) return `<div class="die num"><span>${n}</span></div>`;
    return `<div class="die">${[...Array(9)].map((_, i) => `<i class="${pips.includes(i) ? "on" : ""}"></i>`).join("")}</div>`;
  }
  function cardBody(d) {
    if (d.kind === "math") return `<div class="ac-center"><div class="ac-q">${esc(d.question || "")}</div><div class="ac-huge">${esc(d.answer || "")}</div></div>`;
    if (d.kind === "dice") return `<div class="ac-center"><div class="ac-dice">${(d.dice || []).map(n => dieFace(n)).join("")}</div><div class="ac-q ac-after">${esc(d.answer || "")}</div></div>`;
    if (d.kind === "coin") return `<div class="ac-center"><div class="ac-coin"><div class="coin"><span>${esc(d.coin || "")}</span></div></div><div class="ac-huge ac-after">${esc(d.coin || "")}</div></div>`;
    return `<div class="ac-fact">${d.image ? `<div class="ac-img" style="background-image:url('${d.image.replace(/'/g, "%27")}')"></div>` : ""}
      <div class="ac-text"><div class="ac-big">${esc(d.title || "")}</div>${d.caption ? `<div class="ac-cap">${esc(d.caption)}</div>` : ""}
      <div class="ac-ans">${esc(d.answer || "")}</div>${d.extract || d.page ? `<div class="ac-hint">Tap to learn more</div>` : ""}</div></div>`;
  }
  function showAnswerCard(d) {
    hideCard(true);
    cardData = d; cardExpanded = false;
    const el = document.createElement("div"); el.className = "answer-card " + (d.kind || "fact");
    el.innerHTML = `<div class="ac-backdrop"></div><div class="ac-panel">${cardBody(d)}</div>`;
    el.querySelector(".ac-backdrop").onclick = () => hideCard();
    el.querySelector(".ac-panel").onclick = e => { e.stopPropagation(); if (d.kind === "fact" && (d.extract || d.page)) expandCard(); else hideCard(); };
    document.body.appendChild(el); cardEl = el;
    requestAnimationFrame(() => el.classList.add("in"));
    if (d.kind === "dice") rollDice(el, d);
    if (d.kind === "coin") setTimeout(() => el.classList.add("settled"), 1400);
    const ttl = Math.max(3, +d.ttl || 10) * 1000 + (d.kind === "dice" || d.kind === "coin" ? 1500 : 0);
    cardTimer = setTimeout(() => { if (!cardExpanded) hideCard(); }, ttl);
  }
  function rollDice(el, d) {
    // tumble through random faces, slowing down, then land on the real roll
    const final = d.dice || [], sides = d.sides || 6; let step = 0, delay = 50;
    el.classList.add("rolling");
    const tick = () => {
      if (cardEl !== el) return;
      const box = el.querySelector(".ac-dice"); if (!box) return;
      step += 1;
      const done = step > 10;
      box.innerHTML = final.map(n => dieFace(done ? n : 1 + Math.floor(Math.random() * Math.min(sides, 6)))).join("");
      if (done) { el.classList.add("settled"); return; }
      delay = Math.round(delay * 1.16); setTimeout(tick, delay);
    };
    tick();
  }
  async function expandCard() {
    if (!cardEl || !cardData || cardExpanded) return;
    cardExpanded = true; clearTimeout(cardTimer);
    const el = cardEl, d = cardData, panel = el.querySelector(".ac-panel");
    el.classList.add("expanded");
    panel.innerHTML = `<div class="ac-more"><button class="ac-close" aria-label="Close">${HD.icon("x")}</button>
      <div class="ac-more-head">${d.image ? `<div class="ac-img small" style="background-image:url('${d.image.replace(/'/g, "%27")}')"></div>` : ""}
        <div><div class="ac-big">${esc(d.page || d.title || "")}</div>${d.caption ? `<div class="ac-cap">${esc(d.caption)}</div>` : ""}</div></div>
      <div class="ac-body"><p>${esc(d.extract || d.answer || "")}</p><p class="hint">Loading the rest…</p></div></div>`;
    panel.onclick = e => e.stopPropagation();
    panel.querySelector(".ac-close").onclick = () => hideCard();
    try {
      const r = await HD.api("voice", "card_more", { title: d.page || d.title });
      const body = panel.querySelector(".ac-body"); if (!body || cardEl !== el) return;
      if (r && r.ok && r.text) body.innerHTML = r.text.split(/\n{2,}/).map(par => par.startsWith("== ") ? `<h4>${esc(par.replace(/^=+\s*|\s*=+$/g, ""))}</h4>` : `<p>${esc(par).replace(/\n== (.*?) ==/g, "</p><h4>$1</h4><p>")}</p>`).join("") + `<p class="hint">From Wikipedia</p>`;
      else body.querySelector(".hint").textContent = "That is all I have on it.";
    } catch (e) { const h = panel.querySelector(".ac-body .hint"); if (h) h.textContent = "Could not load more right now."; }
  }
  function hideCard(now) {
    const el = cardEl; if (!el) return; cardEl = null; cardData = null; cardExpanded = false; clearTimeout(cardTimer);
    if (now) { el.remove(); return; }
    el.classList.remove("in"); el.classList.add("out"); setTimeout(() => el.remove(), 900);
  }

  HD.registerApp({ id: "voice", title: "Jarvis", icon: "mic", order: 5, hidden: false, guestHidden: true, idleSize: "1x1", idleAppend: true, render, update, idleWidget, onEvent });
  document.addEventListener("hd-demo-listen", () => { onEvent("wake"); setTimeout(() => onEvent("transcript", { text: "what's the weather tomorrow" }), 800); });
})();
