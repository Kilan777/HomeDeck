/* Countdowns app: days until trips, rent, birthdays. Backend: modules/countdowns.py */
(() => {
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const CSS = `
  .cd-list { display: flex; flex-direction: column; }
  .cd-row { display: flex; align-items: center; gap: 14px; padding: 10px 0; border-bottom: 1px solid var(--sep); min-height: 64px; }
  .cd-row:last-child { border-bottom: 0; }
  .cd-days { min-width: 96px; text-align: center; font-variant-numeric: tabular-nums; }
  .cd-days b { display: block; font-size: 26px; font-weight: 600; letter-spacing: -.02em; line-height: 1.05; }
  .cd-days b.soon { color: var(--app-accent, var(--accent)); }
  .cd-days span { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
  .cd-main { flex: 1; min-width: 0; }
  .cd-title { font-size: 17px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .cd-sub { font-size: 13px; color: var(--fg2); margin-top: 2px; }
  .cd-tag { font-size: 11px; color: var(--muted); margin-left: 6px; }
  .cd-dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .cd-form .seg { margin-top: 8px; }
  .cd-form input[type=date] { width: auto; min-width: 170px; }
  `;
  if (!document.getElementById("cd-style")) { const st = document.createElement("style"); st.id = "cd-style"; st.textContent = CSS; document.head.appendChild(st); }
  const COLORS = [["#ff9f0a", "Amber"], ["#ff3b30", "Red"], ["#5e5ce6", "Indigo"], ["#34c759", "Green"], ["#0a84ff", "Blue"], ["#ff2d55", "Pink"]];
  const bigLabel = r => r.days === 0 ? "Today" : r.days === 1 ? "1 day" : `${r.days} days`;
  const iso = d => { const p = n => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; };
  let rot = 0, rotTimer = null;

  HD.registerApp({
    id: "countdowns", idleAppend: true, title: "Countdowns", icon: "calendar", order: 20, guestHidden: true,
    render(el) {
      const d = new Date(); d.setDate(d.getDate() + 7);
      el.innerHTML = `<div class="card"><h2>Coming up</h2><div class="cd-list" id="cd-list"></div></div>
        <div class="card cd-form"><h2>New countdown</h2>
          <input type="text" id="cd-title" placeholder="Trip to LA, Mom's birthday, rent…">
          <div class="inline" style="margin-top:10px;flex-wrap:wrap;gap:8px"><input type="date" id="cd-date" value="${iso(d)}"><input type="time" id="cd-time" style="width:auto"></div>
          <div class="seg" id="cd-rep">${[["none", "Once"], ["yearly", "Every year"], ["monthly", "Every month"]].map(([v, l], i) => `<button class="segbtn ${i === 0 ? "on" : ""}" data-rep="${v}">${l}</button>`).join("")}</div>
          <div class="inline" style="margin-top:10px;gap:8px;flex-wrap:wrap" id="cd-colors">${COLORS.map(([c, n], i) => `<button class="swatch ${i === 0 ? "on" : ""}" data-c="${c}" style="background:${c};width:34px;height:34px;min-width:34px;min-height:34px" aria-label="${n}"></button>`).join("")}</div>
          <div style="margin-top:12px"><button class="btn primary" id="cd-add">Add</button></div>
          <div class="hint" style="margin-top:8px">Or say "Jarvis, add a countdown for the LA trip on October 3rd" or "how many days until rent".</div></div>`;
      let rep = "none", color = COLORS[0][0];
      el.querySelectorAll("[data-rep]").forEach(b => b.onclick = () => { rep = b.dataset.rep; el.querySelectorAll("[data-rep]").forEach(x => x.classList.toggle("on", x === b)); });
      el.querySelectorAll("[data-c]").forEach(b => b.onclick = () => { color = b.dataset.c; el.querySelectorAll("[data-c]").forEach(x => x.classList.toggle("on", x === b)); });
      el.querySelector("#cd-add").onclick = async () => {
        const title = el.querySelector("#cd-title").value.trim(), date = el.querySelector("#cd-date").value, time = el.querySelector("#cd-time").value;
        if (!title || !date) { HD.toast("Name and date needed", "warning"); return; }
        const r = await HD.api("countdowns", "add", { title, date, time, repeat: rep, color });
        if (r.ok) { el.querySelector("#cd-title").value = ""; HD.toast("Countdown added", "good"); } else HD.toast(r.error || "Could not add", "serious");
      };
      this._sig = null; this.update(HD.state);
    },
    update(s) {
      const box = document.getElementById("cd-list"); if (!box) return;
      const rows = ((s.countdowns || {}).items || []);
      const sig = JSON.stringify(rows); if (sig === this._sig) return; this._sig = sig;
      box.innerHTML = rows.length ? rows.map(r => `<div class="cd-row">
          <div class="cd-days"><b class="${r.days <= 3 ? "soon" : ""}">${esc(bigLabel(r))}</b>${r.days > 14 ? `<span>${esc(r.label)}</span>` : ""}</div>
          ${r.color ? `<span class="cd-dot" style="background:${esc(r.color)}"></span>` : `<span class="cd-dot" style="background:rgba(255,255,255,.18)"></span>`}
          <div class="cd-main"><div class="cd-title">${esc(r.title)}${r.source === "calendar" ? `<span class="cd-tag">from calendar</span>` : r.repeat !== "none" ? `<span class="cd-tag">${r.repeat === "yearly" ? "every year" : "every month"}</span>` : ""}</div><div class="cd-sub">${esc(r.when)}</div></div>
          ${r.source === "manual" ? `<button class="btn small secondary" data-rm="${r.id}" aria-label="Remove">${HD.icon("trash")}</button>` : ""}
        </div>`).join("") : `<div class="hint">Nothing counting down. Add a trip, a birthday or a bill below.</div>`;
      box.querySelectorAll("[data-rm]").forEach(b => b.onclick = () => HD.popup({ title: "Remove this countdown?", actions: [{ label: "Cancel" }, { label: "Remove", onclick: () => HD.api("countdowns", "remove", { id: b.dataset.rm }) }] }));
    },
    idleSize: "2x1",
    idleWidget(el, s) {
      const rows = ((s.countdowns || {}).items || []).slice(0, 3);
      if (!rows.length) { HD.setHtml(el, ""); clearInterval(rotTimer); rotTimer = null; return; }
      const draw = () => { const r = rows[rot % rows.length]; if (!r) return;
        HD.setHtml(el, `<div class="iw-label">Countdown</div><div class="iw-mid">${esc(r.title)}</div><div class="iw-sub">${r.days === 0 ? "Today" : r.days === 1 ? "Tomorrow" : `in ${r.days} days`} · ${esc(r.when)}</div>`); };
      draw();
      if (!rotTimer) rotTimer = setInterval(() => { const e = document.getElementById(el.id); if (!e || !e.isConnected) { clearInterval(rotTimer); rotTimer = null; return; } rot++; const rs = ((HD.state.countdowns || {}).items || []).slice(0, 3); const r = rs[rot % Math.max(1, rs.length)]; if (r) HD.setHtml(e, `<div class="iw-label">Countdown</div><div class="iw-mid">${esc(r.title)}</div><div class="iw-sub">${r.days === 0 ? "Today" : r.days === 1 ? "Tomorrow" : `in ${r.days} days`} · ${esc(r.when)}</div>`); }, 8000);
    },
    onEvent(name, d) {
      if (name === "countdown_today" && d && d.text) HD.toast(d.text, "good", 8000);
    },
  });
})();
