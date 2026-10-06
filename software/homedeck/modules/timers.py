"""Kitchen-style countdown timers, the way Alexa and Google do them.

api: add {seconds, label} -> {id}, cancel {id|label}, add_time {id, seconds}, pause {id}, resume {id}, list, stop
state(): {timers: [{id, label, total, remaining, ends_at, paused}], ringing: [...]}
Timers survive restarts and power cuts: they are written to <data_dir>/timers.json and restored on start; one that
ended while the device was off rings immediately with a note. On finish: emit "timer_done" {id, label}, flash the
LED strip, say "<label> timer is done" once, then ring the chosen tone (modules/ringer.py) until "stop".
Voice (intent): "set a 55 minute timer", "timer for 10 minutes", "set a laundry timer for 45 minutes",
"set a timer for an hour and a half", "how much time is left on the laundry timer", "cancel the pasta timer",
"add 5 minutes to the timer", "pause the timer", "what timers do I have".
"""
import json, os, re, threading, time

NAME = "timers"
DEFAULTS = {}

ctx = None
_timers = {}      # id -> {id, label, total, ends_at, paused_left}
_ringing = {}     # id -> {timer, started, last_said}
_next_id = 1
_lock = threading.Lock()


# ------------------------------------------------------------------ persistence
def _path():
    return os.path.join(ctx.data_dir, "timers.json")


def _save():
    try:
        with _lock:
            data = {"next_id": _next_id, "timers": list(_timers.values())}
        tmp = _path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, _path())
    except Exception as e:
        ctx.log(f"could not save timers: {e}")


def _load():
    global _next_id
    try:
        with open(_path()) as f:
            data = json.load(f)
    except FileNotFoundError:
        return
    except Exception as e:
        ctx.log(f"could not load timers: {e}")
        return
    with _lock:
        _next_id = int(data.get("next_id", 1))
        for t in data.get("timers", []):
            try:
                _timers[int(t["id"])] = {"id": int(t["id"]), "label": str(t.get("label", "")), "total": int(t["total"]),
                                          "ends_at": float(t["ends_at"]), "paused_left": t.get("paused_left")}
            except Exception:
                pass
    if _timers:
        ctx.log(f"restored {len(_timers)} timer(s)")


# ------------------------------------------------------------------ ringing (the ringer module plays the tone)
_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
          11: "eleven", 12: "twelve", 15: "fifteen", 20: "twenty", 25: "twenty five", 30: "thirty", 40: "forty", 45: "forty five", 50: "fifty", 60: "sixty", 90: "ninety"}


def _spoken_label(label):
    """'2 hours' -> 'two hour', 'laundry' -> 'laundry': read well by the voice, no odd plurals."""
    def words(m):
        n = int(m.group(1)); unit = m.group(2).rstrip("s")
        return f"{_WORDS.get(n, str(n))} {unit}"
    return re.sub(r"(\d+) (hours?|minutes?|seconds?)", words, label or "").strip()


def _finish(t, late=False):
    ctx.log(f"timer done: {t['label']}" + (" (ended while off)" if late else ""))
    ctx.emit("timer_done", {"id": t["id"], "label": t["label"], "late": late})
    with _lock:
        _ringing[t["id"]] = {"timer": t, "started": time.time()}
    r = ctx.module("ringer")
    lab = _spoken_label(t["label"])
    line = (f"Your {lab} timer went off while I was restarting." if late
            else (f"{lab} timer is done." if lab else "Your timer is done."))
    if r and hasattr(r, "ring"):
        try:
            r.ring("timer", t["label"], line if r.say_label() else None)
            return
        except Exception as e:
            ctx.log(f"ringer failed: {e}")
    voice = ctx.module("voice")                                  # no ringer: at least say it once
    if voice and hasattr(voice, "say"):
        try:
            voice.say(line)
        except Exception:
            pass


def _stop_ringing():
    with _lock:
        n = len(_ringing)
        _ringing.clear()
    r = ctx.module("ringer")
    if r and hasattr(r, "stop"):
        try:
            if r.state().get("kind") == "timer" or n:
                r.stop()
        except Exception:
            pass
    return n


# ------------------------------------------------------------------ core
def _add(secs, label):
    global _next_id
    with _lock:
        tid = _next_id
        _next_id += 1
        _timers[tid] = {"id": tid, "label": label, "total": int(secs), "ends_at": time.time() + secs, "paused_left": None}
    _save()
    return tid


