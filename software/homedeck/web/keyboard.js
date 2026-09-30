/* On-screen keyboard for the device's touch panel (kiosk only). Slides up when a text field takes focus, types into
   it with proper input events, and goes away on Done, Enter or a tap elsewhere. Phones use their own keyboard. */
(() => {
  const HDS = window.HD || null;                      // absent when injected into another site's page (Spotify sign-in)
  if (HDS && !HDS.KIOSK) return;
  if (window.__hdKbd) return;
  window.__hdKbd = true;
  const CSS = `
#osk { position: fixed; left: 0; right: 0; bottom: 0; z-index: 2147483000; padding: 8px 8px calc(8px + env(safe-area-inset-bottom)); background: #1a1c22; box-sizing: border-box;
  box-shadow: 0 -1px 0 rgba(255,255,255,.12), 0 -20px 60px rgba(0,0,0,.4); transform: translateY(105%); transition: transform .2s ease; touch-action: none; user-select: none; -webkit-user-select: none;
  font-family: Inter, -apple-system, system-ui, sans-serif; }
#osk.in { transform: none; }
#osk .osk-row { display: flex; gap: 6px; justify-content: center; margin-bottom: 6px; }
#osk .osk-row:last-child { margin-bottom: 0; }
#osk .osk-key { flex: 1 1 0; max-width: 84px; height: 46px; border: 0; border-radius: 9px; background: rgba(255,255,255,.14); color: #f5f5f7; font: inherit; font-size: 21px; font-weight: 500; line-height: 1;
  display: flex; align-items: center; justify-content: center; padding: 0; margin: 0; box-shadow: 0 1px 0 rgba(0,0,0,.35); transition: background .08s; cursor: pointer; }
#osk .osk-key:active { background: rgba(255,255,255,.34); }
#osk .osk-key.osk-fn { flex: 1.5 1 0; max-width: 130px; background: rgba(255,255,255,.08); font-size: 16px; }
#osk .osk-key.osk-fn.on { background: #f5f5f7; color: #000; }
#osk .osk-key.osk-fn.caps::after { content: ""; width: 5px; height: 5px; border-radius: 50%; background: #000; margin-left: 6px; }
#osk .osk-key.osk-space { flex: 5 1 0; max-width: 420px; background: rgba(255,255,255,.14); }
#osk .osk-key[data-k="↵"] { background: #0a84ff; color: #fff; }
@media (orientation: landscape) and (max-height: 600px) { #osk .osk-key { height: 42px; font-size: 20px; } #osk .osk-row { gap: 5px; margin-bottom: 5px; } #osk { padding: 6px 10px; } }`;
  if (!HDS && !document.getElementById("osk-style")) { const st = document.createElement("style"); st.id = "osk-style"; st.textContent = CSS; (document.head || document.documentElement).appendChild(st); }
  const ROWS = {
    abc: [["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"], ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
          ["⇧", "z", "x", "c", "v", "b", "n", "m", "⌫"], ["123", ",", "space", ".", "↵"]],
    num: [["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"], ["-", "/", ":", ";", "(", ")", "$", "&", "@", "\""],
          ["#+=", ".", ",", "?", "!", "'", "⌫"], ["abc", "space", "↵"]],
    sym: [["[", "]", "{", "}", "#", "%", "^", "*", "+", "="], ["_", "\\", "|", "~", "<", ">", "€", "£", "¥", "•"],
          ["123", ".", ",", "?", "!", "'", "⌫"], ["abc", "space", "↵"]],
  };
  let el = null, target = null, layout = "abc", shift = false, caps = false, lastShift = 0;
  const editable = n => n && ((n.tagName === "INPUT" && /^(text|search|password|email|url|number|tel)$/.test(n.type || "text")) || n.tagName === "TEXTAREA");

  function build() {
    el = document.createElement("div"); el.id = "osk"; el.setAttribute("role", "group"); el.setAttribute("aria-label", "Keyboard");
    el.addEventListener("pointerdown", e => e.preventDefault());      // keep the field focused while tapping keys
    document.body.appendChild(el);
    render();
  }
  function render() {
    el.innerHTML = ROWS[layout].map(row => `<div class="osk-row">${row.map(k => {
      const wide = k === "space" ? "osk-space" : (k === "⇧" || k === "⌫" || k === "123" || k === "abc" || k === "#+=" || k === "↵") ? "osk-fn" : "";
      const label = k === "space" ? "" : k === "↵" ? (target && (target.type === "search" || target.dataset.enter === "search") ? "Search" : "Done") : (layout === "abc" && (shift || caps) && k.length === 1 ? k.toUpperCase() : k);
      const on = (k === "⇧" && (shift || caps)) ? " on" : "";
      return `<button class="osk-key ${wide}${on}${k === "⇧" && caps ? " caps" : ""}" data-k="${k.replace(/"/g, "&quot;")}" tabindex="-1">${label === "\"" ? "&quot;" : label}</button>`;
    }).join("")}</div>`).join("");
    el.querySelectorAll(".osk-key").forEach(b => b.addEventListener("click", () => press(b.dataset.k)));
  }
  function insert(text) {
    if (!target) return;
    // execCommand fires the beforeinput/input sequence frameworks (React on Spotify's pages) listen to
    if (document.activeElement === target && target.type !== "number") { try { if (document.execCommand("insertText", false, text)) return; } catch (e) {} }
    if (target.type === "number" || typeof target.setRangeText !== "function") target.value += text;
    else { const s = target.selectionStart ?? target.value.length, e = target.selectionEnd ?? s; target.setRangeText(text, s, e, "end"); }
    target.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function backspace() {
    if (!target) return;
    if (document.activeElement === target && target.type !== "number" && target.value) { try { if (document.execCommand("delete", false)) return; } catch (e) {} }
    if (target.type === "number" || typeof target.setRangeText !== "function") { target.value = target.value.slice(0, -1); }
    else { const s = target.selectionStart ?? target.value.length, e = target.selectionEnd ?? s; if (s === e && s > 0) target.setRangeText("", s - 1, s, "end"); else if (s !== e) target.setRangeText("", s, e, "end"); }
    target.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function press(k) {
    if (k === "⇧") { const now = Date.now(); if (now - lastShift < 350) { caps = !caps; shift = false; } else { shift = !shift; if (caps) { caps = false; shift = false; } } lastShift = now; render(); return; }
    if (k === "⌫") { backspace(); return; }
    if (k === "123") { layout = "num"; render(); return; }
    if (k === "abc") { layout = "abc"; render(); return; }
    if (k === "#+=") { layout = "sym"; render(); return; }
    if (k === "↵") {
      if (target) { const t = target; ["keydown", "keypress", "keyup"].forEach(n => t.dispatchEvent(new KeyboardEvent(n, { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }))); t.dispatchEvent(new Event("change", { bubbles: true })); }
      hide(); return;
    }
    if (k === "space") { insert(" "); return; }
    insert(layout === "abc" && (shift || caps) ? k.toUpperCase() : k);
    if (shift && !caps) { shift = false; render(); }
  }
  function show(input) {
    if (!el) build();
    const changed = target !== input; target = input;
    if (changed) { layout = input.type === "number" || input.type === "tel" ? "num" : "abc"; shift = input.type !== "password" && input.type !== "email" && input.type !== "url" && input.type !== "search" && !input.value; caps = false; }
    render();
    el.classList.add("in"); document.body.classList.add("osk-open");
    if (!HDS) document.body.style.paddingBottom = (el.offsetHeight || 220) + "px";     // foreign page: make room ourselves
    setTimeout(() => { try { input.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (e) {} }, 60);
  }
  function hide() {
    if (!el) return;
    el.classList.remove("in"); document.body.classList.remove("osk-open");
    if (!HDS) document.body.style.paddingBottom = "";
    if (target) { const t = target; target = null; if (document.activeElement === t) t.blur(); }
  }
  document.addEventListener("focusin", e => { if (editable(e.target)) show(e.target); });
  document.addEventListener("focusout", e => { if (editable(e.target) && !(e.relatedTarget && editable(e.relatedTarget))) setTimeout(() => { if (!editable(document.activeElement)) hide(); }, 80); });
  document.addEventListener("pointerdown", e => { if (el && el.classList.contains("in") && !el.contains(e.target) && !editable(e.target)) hide(); }, true);
  if (HDS) HDS.keyboard = { show, hide };
  window.__hdKeyboard = { show, hide };
  if (editable(document.activeElement)) show(document.activeElement);       // field already focused when injected
})();
