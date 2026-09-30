/* News app: RSS headlines grouped by source, with a spoken briefing. Backend: modules/news.py */
(() => {
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  HD.registerApp({
    id: "news", title: "News", icon: "news", order: 22,
    render(el) {
      el.innerHTML = `<div class="inline" style="margin-bottom:12px;flex-wrap:wrap"><button class="btn primary" id="nread">${HD.icon("volume")} Read briefing</button><button class="btn secondary" id="nrefresh">${HD.icon("refresh")} Refresh</button><span class="hint" id="nstamp"></span></div><div id="nlist"></div>`;
      el.querySelector("#nread").onclick = async () => { const r = await HD.api("news", "briefing"); if (r.ok && r.text) { HD.api("voice", "say", { text: r.text }); HD.toast("Reading the headlines", "good"); } else HD.toast("No briefing yet", "warning"); };
      el.querySelector("#nrefresh").onclick = () => { HD.api("news", "refresh"); HD.toast("Refreshing"); };
      this._sig = null;
    },
    update(s) {
      const box = document.getElementById("nlist"); if (!box) return;
      const n = s.news || {}; const sig = JSON.stringify([n.fetched_at, n.error]); if (sig === this._sig) return; this._sig = sig;
      const stamp = document.getElementById("nstamp"); if (stamp) stamp.textContent = n.fetched_at ? "Updated " + HD.fmtTime(new Date(n.fetched_at * 1000)) : "Loading…";
      const srcs = n.sources || [];
      if (!srcs.length) { box.innerHTML = `<div class="card hint">${n.error ? esc(n.error) : "Fetching headlines…"}</div>`; return; }
      // no browser on the device: headlines are plain text there; phones get a link
      box.innerHTML = srcs.map(src => `<div class="card"><h2>${esc(src.name)}</h2><div class="rows">${src.items.map(i => `<div class="row">${HD.KIOSK || !i.link ? `<span>${esc(i.title)}</span>` : `<a href="${esc(i.link)}" target="_blank" rel="noopener" style="color:inherit;text-decoration:none">${esc(i.title)}</a>`}</div>`).join("")}</div></div>`).join("")
        + (n.error ? `<div class="hint">Some feeds failed: ${esc(n.error)}</div>` : "");
    },
  });
})();
