"""Transit: next departures from the Muni stops and BART stations the owner picks.

BART comes from the legacy BART API (public key, no signup). Muni real-time comes from 511.org's StopMonitoring
feed, which needs a free API key (https://511.org/open-data/token); until a key is set the Muni side shows how to
get one. Walking time from home (general.location) turns "arrives in 9 min" into "leave in 5 min".
"""
import json, math, re, threading, time, urllib.parse, urllib.request

NAME = "transit"
DEFAULTS = {
    "stops": [],                 # [{"kind": "bart"|"muni", "id": "16TH"|"15696", "name": "...", "lat": .., "lon": ..}]
    "api_key_511": "",           # free key from 511.org for Muni predictions and the Muni stop list
    "walk_m_per_min": 80,        # walking pace used for "leave in N min"
    "poll_s": 45,                # background refresh
    "fast_poll_s": 20,           # while the app is open (it pokes us)
    "max_departures": 10,        # kept in state; the app shows the first few, voice picks the first catchable one
}
BART_KEY = "MW9S-E7SL-26DU-VV8V"
BART_API = "https://api.bart.gov/api/"
API_511 = "https://api.511.org/transit/"
ctx = None
_lock = threading.Lock()
_wake = threading.Event()
_fast_until = 0.0
_s = {"stops": [], "next": None, "updated_at": None, "error": None, "muni_ready": False, "bart_ok": None}
_cache = {"bart_stations": (0, []), "muni_stops": (0, []), "muni_lines": (0, {})}
UA = "HomeDeck/1.0 (transit)"


# ------------------------------------------------------------------ helpers
def _get(url, timeout=10):
    # 511 refuses requests that do not accept gzip (HTTP 406) and always answers compressed, with a BOM
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    txt = raw.decode("utf-8-sig", errors="replace")
    return json.loads(txt)


def _home():
    loc = (ctx.global_config.get("general", {}) or {}).get("location", {}) or {}
    try:
        return float(loc.get("lat")), float(loc.get("lon"))
    except (TypeError, ValueError):
        return None, None


