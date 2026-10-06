/* Presence app (phone only): Home / Away / Auto control and the list of phones to watch on the LAN. */
(() => {
  let root = null, phones = null;
  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) { if (k === "class") el.className = v; else if (k.startsWith("on")) el[k] = v; else el.setAttribute(k, v); }
    for (const k of kids) el.append(k); return el;
  };
  const ago = t => { if (!t) return "never"; const s = Math.round(Date.now() / 1000 - t); return s < 60 ? `${s} s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`; };

  function drawPhones(el) {
    const box = el.querySelector("#pr-phones"); box.innerHTML = "";
    phones.forEach((p, i) => box.append(h("div", { class: "pr-row inline", style: "margin-bottom:8px" },
      h("input", { type: "text", placeholder: "Name", value: p.name || "", oninput: e => p.name = e.target.value }),
      h("input", { type: "text", placeholder: "IP or MAC", value: p.ip || p.mac || "", oninput: e => { const v = e.target.value.trim(); if (/^([0-9a-f]{2}:){5}[0-9a-f]{2}$/i.test(v)) { p.mac = v; delete p.ip; } else { p.ip = v; delete p.mac; } } }),
      Object.assign(h("button", { class: "danger small btn", style: "flex:none;width:44px;padding:0;display:flex;align-items:center;justify-content:center", onclick: () => { phones.splice(i, 1); drawPhones(el); } }), { innerHTML: HD.icon("trash", "") }))));
  }

  HD.registerApp({
    id: "presence", title: "Presence", icon: "home", order: 60, guestHidden: true, kioskHidden: true,
    render(el) {
      root = el; phones = null;
      el.innerHTML = `<div class="card"><div class="seg" id="pr-seg"></div><p class="hint" id="pr-status" style="margin-top:10px;text-align:center"></p></div>
        <div class="card"><h2>Phones to watch</h2><p class="hint">Add each phone's Wi-Fi address (give it a DHCP reservation on the router) or its MAC address. You're home when any of them answers.</p>
        <div id="pr-phones" style="margin:10px 0"></div><div class="actions"><button id="pr-addp">Add phone</button><button class="primary" id="pr-save">Save</button><button id="pr-probe">Check now</button></div>
        <div id="pr-seen" class="rows" style="margin-top:8px"></div></div>`;
      const seg = el.querySelector("#pr-seg");
      for (const m of ["auto", "home", "away"]) seg.append(h("button", { class: "segbtn", "data-m": m, onclick: async () => { await HD.api("presence", "set_mode", { mode: m }); HD.toast(`Mode: ${m}`); } }, m[0].toUpperCase() + m.slice(1)));
      el.querySelector("#pr-addp").onclick = () => { phones.push({ name: "", ip: "" }); drawPhones(el); };
      el.querySelector("#pr-save").onclick = async () => { await HD.api("presence", "set_phones", { phones: phones.filter(p => p.ip || p.mac) }); HD.toast("Phones saved", "good"); };
      el.querySelector("#pr-probe").onclick = async () => { await HD.api("presence", "probe"); HD.toast("Checked"); };
    },
    update(st) {
      if (!root) return; const p = st.presence || {};
      root.querySelectorAll("#pr-seg button").forEach(b => b.classList.toggle("on", b.dataset.m === p.mode));
      root.querySelector("#pr-status").textContent = `${p.home ? "Home" : "Away"} (${p.mode === "auto" ? "detected" : "manual"}) since ${new Date((p.since || 0) * 1000).toLocaleTimeString()}`;
      if (phones === null) { phones = JSON.parse(JSON.stringify(p.phones || [])); drawPhones(root); }
      const seen = root.querySelector("#pr-seen"); seen.innerHTML = Object.entries(p.last_seen || {}).map(([n, t]) => `<div class="row"><span class="k">${n}</span><span class="v">${ago(t)}</span></div>`).join("");
    }
  });
})();
