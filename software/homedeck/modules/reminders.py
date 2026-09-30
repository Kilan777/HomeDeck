"""One-shot reminders, persisted in config, fired by a scheduler thread.

api: add {text, at (epoch seconds)}, remove {id}, list
state(): {reminders: [{id, text, at, done}], next: {...} | None}
intent(text): "remind me at 5 pm to call mom", "remind me in 20 minutes to check the oven",
              "remind me tomorrow at 8 to take out the bins", "what are my reminders", "cancel my reminders"
On fire: emit "reminder" {id, text}; voice.say, leds notify, and a phone push when nobody is home.
"""
import re, threading, time
from datetime import datetime, timedelta

NAME = "reminders"
DEFAULTS = {"reminders": [], "next_id": 1}

_lock = threading.Lock()
ctx = None


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(ctx.global_config["general"]["location"].get("timezone") or "America/Los_Angeles")
    except Exception:
        return None


def _now():
    return datetime.now(_tz())


def _items():
    r = ctx.config.get("reminders")
    if not isinstance(r, list):
        r = []
        ctx.config["reminders"] = r
    return r


def _add(text, at):
    text = str(text or "").strip()[:160]
    if not text:
        return {"ok": False, "error": "empty reminder"}
    try:
        at = float(at)
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad time"}
    if at < time.time() - 60 or at > time.time() + 366 * 86400:
        return {"ok": False, "error": "time must be in the next year"}
    with _lock:
        rid = int(ctx.config.get("next_id", 1))
        ctx.config["next_id"] = rid + 1
        _items().append({"id": rid, "text": text, "at": at, "done": False})
        ctx.save_config()
    return {"ok": True, "id": rid}


def _fmt(at):
    d = datetime.fromtimestamp(at, _tz())
    h24 = ctx.global_config["general"].get("clock_24h")
    t = d.strftime("%H:%M") if h24 else d.strftime("%-I:%M %p").lower()
    now = _now()
    if d.date() == now.date():
        return f"today at {t}"
    if d.date() == (now + timedelta(days=1)).date():
        return f"tomorrow at {t}"
    return d.strftime("%A") + f" at {t}"


# ------------------------------------------------------------------ time parsing
_REL = re.compile(r"in\s+(\d+|an?|half an?)\s+(minute|min|hour|hr|second|sec)s?", re.I)
_ABS = re.compile(r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|o'?clock)?", re.I)
_WORDS = {"a": 1, "an": 1, "half an": 0.5, "half a": 0.5}


def _parse_when(text):
    """Return (epoch, remainder_text) or (None, text). Understands 'in N minutes', 'at 5 pm', 'tomorrow at 8', 'at 17:30'."""
    t = text
    m = _REL.search(t)
    if m:
        n = _WORDS.get(m.group(1).lower(), None)
        n = float(m.group(1)) if n is None else n
        unit = m.group(2).lower()
        secs = n * (3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1)
        return time.time() + secs, (t[:m.start()] + t[m.end():]).strip()
    tomorrow = bool(re.search(r"\btomorrow\b", t, re.I))
    t2 = re.sub(r"\btomorrow\b", "", t, flags=re.I)
    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", t2, re.I) or re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b", t2, re.I)
    if not m:
        return None, text
    hh = int(m.group(1)); mm = int(m.group(2) or 0); ap = (m.group(3) or "").replace(".", "").lower()
    if hh > 23 or mm > 59:
        return None, text
    if ap == "pm" and hh < 12:
        hh += 12
    if ap == "am" and hh == 12:
        hh = 0
    now = _now()
    when = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if tomorrow:
        when += timedelta(days=1)
    elif when <= now:
        if not ap and hh < 12 and when + timedelta(hours=12) > now:
            when += timedelta(hours=12)          # "at 5" said in the afternoon means 5 pm
        else:
            when += timedelta(days=1)
    rest = (t2[:m.start()] + t2[m.end():]).strip()
    return when.timestamp(), rest


