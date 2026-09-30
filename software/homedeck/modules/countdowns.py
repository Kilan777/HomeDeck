"""Countdowns: "Trip to LA in 12 days", "Rent due in 3 days", birthdays.

Manual entries live in config: {id, title, date "YYYY-MM-DD", time "HH:MM" | "", repeat "none"|"yearly"|"monthly", color}.
Calendar entries (trip, flight, birthday, due, ...) within 120 days are pulled from the same iCal feeds the calendar
module uses (its parser is reused; the calendar module's own window is only a week) and marked source "calendar".
api: add {title, date, time?, repeat?, color?}, remove {id}, list
state(): {items: [{id, title, date, time, repeat, source, days, when, label}], next, refreshed_at}
intent(): "how many days until X", "when is X", "add a countdown for X on <date>", "what's coming up"
At 08:00 on the day, Jarvis says "Today: rent is due" once (not in guest mode).
"""
import re, threading, time
from datetime import datetime, date, timedelta

NAME = "countdowns"
DEFAULTS = {"items": [{"id": 1, "title": "Rent due", "date": "2026-10-01", "time": "", "repeat": "monthly", "color": "#ff9f0a"}],
            "next_id": 2, "calendar_days": 120, "announce_time": "08:00", "announce": True}
ctx = None
_lock = threading.Lock()
_cal = {"items": [], "at": 0.0}
_announced = {"day": None}
_KEYWORDS = re.compile(r"\b(trip|flight|vacation|holiday|birthday|bday|anniversary|due|deadline|concert|show|wedding|exam|"
                       r"final|move|moving|launch|graduation|festival|game day|race|marathon)\b", re.I)


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(ctx.global_config["general"]["location"].get("timezone") or "America/Los_Angeles")
    except Exception:
        return None


def _today():
    return datetime.now(_tz()).date()


def _items():
    r = ctx.config.get("items")
    if not isinstance(r, list):
        r = []
        ctx.config["items"] = r
    return r


# ------------------------------------------------------------------ dates
def _next_occurrence(d, repeat, today):
    """The next date on or after today for a repeating entry (yearly/monthly roll over)."""
    if repeat == "yearly":
        try:
            cand = d.replace(year=today.year)
        except ValueError:                       # 29 Feb
            cand = d.replace(year=today.year, day=28)
        if cand < today:
            try:
                cand = d.replace(year=today.year + 1)
            except ValueError:
                cand = d.replace(year=today.year + 1, day=28)
        return cand
    if repeat == "monthly":
        y, m = today.year, today.month
        for _ in range(14):
            last = (date(y + (m // 12), m % 12 + 1, 1) - timedelta(days=1)).day
            cand = date(y, m, min(d.day, last))
            if cand >= today:
                return cand
            m += 1
            if m > 12:
                m = 1; y += 1
        return d
    return d


def _label(days):
    if days < 0:
        return "Past"
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    if days <= 14:
        return f"{days} days"
    if days < 60:
        w = days // 7; rem = days % 7
        return f"{w} week{'s' if w != 1 else ''}" + (f" {rem} d" if rem else "")
    if days < 365:
        m = round(days / 30.44)
        return f"{m} month{'s' if m != 1 else ''}"
    return f"{days // 365} year{'s' if days // 365 != 1 else ''}"


def _spoken(days):
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days <= 21:
        return f"in {days} days"
    w = round(days / 7)
    return f"in {days} days, about {w} weeks"


def _rows():
    today = _today()
    out = []
    for it in _items():
        try:
            d = date.fromisoformat(it["date"])
        except Exception:
            continue
        nxt = _next_occurrence(d, it.get("repeat", "none"), today)
        days = (nxt - today).days
        if days < 0:
            continue                                   # one-off in the past: hidden
        out.append({"id": it["id"], "title": it["title"], "date": nxt.isoformat(), "time": it.get("time") or "",
                    "repeat": it.get("repeat", "none"), "color": it.get("color") or "", "source": "manual",
                    "days": days, "label": _label(days), "when": _when_text(nxt, it.get("time") or "")})
    titles = {r["title"].strip().lower() for r in out}
    for c in _cal["items"]:
        try:
            d = date.fromisoformat(c["date"])
        except Exception:
            continue
        days = (d - today).days
        if days < 0 or c["title"].strip().lower() in titles:
            continue
        out.append({"id": c["id"], "title": c["title"], "date": c["date"], "time": c.get("time") or "", "repeat": "none",
                    "color": "", "source": "calendar", "days": days, "label": _label(days), "when": _when_text(d, c.get("time") or "")})
    out.sort(key=lambda r: (r["days"], r["title"].lower()))
    return out


def _when_text(d, t):
    s = d.strftime("%a, %b %-d")
    if d.year != _today().year:
        s += f" {d.year}"
    if t:
        try:
            hh, mm = [int(x) for x in t.split(":")]
            ap = "pm" if hh >= 12 else "am"; h12 = hh % 12 or 12
            s += f" · {h12}:{mm:02d} {ap}" if mm else f" · {h12} {ap}"
        except Exception:
            pass
    return s


# ------------------------------------------------------------------ calendar feed (reuses the calendar module's parser)
def _refresh_calendar():
    cal = ctx.module("calendar")
    urls = [u for u in ((ctx.global_config.get("calendar") or {}).get("ics_urls") or []) if str(u).strip()]
    if not cal or not urls or not all(hasattr(cal, n) for n in ("_get", "_parse_ics", "_expand", "_as_dt")):
        _cal["items"] = []; _cal["at"] = time.time()
        return
    tz = _tz()
    now = datetime.now(tz)
    win_start = datetime.combine(now.date(), datetime.min.time(), tz)
    win_end = win_start + timedelta(days=int(ctx.config.get("calendar_days", 120)))
    found = {}
    for i, url in enumerate(urls):
        try:
            for ev in cal._parse_ics(cal._get(url), i):
                title = str(ev.get("title") or "").strip()
                if not title or not _KEYWORDS.search(title):
                    continue
                for s, e in cal._expand(ev, win_start, win_end):
                    sd = cal._as_dt(s)
                    day = sd.date().isoformat()
                    key = (title.lower(), day)
                    if key in found:
                        continue
                    tm = "" if ev.get("all_day") else sd.strftime("%H:%M")
                    found[key] = {"id": f"cal-{i}-{abs(hash(key)) % 10**8}", "title": title, "date": day, "time": tm}
        except Exception as e:
            ctx.log(f"calendar feed {i + 1}: {e}")
    _cal["items"] = sorted(found.values(), key=lambda c: c["date"])
    _cal["at"] = time.time()


# ------------------------------------------------------------------ voice
_MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                            "september", "october", "november", "december"])}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_DOW = {d: i for i, d in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}


