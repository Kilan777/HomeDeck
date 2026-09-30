"""Calendar module: reads private iCal (.ics) URLs, e.g. a Google Calendar "secret address".

Config: ics_urls (list of strings), refresh_s.
state(): today [...], upcoming [{date, events: [...]}] for the next 7 days, next_event, refreshed_at, error
  event = {start (iso), end (iso), title, location, all_day, calendar (index)}
Emits "event_soon" {title, start, minutes} 10 minutes before a timed event, once per occurrence.

Parser: VEVENT with DTSTART/DTEND (datetime, all-day DATE, TZID or UTC), SUMMARY, LOCATION, RRULE with
FREQ=DAILY|WEEKLY (INTERVAL, COUNT, UNTIL, BYDAY for weekly), EXDATE. Other frequencies are skipped.
"""
import threading, time, urllib.request
from datetime import datetime, date, timedelta, timezone

NAME = "calendar"
DEFAULTS = {"ics_urls": [], "refresh_s": 900, "notify_minutes": 10}

_state = {"today": [], "upcoming": [], "next_event": None, "refreshed_at": None, "error": None}
_events = []           # expanded occurrences within the window
_lock = threading.Lock()
_wake = threading.Event()
_notified = set()      # (title, start_iso)

DOW = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _get(url, timeout=20):
    if not str(url).lower().startswith(("http://", "https://")):
        raise ValueError("only http(s) calendar URLs are fetched")
    req = urllib.request.Request(url, headers={"User-Agent": "HomeDeck/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _unfold(text):
    """RFC 5545 line unfolding: a line starting with a space/tab continues the previous one."""
    out = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _tzinfo():
    """Local timezone of the device (config timezone if zoneinfo has it, else system local)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(ctx.global_config["general"]["location"].get("timezone", "UTC"))
    except Exception:
        return datetime.now().astimezone().tzinfo


def _parse_dt(value, params):
    """Return (datetime-or-date, all_day). Naive/TZID values become aware in the device timezone
    (good enough for a home display; exotic TZIDs fall back to local)."""
    local = _tzinfo()
    if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
        return date(int(value[:4]), int(value[4:6]), int(value[6:8])), True
    v = value.rstrip("Z")
    dt = datetime.strptime(v[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        dt = dt.replace(tzinfo=timezone.utc).astimezone(local)
    else:
        tzid = params.get("TZID")
        tz = local
        if tzid:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(tzid)
            except Exception:
                tz = local
        dt = dt.replace(tzinfo=tz).astimezone(local)
    return dt, False


def _parse_line(line):
    """'DTSTART;TZID=America/Los_Angeles:20260918T090000' -> ('DTSTART', {'TZID': ...}, '2026...')"""
    if ":" not in line:
        return None, {}, ""
    head, _, value = line.partition(":")
    parts = head.split(";")
    name = parts[0].upper()
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v
    return name, params, value


def _unescape(s):
    return s.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _parse_ics(text, cal_index):
    events = []
    cur = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {"calendar": cal_index, "exdates": set()}
        elif line == "END:VEVENT":
            if cur and "start" in cur:
                events.append(cur)
            cur = None
        elif cur is not None:
            name, params, value = _parse_line(line)
            try:
                if name == "DTSTART":
                    cur["start"], cur["all_day"] = _parse_dt(value, params)
                elif name == "DTEND":
                    cur["end"], _ = _parse_dt(value, params)
                elif name == "SUMMARY":
                    cur["title"] = _unescape(value)
                elif name == "LOCATION":
                    cur["location"] = _unescape(value)
                elif name == "RRULE":
                    cur["rrule"] = dict(p.split("=", 1) for p in value.split(";") if "=" in p)
                elif name == "EXDATE":
                    for v in value.split(","):
                        d, _ = _parse_dt(v.strip(), params)
                        cur["exdates"].add(d if isinstance(d, date) and not isinstance(d, datetime) else d.date())
            except Exception:
                pass  # malformed property: ignore it, keep the event
    return events


def _expand(ev, win_start, win_end):
    """Yield (start, end) occurrences of ev inside [win_start, win_end]."""
    start = ev["start"]
    end = ev.get("end")
    if end is None:
        end = start + timedelta(days=1) if ev.get("all_day") else start + timedelta(hours=1)
    dur = end - start
    rr = ev.get("rrule")
    if not rr:
        if _overlaps(start, end, win_start, win_end):
            yield start, end
        return
    freq = rr.get("FREQ", "").upper()
    if freq not in ("DAILY", "WEEKLY"):
        return  # unsupported recurrence: skip silently
    interval = max(1, int(rr.get("INTERVAL", 1)))
    count = int(rr["COUNT"]) if "COUNT" in rr else None
    until = None
    if "UNTIL" in rr:
        try:
            u, _ = _parse_dt(rr["UNTIL"], {})
            until = u if isinstance(u, datetime) else datetime.combine(u, datetime.max.time(), _tzinfo())
        except Exception:
            until = None
    bydays = [DOW[d] for d in rr.get("BYDAY", "").split(",") if d in DOW] if freq == "WEEKLY" else []
    if freq == "WEEKLY" and not bydays:
        bydays = [_as_dt(start).weekday()]
    n = 0
    cur = start
    guard = 0
    while guard < 2000:
        guard += 1
        if freq == "DAILY":
            occ = [cur]
            step = timedelta(days=interval)
        else:
            # week starting Monday of cur, one occurrence per BYDAY
            base = cur - timedelta(days=_as_dt(cur).weekday())
            occ = [base + timedelta(days=d) for d in sorted(bydays)]
            step = timedelta(weeks=interval)
        for o in occ:
            if o < start:
                continue
            if until and _as_dt(o) > until:
                return
            if count is not None and n >= count:
                return
            n += 1
            oe = o + dur
            if _as_dt(o).date() in ev.get("exdates", set()):
                continue
            if _as_dt(o) > win_end:
                return
            if _overlaps(o, oe, win_start, win_end):
                yield o, oe
        cur = cur + step


def _as_dt(x):
    return x if isinstance(x, datetime) else datetime.combine(x, datetime.min.time(), _tzinfo())


def _overlaps(s, e, ws, we):
    return _as_dt(e) > ws and _as_dt(s) <= we


def _iso(x):
    return x.isoformat()


def refresh():
    urls = [u for u in (ctx.config.get("ics_urls") or []) if u.strip()]
    tz = _tzinfo()
    now = datetime.now(tz)
    win_start = datetime.combine(now.date(), datetime.min.time(), tz)
    win_end = win_start + timedelta(days=8)
    occurrences = []
    errors = []
    for i, url in enumerate(urls):
        try:
            for ev in _parse_ics(_get(url), i):
                for s, e in _expand(ev, win_start, win_end):
                    occurrences.append({"start": _iso(s), "end": _iso(e), "sort": _as_dt(s).timestamp(),
                                        "title": ev.get("title", "(untitled)"), "location": ev.get("location", ""),
                                        "all_day": bool(ev.get("all_day")), "calendar": i})
        except Exception as e:
            errors.append(f"calendar {i + 1}: {e}")
    occurrences.sort(key=lambda o: (o["sort"], not o["all_day"]))
    today = [o for o in occurrences if o["start"][:10] == now.date().isoformat()]
    upcoming = []
    for d in range(1, 8):
        day = (now.date() + timedelta(days=d)).isoformat()
        evs = [o for o in occurrences if o["start"][:10] == day]
        if evs:
            upcoming.append({"date": day, "events": evs})
    nxt = next((o for o in occurrences if not o["all_day"] and o["sort"] > now.timestamp()), None)
    with _lock:
        _events[:] = occurrences
        _state.update({"today": today, "upcoming": upcoming, "next_event": nxt,
                       "refreshed_at": time.time(), "error": "; ".join(errors) or None,
                       "configured": bool(urls)})


def _notify_soon():
    mins = int(ctx.config.get("notify_minutes", 10))
    now = time.time()
    with _lock:
        evs = list(_events)
    for o in evs:
        if o["all_day"]:
            continue
        delta = o["sort"] - now
        key = (o["title"], o["start"])
        if 0 < delta <= mins * 60 and key not in _notified:
            _notified.add(key)
            ctx.emit("event_soon", {"title": o["title"], "start": o["start"], "location": o["location"],
                                    "minutes": int(round(delta / 60))})


def start(ctx_):
    global ctx
    ctx = ctx_
    last = 0
    while True:
        if time.time() - last >= ctx.config.get("refresh_s", 900):
            try:
                refresh()
            except Exception as e:
                ctx.log(f"refresh failed: {e}")
                with _lock:
                    _state["error"] = str(e)
            last = time.time()
        try:
            _notify_soon()
        except Exception as e:
            ctx.log(f"notify failed: {e}")
        _wake.wait(30)
        if _wake.is_set():
            _wake.clear()
            last = 0


def state():
    with _lock:
        return dict(_state)


def api(action, params):
    if action == "refresh":
        _wake.set()
        return {"ok": True}
    if action == "set_urls":
        urls = [str(u).strip() for u in (params.get("urls") or []) if isinstance(u, str) and u.strip()]
        urls = [u for u in urls if u.lower().startswith(("http://", "https://")) and len(u) <= 500][:10]
        ctx.config["ics_urls"] = urls
        ctx.save_config()
        _wake.set()
        return {"ok": True, "urls": urls}
    return {"ok": False, "error": f"unknown action {action}"}


def on_config():
    _wake.set()
