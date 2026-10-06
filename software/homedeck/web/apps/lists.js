/* Lists app: shopping / to-do with tabs, tick and delete. Backend: modules/lists.py */
(() => {
  let current = null;
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function draw(s) {
    const box = document.getElementById("lists-box"); if (!box) return;
    const ls = (s.lists && s.lists.lists) || {}; const names = Object.keys(ls);
    if (!names.length) { box.innerHTML = `<div class="hint">No lists yet.</div>`; return; }
    if (!current || !ls[current]) current = names[0];
    const items = ls[current] || [];
    const tabs = `<div class="seg" id="ltabs">${names.map(n => `<button class="segbtn ${n === current ? "on" : ""}" data-n="${esc(n)}">${esc(n)}${(s.lists.open_counts || {})[n] ? ` <span class="badge">${s.lists.open_counts[n]}</span>` : ""}</button>`).join("")}</div>`;
    const rows = items.length ? items.map(i => `<div class="row" style="gap:10px">
        <button class="switch ${i.done ? "on" : ""}" data-t="${i.id}" aria-label="Done" style="width:30px;height:30px;border-radius:50%;padding:0;display:flex;align-items:center;justify-content:center">${i.done ? HD.icon("check") : ""}</button>
        <span style="flex:1;${i.done ? "color:var(--muted);text-decoration:line-through" : ""}">${esc(i.text)}</span>
        <button class="btn small secondary" data-x="${i.id}" aria-label="Remove">${HD.icon("trash")}</button></div>`).join("")
      : `<div class="hint">Nothing here. Add something below, or say "Jarvis, add milk to my shopping list".</div>`;
    box.innerHTML = `${tabs}
      <div class="card" style="margin-top:12px"><div class="rows" id="litems">${rows}</div>
        <div class="inline" style="margin-top:10px"><input type="text" id="lnew" placeholder="Add to ${esc(current)}…" style="flex:1"><button class="btn primary" id="ladd">Add</button></div></div>
      <div class="inline" style="margin-top:10px;flex-wrap:wrap"><button class="btn secondary" id="lclear">Clear ticked</button><button class="btn secondary" id="lnewlist">New list</button></div>`;
    box.querySelectorAll("#ltabs [data-n]").forEach(b => b.onclick = () => { current = b.dataset.n; draw(HD.state); });
    box.querySelectorAll("[data-t]").forEach(b => b.onclick = () => HD.api("lists", "toggle", { list: current, id: +b.dataset.t }));
    box.querySelectorAll("[data-x]").forEach(b => b.onclick = () => HD.api("lists", "remove", { list: current, id: +b.dataset.x }));
    const add = async () => { const inp = box.querySelector("#lnew"); const t = inp.value.trim(); if (!t) return; const r = await HD.api("lists", "add", { list: current, text: t }); if (r.ok) { inp.value = ""; HD.toast("Added", "good"); } else HD.toast(r.error || "Could not add", "serious"); };
    box.querySelector("#ladd").onclick = add;
    box.querySelector("#lnew").onkeydown = e => { if (e.key === "Enter") add(); };
    box.querySelector("#lclear").onclick = () => HD.api("lists", "clear_done", { list: current });
    box.querySelector("#lnewlist").onclick = () => {
      const w = HD.popup({ title: "New list", body: `<input type="text" id="lname" placeholder="Name" style="margin-top:8px">`, actions: [{ label: "Cancel" }, { label: "Create", onclick: async () => { const n = document.getElementById("lname-val") ? document.getElementById("lname-val").value : ""; } }] });
      const inp = w.querySelector("#lname"); const btn = w.querySelectorAll(".pactions button")[1];
      btn.onclick = async () => { const n = inp.value.trim(); w.remove(); if (!n) return; const r = await HD.api("lists", "new_list", { name: n }); if (r.ok) { current = r.name; HD.toast("List created", "good"); } else HD.toast(r.error || "Could not create", "serious"); };
    };
  }

  HD.registerApp({
    id: "lists", title: "Lists", icon: "list", order: 18, guestHidden: true,
    render(el) { el.innerHTML = `<div id="lists-box"></div>`; draw(HD.state); },
    update(s) {
      // redraw only when the data changed, so typing in the add box is never interrupted
      const sig = JSON.stringify(s.lists && s.lists.lists);
      if (sig !== this._sig) { this._sig = sig; const inp = document.getElementById("lnew"); const keep = inp ? inp.value : ""; draw(s); const n = document.getElementById("lnew"); if (n && keep) n.value = keep; }
    },
    idleWidget(el, s) {
      const n = ((s.lists || {}).open_counts || {}).Shopping || 0;
      if (!n) { HD.setHtml(el, ""); return; }
      HD.setHtml(el, `<div class="iw-label">Shopping</div><div class="iw-big">${n}<span class="iw-unit">${n === 1 ? "item" : "items"}</span></div><div class="iw-sub">Tap to see the list</div>`);
    },
  });
})();
