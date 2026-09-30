/* Reminders app: one-shot reminders with a time. Backend: modules/reminders.py */
(() => {
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const when = at => { const d = new Date(at * 1000), now = new Date(); const t = HD.fmtTime(d);
    if (d.toDateString() === now.toDateString()) return `Today ${t}`;
    const tm = new Date(now); tm.setDate(tm.getDate() + 1); if (d.toDateString() === tm.toDateString()) return `Tomorrow ${t}`;
    return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" }) + " " + t; };
  const localInput = d => { const p = n => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };

  HD.registerApp({
    id: "reminders", idleAppend: true, title: "Reminders", icon: "bell", order: 19, guestHidden: true,
    render(el) {
      const d = new Date(Date.now() + 3600 * 1000); d.setSeconds(0, 0);
      el.innerHTML = `<div class="card"><h2>New reminder</h2>
          <input type="text" id="rtext" placeholder="Remind me to…">
          <div class="inline" style="margin-top:10px;flex-wrap:wrap"><input type="datetime-local" id="rwhen" value="${localInput(d)}" style="flex:1;min-width:200px"><button class="btn primary" id="radd">Add</button></div>
          <div class="hint" style="margin-top:8px">Or say "Jarvis, remind me at 5 pm to call mom" or "remind me in 20 minutes to check the oven".</div></div>
        <div class="card"><h2>Upcoming</h2><div class="rows" id="rlist"></div></div>`;
      el.querySelector("#radd").onclick = async () => {
        const text = el.querySelector("#rtext").value.trim(); const at = new Date(el.querySelector("#rwhen").value).getTime() / 1000;
        if (!text || !at) { HD.toast("Text and time needed", "warning"); return; }
        const r = await HD.api("reminders", "add", { text, at }); if (r.ok) { el.querySelector("#rtext").value = ""; HD.toast("Reminder set", "good"); } else HD.toast(r.error || "Could not add", "serious");
      };
    },
    update(s) {
      const box = document.getElementById("rlist"); if (!box) return;
      const rs = ((s.reminders || {}).reminders || []);
      const sig = JSON.stringify(rs); if (sig === this._sig) return; this._sig = sig;
      box.innerHTML = rs.length ? rs.map(r => `<div class="row"><span style="flex:1;${r.done ? "color:var(--muted)" : ""}">${esc(r.text)}<div class="hint">${r.done ? "Fired · " : ""}${when(r.at)}</div></span><button class="btn small secondary" data-id="${r.id}" aria-label="Remove">${HD.icon("trash")}</button></div>`).join("")
        : `<div class="hint">No reminders.</div>`;
      box.querySelectorAll("[data-id]").forEach(b => b.onclick = () => HD.api("reminders", "remove", { id: +b.dataset.id }));
    },
    idleSize: "2x1",
    idleWidget(el, s) {
      const n = (s.reminders || {}).next;
      if (!n || n.at - Date.now() / 1000 > 86400) { HD.setHtml(el, ""); return; }
      HD.setHtml(el, `<div class="iw-label">Reminder</div><div class="iw-mid">${esc(n.text)}</div><div class="iw-sub">${when(n.at)}</div>`);
    },
    onEvent(name, d) {
      if (name === "reminder") HD.popup({ title: "Reminder", body: `<div class="big">${esc(d.text || "")}</div>`, level: "good", actions: [{ label: "OK" }] });
    },
  });
})();