def _find(ref):
    """Timer by id, by label words, or the soonest one when ref is empty."""
    with _lock:
        rows = list(_timers.values())
    if not rows:
        return None
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        return next((t for t in rows if t["id"] == int(ref)), None)
    ref = (ref or "").strip().lower()
    if ref:
        words = [w for w in re.split(r"\W+", ref) if w and w not in ("the", "my", "timer", "timers", "a", "an")]
        if words:
            hits = [t for t in rows if all(w in t["label"].lower() for w in words)]
            if hits:
                return min(hits, key=lambda t: t["ends_at"])
            hits = [t for t in rows if any(w in t["label"].lower() for w in words)]
            if hits:
                return min(hits, key=lambda t: t["ends_at"])
            return None
    return min(rows, key=lambda t: t["ends_at"])


def api(action, params):
    if action == "add":
        try:
            secs = int(float(params.get("seconds", 0)))
        except (TypeError, ValueError):
            return {"ok": False, "error": "seconds must be a number"}
        if secs <= 0 or secs > 7 * 86400:
            return {"ok": False, "error": "seconds must be between 1 and 7 days"}
        label = str(params.get("label") or "").strip()[:60] or _fmt_dur(secs)
        tid = _add(secs, label)
        return {"ok": True, "id": tid, "label": label}
    if action == "cancel":
        if _ringing and params.get("id") in [r["timer"]["id"] for r in _ringing.values()] or (not _timers and _ringing):
            _stop_ringing()
            return {"ok": True, "stopped": True}
        t = _find(params.get("id", params.get("label", "")))
        if not t:
            if _ringing:
                _stop_ringing()
                return {"ok": True, "stopped": True}
            return {"ok": False, "error": "no such timer"}
        with _lock:
            _timers.pop(t["id"], None)
        _save()
        return {"ok": True, "label": t["label"]}
    if action == "add_time":
        t = _find(params.get("id", params.get("label", "")))
        secs = int(float(params.get("seconds", 0) or 0))
        if not t or not secs:
            return {"ok": False, "error": "no such timer"}
        with _lock:
            if t.get("paused_left") is not None:
                t["paused_left"] = max(1, t["paused_left"] + secs)
            else:
                t["ends_at"] = max(time.time() + 1, t["ends_at"] + secs)
            t["total"] = max(1, t["total"] + secs)
        _save()
        return {"ok": True, "label": t["label"]}
    if action in ("pause", "resume"):
        t = _find(params.get("id", params.get("label", "")))
        if not t:
            return {"ok": False, "error": "no such timer"}
        with _lock:
            if action == "pause" and t.get("paused_left") is None:
                t["paused_left"] = max(1, int(t["ends_at"] - time.time()))
            elif action == "resume" and t.get("paused_left") is not None:
                t["ends_at"] = time.time() + t["paused_left"]; t["paused_left"] = None
        _save()
        return {"ok": True, "label": t["label"]}
    if action == "stop":
        return {"ok": True, "stopped": _stop_ringing()}
    if action == "list":
        return state()
    return {"ok": False, "error": f"unknown action {action}"}


def start(ctx_):
    global ctx
    ctx = ctx_
    _load()
    now = time.time()
    late = []
    with _lock:
        for tid, t in list(_timers.items()):
            if t.get("paused_left") is None and now >= t["ends_at"]:
                late.append(_timers.pop(tid))
    if late:
        _save()
    for t in late:
        _finish(t, late=True)
    while True:
        now = time.time()
        done = []
        with _lock:
            for tid, t in list(_timers.items()):
                if t.get("paused_left") is None and now >= t["ends_at"]:
                    done.append(_timers.pop(tid))
        if done:
            _save()
        for t in done:
            _finish(t)
        # the ringer stops itself after its limit; forget the ringing record when it has
        if _ringing:
            r = ctx.module("ringer")
            try:
                if r and not r.state().get("ringing"):
                    with _lock:
                        _ringing.clear()
            except Exception:
                pass
        time.sleep(0.5)


def state():
    now = time.time()
    with _lock:
        rows = []
        for t in _timers.values():
            left = t["paused_left"] if t.get("paused_left") is not None else max(0, int(round(t["ends_at"] - now)))
            rows.append({"id": t["id"], "label": t["label"], "total": t["total"], "remaining": left,
                         "ends_at": t["ends_at"], "paused": t.get("paused_left") is not None})
        ringing = [{"id": r["timer"]["id"], "label": r["timer"]["label"]} for r in _ringing.values()]
    rows.sort(key=lambda r: r["remaining"])
    return {"timers": rows, "ringing": ringing}


# ------------------------------------------------------------------ voice
_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
        "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90}