def _parse_date(text):
    """'october 3rd', 'oct 3', '10/3', 'the 1st', 'next friday', 'friday', 'tomorrow', 'in 2 weeks', 'in 10 days'. Returns date or None."""
    t = (text or "").lower().strip()
    today = _today()
    if "tomorrow" in t:
        return today + timedelta(days=1)
    m = re.search(r"\bin\s+(\d+|a|an|one|two|three|four|five|six)\s+(day|week|month)s?\b", t)
    if m:
        w = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
        n = w.get(m.group(1), None); n = int(m.group(1)) if n is None else n
        u = m.group(2)
        if u == "day": return today + timedelta(days=n)
        if u == "week": return today + timedelta(weeks=n)
        mo = today.month + n; y = today.year + (mo - 1) // 12; mo = (mo - 1) % 12 + 1
        return date(y, mo, min(today.day, 28))
    m = re.search(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", t) or \
        re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + "|".join(_MONTHS) + r")(?:,?\s+(\d{4}))?\b", t)
    if m:
        g = m.groups()
        if g[0] in _MONTHS: mo, dd, yy = _MONTHS[g[0]], int(g[1]), g[2]
        else: dd, mo, yy = int(g[0]), _MONTHS[g[1]], g[2]
        try:
            d = date(int(yy) if yy else today.year, mo, dd)
        except ValueError:
            return None
        if not yy and d < today:
            d = date(today.year + 1, mo, dd)
        return d
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        mo, dd, yy = int(m.group(1)), int(m.group(2)), m.group(3)
        try:
            y = int(yy) if yy else today.year
            if y < 100: y += 2000
            d = date(y, mo, dd)
        except ValueError:
            return None
        if not yy and d < today:
            d = date(today.year + 1, mo, dd)
        return d
    m = re.search(r"\b(?:next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
    if m:
        target = _DOW[m.group(1)]
        ahead = (target - today.weekday()) % 7
        if ahead == 0 or "next" in t and ahead < 7 and ahead == 0:
            ahead = 7
        return today + timedelta(days=ahead)
    m = re.search(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)\b", t)
    if m:
        dd = int(m.group(1))
        for k in range(0, 3):
            mo = today.month + k; y = today.year + (mo - 1) // 12; mo = (mo - 1) % 12 + 1
            try:
                d = date(y, mo, dd)
            except ValueError:
                continue
            if d >= today:
                return d
    return None


def _find(rows, name):
    name = name.lower().strip(" ?.")
    name = re.sub(r"^(my|the|our)\s+", "", name)
    best = None
    for r in rows:
        t = r["title"].lower()
        if t == name or name in t or t in name:
            return r
        words = set(re.findall(r"[a-z0-9]+", name)) & set(re.findall(r"[a-z0-9]+", t))
        if words and (best is None or len(words) > best[0]):
            best = (len(words), r)
    return best[1] if best else None


def intent(text):
    t = re.sub(r"[.!?]+$", "", (text or "").strip())
    low = t.lower()
    if not t:
        return None
    # transit questions ("next 22", "when is the next bart") belong to the transit module
    if re.search(r"\b(bus|train|bart|muni|caltrain|line|stop|station|departure)\b", low) or re.search(r"\bnext\s+\d+\b", low):
        return None
    m = re.match(r"^(?:please\s+)?(?:add|create|set|start)\s+(?:a\s+)?countdown\s+(?:for|to|until|till)\s+(.+)$", t, re.I)
    if m:
        body = m.group(1).strip()
        d = _parse_date(body)
        if not d:
            return "When is it? Say a date like October 3rd or next Friday."
        title = re.sub(r"\b(on|for|at|in|next|the)\s+.*$", "", body, flags=re.I).strip(" ,") if not re.search(r"\b(on|next|in)\b", body, re.I) else re.split(r"\s+(?:on|next|in)\s+", body, maxsplit=1, flags=re.I)[0].strip(" ,")
        title = re.sub(r"\b(" + "|".join(_MONTHS) + r")\b.*$", "", title, flags=re.I).strip(" ,")
        title = re.sub(r"^(the|my|our|a|an)\s+", "", title, flags=re.I).strip() or "Countdown"
        r = api("add", {"title": title[:1].upper() + title[1:], "date": d.isoformat()})
        if not r.get("ok"):
            return "I couldn't add that countdown."
        days = (d - _today()).days
        return f"Okay, {title} is {_spoken(days)}."
    if re.search(r"\b(what'?s|what is|anything)\s+coming up\b|\bmy countdowns?\b|\bupcoming countdowns?\b|\bcountdowns\b", low):
        rows = _rows()[:4]
        if not rows:
            return "Nothing is counting down right now."
        return "Coming up: " + "; ".join(f"{r['title']} {_spoken(r['days'])}" for r in rows) + "."
    m = re.match(r"^(?:how (?:many|much) (?:days|time|long)\s+(?:until|till|to|before|left until)|how long until|when is|when'?s|what day is)\s+(.+)$", t, re.I)
    if m:
        rows = _rows()
        r = _find(rows, m.group(1))
        if not r:
            if re.search(r"\b(rent|trip|birthday|flight|due)\b", low):
                return "I don't have a countdown for that."
            return None
        d = date.fromisoformat(r["date"])
        return f"{r['title']} is {_spoken(r['days'])}, on {d.strftime('%A, %B %-d')}."
    return None


# ------------------------------------------------------------------ loop
def _announce_if_due():
    if not ctx.config.get("announce", True) or ctx.global_config.get("general", {}).get("guest_mode"):
        return
    now = datetime.now(_tz())
    try:
        hh, mm = [int(x) for x in str(ctx.config.get("announce_time", "08:00")).split(":")]
    except Exception:
        hh, mm = 8, 0
    if _announced["day"] == now.date().isoformat() or (now.hour, now.minute) < (hh, mm):
        return
    _announced["day"] = now.date().isoformat()
    todays = [r for r in _rows() if r["days"] == 0]
    if not todays:
        return
    text = "Today: " + " and ".join(r["title"] for r in todays) + "."
    ctx.emit("countdown_today", {"items": todays, "text": text})
    voice = ctx.module("voice")
    if voice and hasattr(voice, "say"):
        try: voice.say(text, blocking=False)
        except Exception as e: ctx.log(f"voice failed: {e}")


def start(c):
    global ctx
    ctx = c
    _items()
    last_cal = 0.0
    while True:
        try:
            if time.time() - last_cal > 3600:
                _refresh_calendar(); last_cal = time.time()
            _announce_if_due()
        except Exception as e:
            ctx.log(f"loop error: {e}")
        time.sleep(30)


def state():
    rows = _rows()
    return {"items": rows, "next": rows[0] if rows else None, "refreshed_at": _cal["at"]}


def api(action, params):
    if action == "add":
        title = str(params.get("title") or "").strip()[:80]
        try:
            d = date.fromisoformat(str(params.get("date") or "")[:10])
        except Exception:
            return {"ok": False, "error": "date must be YYYY-MM-DD"}
        if not title:
            return {"ok": False, "error": "title needed"}
        rep = params.get("repeat") or "none"
        if rep not in ("none", "yearly", "monthly"):
            rep = "none"
        tm = str(params.get("time") or "")[:5]
        if tm and not re.fullmatch(r"\d{2}:\d{2}", tm):
            tm = ""
        col = str(params.get("color") or "")[:9]
        with _lock:
            cid = int(ctx.config.get("next_id", 1)); ctx.config["next_id"] = cid + 1
            _items().append({"id": cid, "title": title, "date": d.isoformat(), "time": tm, "repeat": rep, "color": col})
            ctx.save_config()
        return {"ok": True, "id": cid}
    if action == "remove":
        cid = params.get("id")
        with _lock:
            items = _items()
            for it in items:
                if str(it["id"]) == str(cid):
                    items.remove(it); ctx.save_config()
                    return {"ok": True}
        return {"ok": False, "error": "not found"}
    if action == "list":
        return state()
    if action == "refresh":
        _refresh_calendar()
        return {"ok": True, "calendar_items": len(_cal["items"])}
    return {"ok": False, "error": f"unknown action {action}"}
