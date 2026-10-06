/* Settings app: general (location, clock, units), device controls, guest mode phrase, notifications topic, logs. */
(() => {
  const field = (label, inner) => `<label class="field">${label}${inner}</label>`;
  HD.registerApp({
    id: "settings", title: "Settings", icon: "gear", order: 99, guestHidden: true,
    render(el) {
      const g = HD.config.general || {}, loc = g.location || {};
      const nt = (HD.config.notify || {});
      el.innerHTML = `
      <div class="card"><h3>Location & format</h3>
        ${field("Home address", `<div class="inline"><input type="text" id="s_addr" placeholder="123 Main Street, San Francisco" value="${loc.address || ""}"><button class="btn" id="s_geo" style="flex:none">Look up</button></div>`)}
        <div class="hint" id="s_geores" style="margin:6px 0 10px">Used for weather, bikes and the radar. Only the coordinates are sent to the weather and bike services.</div>
        <div class="grid2">
          ${field("City", `<input type="text" id="s_city" value="${loc.city || ""}">`)}
          ${field("ZIP", `<input type="text" id="s_zip" value="${loc.zip || ""}">`)}
          ${field("Latitude", `<input type="number" step="0.0001" id="s_lat" value="${loc.lat ?? ""}">`)}
          ${field("Longitude", `<input type="number" step="0.0001" id="s_lon" value="${loc.lon ?? ""}">`)}
        </div>
        <div style="height:10px"></div>
        <div class="grid2">
          ${field("Clock", `<div class="seg"><button class="segbtn ${g.clock_24h ? "" : "on"}" data-k="clock_24h" data-v="false">12 h</button><button class="segbtn ${g.clock_24h ? "on" : ""}" data-k="clock_24h" data-v="true">24 h</button></div>`)}
          ${field("Units", `<div class="seg"><button class="segbtn ${g.units !== "metric" ? "on" : ""}" data-k="units" data-v="imperial">°F, mph</button><button class="segbtn ${g.units === "metric" ? "on" : ""}" data-k="units" data-v="metric">°C, km/h</button></div>`)}
        </div>
        <div style="margin-top:12px"><button class="btn primary" id="s_save">Save location</button> <button class="btn" id="s_locate">Use phone location</button></div>
      </div>
      <div class="card"><h3>Home screen</h3>
        ${field("Style", `<div class="seg" id="s_style">${[["board","Widget board"],["clockfirst","Clock-first"],["ambient","Ambient"],["weather","Weather-led"]].map(([v,l]) => `<button class="segbtn ${((g.home_style || "board") === v) ? "on" : ""}" data-hs="${v}">${l}</button>`).join("")}</div>`)}
        <div style="height:12px"></div>
        ${field("Background", `<div class="seg" id="s_bgmode">${[["live","Live sky"],["solid","Solid"],["gradient","Gradient"]].map(([v,l]) => `<button class="segbtn ${(((g.background || {}).mode || "live") === v) ? "on" : ""}" data-bg="${v}">${l}</button>`).join("")}</div>`)}
        <div id="s_bgpick" style="margin-top:10px"></div>
        ${field("Orientation", `<div class="seg" id="s_ori">${[["portrait","Portrait"],["landscape","Landscape"],["landscape_flipped","Landscape, flipped"]].map(([v,l]) => `<button class="segbtn ${((g.orientation || "portrait") === v) ? "on" : ""}" data-ori="${v}">${l}</button>`).join("")}</div>`)}
        <div class="hint" style="margin:14px 0 10px">Choose which tiles show on the home screen and their order.</div>
        <div class="rows" id="s_home" style="margin-top:8px"></div>
      </div>
      <div class="card"><h3>Room temperature</h3>
        <div class="hint">The sensors sit near the processor and can read warm. Compare with a thermometer and enter the difference here.</div>
        <div class="grid2" style="margin-top:8px">
          ${field("Offset (°F, can be negative)", `<input type="number" step="0.5" id="s_toff" value="${(((HD.config.sensors || {}).temp_offset_c || 0) * 9 / 5).toFixed(1)}">`)}
          ${field("Source", `<div class="seg"><button class="segbtn ${(HD.config.sensors || {}).temp_source !== "bme688" ? "on" : ""}" data-ts="scd40">SCD40</button><button class="segbtn ${(HD.config.sensors || {}).temp_source === "bme688" ? "on" : ""}" data-ts="bme688">BME688</button></div>`)}
        </div>
        <div style="margin-top:10px"><button class="btn" id="s_tsave">Save offset</button></div>
      </div>
      <div class="card"><h3>Guest mode</h3>
        <div class="hint">Guest mode hides personal apps and widgets and shows nothing about it on screen. Enter or leave it by holding the clock for 3 seconds, or by saying the exit phrase to Jarvis.</div>
        <div style="height:8px"></div>
        ${field("Exit phrase", `<input type="text" id="s_gp" value="${g.guest_exit_phrase || ""}">`)}
        <div style="margin-top:10px"><button class="btn" id="s_guest">${g.guest_mode ? "Leave guest mode" : "Enter guest mode now"}</button></div>
      </div>
      <div class="card"><h3>Phone notifications</h3>
        <div class="hint">Install the free <b>ntfy</b> app (iOS/Android) and subscribe to the topic below. Motion alerts while you're away, alarms and nudges arrive there. The topic name is the only thing protecting these messages, so treat it like a password. Motion snapshots are attached and pass through ntfy's servers; the switch below sends text only instead.</div>
        <label class="inline" style="margin-top:8px"><input type="checkbox" id="s_nimg" ${nt.attach_images === false ? "" : "checked"}> Attach a snapshot to motion alerts</label>
        <div class="rows" style="margin-top:8px"><div class="row"><span class="k">Topic</span><span class="v" id="s_topic" style="font-family:ui-monospace,Menlo,monospace;font-size:15px">${nt.ntfy_topic || "…"}</span></div><div class="row"><span class="k">Server</span><span class="v">${nt.ntfy_server || "https://ntfy.sh"}</span></div></div>
        <div style="margin-top:10px"><button class="btn" id="s_ntest">Send a test notification</button></div>
      </div>
      <div class="card"><h3>Wi-Fi</h3>
        <div class="rows"><div class="row"><span class="k">Connected to</span><span class="v" id="wf_cur">…</span></div><div class="row"><span class="k">Address</span><span class="v" id="wf_ip">…</span></div></div>
        <div class="inline" style="margin-top:10px;gap:8px"><button class="btn" id="wf_scan">Find networks</button><span class="hint" id="wf_msg"></span></div>
        <div id="wf_list" class="rows" style="margin-top:8px"></div>
        <div id="wf_join" class="hidden" style="margin-top:10px"></div>
        <div id="wf_saved" style="margin-top:12px"></div>
      </div>
      <div class="card"><h3>Remote access</h3>
        <div class="hint">Reach this device from anywhere at <b>https://${(HD.config.auth && HD.config.auth.public_host) || "jarvis.example.com"}</b>. Only the Google accounts listed here can sign in; a signed-in phone stays signed in for the session length. The device's own screen never asks.</div>
        <div style="height:10px"></div>
        <div class="grid2">
          ${field("Public host", `<input type="text" id="a_host" value="${(HD.config.auth && HD.config.auth.public_host) || ""}">`)}
          ${field("Session length, days", `<input type="number" id="a_days" min="1" max="365" value="${(HD.config.auth && HD.config.auth.session_days) || 30}">`)}
        </div>
        <div style="height:8px"></div>
        ${field("Google client ID", `<input type="text" id="a_cid" value="${(HD.config.auth && HD.config.auth.google_client_id) || ""}" placeholder="…apps.googleusercontent.com">`)}
        <div style="height:8px"></div>
        ${field("Google client secret", `<input type="password" id="a_csec" value="" placeholder="${(HD.config.auth && (HD.config.auth.google_client_secret_set || HD.config.auth.google_client_secret)) ? "saved, leave blank to keep" : "GOCSPX-…"}">`)}
        <div style="height:8px"></div>
        ${field("Allowed Google accounts, comma separated", `<input type="text" id="a_emails" value="${((HD.config.auth && HD.config.auth.allowed_emails) || []).join(", ")}" placeholder="you@gmail.com">`)}
        <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center"><button class="btn primary" id="a_save">Save</button>
          <label class="inline" style="margin-left:auto"><span class="k">Enable sign-in</span><button class="switch ${(HD.config.auth && HD.config.auth.enabled) ? "on" : ""}" id="a_enable" aria-label="Enable remote sign-in"></button></label></div>
        <div class="rows" id="a_status" style="margin-top:10px"></div>
        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap"><button class="btn" id="a_token">Create device token</button><button class="btn" id="a_logoutall">Sign out everywhere</button></div>
        <div class="hint" id="a_tokout" style="margin-top:6px"></div>
        <div class="hint" style="margin-top:12px">Setup, once:
          <ol style="margin:6px 0 0 18px;padding:0">
            <li>duckdns.org: create a name, then on the Pi run <code>sudo bash /opt/homedeck/install/remote_access.sh &lt;name&gt; &lt;token&gt;</code></li>
            <li>Domain DNS: CNAME <b>jarvis</b> to <b>&lt;name&gt;.duckdns.org</b></li>
            <li>Router: forward TCP 443 and 80 to the Pi, with a DHCP reservation</li>
            <li>Google Cloud console: OAuth client, Web application, redirect URI <b>https://jarvis.example.com/auth/callback</b>; paste ID and secret above, add your email, Save, then Enable</li>
          </ol></div>
      </div>
      <div class="card"><h3>Audio</h3>
        <div class="hint">System-wide volume for Jarvis, timers, alarms and Spotify. 50 to 65 % avoids clipping on this amplifier with the small speakers; night mode caps the level automatically.</div>
        <div style="height:8px"></div>
        <div class="grid2">
          ${field("Volume now", `<div class="inline"><input type="range" min="0" max="100" id="s_volnow" value="${(HD.state.audio && HD.state.audio.volume_pct) || 55}"><span id="s_volnowv" style="min-width:44px;text-align:right">${(HD.state.audio && HD.state.audio.volume_pct) || 55}%</span></div>`)}
          ${field("Volume at startup", `<input type="number" min="0" max="100" id="s_voldef" value="${(HD.config.audio && HD.config.audio.default_volume) ?? 55}">`)}
          ${field("Night mode maximum", `<input type="number" min="0" max="100" id="s_volnight" value="${(HD.config.audio && HD.config.audio.night_max_pct) ?? 35}">`)}
        </div>
        <div class="hint" id="s_audiost" style="margin-top:6px"></div>
        <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" id="s_volsave">Save audio settings</button><button class="btn" id="s_voltest">Play a test tone</button></div>
      </div>
      <div class="card"><h3>Sounds</h3>
        <div class="hint">What rings when a timer ends or an alarm goes off, and how loud. The level is set for the ring and the volume goes back afterwards.</div>
        <div id="s_snd" style="margin-top:10px"></div>
      </div>
      <div class="card"><h3>Device</h3>
        <div class="rows" id="s_sys"></div>
        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap"><button class="btn" id="s_off">Screen off</button><button class="btn" id="s_reboot">Restart HomeDeck</button></div>
      </div>`;
      const renderHome = () => { const gg = HD.config.general || {}; const hidden = new Set(gg.home_hidden || ["lists", "fan", "transit", "flights"]); const order = gg.home_order || [];
        const all = Object.values(HD.apps).filter(a => a.idleWidget && !a.kioskHidden).sort((x, y) => { const ix = order.indexOf(x.id), iy = order.indexOf(y.id); return (ix < 0 ? 1000 + (x.order || 99) : ix) - (iy < 0 ? 1000 + (y.order || 99) : iy); });
        const box = el.querySelector("#s_home"); if (!box) return;
        box.innerHTML = all.map((a, i) => `<div class="row"><span class="k">${a.title}</span><span class="inline"><button class="btn small" data-mv="${a.id}" data-d="-1" ${i === 0 ? "disabled" : ""}>Up</button><button class="btn small" data-mv="${a.id}" data-d="1" ${i === all.length - 1 ? "disabled" : ""}>Down</button><button class="switch ${hidden.has(a.id) ? "" : "on"}" data-tg="${a.id}"></button></span></div>`).join("");
        box.querySelectorAll("[data-tg]").forEach(b => b.onclick = async () => { const h = new Set(hidden); h.has(b.dataset.tg) ? h.delete(b.dataset.tg) : h.add(b.dataset.tg); await HD.saveConfig({ general: { home_hidden: [...h] } }); renderHome(); });
        box.querySelectorAll("[data-mv]").forEach(b => b.onclick = async () => { const ids = all.map(a => a.id); const i = ids.indexOf(b.dataset.mv), j = i + (+b.dataset.d); if (j < 0 || j >= ids.length) return; [ids[i], ids[j]] = [ids[j], ids[i]]; await HD.saveConfig({ general: { home_order: ids } }); renderHome(); }); };
      const SOLIDS = [["Graphite","#1c1c1e"],["Midnight","#0b1a33"],["Ink","#101418"],["Forest","#0f2a1f"],["Plum","#241633"],["Slate","#1f2933"],["Sand","#2b241c"],["Rose","#2a1620"]];
      const GRADS = [["Dusk","#1b2735","#090a0f"],["Ocean","#0f2027","#2c5364"],["Moss","#0b2a24","#0d3b36"],["Ember","#2b1b12","#120c08"],["Steel","#1f2933","#0b0f14"],["Night","#0b1a33","#000000"]];
      const renderBg = () => { const bg = (HD.config.general || {}).background || { mode: "live" }; const box = el.querySelector("#s_bgpick"); if (!box) return;
        el.querySelectorAll("[data-bg]").forEach(b => b.classList.toggle("on", b.dataset.bg === (bg.mode || "live")));
        if ((bg.mode || "live") === "live") { box.innerHTML = `<div class="hint">The sky follows the real weather, day and night.</div>`; return; }
        if (bg.mode === "solid") box.innerHTML = `<div class="bg-swatches">${SOLIDS.map(([n,c]) => `<button class="bg-sw ${bg.color === c ? "on" : ""}" data-c="${c}" style="background:${c}" aria-label="${n}"><span>${n}</span></button>`).join("")}</div><label class="bg-custom"><input type="color" id="s_bgcustom" value="${bg.color || "#1c1c1e"}"><span class="hint">Custom colour</span></label>`;
        else box.innerHTML = `<div class="bg-swatches">${GRADS.map(([n,a,b]) => `<button class="bg-sw ${(bg.gradient || [])[0] === a ? "on" : ""}" data-g="${a},${b}" style="background:linear-gradient(180deg,${a},${b})" aria-label="${n}"><span>${n}</span></button>`).join("")}</div>`;
        box.querySelectorAll("[data-c]").forEach(b => b.onclick = async () => { await HD.saveConfig({ general: { background: { mode: "solid", color: b.dataset.c } } }); HD.applyBackground(); renderBg(); });
        box.querySelectorAll("[data-g]").forEach(b => b.onclick = async () => { await HD.saveConfig({ general: { background: { mode: "gradient", gradient: b.dataset.g.split(",") } } }); HD.applyBackground(); renderBg(); });
        const cc = box.querySelector("#s_bgcustom"); if (cc) cc.onchange = async e => { await HD.saveConfig({ general: { background: { mode: "solid", color: e.target.value } } }); HD.applyBackground(); renderBg(); }; };
      renderBg();
      el.querySelectorAll("[data-bg]").forEach(b => b.onclick = async () => { const bg = (HD.config.general || {}).background || {}; await HD.saveConfig({ general: { background: { mode: b.dataset.bg, color: bg.color || "#1c1c1e", gradient: bg.gradient || ["#1b2735", "#090a0f"] } } }); HD.applyBackground(); renderBg(); });
      renderHome();
      el.querySelectorAll("[data-ori]").forEach(b => b.onclick = async () => { const r = await HD.api("display", "set_orientation", { orientation: b.dataset.ori }); await HD.loadConfig?.(); this.render(el); HD.toast(r && r.ok ? "Screen rotated" : "Saved, applies at next start", r && r.ok ? "good" : "warning"); });
      el.querySelectorAll("[data-hs]").forEach(b => b.onclick = async () => { await HD.saveConfig({ general: { home_style: b.dataset.hs } }); this.render(el); HD.toast("Home style: " + b.textContent, "good"); });
      el.querySelectorAll(".segbtn:not([data-hs]):not([data-bg]):not([data-ts]):not([data-ori])").forEach(b => b.onclick = async () => { const v = b.dataset.v === "true" ? true : b.dataset.v === "false" ? false : b.dataset.v; await HD.saveConfig({ general: { [b.dataset.k]: v } }); this.render(el); });
      el.querySelector("#s_geo").onclick = async () => { const r = await HD.api("weather", "geocode", { address: el.querySelector("#s_addr").value }); const o = el.querySelector("#s_geores");
        if (!r.ok) { o.textContent = r.error; return; } el.querySelector("#s_lat").value = r.lat.toFixed(4); el.querySelector("#s_lon").value = r.lon.toFixed(4); if (r.city) el.querySelector("#s_city").value = r.city; if (r.zip) el.querySelector("#s_zip").value = r.zip; o.textContent = "Found: " + r.display + " — press Save location"; };
      el.querySelector("#s_save").onclick = async () => {
        await HD.saveConfig({ general: { location: { address: el.querySelector("#s_addr").value, city: el.querySelector("#s_city").value, zip: el.querySelector("#s_zip").value, lat: parseFloat(el.querySelector("#s_lat").value), lon: parseFloat(el.querySelector("#s_lon").value) }, guest_exit_phrase: el.querySelector("#s_gp").value } });
        HD.toast("Saved", "good"); ["weather", "bikes"].forEach(m => HD.api(m, "refresh").catch(() => {}));
      };
      el.querySelector("#s_locate").onclick = () => navigator.geolocation ? navigator.geolocation.getCurrentPosition(p => { el.querySelector("#s_lat").value = p.coords.latitude.toFixed(4); el.querySelector("#s_lon").value = p.coords.longitude.toFixed(4); HD.toast("Filled in, press Save"); }, () => HD.toast("Location not available", "warning")) : HD.toast("Not supported here", "warning");
      el.querySelector("#s_tsave").onclick = async () => { await HD.saveConfig({ sensors: { temp_offset_c: parseFloat(el.querySelector("#s_toff").value || "0") * 5 / 9 } }); HD.toast("Saved", "good"); };
      el.querySelectorAll("[data-ts]").forEach(b => b.onclick = async () => { await HD.saveConfig({ sensors: { temp_source: b.dataset.ts } }); this.render(el); });
      el.querySelector("#s_guest").onclick = async () => { await HD.saveConfig({ general: { guest_mode: !HD.isGuest() } }); HD.showIdle(); };
      el.querySelector("#s_nimg").onchange = e => HD.saveConfig({ notify: { attach_images: e.target.checked } });
      el.querySelector("#s_ntest").onclick = () => HD.api("notify", "test").then(r => HD.toast(r.ok ? "Sent" : ("Failed: " + (r.error || "")), r.ok ? "good" : "warning"));
      const authSave = async (extra) => { const part = { auth: { public_host: el.querySelector("#a_host").value.trim(), session_days: parseInt(el.querySelector("#a_days").value) || 30, google_client_id: el.querySelector("#a_cid").value.trim(), allowed_emails: el.querySelector("#a_emails").value.split(",").map(x => x.trim()).filter(Boolean), ...(extra || {}) } };
        const sec = el.querySelector("#a_csec").value.trim(); if (sec) part.auth.google_client_secret = sec; const r = await HD.saveConfig(part); return r; };
      el.querySelector("#a_save").onclick = async () => { await authSave(); HD.toast("Saved", "good"); };
      el.querySelector("#a_enable").onclick = async () => { const on = !(HD.config.auth && HD.config.auth.enabled); if (on) { const a = HD.config.auth || {}; const cid = el.querySelector("#a_cid").value.trim(), em = el.querySelector("#a_emails").value.trim(); if (!cid || !em || (!a.google_client_secret && !el.querySelector("#a_csec").value.trim())) { HD.toast("Fill in client ID, secret and your email first", "warning"); return; } }
        const r = await authSave({ enabled: on }); const now = r.config && r.config.auth && r.config.auth.enabled; el.querySelector("#a_enable").classList.toggle("on", !!now); HD.toast(now ? "Remote sign-in enabled" : "Remote sign-in off", now ? "good" : "info"); };
      el.querySelector("#a_token").onclick = async () => { const name = prompt("Name for this device token (e.g. iPhone app)", "iPhone"); if (!name) return; const r = await HD.api("auth", "create_token", { name }); el.querySelector("#a_tokout").innerHTML = r.ok ? `Token for <b>${r.name}</b>, shown once, copy it now:<br><code style="user-select:all;word-break:break-all">${r.token}</code><br>Send it as the <code>X-HomeDeck-Token</code> header.` : (r.error || "failed"); };
      el.querySelector("#a_logoutall").onclick = () => HD.popup({ title: "Sign out every phone and browser?", body: "Everyone will have to sign in with Google again. The device's own screen is unaffected.", actions: [{ label: "Cancel" }, { label: "Sign out all", onclick: () => HD.api("auth", "logout_all").then(() => HD.toast("Done", "good")) }] });
      // ---- Wi-Fi
      const wfBars = n => { const b = n >= 75 ? 4 : n >= 50 ? 3 : n >= 25 ? 2 : 1; return `<span class="wf-bars" aria-label="${n}%">${[1,2,3,4].map(i => `<i class="${i <= b ? "on" : ""}"></i>`).join("")}</span>`; };
      const wfStatus = async () => {
        const r = await HD.api("wifi", "status", {}); if (!r || !r.ok) return r;
        el.querySelector("#wf_cur").textContent = r.ssid ? `${r.ssid}${r.signal != null ? " · " + r.signal + "%" : ""}` : "Not connected";
        el.querySelector("#wf_ip").textContent = r.ip || "–";
        const saved = (r.saved || []).filter(n => n !== r.ssid);
        el.querySelector("#wf_saved").innerHTML = saved.length ? `<div class="sec" style="margin-bottom:4px">Saved networks</div><div class="rows">${saved.map(n => `<div class="row"><span class="k">${HD.esc ? HD.esc(n) : n}</span><span class="inline"><button class="btn small" data-wfup="${encodeURIComponent(n)}">Connect</button><button class="btn small secondary" data-wfforget="${encodeURIComponent(n)}">Forget</button></span></div>`).join("")}</div>` : "";
        el.querySelectorAll("[data-wfup]").forEach(b => b.onclick = () => wfJoin(decodeURIComponent(b.dataset.wfup), true));
        el.querySelectorAll("[data-wfforget]").forEach(b => b.onclick = async () => { await HD.api("wifi", "forget", { ssid: decodeURIComponent(b.dataset.wfforget) }); HD.toast("Forgotten"); wfStatus(); });
        return r;
      };
      const wfJoin = (ssid, secured) => {
        const box = el.querySelector("#wf_join"); box.classList.remove("hidden");
        box.innerHTML = `<div class="sec" style="margin-bottom:6px">Join ${ssid}</div><div class="inline" style="gap:8px;flex-wrap:wrap">${secured ? `<input type="password" id="wf_pw" placeholder="Password" autocomplete="off" style="flex:1;min-width:180px">` : ""}<button class="btn primary" id="wf_go">Connect</button><button class="btn" id="wf_cancel">Cancel</button></div><div class="hint" id="wf_res" style="margin-top:8px"></div>`;
        box.scrollIntoView({ block: "nearest" });
        const pw = box.querySelector("#wf_pw"); if (pw) setTimeout(() => pw.focus(), 50);
        box.querySelector("#wf_cancel").onclick = () => { box.classList.add("hidden"); box.innerHTML = ""; };
        const go = async () => {
          const password = pw ? pw.value : "";
          if (secured && !password && !(HD.state.wifi && (HD.state.wifi.saved || []).includes(ssid))) { HD.toast("Enter the password", "warning"); return; }
          const res = box.querySelector("#wf_res"); res.textContent = `Connecting to ${ssid}…`;
          const r = await HD.api("wifi", "connect", { ssid, password });
          if (!r || !r.ok) { res.textContent = (r && r.error) || "Could not start"; return; }
          for (let i = 0; i < 40; i++) {
            await new Promise(ok => setTimeout(ok, 1500));
            const st = await HD.api("wifi", "status", {});
            if (st && !st.busy && st.last_result) { res.textContent = st.last_result.message; if (st.last_result.ok) { HD.toast(st.last_result.message, "good"); setTimeout(() => { box.classList.add("hidden"); box.innerHTML = ""; }, 1500); } await wfStatus(); return; }
          }
          res.textContent = "Still trying… check again in a moment.";
        };
        box.querySelector("#wf_go").onclick = go;
        if (pw) pw.onkeydown = e => { if (e.key === "Enter") go(); };
      };
      el.querySelector("#wf_scan").onclick = async () => {
        const msg = el.querySelector("#wf_msg"), list = el.querySelector("#wf_list"); msg.textContent = "Scanning…";
        const r = await HD.api("wifi", "scan", {}); msg.textContent = r && r.ok ? `${r.networks.length} found` : ((r && r.error) || "Scan failed");
        if (!r || !r.ok) return;
        list.innerHTML = r.networks.map(n => `<button class="row wf-net" data-wf="${encodeURIComponent(n.ssid)}" data-sec="${n.secured ? 1 : 0}"><span class="k">${n.ssid}${n.active ? ' <span class="hint">· connected</span>' : ""}</span><span class="inline" style="gap:8px">${n.secured ? HD.icon("lock", "wf-lock") : ""}${wfBars(n.signal)}</span></button>`).join("");
        list.querySelectorAll(".wf-net").forEach(b => b.onclick = () => wfJoin(decodeURIComponent(b.dataset.wf), b.dataset.sec === "1"));
      };
      wfStatus();
      // ---- Sounds (ringtones)
      const renderSounds = () => {
        const r = (HD.state && HD.state.ringer) || {}; const box = el.querySelector("#s_snd"); if (!box) return;
        const tones = r.tones || ["Chime", "Marimba", "Classic", "Digital", "Gentle"];
        const pick = (kind) => `<div class="seg" data-kind="${kind}">${tones.map(t => `<button class="segbtn ${(r[kind + "_tone"] || "") === t ? "on" : ""}" data-tone="${t}">${t}</button>`).join("")}</div>`;
        const vol = (kind) => `<div class="inline" style="margin-top:8px"><input type="range" min="10" max="100" id="s_${kind}vol" value="${r[kind + "_volume"] ?? 60}"><span style="min-width:44px;text-align:right" id="s_${kind}volv">${r[kind + "_volume"] ?? 60}%</span><button class="btn small" data-prev="${kind}">Preview</button></div>`;
        box.innerHTML = `<div class="sec" style="margin:4px 0 6px">Timer</div>${pick("timer")}${vol("timer")}
          <div class="sec" style="margin:14px 0 6px">Alarm</div>${pick("alarm")}${vol("alarm")}
          <label class="row" style="margin-top:12px"><span class="k">Say what it is first<div class="hint">One line like "Laundry timer is done", then the tone</div></span><button class="switch ${r.say_label !== false ? "on" : ""}" id="s_saylabel" aria-label="Say the label first"></button></label>`;
        box.querySelectorAll("[data-tone]").forEach(b => b.onclick = async () => { const kind = b.closest("[data-kind]").dataset.kind; await HD.api("ringer", "set", { [kind + "_tone"]: b.dataset.tone }); await HD.api("ringer", "preview", { tone: b.dataset.tone, volume: +el.querySelector(`#s_${kind}vol`).value, seconds: 3 }); renderSoundsSoon(); });
        ["timer", "alarm"].forEach(kind => { const rng = box.querySelector(`#s_${kind}vol`), lbl = box.querySelector(`#s_${kind}volv`); let t;
          rng.oninput = () => { lbl.textContent = rng.value + "%"; HD.api("ringer", "set_live_volume", { volume: +rng.value }); clearTimeout(t); t = setTimeout(() => HD.api("ringer", "set", { [kind + "_volume"]: +rng.value }), 250); }; });
        box.querySelectorAll("[data-prev]").forEach(b => b.onclick = () => { const kind = b.dataset.prev; HD.api("ringer", "preview", { tone: (HD.state.ringer || {})[kind + "_tone"], volume: +el.querySelector(`#s_${kind}vol`).value, seconds: 4 }); });
        box.querySelector("#s_saylabel").onclick = async (e) => { const on = !e.currentTarget.classList.contains("on"); await HD.api("ringer", "set", { say_label: on }); e.currentTarget.classList.toggle("on", on); };
      };
      let sndT; const renderSoundsSoon = () => { clearTimeout(sndT); sndT = setTimeout(renderSounds, 1500); };
      renderSounds();
      el.querySelector("#s_off").onclick = () => HD.api("display", "screen_off");
      el.querySelector("#s_reboot").onclick = () => HD.popup({ title: "Restart the HomeDeck service?", body: "Takes about 10 seconds. Playback and voice stop briefly.", actions: [{ label: "Cancel" }, { label: "Restart", onclick: () => HD.api("display", "restart_service") }] });
    },
    update(s) {
      const el = document.getElementById("s_sys"); if (!el) return;
      const d = s.display || {}, p = s.presence || {};
      el.innerHTML = [["Brightness", `${d.brightness_pct ?? "?"}%`], ["Light", d.lux != null ? `${d.lux} lux · ${d.lux_source || ""}` : "No reading"], ["Mode", d.night ? "Night" : "Day"], ["Presence", p.home === false ? "Away" : "Home"]].map(([k, v]) => `<div class="row"><span class="k">${k}</span><span class="v">${v}</span></div>`).join("");
      const as = document.getElementById("a_status"); if (as && s.auth) { const a = s.auth; const ll = a.last_login ? `${a.last_login.email} · ${new Date(a.last_login.ts * 1000).toLocaleString()}` : "never";
        as.innerHTML = [["Status", a.enabled ? "Enabled" : a.configured ? "Configured, not enabled" : "Not configured"], ["Signed-in devices", a.sessions_active], ["Last sign-in", ll], ["Failed attempts, 10 min", a.failures_10m], ["Device tokens", (a.tokens || []).map(t => t.name).join(", ") || "none"]].map(([k, v]) => `<div class="row"><span class="k">${k}</span><span class="v">${v}</span></div>`).join(""); }
      const t = document.getElementById("s_topic"); if (t && s.notify && s.notify.topic) t.textContent = s.notify.topic;
      const ast = document.getElementById("s_audiost"); if (ast && s.audio) { ast.textContent = s.audio.error ? s.audio.error : `Volume ${s.audio.volume_pct == null ? "?" : s.audio.volume_pct + "%"}${s.audio.muted ? " (muted)" : ""}`;
        const r = document.getElementById("s_volnow"); if (r && document.activeElement !== r && s.audio.volume_pct != null) { r.value = s.audio.volume_pct; document.getElementById("s_volnowv").textContent = s.audio.volume_pct + "%"; } }
    }
  });
})();