_UNIT = {"h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600, "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
         "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1}
# common mis-hearings of "timer" by speech-to-text
_TIMER_WORDS = r"(?:timer|timers|time her|tymer|hammer|timber|tumor|timmer|time-r|primer|climber)"


def _norm(t):
    t = t.lower().strip().rstrip(".!?")
    t = re.sub(r"\b(\w+)[- ]?(hundred)\b", r"\1 \2", t)
    t = re.sub(r"\btwenty[- ](\w+)\b", lambda m: str(20 + _NUM.get(m.group(1), 0)) if m.group(1) in _NUM and _NUM[m.group(1)] < 10 else m.group(0), t)
    t = re.sub(r"\bthirty[- ](\w+)\b", lambda m: str(30 + _NUM.get(m.group(1), 0)) if m.group(1) in _NUM and _NUM[m.group(1)] < 10 else m.group(0), t)
    t = re.sub(r"\bforty[- ](\w+)\b", lambda m: str(40 + _NUM.get(m.group(1), 0)) if m.group(1) in _NUM and _NUM[m.group(1)] < 10 else m.group(0), t)
    t = re.sub(r"\bfifty[- ](\w+)\b", lambda m: str(50 + _NUM.get(m.group(1), 0)) if m.group(1) in _NUM and _NUM[m.group(1)] < 10 else m.group(0), t)
    t = re.sub(r"\b(" + "|".join(k for k in _NUM if k not in ("a", "an")) + r")\b", lambda m: str(_NUM[m.group(1)]), t)
    t = re.sub(r"\bhalf an hour\b|\bhalf hour\b", "30 minutes", t)
    t = re.sub(r"\bquarter of an hour\b|\bquarter hour\b", "15 minutes", t)
    t = re.sub(r"\bthree quarters of an hour\b", "45 minutes", t)
    t = re.sub(r"\b(\d+)\s*(?:h|hr|hrs|hours?)\s*and\s*a\s*half\b", lambda m: f"{m.group(1)} hours 30 minutes", t)
    t = re.sub(r"\b(?:an|1|one)\s*hour\s*and\s*a\s*half\b", "1 hour 30 minutes", t)
    t = re.sub(r"\ban hour and a quarter\b", "1 hour 15 minutes", t)
    t = re.sub(r"\b(\d+)\s*(?:m|min|mins|minutes?)\s*and\s*a\s*half\b", lambda m: f"{m.group(1)} minutes 30 seconds", t)
    t = re.sub(r"\b(\d+)[:.](\d{2})\b", lambda m: f"{m.group(1)} minutes {int(m.group(2))} seconds" if int(m.group(1)) < 60 and "hour" not in t else m.group(0), t)
    t = re.sub(r"\b(\d+)h(\d+)\b", r"\1 hours \2 minutes", t)
    t = re.sub(r"\ban?\s+(hour|minute|second)\b", r"1 \1", t)
    return re.sub(r"\s+", " ", t)


def _duration(t):
    """Total seconds from every '<n> <unit>' pair in the text, or None."""
    total = 0; found = False
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", t):
        unit = m.group(2)
        if unit not in _UNIT:
            continue
        total += float(m.group(1)) * _UNIT[unit]; found = True
    return int(round(total)) if found and total > 0 else None


def _fmt_dur(secs):
    h, rem = divmod(int(secs), 3600); m, s = divmod(rem, 60)
    parts = []
    if h: parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m: parts.append(f"{m} minute{'s' if m != 1 else ''}")
    if s and not h: parts.append(f"{s} second{'s' if s != 1 else ''}")
    return " ".join(parts) or "0 seconds"


def _label_from(t, secs_text_removed):
    """'set a laundry timer for 45 minutes' -> 'laundry'; 'timer for the pasta' -> 'pasta'; 'called eggs' -> 'eggs'."""
    x = secs_text_removed
    m = re.search(r"\b(?:called|named|for the|for my)\s+([a-z][a-z '\-]{1,30}?)\s*$", x)
    if m:
        return m.group(1).strip()
    m = re.search(r"\b(?:set|start|create|make)\s+(?:a|an|the|my)?\s*([a-z][a-z '\-]{1,30}?)\s+" + _TIMER_WORDS + r"\b", x)
    if m and m.group(1).strip() not in ("new", "another", "second", "quick"):
        return m.group(1).strip()
    m = re.search(_TIMER_WORDS + r"\s+(?:for|to)\s+(?:the|my)?\s*([a-z][a-z '\-]{1,30}?)\s*$", x)
    if m and not re.search(r"\d", m.group(1)):
        return m.group(1).strip()
    return ""


def intent(text):
    raw = (text or "").strip()
    if not raw:
        return None
    t = _norm(raw)
    has_timer_word = re.search(r"\b" + _TIMER_WORDS + r"\b", t) is not None
    dur = _duration(t)

    # what timers do I have / how much time is left
    if re.search(r"\b(how much time|how long|time left|what's left|how many minutes)\b", t) and (has_timer_word or "left" in t):
        st = state()
        if not st["timers"]:
            return "No timers running."
        ref = re.sub(r".*\bon\b", "", t) if re.search(r"\bon (the |my )?\w", t) else ""
        tt = _find(ref) if ref.strip() else _find("")
        if tt is None:
            return "I don't have a timer by that name."
        left = next((r["remaining"] for r in st["timers"] if r["id"] == tt["id"]), 0)
        return f"{_fmt_dur(left)} left on the {tt['label']} timer." if tt["label"] else f"{_fmt_dur(left)} left."
    if has_timer_word and re.search(r"\b(what|which|list|any|do i have)\b", t) and dur is None:
        st = state()
        if not st["timers"]:
            return "No timers running."
        return "; ".join(f"{r['label']}, {_fmt_dur(r['remaining'])} left" for r in st["timers"][:4]) + "."

    # cancel / stop
    if has_timer_word and re.search(r"\b(cancel|delete|remove|clear|kill|forget)\b", t):
        if re.search(r"\b(all|every)\b", t):
            with _lock:
                n = len(_timers); _timers.clear()
            _save(); _stop_ringing()
            return f"Cancelled {n} timer{'s' if n != 1 else ''}." if n else "No timers running."
        ref = re.sub(r"\b(cancel|delete|remove|clear|kill|forget|please|the|my)\b|" + _TIMER_WORDS, " ", t)
        tt = _find(ref.strip()) if ref.strip() else _find("")
        if not tt:
            return "No timers running." if not _timers else "I don't have a timer by that name."
        api("cancel", {"id": tt["id"]})
        return f"{tt['label']} timer cancelled." if tt["label"] else "Timer cancelled."
    if re.search(r"\b(stop|dismiss|okay|ok|thanks|thank you|got it|shut up|quiet)\b", t) and _ringing and not dur:
        _stop_ringing()
        return ""
    if has_timer_word and re.search(r"\b(pause|hold)\b", t):
        tt = _find("")
        if not tt:
            return "No timers running."
        api("pause", {"id": tt["id"]}); return f"{tt['label']} timer paused."
    if has_timer_word and re.search(r"\b(resume|continue|unpause|restart)\b", t):
        tt = _find("")
        if not tt:
            return "No timers running."
        api("resume", {"id": tt["id"]}); return f"{tt['label']} timer running again."

    # add / take time
    if dur is not None and re.search(r"\b(add|extend|give|another|more)\b", t) and (has_timer_word or _timers):
        tt = _find(re.sub(r".*\b(to|on)\b", "", t)) if re.search(r"\b(to|on) (the |my )?\w", t) else _find("")
        if not tt:
            return "No timers running."
        api("add_time", {"id": tt["id"], "seconds": dur})
        left = next((r["remaining"] for r in state()["timers"] if r["id"] == tt["id"]), 0)
        return f"Added {_fmt_dur(dur)}. {_fmt_dur(left)} left."
    if dur is not None and re.search(r"\b(take|remove|subtract|less)\b", t) and has_timer_word:
        tt = _find("")
        if not tt:
            return "No timers running."
        api("add_time", {"id": tt["id"], "seconds": -dur})
        left = next((r["remaining"] for r in state()["timers"] if r["id"] == tt["id"]), 0)
        return f"Took off {_fmt_dur(dur)}. {_fmt_dur(left)} left."

    # set a timer: any duration plus a timer word, or "set/start ... for <duration>" without alarm/reminder words
    if dur is not None and (has_timer_word or (re.search(r"\b(set|start|count|countdown)\b", t)
                                               and not re.search(r"\b(alarm|remind|reminder|wake|volume|brightness|fan|light)\b", t))):
        if dur > 7 * 86400:
            return "That's longer than a week; use a reminder instead."
        stripped = re.sub(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", " ", t)
        stripped = re.sub(r"\b(for|and|of)\s*$", "", re.sub(r"\s+", " ", stripped)).strip()
        label = _label_from(t, stripped)
        tid = _add(dur, label or _fmt_dur(dur))
        return f"{label.capitalize()} timer set for {_fmt_dur(dur)}." if label else f"Timer set for {_fmt_dur(dur)}."
    if has_timer_word and dur is None and re.search(r"\b(set|start)\b", t):
        return "For how long?"
    return None