def intent(text):
    t = re.sub(r"[.!?]+$", "", (text or "").strip())
    low = t.lower()
    if not t:
        return None
    if re.search(r"\b(what|list|read|show|any)\b.*\breminders?\b", low) or re.match(r"^(my )?reminders$", low):
        with _lock:
            pend = sorted([r for r in _items() if not r.get("done")], key=lambda r: r["at"])
        if not pend:
            return "You have no reminders."
        parts = [f"{r['text']} {_fmt(r['at'])}" for r in pend[:5]]
        return ("You have one reminder: " if len(pend) == 1 else f"You have {len(pend)} reminders: ") + "; ".join(parts) + "."
    if re.search(r"\b(cancel|delete|clear|remove)\b.*\breminders?\b", low):
        with _lock:
            n = sum(1 for r in _items() if not r.get("done"))
            ctx.config["reminders"] = []
            ctx.save_config()
        return f"Cancelled {n} reminder{'s' if n != 1 else ''}." if n else "There were no reminders to cancel."
    m = re.match(r"^(?:please\s+)?(?:remind me|set a reminder|reminder)\s*(.*)$", t, re.I)
    if not m:
        return None
    body = m.group(1).strip()
    at, rest = _parse_when(body)
    if at is None:
        return "When should I remind you? Say a time like 'at 5 pm' or 'in 20 minutes'."
    rest = re.sub(r"^\s*(to|that|about)\s+", "", rest, flags=re.I).strip(" ,")
    rest = re.sub(r"\s*(to|that|about)\s*$", "", rest, flags=re.I).strip(" ,")
    if not rest:
        return "What should I remind you about?"
    r = _add(rest, at)
    if not r.get("ok"):
        return "I couldn't set that reminder."
    return f"Okay, I'll remind you to {rest} {_fmt(at)}."


# ------------------------------------------------------------------ scheduler
def _fire(r):
    ctx.log(f"reminder: {r['text']}")
    ctx.emit("reminder", {"id": r["id"], "text": r["text"]})
    leds = ctx.module("leds")
    if leds and hasattr(leds, "pattern"):
        try: leds.pattern("notify")
        except Exception as e: ctx.log(f"leds failed: {e}")
    voice = ctx.module("voice")
    if voice and hasattr(voice, "say"):
        try: voice.say(f"Reminder: {r['text']}", blocking=False)
        except TypeError:
            try: voice.say(f"Reminder: {r['text']}")
            except Exception as e: ctx.log(f"voice failed: {e}")
        except Exception as e: ctx.log(f"voice failed: {e}")
    pres, notify = ctx.module("presence"), ctx.module("notify")
    try:
        away = pres is not None and hasattr(pres, "is_home") and not pres.is_home()
    except Exception:
        away = False
    if away and notify and hasattr(notify, "send"):
        try: notify.send("Reminder", r["text"])
        except Exception as e: ctx.log(f"notify failed: {e}")


def start(c):
    global ctx
    ctx = c
    _items()
    while True:
        now = time.time()
        due = []
        with _lock:
            for r in _items():
                if not r.get("done") and now >= float(r.get("at", 0)):
                    r["done"] = True
                    due.append(dict(r))
            if due:
                # keep only the last 20 fired ones for the list view
                items = _items()
                fired = [r for r in items if r.get("done")]
                for r in fired[:-20]:
                    items.remove(r)
                ctx.save_config()
        for r in due:
            _fire(r)
        time.sleep(1)


def state():
    with _lock:
        rows = sorted([dict(r) for r in _items()], key=lambda r: r["at"])
    pend = [r for r in rows if not r.get("done")]
    return {"reminders": rows, "next": pend[0] if pend else None}


def api(action, params):
    if action == "add":
        return _add(params.get("text"), params.get("at"))
    if action == "remove":
        try:
            rid = int(params.get("id"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "id must be a number"}
        with _lock:
            items = _items()
            for r in items:
                if r["id"] == rid:
                    items.remove(r)
                    ctx.save_config()
                    return {"ok": True}
        return {"ok": False, "error": "not found"}
    if action == "list":
        return state()
    return {"ok": False, "error": f"unknown action {action}"}
