/* Guest app: the Wi-Fi as a QR code on a white plate, the network name, house notes, and a full-screen "here's the
   Wi-Fi" overlay that Jarvis (or the phone) can trigger for a minute. Backend: modules/guest.py */
(() => {
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const style = document.createElement("style");
  style.textContent = `
  .gst-plate { background: #fff; border-radius: 18px; padding: 14px; display: inline-block; color: #111; line-height: 0; box-shadow: 0 10px 30px rgba(0,0,0,.35); }
  .gst-plate svg { width: 170px; height: 170px; display: block; }
  .gst-hero { display: flex; gap: 22px; align-items: center; }
  .gst-hero .gst-txt { min-width: 0; flex: 1; }
  .gst-ssid { font-size: 21px; font-weight: 650; letter-spacing: -.01em; line-height: 1.2; overflow-wrap: anywhere; }
  .gst-pw { font-size: 19px; font-variant-numeric: tabular-nums; font-family: ui-monospace, Menlo, monospace; margin-top: 6px; }
  .gst-note { font-size: 17px; padding: 10px 0; border-bottom: 1px solid var(--sep); }
  .gst-note:last-child { border-bottom: 0; }
  .gst-show { margin-top: 12px; }
  #gst-overlay { position: fixed; inset: 0; z-index: 90; background: rgba(6,8,12,.94); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; cursor: pointer; animation: popin .2s var(--ease); }
  #gst-overlay .gst-plate { padding: 18px; border-radius: 22px; }
  #gst-overlay .gst-plate svg { width: min(300px, 56vh); height: min(300px, 56vh); }
  #gst-overlay .gst-name { color: #fff; font-size: 26px; font-weight: 650; letter-spacing: -.01em; text-align: center; }
  #gst-overlay .gst-sub { color: rgba(255,255,255,.66); font-size: 16px; text-align: center; }
  #gst-overlay .gst-bar { position: absolute; left: 0; bottom: 0; height: 3px; background: var(--accent); width: 100%; transform-origin: left; }
  @media (orientation: landscape) and (max-height: 600px) {
    #gst-overlay { flex-direction: row; gap: 40px; }
    #gst-overlay .gst-side { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; max-width: 360px; }
    #gst-overlay .gst-name, #gst-overlay .gst-sub { text-align: left; }
    #gst-overlay .gst-plate svg { width: min(340px, 74vh); height: min(340px, 74vh); }
  }`;
  document.head.appendChild(style);

  let cardData = null, overlayTimer = null, barAnim = null;

  async function load() { const r = await HD.api("guest", "card", {}); if (r && r.ok) cardData = r; return r; }

  function closeOverlay() {
    const o = document.getElementById("gst-overlay"); if (o) o.remove();
    clearTimeout(overlayTimer); overlayTimer = null;
  }
  async function showOverlay(seconds) {
    const r = cardData && cardData.qr_svg ? cardData : await load();
    if (!r || !r.ok) { HD.toast(r && r.error ? r.error : "Wi-Fi details unavailable", "warning"); return; }
    closeOverlay();
    const secs = Math.max(5, Number(seconds) || r.show_seconds || 60);
    const o = document.createElement("div"); o.id = "gst-overlay";
    o.innerHTML = `<div class="gst-plate">${r.qr_svg}</div><div class="gst-side"><div class="gst-name">${esc(r.ssid)}</div><div class="gst-sub">Scan with your phone's camera to join</div>${r.show_password && r.password ? `<div class="gst-sub" style="font-family:ui-monospace,Menlo,monospace;color:#fff">${esc(r.password)}</div>` : ""}<div class="gst-sub">Tap to close</div></div><div class="gst-bar"></div>`;
    o.addEventListener("click", closeOverlay);
    document.body.appendChild(o);
    const bar = o.querySelector(".gst-bar");
    bar.animate([{ transform: "scaleX(1)" }, { transform: "scaleX(0)" }], { duration: secs * 1000, fill: "forwards", easing: "linear" });
    overlayTimer = setTimeout(closeOverlay, secs * 1000);
  }

  function draw(el) {
    const r = cardData;
    if (!r) { el.innerHTML = `<div class="card hint">Reading the Wi-Fi details…</div>`; return; }
    if (!r.ok) { el.innerHTML = `<div class="card"><h3>Wi-Fi</h3><div class="hint">${esc(r.error || "Not connected to Wi-Fi")}</div></div>`; return; }
    const notes = r.notes || [];
    el.innerHTML = `
      <div class="card"><h3>Wi-Fi</h3>
        <div class="gst-hero"><div class="gst-plate">${r.qr_svg}</div>
          <div class="gst-txt"><div class="gst-ssid">${esc(r.ssid)}</div><div class="hint" style="margin-top:4px">Scan with your phone's camera to join.</div>
            ${r.show_password && r.password ? `<div class="gst-pw">${esc(r.password)}</div>` : ""}
            <div class="gst-show"><button class="btn primary" id="gst-big">Show full screen</button></div>
            <div class="hint" style="margin-top:10px">Or say "Jarvis, give me the Wi-Fi".</div>
          </div></div>
      </div>
      <div class="card"><h3>House notes</h3>
        ${notes.length ? notes.map(n => `<div class="gst-note">${esc(n)}</div>`).join("") : `<div class="hint">No notes yet.</div>`}
      </div>
      ${HD.isGuest() ? "" : `<details class="card disclose"><summary><span>Guest settings</span>${HD.icon("chevron-down", "")}</summary>
        <div class="hint">One note per line. Guests see these on this card; nothing else of yours shows in guest mode.</div>
        <textarea id="gst-notes" rows="4" style="margin:10px 0">${esc(notes.join("\n"))}</textarea>
        <label class="row"><span class="k">Show the password as text too</span><button class="switch ${r.show_password ? "on" : ""}" id="gst-pw-sw" aria-label="Show password"></button></label>
        <div class="row"><span class="k">Full-screen time</span><span class="v"><input type="number" id="gst-secs" min="10" max="600" value="${r.show_seconds || 60}" style="width:88px;text-align:right"> s</span></div>
        <div style="margin-top:10px"><button class="btn primary" id="gst-save">Save</button></div>
      </details>`}`;
    el.querySelector("#gst-big").onclick = () => showOverlay(r.show_seconds);
    const save = el.querySelector("#gst-save");
    if (save) {
      const sw = el.querySelector("#gst-pw-sw");
      sw.onclick = () => sw.classList.toggle("on");
      save.onclick = async () => {
        await HD.api("guest", "set_notes", { notes: el.querySelector("#gst-notes").value });
        await HD.api("guest", "set_options", { show_password: sw.classList.contains("on"), show_seconds: +el.querySelector("#gst-secs").value || 60 });
        HD.toast("Saved", "good"); await load(); draw(el);
      };
    }
  }

  HD.registerApp({
    id: "guest", title: "Guest", icon: "home", order: 40, guestHidden: false,
    render(el) { cardData = null; draw(el); load().then(() => { if (el.isConnected) draw(el); }); },
    update() {},
    onEvent(name, data) { if (name === "show_wifi") showOverlay(data && data.seconds); if (name === "hide_wifi") closeOverlay(); },
  });
})();