def _dist_m(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(2 * R * math.asin(math.sqrt(a)))


def _walk_min(dist_m):
    if dist_m is None:
        return None
    pace = float(ctx.config.get("walk_m_per_min", 80) or 80)
    return max(1, int(math.ceil(dist_m / pace)))


def _key():
    return (ctx.config.get("api_key_511") or "").strip()


# ------------------------------------------------------------------ BART
def bart_stations():
    ts, lst = _cache["bart_stations"]
    if lst and time.time() - ts < 86400:
        return lst
    j = _get(BART_API + f"stn.aspx?cmd=stns&key={BART_KEY}&json=y")
    out = []
    for st in (((j.get("root") or {}).get("stations") or {}).get("station") or []):
        try:
            out.append({"kind": "bart", "id": st["abbr"], "name": st["name"], "lat": float(st["gtfs_latitude"]), "lon": float(st["gtfs_longitude"]), "city": st.get("city")})
        except (KeyError, ValueError, TypeError):
            continue
    _cache["bart_stations"] = (time.time(), out)
    return out


def _bart_departures(abbr):
    j = _get(BART_API + f"etd.aspx?cmd=etd&orig={urllib.parse.quote(abbr)}&key={BART_KEY}&json=y")
    root = j.get("root") or {}
    stations = root.get("station") or []
    deps = []
    if not stations:
        msg = ((root.get("message") or {}).get("warning")) or "no trains"
        return deps, str(msg)
    for etd in (stations[0].get("etd") or []):
        for est in (etd.get("estimate") or []):
            if str(est.get("cancelflag", "0")) == "1":
                continue
            m = est.get("minutes", "")
            mins = 0 if str(m).lower().startswith("leav") else int(m) if str(m).isdigit() else None
            if mins is None:
                continue
            deps.append({"route": etd.get("abbreviation") or "", "line": (est.get("color") or "").title(), "dest": etd.get("destination") or "",
                         "mins": mins, "cars": int(est.get("length") or 0) or None, "color": est.get("hexcolor"), "platform": est.get("platform"),
                         "direction": est.get("direction"), "delay_s": int(est.get("delay") or 0)})
    deps.sort(key=lambda d: d["mins"])
    return deps, None


# ------------------------------------------------------------------ Muni (511)
def muni_stops():
    ts, lst = _cache["muni_stops"]
    if lst and time.time() - ts < 86400:
        return lst
    key = _key()
    if not key:
        raise RuntimeError("511 API key needed")
    j = _get(API_511 + f"stops?api_key={urllib.parse.quote(key)}&operator_id=SF&format=json", 25)
    pts = (((j.get("Contents") or {}).get("dataObjects") or {}).get("ScheduledStopPoint")) or []
    out = []
    for p in pts:
        try:
            loc = p.get("Location") or {}
            out.append({"kind": "muni", "id": str(p["id"]), "name": p.get("Name") or str(p["id"]),
                        "lat": float(loc.get("Latitude")), "lon": float(loc.get("Longitude"))})
        except (KeyError, ValueError, TypeError):
            continue
    _cache["muni_stops"] = (time.time(), out)
    return out


def muni_lines():
    ts, m = _cache["muni_lines"]
    if m and time.time() - ts < 86400:
        return m
    key = _key()
    if not key:
        return {}
    try:
        j = _get(API_511 + f"lines?api_key={urllib.parse.quote(key)}&operator_id=SF&format=json", 20)
        m = {str(l.get("Id")): (l.get("Name") or "") for l in (j if isinstance(j, list) else [])}
        _cache["muni_lines"] = (time.time(), m)
    except Exception:
        m = {}
    return m


def _iso_to_epoch(s):
    """511 timestamps are UTC ISO-8601 with a trailing Z."""
    try:
        import datetime as _dt
        return _dt.datetime.strptime(s.replace("Z", "+00:00")[:25], "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except Exception:
        return None


def _muni_departures(stop_code):
    key = _key()
    if not key:
        return [], "Add a free 511.org key in the app for Muni times"
    j = _get(API_511 + f"StopMonitoring?api_key={urllib.parse.quote(key)}&agency=SF&stopCode={urllib.parse.quote(str(stop_code))}&format=json", 15)
    sd = (j.get("ServiceDelivery") or {})
    smd = sd.get("StopMonitoringDelivery") or {}
    if isinstance(smd, list):
        smd = smd[0] if smd else {}
    visits = smd.get("MonitoredStopVisit") or []
    names = muni_lines()
    now = time.time()
    deps = []
    for v in visits:
        mvj = v.get("MonitoredVehicleJourney") or {}
        call = mvj.get("MonitoredCall") or {}
        when = call.get("ExpectedDepartureTime") or call.get("ExpectedArrivalTime") or call.get("AimedDepartureTime")
        t = _iso_to_epoch(when) if when else None
        if t is None:
            continue
        mins = max(0, int((t - now) // 60))
        route = str(mvj.get("LineRef") or "")
        deps.append({"route": route, "line": (mvj.get("PublishedLineName") or names.get(route) or "").title(),
                     "dest": (mvj.get("DestinationName") or "").strip(), "mins": mins, "cars": None, "color": None,
                     "direction": mvj.get("DirectionRef"), "delay_s": 0})
    deps.sort(key=lambda d: d["mins"])
    return deps, None


# ------------------------------------------------------------------ refresh
def _refresh():
    lat, lon = _home()
    stops = ctx.config.get("stops") or []
    out, errs = [], []
    maxd = int(ctx.config.get("max_departures", 4) or 4)
    for st in stops:
        kind, sid = st.get("kind"), st.get("id")
        entry = {"kind": kind, "id": sid, "name": st.get("name") or sid, "lat": st.get("lat"), "lon": st.get("lon"), "departures": [], "error": None}
        try:
            entry["dist_m"] = _dist_m(lat, lon, st.get("lat"), st.get("lon"))
            entry["walk_min"] = _walk_min(entry["dist_m"])
            if kind == "bart":
                deps, err = _bart_departures(sid)
                _s["bart_ok"] = err is None
            else:
                deps, err = _muni_departures(sid)
            for d in deps:
                d["leave_in"] = (d["mins"] - entry["walk_min"]) if entry.get("walk_min") is not None else None
            entry["departures"] = deps[:maxd] if kind == "bart" else deps[:maxd]
            entry["error"] = err
            if err:
                errs.append(f"{entry['name']}: {err}")
        except Exception as e:
            entry["error"] = str(e)[:120]
            errs.append(f"{entry['name']}: {entry['error']}")
        out.append(entry)
    nxt = _pick_next(out)
    with _lock:
        _s.update({"stops": out, "next": nxt, "updated_at": time.time(), "error": "; ".join(errs) if errs else None,
                   "muni_ready": bool(_key())})


def _pick_next(stops):
    """The departure worth leaving for: catchable (leave_in >= 0) and soonest; else the soonest uncatchable one."""
    cands = []
    for st in stops:
        for d in st.get("departures") or []:
            li = d.get("leave_in")
            if li is None:
                li = d["mins"]
            cands.append((li, {"stop": st["name"], "kind": st["kind"], "route": d["route"], "line": d.get("line"), "dest": d["dest"], "mins": d["mins"],
                              "leave_in": li, "walk_min": st.get("walk_min"), "color": d.get("color")}))
    if not cands:
        return None
    pool = [c for c in cands if c[0] >= 0] or cands
    pool.sort(key=lambda c: (c[1]["mins"], c[0]))
    return pool[0][1]


# ------------------------------------------------------------------ public
def state():
    with _lock:
        return dict(_s)


def _fmt_dep(d, stop_name=None):
    who = f"{d['route']} {d.get('line') or ''}".strip() if d.get("kind", "") != "bart" else f"{d.get('line') or d['route']} line"
    where = f" to {d['dest']}" if d.get("dest") else ""
    when = "is leaving now" if d["mins"] <= 0 else f"is in {d['mins']} minute{'s' if d['mins'] != 1 else ''}"
    lead = f"The next {who}{where}" + (f" from {stop_name}" if stop_name else "")
    tail = ""
    if d.get("leave_in") is not None:
        tail = " Leave now." if d["leave_in"] <= 0 else f" Leave in {d['leave_in']}."
    return f"{lead} {when}.{tail}"


def intent(text):
    t = (text or "").lower().strip().rstrip(".!?")
    route_only = re.fullmatch(r"(?:when(?:'s| is) the )?next (?:the )?([0-9]{1,3}[a-z]?|[a-z])(?: line| bus| train)?", t)
    if not route_only and not re.search(r"\b(bus|train|bart|muni|transit|downtown|departure|departures)\b", t):
        return None
    if not route_only and not re.search(r"\b(next|when|how (?:do|can) i get|leave|catch|departure|coming)", t):
        return None
    st = state()
    stops = st.get("stops") or []
    if not stops:
        return "No transit stops are set up yet. Add them in the Transit app."
    want_bart = bool(re.search(r"\bbart\b|\btrain\b", t))
    want_bus = bool(re.search(r"\bbus\b|\bmuni\b", t))
    downtown = bool(re.search(r"\bdowntown\b|\bthe city\b|\bembarcadero\b|\bmontgomery\b", t))
    m = route_only or re.search(r"\bnext (?:the )?([0-9]{1,3}[a-z]?)\b(?: line| bus)?", t)
    route = m.group(1).upper() if m else None
    if want_bus and not any(s["kind"] == "muni" for s in stops):
        return "No Muni stops are set up yet. Add one in the Transit app; Muni times need a free 511 key."
    cands = []
    for s in stops:
        if want_bart and s["kind"] != "bart":
            continue
        if want_bus and s["kind"] != "muni":
            continue
        for d in s.get("departures") or []:
            if route and d["route"].upper() != route and (d.get("line") or "").upper() != route:
                continue
            if downtown and s["kind"] == "bart" and (d.get("direction") or "").lower() != "north":
                continue
            li = d.get("leave_in") if d.get("leave_in") is not None else d["mins"]
            cands.append((li, d, s))
    if not cands:
        if route:
            return f"I don't see a {route} at your stops right now."
        return "Nothing is coming soon at your stops."
    # the one worth going for: catchable (leave_in >= 0) and soonest
    pool = [c for c in cands if c[0] >= 0]
    if not pool:
        near = min((s for s in stops if any(c[2] is s for c in cands)), key=lambda s: s.get("walk_min") or 99)
        return f"Nothing you can still make is listed at {near['name']}; it's a {near.get('walk_min') or '?'} minute walk, so check again in a few minutes."
    pool.sort(key=lambda c: (c[1]["mins"], c[0]))
    li, d, s = pool[0]
    d = dict(d); d["kind"] = s["kind"]
    if s["kind"] == "bart":
        others = [c for c in pool[1:3] if c[2] is s]
        more = "; then " + ", ".join(f"{c[1]['dest']} in {c[1]['mins']}" for c in others) if others else ""
        return _fmt_dep(d, s["name"]).rstrip(".") + more + "."
    return _fmt_dep(d, s["name"])


def api(action, params):
    global _fast_until
    if action in ("status", "refresh"):
        if action == "refresh":
            _wake.set()
        return {"ok": True, **state()}
    if action == "poke":                                     # the app is open: refresh faster for a while
        _fast_until = time.time() + 180
        _wake.set()
        return {"ok": True}
    if action == "bart_stations":
        try:
            lat, lon = _home()
            lst = [dict(s, dist_m=_dist_m(lat, lon, s["lat"], s["lon"])) for s in bart_stations()]
            lst.sort(key=lambda s: (s["dist_m"] is None, s["dist_m"] or 0))
            return {"ok": True, "stations": lst}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if action == "muni_search":
        q = (params.get("q") or "").strip().lower()
        try:
            lat, lon = _home()
            lst = muni_stops()
            if q:
                words = q.split()
                lst = [s for s in lst if all(w in s["name"].lower() for w in words)]
            lst = [dict(s, dist_m=_dist_m(lat, lon, s["lat"], s["lon"])) for s in lst]
            lst.sort(key=lambda s: (s["dist_m"] is None, s["dist_m"] or 0))
            return {"ok": True, "stops": lst[:40]}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if action == "add_stop":
        st = {k: params.get(k) for k in ("kind", "id", "name", "lat", "lon")}
        if st["kind"] not in ("bart", "muni") or not st["id"]:
            return {"ok": False, "error": "kind and id required"}
        st["id"] = str(st["id"])
        stops = [s for s in (ctx.config.get("stops") or []) if not (s.get("kind") == st["kind"] and str(s.get("id")) == st["id"])]
        stops.append(st)
        ctx.config["stops"] = stops
        ctx.save_config()
        _wake.set()
        return {"ok": True, "stops": stops}
    if action == "remove_stop":
        kind, sid = params.get("kind"), str(params.get("id") or "")
        ctx.config["stops"] = [s for s in (ctx.config.get("stops") or []) if not (s.get("kind") == kind and str(s.get("id")) == sid)]
        ctx.save_config()
        _wake.set()
        return {"ok": True, "stops": ctx.config["stops"]}
    if action == "set_key":
        ctx.config["api_key_511"] = str(params.get("api_key_511") or "").strip()
        ctx.save_config()
        _cache["muni_stops"] = (0, []); _cache["muni_lines"] = (0, {})
        _wake.set()
        return {"ok": True, "set": bool(ctx.config["api_key_511"])}
    return {"ok": False, "error": f"unknown action {action}"}


def start(c):
    global ctx
    ctx = c
    while True:
        try:
            _refresh()
        except Exception as e:
            with _lock:
                _s["error"] = str(e)[:160]
            ctx.log(f"refresh failed: {e}")
        fast = time.time() < _fast_until
        _wake.wait(float(ctx.config.get("fast_poll_s", 20) if fast else ctx.config.get("poll_s", 45)))
        _wake.clear()
