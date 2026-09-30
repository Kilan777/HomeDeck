/* Bay Wheels bikes app. Backend: modules/bikes.py
   Shows only usable stations (an out-of-service one is listed greyed), and the closest available e-bikes around home,
   docked or free-floating, so a bike right outside is never missed. */
(() => {
  let nearby = null, chosen = new Set();
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const dist = m => {
    if (m == null) return "?";
    if (HD.units() === "metric") return m < 950 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`;
    const ft = m * 3.281; return ft < 950 ? `${Math.round(ft / 50) * 50} ft` : `${(m / 1609.34).toFixed(1)} mi`;
  };
  const range = m => m == null ? "" : (HD.units() === "metric" ? `${Math.round(m / 1000)} km range` : `${Math.round(m / 1609.34)} mi range`);
  const short = name => { const parts = String(name || "").split(/\s+at\s+/i).map(p => p.replace(/\b(St|Street|Ave|Avenue|Blvd|Rd|Way|Dr)\b\.?\s*$/i, "").trim()).filter(Boolean); const named = parts.filter(p => !/^\d+(st|nd|rd|th)$/i.test(p)); return named[0] || parts[0] || name; };
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

  if (!document.getElementById("bikes-style")) {
    const st = document.createElement("style"); st.id = "bikes-style"; st.textContent = `
      .bk-row.out { opacity: .55; }
      .bk-row.out .bk-n { color: var(--muted); }
      .bk-badge { display: inline-block; font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--warning); margin-left: 8px; }
      .bk-n { font-size: 22px; font-weight: 600; display: inline-flex; align-items: center; gap: 4px; font-variant-numeric: tabular-nums; }
      .bk-n svg { width: 18px; height: 18px; }
      .bk-dir { display: inline-block; min-width: 26px; text-align: center; font-size: 11px; font-weight: 600; letter-spacing: .04em; color: var(--fg2); background: rgba(255,255,255,.08); border-radius: 6px; padding: 2px 5px; margin-right: 6px; }
      .bk-near { color: var(--accent); }
    `; document.head.appendChild(st);
  }

  async function loadPicker(box) {
    const r = await HD.api("bikes", "nearby", {});
    nearby = r.stations || []; chosen = new Set(nearby.filter(s => s.chosen).map(s => s.id));
    drawPicker(box);
  }
  function drawPicker(box) {
    box.innerHTML = nearby.map(s => `<label class="row">
      <span style="flex:1">${esc(s.name)}<div class="hint">${dist(s.dist_m)} · ${s.usable === false ? "out of service" : `${s.ebikes ?? "?"} e-bikes · ${s.bikes ?? "?"} classic`}</div></span>
      <input type="checkbox" data-id="${s.id}" ${chosen.has(s.id) ? "checked" : ""}></label>`).join("");
    box.querySelectorAll("input").forEach(cb => cb.onchange = async () => {
      cb.checked ? chosen.add(cb.dataset.id) : chosen.delete(cb.dataset.id);
      await HD.api("bikes", "set_stations", { ids: [...chosen] }); HD.toast("Stations saved", "good");
    });
  }

  function bikeLine(x) {
    if (x.kind === "station") return `${plural(x.count, "e-bike")} at ${esc(x.station)}`;
    return `Free e-bike${x.near ? ` near ${esc(short(x.near))}` : " nearby"}`;
  }

  HD.registerApp({
    id: "bikes", title: "Bikes", icon: "bike", order: 20,
    idleWidget(el, s) {
      const b = s.bikes || {}, usable = b.stations || [], st = usable[0], ne = b.nearest_ebike;
      if (!st && !ne) {
        if (b.error && !b.fetched_at) { HD.setHtml(el, `<div class="iw-label">E-bikes</div><div class="hint">offline</div>`); return "1x1"; }
        if (!b.fetched_at) { HD.setHtml(el, `<div class="iw-label">E-bikes</div><div class="hint">loading…</div>`); return "1x1"; }
        const out = (b.out || []).length;
        HD.setHtml(el, `<div class="iw-label">E-bikes</div><div class="iw-mid" style="color:var(--fg2)">None</div><div class="iw-sub">${out ? plural(out, "station") + " out of service" : "Nothing nearby"}</div>`);
        return "1x1";
      }
      el.classList.toggle("warn", !!b.low);
      // a bike closer than every usable station gets the tile (a station name is the normal case)
      if (ne && ne.closer_than_stations) {
        const where = ne.kind === "station" ? short(ne.station) : `${dist(ne.dist_m)} ${ne.dir}`;
        HD.setHtml(el, `<div class="iw-label">E-bike ${ne.kind === "station" ? "at " + esc(where) : "nearby"}</div><div class="iw-big"><span class="iw-icon">${HD.icon("bolt")}</span>${ne.kind === "station" ? ne.count : dist(ne.dist_m)}</div>
          <div class="iw-sub">${ne.kind === "station" ? dist(ne.dist_m) + " away" : `${ne.dir} · ${plural(ne.walk_min, "min")} walk`}${st ? ` · ${short(st.name)} ${st.ebikes ?? 0}` : ""}</div>`);
        return "2x1";
      }
      HD.setHtml(el, `<div class="iw-label">E-bikes</div><div class="iw-big"><span class="iw-icon">${HD.icon("bolt")}</span>${st.ebikes ?? "–"}</div>
        <div class="iw-sub">${b.low ? "Running low" : esc(short(st.name))}</div>`);
      return "1x1";
    },
    render(el) {
      el.innerHTML = `<div class="card"><h2>Your stations</h2><div class="rows" id="bstations"></div><div class="hint" id="bmeta" style="margin-top:8px;color:var(--muted)"></div></div>
        <div class="card"><h2>Closest e-bikes</h2><div class="rows" id="bfree"><div class="hint">Loading…</div></div><div class="hint" style="margin-top:8px">Docked at any station or parked on the street, nearest first.</div></div>
        <div class="card"><h2>Morning warning</h2><div class="row"><span class="k">Warn when fewer e-bikes than</span>
          <select id="bthr" style="width:auto;min-width:72px;text-align:center">${[1, 2, 3, 4, 5, 8].map(n => `<option>${n}</option>`).join("")}</select></div><div class="hint">Checked between 6 and 10 am, counting your working stations and free e-bikes nearby.</div></div>
        <div class="card"><h2>Nearby stations</h2><div class="rows" id="bpicker"><div class="hint">Loading…</div></div></div>`;
      const thr = el.querySelector("#bthr"); thr.value = (HD.config.bikes || {}).low_threshold || 2;
      thr.onchange = () => HD.saveConfig({ bikes: { low_threshold: +thr.value } }).then(() => HD.toast("Saved", "good"));
      loadPicker(el.querySelector("#bpicker")).catch(e => el.querySelector("#bpicker").innerHTML = `<div class="err">${esc(e)}</div>`);
    },
    update(s) {
      const b = s.bikes || {}, box = document.getElementById("bstations"); if (!box) return;
      const usable = b.stations || [], out = b.out || [];
      if (b.error && !usable.length && !out.length) { box.innerHTML = `<div class="err">Bay Wheels feed offline: ${esc(b.error)}</div>`; return; }
      const row = (st, i, isOut) => `<div class="row bk-row ${isOut ? "out" : ""}"><span style="flex:1">${esc(st.name)}${isOut ? `<span class="bk-badge">${esc(st.reason || "Out of service")}</span>` : ""}<div class="hint">${st.primary ? "Primary · " : ""}${dist(st.dist_m)} away</div></span>
        <span class="v"><b class="bk-n" style="color:${isOut ? "var(--muted)" : (st.ebikes || 0) === 0 ? "var(--serious)" : "var(--fg)"}">${HD.icon("bolt")}${isOut ? "–" : (st.ebikes ?? "?")}</b><div class="hint">${isOut ? "no rentals" : `${st.bikes ?? "?"} classic · ${st.docks ?? "?"} docks`}</div></span></div>`;
      box.innerHTML = [...usable.map((st, i) => row(st, i, false)), ...out.map(st => row(st, 99, true))].join("") || `<div class="hint">No stations yet, pick some below.</div>`;
      document.getElementById("bmeta").textContent = b.fetched_at ? `${b.total_ebikes} e-bikes within reach · updated ${HD.fmtTime(new Date(b.fetched_at * 1000))}` : "";
      const fb = document.getElementById("bfree");
      if (fb) {
        const list = b.free_ebikes || [];
        fb.innerHTML = list.length ? list.map((x, i) => `<div class="row"><span style="flex:1"><span class="bk-dir">${esc(x.dir)}</span>${bikeLine(x)}${i === 0 && b.nearest_ebike && b.nearest_ebike.closer_than_stations ? ` <span class="bk-near">· closest to you</span>` : ""}<div class="hint">${plural(x.walk_min, "min")} walk${x.range_m ? " · " + range(x.range_m) : ""}</div></span><span class="v">${dist(x.dist_m)}</span></div>`).join("")
          : `<div class="hint">No available e-bikes within ${dist((HD.config.bikes || {}).radius_m || 500)} of home.</div>`;
      }
    },
    onEvent(name, data) { if (name === "bikes_low") HD.toast(data.text || "Few e-bikes nearby", "warning", 8000); },
  });
})();
