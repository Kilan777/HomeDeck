/* Transit: next Muni and BART departures from the stops the owner picked, with walking time from home. Backend: modules/transit.py */
(() => {
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const BUS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3" width="16" height="15" rx="3"/><path d="M4 11h16M8 21v-3M16 21v-3M8 15h.01M16 15h.01"/></svg>';
  const TRAIN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="14" rx="3"/><path d="M5 11h14M9 21l-1.5-2M15 21l1.5-2M9 15h.01M15 15h.01"/></svg>';
  const CSS = `
  .tr-list { display: flex; flex-direction: column; }
  .tr-dep { display: flex; align-items: center; gap: 12px; min-height: 52px; padding: 6px 0; border-bottom: 1px solid var(--sep); }
  .tr-dep:last-child { border-bottom: 0; }
  .tr-badge { min-width: 46px; height: 32px; padding: 0 10px; border-radius: 9px; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; font-size: 15px; letter-spacing: -.01em; background: rgba(255,255,255,.14); color: #fff; flex: none; }
  .tr-dest { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
  .tr-dest b { font-weight: 600; font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tr-dest span { font-size: 12.5px; color: var(--fg2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tr-mins { text-align: right; flex: none; font-variant-numeric: tabular-nums; }
  .tr-mins b { display: block; font-size: 22px; font-weight: 600; line-height: 1.05; letter-spacing: -.02em; }
  .tr-mins b.now { color: var(--good); font-size: 17px; }
  .tr-mins span { display: block; font-size: 12px; color: var(--fg2); }
  .tr-mins span.go { color: var(--warning); font-weight: 600; }
  .tr-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 6px; }
  .tr-head h3 { margin: 0; }
  .tr-head .tr-walk { font-size: 12.5px; color: var(--fg2); white-space: nowrap; }
  .tr-kind { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); letter-spacing: .06em; text-transform: uppercase; }
  .tr-kind svg { width: 16px; height: 16px; }
  .tr-pick { display: flex; flex-direction: column; gap: 10px; }
  .tr-res { max-height: 260px; overflow-y: auto; display: flex; flex-direction: column; }
  .tr-res .row { min-height: 46px; }
  .tr-res .row .k { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
  .tr-res .row .k small { color: var(--fg2); font-size: 12px; }
  .tr-stops .row .k { display: flex; flex-direction: column; gap: 1px; }
  .tr-stops .row .k small { color: var(--fg2); font-size: 12px; }
  #transit-app .tr-empty { padding: 6px 0; }
  `;
  let root = null, pokeTimer = null, lastSig = "";
  const units = () => HD.units();
  const distTxt = m => m == null ? "" : units() === "metric" ? (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${m} m`) : (m >= 1609 ? `${(m / 1609).toFixed(1)} mi` : `${Math.round(m * 3.281 / 10) * 10} ft`);
  const isSet = () => !!(HD.config.transit && (HD.config.transit.api_key_511_set || (HD.config.transit.api_key_511 && HD.config.transit.api_key_511 !== "")));

  function depRow(d, kind) {
    const style = kind === "bart" && d.color ? `style="background:${esc(d.color)};color:${/ffff33|ffff00|ff9933|d5cfe4/i.test(d.color) ? "#000" : "#fff"}"` : "";
    const badge = kind === "bart" ? (d.line || d.route || "BART") : (d.route || "");
    const sub = kind === "bart" ? [d.cars ? `${d.cars} cars` : "", d.platform ? `Platform ${d.platform}` : ""].filter(Boolean).join(" · ") : (d.line || "");
    const mins = d.mins <= 0 ? `<b class="now">Leaving</b>` : `<b>${d.mins}<small style="font-size:13px;font-weight:500"> min</small></b>`;
    const go = d.leave_in == null ? "" : d.leave_in <= 0 ? `<span class="go">Leave now</span>` : `<span>Leave in ${d.leave_in}</span>`;
    return `<div class="tr-dep"><span class="tr-badge" ${style}>${esc(badge)}</span><div class="tr-dest"><b>${esc(d.dest || "")}</b>${sub ? `<span>${esc(sub)}</span>` : ""}</div><div class="tr-mins">${mins}${go}</div></div>`;
  }

  function stopCard(st) {
    const kind = st.kind === "bart" ? `${TRAIN} BART` : `${BUS} Muni`;
    const walk = st.walk_min != null ? `${distTxt(st.dist_m)} · ${st.walk_min} min walk` : "";
    let body;
    if (st.error && !(st.departures || []).length) body = `<div class="hint tr-empty">${esc(st.error)}</div>`;
    else if (!(st.departures || []).length) body = `<div class="hint tr-empty">Nothing scheduled soon.</div>`;
    else body = `<div class="tr-list">${st.departures.slice(0, 5).map(d => depRow(d, st.kind)).join("")}</div>`;
    return `<div class="card"><div class="tr-head"><div><span class="tr-kind">${kind}</span><h3 style="margin-top:2px">${esc(st.name)}</h3></div><span class="tr-walk">${esc(walk)}</span></div>${body}</div>`;
  }

  let lastStopsSig = "";
  function draw(s) {
    const el = document.getElementById("transit-app"); if (!el) return;
    const t = (s && s.transit) || {};
    const stops = t.stops || [];
    if (!el.children.length) el.innerHTML = `<div id="tr-deps"></div><div id="tr-stopcard"></div>`;
    // departures: redrawn whenever the data changes (every poll)
    const sig = JSON.stringify([stops, t.error, t.updated_at]);
    if (sig !== lastSig) {
      lastSig = sig;
      el.querySelector("#tr-deps").innerHTML = stops.length ? stops.map(stopCard).join("") : `<div class="card"><h3>Departures</h3><div class="hint">No stops yet. Add a BART station or a Muni stop below.</div></div>`;
    }
    // the stops card with its picker is only rebuilt when the stop list itself changes (keeps searches and lists stable)
    const ssig = JSON.stringify(stops.map(x => [x.kind, x.id, x.dist_m]));
    if (ssig !== lastStopsSig) {
      lastStopsSig = ssig;
      const card = el.querySelector("#tr-stopcard");
      card.innerHTML = `<div class="card"><h3>Stops</h3><div class="rows tr-stops">${stops.map(st => `<div class="row"><span class="k">${esc(st.name)}<small>${st.kind === "bart" ? "BART" : "Muni"}${st.dist_m != null ? " · " + distTxt(st.dist_m) : ""}</small></span><button class="btn small secondary" data-rm="${esc(st.kind)}:${esc(st.id)}">Remove</button></div>`).join("") || `<div class="hint">None yet.</div>`}</div>
        <div class="tr-pick" style="margin-top:12px"><div class="seg"><button class="segbtn on" data-pk="bart">BART station</button><button class="segbtn" data-pk="muni">Muni stop</button></div><div id="tr-picker"></div></div>
        <div class="hint" id="tr-upd" style="margin-top:10px"></div></div>`;
      card.querySelectorAll("[data-rm]").forEach(b => b.onclick = async () => { const [kind, id] = b.dataset.rm.split(":"); await HD.api("transit", "remove_stop", { kind, id }); HD.toast("Stop removed"); });
      card.querySelectorAll("[data-pk]").forEach(b => b.onclick = () => { card.querySelectorAll("[data-pk]").forEach(x => x.classList.toggle("on", x === b)); picker(el, b.dataset.pk); });
      picker(el, "bart");
    }
    const upd = el.querySelector("#tr-upd"); if (upd) upd.textContent = t.updated_at ? `Updated ${HD.fmtTime(new Date(t.updated_at * 1000))}` : "Loading…";
  }

  async function picker(el, kind) {
    const box = el.querySelector("#tr-picker"); if (!box) return;
    if (kind === "bart") {
      box.innerHTML = `<div class="hint">Loading stations…</div>`;
      const r = await HD.api("transit", "bart_stations", {});
      if (!r || !r.ok) { box.innerHTML = `<div class="hint">${esc((r && r.error) || "BART list unavailable")}</div>`; return; }
      box.innerHTML = `<div class="tr-res rows">${r.stations.slice(0, 12).map(s => `<div class="row"><span class="k">${esc(s.name)}<small>${esc(s.city || "")}${s.dist_m != null ? " · " + distTxt(s.dist_m) : ""}</small></span><button class="btn small" data-add='${esc(JSON.stringify({ kind: "bart", id: s.id, name: s.name, lat: s.lat, lon: s.lon }))}'>Add</button></div>`).join("")}</div>`;
    } else {
      if (!isSet()) {
        box.innerHTML = `<div class="hint">Muni times come from 511.org, which needs a free key. Get one at 511.org/open-data/token (instant), then paste it here.</div>
          <div class="inline" style="margin-top:8px;gap:8px"><input type="password" id="tr-key" placeholder="511 API key" autocomplete="off" style="flex:1"><button class="btn primary" id="tr-key-save">Save</button></div>`;
        box.querySelector("#tr-key-save").onclick = async () => { const k = box.querySelector("#tr-key").value.trim(); if (!k) return; const r = await HD.api("transit", "set_key", { api_key_511: k }); if (r && r.ok) { HD.toast("Key saved", "good"); if (HD.config.transit) HD.config.transit.api_key_511_set = true; picker(el, "muni"); } };
        return;
      }
      box.innerHTML = `<div class="inline" style="gap:8px"><input type="search" id="tr-q" placeholder="Stop name, e.g. 16th St & Valencia" autocomplete="off" style="flex:1" data-enter="search"><button class="btn primary" id="tr-go">Search</button></div><div id="tr-mres" class="tr-res rows" style="margin-top:8px"></div>`;
      const go = async () => {
        const q = box.querySelector("#tr-q").value.trim(); const res = box.querySelector("#tr-mres"); res.innerHTML = `<div class="hint">Searching…</div>`;
        const r = await HD.api("transit", "muni_search", { q });
        if (!r || !r.ok) { res.innerHTML = `<div class="hint">${esc((r && r.error) || "Search failed")}</div>`; return; }
        res.innerHTML = r.stops.map(s => `<div class="row"><span class="k">${esc(s.name)}<small>Stop ${esc(s.id)}${s.dist_m != null ? " · " + distTxt(s.dist_m) : ""}</small></span><button class="btn small" data-add='${esc(JSON.stringify({ kind: "muni", id: s.id, name: s.name, lat: s.lat, lon: s.lon }))}'>Add</button></div>`).join("") || `<div class="hint">No stops match.</div>`;
        wireAdd(res);
      };
      box.querySelector("#tr-go").onclick = go;
      box.querySelector("#tr-q").addEventListener("keydown", e => { if (e.key === "Enter") go(); });
      go();
    }
    wireAdd(box);
  }
  function wireAdd(scope) {
    scope.querySelectorAll("[data-add]").forEach(b => b.onclick = async () => { const st = JSON.parse(b.dataset.add); const r = await HD.api("transit", "add_stop", st); if (r && r.ok) HD.toast(`Added ${st.name}`, "good"); });
  }

  HD.registerApp({
    id: "transit", title: "Transit", icon: BUS, order: 26, guestHidden: false,
    render(el) {
      root = el;
      if (!document.getElementById("transit-css")) { const st = document.createElement("style"); st.id = "transit-css"; st.textContent = CSS; document.head.appendChild(st); }
      el.innerHTML = `<div id="transit-app"></div>`; lastSig = ""; lastStopsSig = "";
      draw(HD.state);
      HD.api("transit", "poke", {});
      clearInterval(pokeTimer); pokeTimer = setInterval(() => { if (!el.isConnected) { clearInterval(pokeTimer); return; } HD.api("transit", "poke", {}); }, 60000);
    },
    update(s) { if (root && root.isConnected && !(document.activeElement && document.activeElement.matches("input"))) draw(s); },
    idleSize: "2x1",
    idleWidget(el, s) {
      const n = s.transit && s.transit.next;
      if (!n) { HD.setHtml(el, ""); return "2x1"; }
      const who = n.kind === "bart" ? `${n.line ? n.line + " line" : "BART"} to ${n.dest}` : `${n.route}${n.line ? " " + n.line : ""} to ${n.dest}`;
      const catchable = n.leave_in == null || n.leave_in >= 0;
      const head = !catchable ? (n.mins <= 0 ? "Leaving now" : `In ${n.mins} min`) : n.leave_in <= 0 ? "Leave now" : `Leave in ${n.leave_in} min`;
      const tail = catchable ? (n.mins <= 0 ? "leaving" : `${n.mins} min`) : `${n.walk_min} min walk`;
      HD.setHtml(el, `<div class="iw-label">Transit</div><div class="iw-mid">${esc(head)}</div><div class="iw-sub">${esc(who)} · ${esc(n.stop)} · ${esc(tail)}</div>`);
      return "2x1";
    },
  });
})();
