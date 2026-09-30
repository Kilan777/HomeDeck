"""Personal memory for Jarvis: what to call the owner and facts the owner asked it to remember.

Everything lives in config (memory.name, memory.facts) on the device. Facts are injected into the LLM context
so answers can use them ("my bike lock code", "my wife's name", ...). Voice intents handle add/list/forget.
"""
import re, time

NAME = "memory"
DEFAULTS = {"name": "", "facts": []}   # facts: [{"text": ..., "ts": ...}]
ctx = None

def start(c):
    global ctx
    ctx = c

def state():
    return {"name": ctx.config.get("name", ""), "facts": list(ctx.config.get("facts", []))}

def context():
    """One short paragraph for the LLM system prompt."""
    name = (ctx.config.get("name") or "").strip()
    facts = [f["text"] for f in ctx.config.get("facts", [])][-30:]
    out = []
    if name:
        out.append(f"The owner wants to be called {name}; use that name naturally, not in every sentence.")
    if facts:
        out.append("Things the owner asked you to remember: " + "; ".join(facts) + ".")
    return " ".join(out)

def _save():
    ctx.save_config()

def api(action, params):
    if action == "set_name":
        ctx.config["name"] = str(params.get("name", ""))[:60].strip(); _save(); return {"ok": True}
    if action == "add":
        t = str(params.get("text", "")).strip()[:300]
        if not t: return {"ok": False, "error": "empty"}
        ctx.config.setdefault("facts", []).append({"text": t, "ts": time.time()}); _save(); return {"ok": True}
    if action == "remove":
        i = int(params.get("index", -1)); facts = ctx.config.get("facts", [])
        if 0 <= i < len(facts): facts.pop(i); _save(); return {"ok": True}
        return {"ok": False, "error": "no such fact"}
    if action == "clear":
        ctx.config["facts"] = []; _save(); return {"ok": True}
    return {"ok": False, "error": "unknown action"}

def intent(text):
    t = (text or "").strip()
    tl = t.lower()
    m = re.search(r"\b(?:call me|my name is|i am called|you can call me)\s+([a-z][a-z' -]{0,40}?)(?:\s+(?:from now on|now|please|okay))?[.!]?$", tl)
    if m:
        name = m.group(1).strip().title()
        api("set_name", {"name": name}); return f"Got it, {name}."
    if re.search(r"\b(what'?s my name|who am i|what do you call me)\b", tl):
        n = ctx.config.get("name"); return f"You're {n}." if n else "You haven't told me your name yet. Say 'call me' and your name."
    m = re.search(r"\b(?:remember|note|keep in mind)\s+(?:that\s+)?(.+)$", t, re.I)
    if m and not re.search(r"\bremind me\b", tl):
        fact = m.group(1).strip().rstrip(".")
        api("add", {"text": fact}); return "Okay, I'll remember that."
    if re.search(r"\b(what do you remember|what have i told you|what do you know about me)\b", tl):
        facts = [f["text"] for f in ctx.config.get("facts", [])]
        if not facts: return "Nothing yet. Say 'remember that' and something."
        return "You told me: " + "; ".join(facts[-6:]) + ("." if len(facts) <= 6 else f", and {len(facts) - 6} more.")
    m = re.search(r"\bforget\s+(?:that\s+|about\s+)?(.+)$", tl)
    if m:
        key = m.group(1).strip().rstrip(".")
        if key in ("everything", "it all", "all of it"):
            api("clear", {}); return "Forgotten."
        facts = ctx.config.get("facts", [])
        for i, f in enumerate(facts):
            if key in f["text"].lower():
                facts.pop(i); _save(); return "Forgotten."
        return "I don't have that stored."
    return None
