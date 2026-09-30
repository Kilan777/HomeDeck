/* Games: voice games mirrored on screen (trivia, riddles, quizzes, dice, coin, stories) and touch games
   (tic-tac-toe, memory, Simon). Backend: modules/games.py. Kid-sized targets, no emojis, drawn glyphs only. */
(() => {
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const CSS = `
  .gm-home { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
  .gm-tile { border: 0; border-radius: 18px; padding: 16px 14px 14px; min-height: 112px; text-align: left; color: #fff; font: inherit;
    display: flex; flex-direction: column; justify-content: space-between; gap: 8px; box-shadow: inset 0 1px 0 rgba(255,255,255,.22), inset 0 0 0 1px rgba(0,0,0,.12); cursor: pointer; transition: transform .12s; }
  .gm-tile:active { transform: scale(.96); }
  .gm-tile, .gm-tile b, .gm-tile span, .gm-tile div { color: #fff !important; }
  .gm-tile b { font-size: 17px; font-weight: 600; letter-spacing: -.01em; }
  .gm-tile span { font-size: 12.5px; opacity: .85; }
  .gm-tile svg { width: 30px; height: 30px; stroke: currentColor; fill: none; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
  .gm-stage { min-height: 300px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; text-align: center; }
  .gm-top { display: flex; align-items: center; justify-content: space-between; width: 100%; gap: 10px; }
  .gm-top h3 { margin: 0; font-size: 20px; font-weight: 650; }
  .gm-score { font-variant-numeric: tabular-nums; color: var(--fg2); font-size: 15px; }
  .gm-q { font-size: 24px; font-weight: 600; letter-spacing: -.01em; line-height: 1.25; max-width: 760px; text-wrap: balance; }
  .gm-opts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; width: 100%; max-width: 780px; }
  .gm-opt { border: 0; border-radius: 16px; padding: 16px 18px; min-height: 66px; background: rgba(255,255,255,.12); box-shadow: inset 0 0 0 1px rgba(255,255,255,.14);
    color: var(--fg); font: inherit; font-size: 18px; text-align: left; display: flex; align-items: center; gap: 14px; cursor: pointer; }
  .gm-opt i { font-style: normal; width: 34px; height: 34px; border-radius: 50%; background: var(--app-accent, var(--accent)); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; flex: none; }
  .gm-opt, .gm-opt span { color: var(--fg) !important; }
  .gm-opt.ok { background: rgba(52,199,89,.35); } .gm-opt.bad { background: rgba(255,69,58,.35); }
  .gm-ttt button, .gm-actions .btn { color: var(--fg); }
  .gm-last { font-size: 17px; color: var(--fg2); }
  .gm-last.ok { color: #34c759; } .gm-last.bad { color: #ff453a; }
  .gm-big { font-size: 92px; font-weight: 700; letter-spacing: -.04em; line-height: 1; font-variant-numeric: tabular-nums; }
  .gm-die { width: 120px; height: 120px; border-radius: 26px; background: #fff; color: #111; display: grid; grid-template-columns: repeat(3, 1fr); grid-template-rows: repeat(3, 1fr); padding: 16px; box-sizing: border-box; box-shadow: 0 14px 30px rgba(0,0,0,.4); animation: gm-roll .6s ease-out; }
  .gm-die i { width: 20px; height: 20px; border-radius: 50%; background: #111; justify-self: center; align-self: center; opacity: 0; }
  .gm-die i.on { opacity: 1; }
  .gm-dice { display: flex; gap: 20px; }
  .gm-num { width: 120px; height: 120px; border-radius: 26px; background: #fff; color: #111; display: flex; align-items: center; justify-content: center; font-size: 56px; font-weight: 700; box-shadow: 0 14px 30px rgba(0,0,0,.4); animation: gm-roll .6s ease-out; }
  @keyframes gm-roll { 0% { transform: rotate(-200deg) scale(.4); opacity: 0; } 70% { transform: rotate(15deg) scale(1.08); opacity: 1; } 100% { transform: none; } }
  .gm-coin { width: 130px; height: 130px; border-radius: 50%; background: radial-gradient(circle at 35% 30%, #ffe08a, #d69a12 70%, #9a6b05); color: #4a3200; display: flex; align-items: center; justify-content: center; font-size: 26px; font-weight: 700; letter-spacing: .04em; box-shadow: 0 14px 30px rgba(0,0,0,.4), inset 0 0 0 6px rgba(255,255,255,.25); animation: gm-flip .9s ease-out; }
  @keyframes gm-flip { 0% { transform: rotateX(0) translateY(0); } 50% { transform: rotateX(900deg) translateY(-60px); } 100% { transform: rotateX(1800deg) translateY(0); } }
  .gm-story { font-size: 22px; line-height: 1.45; max-width: 780px; text-align: left; min-height: 150px; }
  .gm-actions { display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; }
  .gm-actions .btn { min-height: 48px; padding: 0 20px; font-size: 17px; }
  /* tic-tac-toe */
  .gm-ttt { display: grid; grid-template-columns: repeat(3, 96px); gap: 8px; }
  .gm-ttt button { width: 96px; height: 96px; border: 0; border-radius: 16px; background: rgba(255,255,255,.12); color: var(--fg); font-size: 48px; font-weight: 700; font-family: inherit; }
  .gm-ttt button { font-size: 46px !important; line-height: 1 !important; padding: 0 !important; }
  .gm-ttt button.x { color: #0a84ff !important; } .gm-ttt button.o { color: #ff9f0a !important; } .gm-ttt button.win { background: rgba(52,199,89,.35); }
  .gm-ttt button:disabled { opacity: 1 !important; }
  /* memory */
  .gm-mem { display: grid; grid-template-columns: repeat(6, 88px); gap: 10px; }
  .gm-mem button { width: 88px; height: 88px; border: 0; border-radius: 16px; background: rgba(255,255,255,.14); display: flex; align-items: center; justify-content: center; padding: 0; transition: background .15s; }
  .gm-mem button svg { width: 54px; height: 54px; opacity: 0; transition: opacity .15s; }
  .gm-mem button.up svg, .gm-mem button.done svg { opacity: 1; }
  .gm-mem button.up { background: rgba(255,255,255,.3); } .gm-mem button.done { background: rgba(52,199,89,.25); }
  /* simon */
  .gm-simon { display: grid; grid-template-columns: repeat(2, 130px); gap: 12px; }
  .gm-simon button { width: 130px; height: 130px; border: 0; border-radius: 22px; opacity: .55; transition: opacity .08s, transform .08s; }
  .gm-simon button.lit { opacity: 1; transform: scale(1.04); box-shadow: 0 0 30px currentColor; }
  .gm-simon .g { background: #34c759 !important; color: #34c759; } .gm-simon .r { background: #ff453a !important; color: #ff453a; } .gm-simon .y { background: #ffd60a !important; color: #ffd60a; } .gm-simon .b { background: #0a84ff !important; color: #0a84ff; }
  .gm-mem button { background: rgba(255,255,255,.14) !important; } .gm-mem button.up { background: rgba(255,255,255,.3) !important; } .gm-mem button.done { background: rgba(52,199,89,.25) !important; }
  .gm-scores .row .v { font-variant-numeric: tabular-nums; }
  @media (orientation: landscape) and (max-height: 600px) {
    .gm-home { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
    .gm-tile { min-height: 96px; padding: 12px 12px 10px; }
    .gm-stage { min-height: 260px; }
    .gm-q { font-size: 21px; }
    .gm-opt { min-height: 56px; font-size: 16px; padding: 12px 14px; }
    .gm-ttt { grid-template-columns: repeat(3, 84px); } .gm-ttt button { width: 84px; height: 84px; font-size: 40px !important; }
    .gm-mem { grid-template-columns: repeat(6, 76px); } .gm-mem button { width: 76px; height: 76px; }
    .gm-simon { grid-template-columns: repeat(2, 112px); } .gm-simon button { width: 112px; height: 112px; }
    .gm-story { font-size: 19px; }
    #games-body { column-span: all; }
  }`;
  if (!document.getElementById("games-style")) { const st = document.createElement("style"); st.id = "games-style"; st.textContent = CSS; document.head.appendChild(st); }

  const G = {
    dice: `<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="4"/><circle cx="8" cy="8" r="1.2" fill="currentColor"/><circle cx="16" cy="8" r="1.2" fill="currentColor"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="8" cy="16" r="1.2" fill="currentColor"/><circle cx="16" cy="16" r="1.2" fill="currentColor"/></svg>`,
    coin: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v10M9.5 9.5h4a1.5 1.5 0 010 3h-3a1.5 1.5 0 000 3h4"/></svg>`,
    joke: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 14s1.5 2 4 2 4-2 4-2M9 9.5h.01M15 9.5h.01"/></svg>`,
    riddle: `<svg viewBox="0 0 24 24"><path d="M9 9a3 3 0 115.5 1.6c-1 .9-2.5 1.4-2.5 3.4"/><path d="M12 17.5h.01"/><circle cx="12" cy="12" r="9"/></svg>`,
    trivia: `<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 9h8M8 12.5h8M8 16h5"/></svg>`,
    math: `<svg viewBox="0 0 24 24"><path d="M5 6h6M8 3v6M13 5l6 6M19 5l-6 6M5 15h6M13 15h6M13 19h6"/></svg>`,
    spell: `<svg viewBox="0 0 24 24"><path d="M4 19l4-13h2l4 13M6 14h6M15 6h5M17.5 6v13"/></svg>`,
    animal: `<svg viewBox="0 0 24 24"><path d="M5 9c-1.5-3 1-6 3-4l1.5 2h5L16 5c2-2 4.5 1 3 4l-1 1.5V15a6 6 0 01-12 0v-4.5z"/><path d="M9.5 12h.01M14.5 12h.01M11 16h2"/></svg>`,
    story: `<svg viewBox="0 0 24 24"><path d="M4 5.5A2.5 2.5 0 016.5 3H20v16H6.5A2.5 2.5 0 004 21.5z"/><path d="M4 18.5A2.5 2.5 0 016.5 16H20"/></svg>`,
    wyr: `<svg viewBox="0 0 24 24"><path d="M3 6h7l2 3h9v9H3z"/><path d="M12 9v9"/></svg>`,
    eightball: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="10" r="3.2"/><path d="M11 9.2h2M12 8.2v3.6"/></svg>`,
    rps: `<svg viewBox="0 0 24 24"><path d="M7 11V7a1.5 1.5 0 013 0v4M10 10V5a1.5 1.5 0 013 0v5M13 10V6a1.5 1.5 0 013 0v6M16 11a1.5 1.5 0 013 0v4a6 6 0 01-6 6h-2a6 6 0 01-6-6v-3"/></svg>`,
    ttt: `<svg viewBox="0 0 24 24"><path d="M9 3v18M15 3v18M3 9h18M3 15h18"/></svg>`,
    memory: `<svg viewBox="0 0 24 24"><rect x="3" y="4" width="8" height="7" rx="2"/><rect x="13" y="4" width="8" height="7" rx="2"/><rect x="3" y="13" width="8" height="7" rx="2"/><rect x="13" y="13" width="8" height="7" rx="2"/></svg>`,
    simon: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 3v18M3 12h18"/></svg>`,
  };
  const TILES = [
    ["trivia", "Trivia", "5 questions", "#af52de", "trivia", "let's play trivia"],
    ["riddle", "Riddle", "Guess it", "#ff9f0a", "riddle", "tell me a riddle"],
    ["joke", "Joke", "Groan guaranteed", "#ff375f", "joke", "tell me a joke"],
    ["dice", "Dice", "Roll one", "#0a84ff", "dice", "roll a dice"],
    ["coin", "Coin", "Heads or tails", "#ffd60a", "coin", "flip a coin"],
    ["math", "Math quiz", "Add and subtract", "#34c759", "math", "math quiz"],
    ["tables", "Times tables", "2 to 12", "#30b0c7", "math", "times tables"],
    ["spell", "Spelling bee", "Letter by letter", "#5e5ce6", "spell", "spelling bee"],
    ["animal", "Animal sounds", "Moo, woof, quack", "#ff6b35", "animal", "animal sounds"],
    ["story", "Story", "Made up just now", "#a2845e", "story", "tell me a story"],
    ["wyr", "Would you rather", "Pick one", "#64d2ff", "wyr", "would you rather"],
    ["eightball", "Magic 8 ball", "Ask anything", "#1c1c1e", "eightball", "ask the 8 ball if today is lucky"],
    ["rps", "Rock paper scissors", "Best of one", "#ff453a", "rps", "rock paper scissors"],
    ["ttt", "Tic-tac-toe", "Beat Jarvis", "#0a84ff", "ttt", null],
    ["memory", "Memory", "12 cards", "#34c759", "memory", null],
    ["simon", "Simon", "Repeat the lights", "#ff9f0a", "simon", null],
  ];

  let root = null, view = "home", lastSig = "", ttt = null, mem = null, simon = null, storyPage = 0, audioCtx = null;
  const st = () => (HD.state && HD.state.games) || {};

  // ------------------------------------------------------------- home
  function home() {
    const s = st(); const scores = s.scores || {};
    const rows = Object.entries(scores).sort((a, b) => (b[1].at || 0) - (a[1].at || 0)).slice(0, 6);
    root.innerHTML = `<div class="card" id="games-body"><div class="gm-home">${TILES.map(t => `<button class="gm-tile" data-g="${t[0]}" style="background:${t[3]}">${G[t[4]]}<div><b>${t[1]}</b><br><span>${t[2]}</span></div></button>`).join("")}</div></div>
      <div class="card gm-scores"><h3>High scores</h3>${rows.length ? `<div class="rows">${rows.map(([g, v]) => `<div class="row"><span class="k">${esc(name(g))}</span><span class="v">${v.best}</span></div>`).join("")}</div>` : `<div class="hint">Play a round to set one.</div>`}</div>
      <div class="card"><h3>By voice</h3><div class="hint">Say "Jarvis, tell me a riddle", "let's play trivia", "math quiz", "spelling bee", "roll two dice", "tell me a story about a dragon". While a game waits for your answer you don't need the wake word.</div></div>`;
    root.querySelectorAll(".gm-tile").forEach(b => b.onclick = () => launch(b.dataset.g));
  }
  const name = g => ({ trivia: "Trivia", math: "Math quiz", spelling: "Spelling bee", animals: "Animal sounds", riddles: "Riddles", rps: "Rock paper scissors wins", ttt: "Tic-tac-toe wins", memory: "Memory (fewest moves)", simon: "Simon (longest run)" }[g] || g);
  async function launch(g) {
    const t = TILES.find(x => x[0] === g);
    if (g === "ttt") return tttStart();
    if (g === "memory") return memStart();
    if (g === "simon") return simonStart();
    view = "voice"; stage(`<div class="gm-stage"><div class="hint">Starting…</div></div>`);
    await HD.api("games", "start", { text: t[5], speak: true });
  }

  // ------------------------------------------------------------- voice mirror
  function stage(inner, title) {
    view = view === "home" ? "voice" : view;
    root.innerHTML = `<div class="card" id="games-body"><div class="gm-top"><button class="btn" id="gm-back">All games</button><h3>${esc(title || "")}</h3><span class="gm-score" id="gm-score"></span></div>${inner}</div>`;
    root.querySelector("#gm-back").onclick = () => { HD.api("games", "end", {}); view = "home"; ttt = mem = simon = null; home(); };
  }
  function dieHtml(n) {
    const on = { 1: [4], 2: [0, 8], 3: [0, 4, 8], 4: [0, 2, 6, 8], 5: [0, 2, 4, 6, 8], 6: [0, 2, 3, 5, 6, 8] }[n] || [];
    return `<div class="gm-die">${[...Array(9)].map((_, i) => `<i class="${on.includes(i) ? "on" : ""}"></i>`).join("")}</div>`;
  }
  function mirror(s, force) {
    if (!root || !root.isConnected) return;
    const sig = JSON.stringify([s.active, s.prompt, s.options, s.score, s.round, s.last, s.story && s.story.topic]);
    if (sig === lastSig && !force) return; lastSig = sig;
    if (view !== "voice" && view !== "home") return;              // a touch game is on screen
    const last = s.last || {};
    if (s.story && !s.active) {
      const pages = s.story.pages || [s.story.text]; storyPage = Math.min(storyPage, pages.length - 1);
      stage(`<div class="gm-stage"><div class="gm-story">${esc(pages[storyPage])}</div><div class="gm-actions"><button class="btn" id="gm-prev" ${storyPage === 0 ? "disabled" : ""}>Back</button><span class="gm-score">Page ${storyPage + 1} of ${pages.length}</span><button class="btn primary" id="gm-next" ${storyPage >= pages.length - 1 ? "disabled" : ""}>Next page</button></div></div>`, `A story about ${s.story.topic}`);
      root.querySelector("#gm-prev").onclick = () => { storyPage--; mirror(s, true); };
      root.querySelector("#gm-next").onclick = () => { storyPage++; mirror(s, true); };
      return;
    }
    if (!s.active) {
      if (last.dice) { stage(`<div class="gm-stage"><div class="gm-dice">${last.dice.map(n => last.sides === 6 ? dieHtml(n) : `<div class="gm-num">${n}</div>`).join("")}</div><div class="gm-last">${esc(last.text)}</div><div class="gm-actions"><button class="btn primary" id="gm-again">Roll again</button></div></div>`, "Dice"); root.querySelector("#gm-again").onclick = () => HD.api("games", "start", { text: last.dice.length > 1 ? "roll two dice" : (last.sides === 6 ? "roll a dice" : `roll a d${last.sides}`), speak: true }); return; }
      if (last.coin) { stage(`<div class="gm-stage"><div class="gm-coin">${esc(last.coin)}</div><div class="gm-actions"><button class="btn primary" id="gm-again">Flip again</button></div></div>`, "Coin"); root.querySelector("#gm-again").onclick = () => HD.api("games", "start", { text: "flip a coin", speak: true }); return; }
      if (last.eightball) { stage(`<div class="gm-stage"><div class="gm-big" style="font-size:40px">${esc(last.text)}</div></div>`, "Magic 8 ball"); return; }
      if (last.text && view === "voice") { stage(`<div class="gm-stage"><div class="gm-q">${esc(last.text)}</div><div class="gm-actions"><button class="btn" id="gm-home2">All games</button></div></div>`, ""); root.querySelector("#gm-home2").onclick = () => { view = "home"; home(); }; return; }
      if (view === "home") home();
      return;
    }
    storyPage = 0;
    const title = { trivia: "Trivia", riddle: "Riddle", math: "Math quiz", spell: "Spelling bee", animal: "Animal sounds", rps: "Rock paper scissors", wyr: "Would you rather" }[s.kind] || "Game";
    const opts = (s.options || []).length ? `<div class="gm-opts">${s.options.map((o, i) => `<button class="gm-opt" data-a="${esc(o)}"><i>${"ABCD"[i]}</i><span>${esc(o)}</span></button>`).join("")}</div>` : "";
    const lastLine = last.text ? `<div class="gm-last ${last.ok === true ? "ok" : last.ok === false ? "bad" : ""}">${esc(last.text)}</div>` : "";
    const actions = s.kind === "riddle" ? `<div class="gm-actions"><button class="btn" data-say="give up">Give up</button></div>`
      : s.kind === "rps" ? `<div class="gm-actions">${["rock", "paper", "scissors"].map(m => `<button class="btn primary" data-say="${m}">${m[0].toUpperCase() + m.slice(1)}</button>`).join("")}</div>`
      : (s.kind === "math" || s.kind === "spell" || s.kind === "animal") ? `<div class="gm-actions"><button class="btn" data-say="skip">Skip</button></div>` : "";
    stage(`<div class="gm-stage">${lastLine}<div class="gm-q">${esc(s.prompt)}</div>${opts}${actions}<div class="hint">Listening for your answer</div></div>`, title);
    const sc = root.querySelector("#gm-score"); if (sc) sc.textContent = s.total ? `${s.score} / ${s.round} of ${s.total}` : "";
    root.querySelectorAll(".gm-opt").forEach(b => b.onclick = () => { root.querySelectorAll(".gm-opt").forEach(x => x.disabled = true); HD.api("games", "answer", { text: b.dataset.a }); });
    root.querySelectorAll("[data-say]").forEach(b => b.onclick = () => HD.api("games", "answer", { text: b.dataset.say }));
  }

  // ------------------------------------------------------------- tic-tac-toe
  const LINES = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]];
  const winner = b => { for (const l of LINES) if (b[l[0]] && b[l[0]] === b[l[1]] && b[l[0]] === b[l[2]]) return { p: b[l[0]], line: l }; return b.every(Boolean) ? { p: "draw" } : null; };
  function minimax(b, player) {
    const w = winner(b); if (w) return { score: w.p === "O" ? 1 : w.p === "X" ? -1 : 0 };
    let best = null;
    for (let i = 0; i < 9; i++) if (!b[i]) { b[i] = player; const r = minimax(b, player === "O" ? "X" : "O"); b[i] = null;
      if (!best || (player === "O" ? r.score > best.score : r.score < best.score)) best = { score: r.score, move: i }; }
    return best;
  }
  function tttStart() { view = "ttt"; ttt = { b: Array(9).fill(null), over: null, turn: "X" }; tttDraw(); }
  function tttDraw() {
    const w = ttt.over;
    stage(`<div class="gm-stage"><div class="gm-last">${w ? (w.p === "draw" ? "It's a draw." : w.p === "X" ? "You win!" : "Jarvis wins.") : (ttt.turn === "X" ? "Your move. You are X." : "Jarvis is thinking…")}</div>
      <div class="gm-ttt">${ttt.b.map((c, i) => `<button data-i="${i}" class="${c ? c.toLowerCase() : ""} ${w && w.line && w.line.includes(i) ? "win" : ""}" ${c || w ? "disabled" : ""}>${c || ""}</button>`).join("")}</div>
      <div class="gm-actions"><button class="btn primary" id="gm-new">New game</button></div></div>`, "Tic-tac-toe");
    root.querySelector("#gm-new").onclick = tttStart;
    root.querySelectorAll(".gm-ttt button").forEach(b => b.onclick = () => {
      const i = +b.dataset.i; if (ttt.b[i] || ttt.over) return;
      ttt.b[i] = "X"; ttt.over = winner(ttt.b); ttt.turn = "O"; tttDraw();
      if (ttt.over) return finishTtt();
      setTimeout(() => { const m = minimax(ttt.b.slice(), "O"); ttt.b[m.move] = "O"; ttt.over = winner(ttt.b); ttt.turn = "X"; tttDraw(); if (ttt.over) finishTtt(); }, 350);
    });
  }
  function finishTtt() { if (ttt.over.p === "X") HD.api("games", "score", { game: "ttt", value: ((st().scores || {}).ttt || {}).best + 1 || 1 }); }

  // ------------------------------------------------------------- memory
  const SHAPES = [["#ff453a", "circle", `<circle cx="12" cy="12" r="8"/>`], ["#0a84ff", "square", `<rect x="4" y="4" width="16" height="16" rx="3"/>`], ["#34c759", "triangle", `<path d="M12 4l8 16H4z"/>`],
    ["#ffd60a", "star", `<path d="M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6-5.4-3-5.4 3 1.2-6L4.3 9.3l6.1-.7z"/>`], ["#af52de", "diamond", `<path d="M12 3l9 9-9 9-9-9z"/>`], ["#ff9f0a", "heart", `<path d="M12 20s-7-4.5-7-10a4 4 0 017-2.5A4 4 0 0119 10c0 5.5-7 10-7 10z"/>`]];
  function memStart() {
    view = "memory";
    const deck = [...SHAPES, ...SHAPES].map((s, i) => ({ id: i, key: s[1], color: s[0], path: s[2], up: false, done: false }));
    for (let i = deck.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [deck[i], deck[j]] = [deck[j], deck[i]]; }
    mem = { deck, open: [], moves: 0, lock: false }; memDraw();
  }
  function memDraw() {
    const done = mem.deck.every(c => c.done);
    stage(`<div class="gm-stage"><div class="gm-last">${done ? `All matched in ${mem.moves} moves!` : `Find the pairs · ${mem.moves} moves`}</div>
      <div class="gm-mem">${mem.deck.map((c, i) => `<button data-i="${i}" class="${c.done ? "done" : c.up ? "up" : ""}"><svg viewBox="0 0 24 24" fill="${c.color}" stroke="none">${c.path}</svg></button>`).join("")}</div>
      <div class="gm-actions"><button class="btn primary" id="gm-new">New game</button></div></div>`, "Memory");
    root.querySelector("#gm-new").onclick = memStart;
    root.querySelectorAll(".gm-mem button").forEach(b => b.onclick = () => {
      const c = mem.deck[+b.dataset.i]; if (mem.lock || c.up || c.done) return;
      c.up = true; mem.open.push(c);
      if (mem.open.length === 2) { mem.moves++; const [a, d] = mem.open;
        if (a.key === d.key) { a.done = d.done = true; mem.open = []; memDraw(); if (mem.deck.every(x => x.done)) HD.api("games", "score", { game: "memory", value: -mem.moves }); }
        else { mem.lock = true; memDraw(); setTimeout(() => { a.up = d.up = false; mem.open = []; mem.lock = false; memDraw(); }, 700); }
      } else memDraw();
    });
  }

  // ------------------------------------------------------------- simon
  const PADS = [["g", 392], ["r", 330], ["y", 262], ["b", 196]];
  function tone(hz, ms) {
    try { audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)(); const o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.frequency.value = hz; o.type = "sine"; g.gain.value = 0.0001; o.connect(g); g.connect(audioCtx.destination); o.start();
      g.gain.exponentialRampToValueAtTime(0.25, audioCtx.currentTime + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + ms / 1000); o.stop(audioCtx.currentTime + ms / 1000 + 0.05); } catch (e) {}
  }
  function simonStart() { view = "simon"; simon = { seq: [], pos: 0, playing: false, best: 0 }; simonDraw("Watch, then repeat."); setTimeout(simonNext, 600); }
  function simonDraw(msg) {
    stage(`<div class="gm-stage"><div class="gm-last">${esc(msg)}</div><div class="gm-simon">${PADS.map(p => `<button class="${p[0]}" data-p="${p[0]}"></button>`).join("")}</div><div class="gm-actions"><button class="btn primary" id="gm-new">Restart</button></div></div>`, "Simon");
    const sc = root.querySelector("#gm-score"); if (sc) sc.textContent = `Round ${simon.seq.length}`;
    root.querySelector("#gm-new").onclick = simonStart;
    root.querySelectorAll(".gm-simon button").forEach(b => b.onclick = () => simonPress(b.dataset.p));
  }
  function light(p, ms = 350) { const b = root.querySelector(`.gm-simon [data-p="${p}"]`); if (!b) return; b.classList.add("lit"); tone(PADS.find(x => x[0] === p)[1], ms); setTimeout(() => b.classList.remove("lit"), ms); }
  function simonNext() {
    simon.seq.push(PADS[Math.floor(Math.random() * 4)][0]); simon.pos = 0; simon.playing = true; simonDraw("Watch…");
    simon.seq.forEach((p, i) => setTimeout(() => light(p), 500 + i * 600));
    setTimeout(() => { simon.playing = false; simonDraw("Your turn."); }, 500 + simon.seq.length * 600);
  }
  function simonPress(p) {
    if (!simon || simon.playing) return; light(p, 220);
    if (p !== simon.seq[simon.pos]) { const n = simon.seq.length - 1; simonDraw(`Wrong. You got ${n} in a row.`); HD.api("games", "score", { game: "simon", value: n }); simon.playing = true; return; }
    simon.pos++;
    if (simon.pos >= simon.seq.length) { simon.playing = true; simonDraw("Nice!"); setTimeout(simonNext, 700); }
  }

  // ------------------------------------------------------------- app
  HD.registerApp({
    id: "games", title: "Games", icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9h12a4 4 0 014 4v2a3 3 0 01-5.2 2L15 15H9l-1.8 2A3 3 0 012 15v-2a4 4 0 014-4z"/><path d="M8 12v3M6.5 13.5h3M15.5 12.5h.01M17.5 14.5h.01"/></svg>`, order: 40, guestHidden: false,
    render(el) { root = el; view = "home"; lastSig = ""; ttt = mem = simon = null; home(); const s = st(); if (s.active) { view = "voice"; mirror(s, true); } },
    update(s) {
      if (!root || !root.isConnected) return; const g = (s && s.games) || {};
      if (view === "voice") mirror(g);
      else if (view === "home" && g.active) { view = "voice"; mirror(g, true); }
      else if (view === "home") { const sig = JSON.stringify(g.scores || {}); if (sig !== lastSig) { lastSig = sig; home(); } }
    },
    onEvent(name, data) {
      // a voice game (or a dice/coin/story result) just happened: show it, opening the app if needed
      if (name === "game_open") { view = "voice"; lastSig = ""; if (!root || !root.isConnected) HD.openApp("games"); setTimeout(() => mirror(data && data.kind ? { ...st(), ...(data.state || {}) } : st(), true), 200); }
      else if (name === "game" && root && root.isConnected && (view === "voice" || view === "home")) { if (data && (data.active || data.last || data.story)) view = "voice"; mirror(data || st(), true); }
    },
  });
})();
