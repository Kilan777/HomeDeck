"""Bay Wheels (Lyft) bike availability from the public GBFS 2.3 feed.

Config: stations (list of station_id strings the user picked, primary first; empty = 3 nearest),
        radius_m, low_threshold (e-bikes), notify_low, refresh_s.
state():
  stations      usable chosen stations, in the user's order (primary first) [{id, name, dist_m, bikes (classic),
                ebikes, total, docks, lat, lon, usable, reason}]
  out           chosen stations that are out of service (same shape, usable False, reason text)
  free_ebikes   closest available e-bikes near home, docked at any station or free-floating, distance-sorted (<= 5)
                [{dist_m, bearing, dir, walk_min, range_m, station (name or None), near (nearest station name), lat, lon}]
  nearest_ebike the closest one of those, plus closer_than_stations (closer than every usable chosen station)
  total_ebikes  e-bikes at usable chosen stations plus free-floating e-bikes inside radius_m
  low, spoken (one or two sentences for Jarvis), fetched_at, error
Emits "bikes_low" once per morning (06:00-10:00 local) when total_ebikes < low_threshold.
"""
import json, math, threading, time, urllib.request
from datetime import datetime

NAME = "bikes"
DEFAULTS = {"stations": [], "radius_m": 500, "low_threshold": 2, "notify_low": True, "refresh_s": 30}
BASE = "https://gbfs.lyft.com/gbfs/2.3/bay/en/"
INFO_URL = BASE + "station_information.json"
STATUS_URL = BASE + "station_status.json"
FREE_URL = BASE + "free_bike_status.json"
TYPES_URL = BASE + "vehicle_types.json"

_state = {"stations": [], "out": [], "free_ebikes": [], "nearest_ebike": None, "total_ebikes": None, "low": False,
          "spoken": "", "fetched_at": None, "error": None}
_info = {}            # station_id -> {name, lat, lon}
_info_at = 0
_etypes = set()       # vehicle_type_ids that are electric
_types_at = 0
_status = {}          # station_id -> status dict
_free = []            # free-floating bikes (raw)
_lock = threading.Lock()
_wake = threading.Event()
_notified_day = None
_last_free, _last_radius = [], 500.0
ctx = None


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "HomeDeck/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _dist_m(lat1, lon1, lat2, lon2):
    """Haversine distance in metres."""
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


_DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
_DIR_WORDS = {"N": "north", "NE": "northeast", "E": "east", "SE": "southeast", "S": "south", "SW": "southwest", "W": "west", "NW": "northwest"}


def _dir(bearing):
    return _DIRS[int((bearing + 22.5) // 45) % 8]


def _metric():
    try:
        return (ctx.global_config.get("general", {}).get("units") or "imperial") == "metric"
    except Exception:
        return False


def _fmt_dist(m):
    """Spoken/printed distance in the owner's units."""
    if _metric():
        return f"{int(round(m / 10.0) * 10)} metres" if m < 950 else f"{m / 1000:.1f} kilometres"
    ft = m * 3.28084
    if ft < 950:
        return f"{int(round(ft / 50.0) * 50)} feet"
    return f"{m / 1609.34:.1f} miles"


def _short(name):
    """"15th St at Valencia St" -> "Valencia", "Dolores St at 15th St" -> "Dolores": prefer the named street over a numbered one."""
    import re as _re
    parts = [p.strip() for p in (name or "").split(" at ")]
    def strip(s):
        for suf in (" St", " Street", " Ave", " Avenue", " Blvd", " Rd", " Way", " Dr"):
            if s.endswith(suf):
                s = s[: -len(suf)]
        return s.strip()
    parts = [strip(p) for p in parts if p]
    if not parts:
        return name
    named = [p for p in parts if not _re.match(r"^\d+(st|nd|rd|th)$", p, _re.I)]
    return (named[0] if named else parts[0]) or name


# ------------------------------------------------------------------ feeds
def _load_info(force=False):
    """Station list and vehicle types change rarely: refresh once an hour."""
    global _info, _info_at, _etypes, _types_at
    now = time.time()
    if not _info or force or now - _info_at >= 3600:
        d = _get(INFO_URL)
        _info = {s["station_id"]: {"name": s["name"], "lat": s["lat"], "lon": s["lon"]} for s in d["data"]["stations"]}
        _info_at = now
    if not _etypes or force or now - _types_at >= 3600:
        try:
            d = _get(TYPES_URL)
            _etypes = {str(t["vehicle_type_id"]) for t in d["data"]["vehicle_types"]
                       if "electric" in str(t.get("propulsion_type", "")).lower()}
        except Exception:
            _etypes = {"2"}
        _types_at = now


def _load_status():
    global _status, _free
    d = _get(STATUS_URL)
    _status = {s["station_id"]: s for s in d["data"]["stations"]}
    try:
        f = _get(FREE_URL)
        _free = f["data"].get("bikes") or []
    except Exception as e:
        ctx.log(f"free bikes feed failed: {e}")
        _free = []


def _ebikes(st):
    """E-bike count at a station: Lyft's num_ebikes_available, else the electric vehicle types' counts."""
    if st.get("num_ebikes_available") is not None:
        return int(st.get("num_ebikes_available") or 0)
    n = 0
    for vt in st.get("vehicle_types_available", []) or []:
        if str(vt.get("vehicle_type_id")) in _etypes:
            n += int(vt.get("count", 0) or 0)
    return n


def _usable(st):
    """A station is usable when it is installed, renting and reporting; otherwise a reason is given."""
    if not st:
        return False, "No status"
    if not int(st.get("is_installed", 1) or 0):
        return False, "Not installed"
    if not int(st.get("is_renting", 1) or 0):
        return False, "Out of service"
    if st.get("status") not in (None, "active"):
        return False, str(st.get("status")).replace("_", " ").capitalize()
    return True, ""


def _row(sid, lat, lon):
    i = _info.get(sid)
    s = _status.get(sid)
    if not i:
        return None
    usable, reason = _usable(s)
    total = int(s.get("num_bikes_available") or 0) if s else None
    eb = _ebikes(s) if s else None
    return {"id": sid, "name": i["name"], "lat": i["lat"], "lon": i["lon"],
            "dist_m": round(_dist_m(lat, lon, i["lat"], i["lon"])),
            "total": total, "bikes": (max(0, total - eb) if total is not None and eb is not None else None),
            "ebikes": eb, "docks": (int(s.get("num_docks_available") or 0) if s else None),
            "renting": bool(int(s.get("is_renting", 1) or 0)) if s else None,
            "usable": usable, "reason": reason}


def _nearest(lat, lon, n):
    rows = [_row(sid, lat, lon) for sid in _info]
    rows = [r for r in rows if r]
    rows.sort(key=lambda r: r["dist_m"])
    return rows[:n]


def _chosen_ids():
    ids = list(ctx.config.get("stations") or [])
    if ids:
        return ids
    loc = ctx.global_config["general"]["location"]
    return [r["id"] for r in _nearest(loc["lat"], loc["lon"], 3)]


def _nearest_station_name(lat, lon, within_m=150):
    best, bd = None, within_m
    for sid, i in _info.items():
        d = _dist_m(lat, lon, i["lat"], i["lon"])
        if d < bd:
            best, bd = i["name"], d
    return best


def _free_ebikes(lat, lon, radius_m, chosen_ids):
    """Available e-bikes near home: docked at any station inside the radius, or free-floating."""
    out = []
    for b in _free:
        if "lat" not in b or "lon" not in b:
            continue
        if int(b.get("is_disabled", 0) or 0) or int(b.get("is_reserved", 0) or 0):
            continue
        vt = str(b.get("vehicle_type_id", ""))
        typ = str(b.get("type", "")).lower()
        if _etypes and vt not in _etypes and "electric" not in typ:
            continue
        d = _dist_m(lat, lon, b["lat"], b["lon"])
        if d > radius_m * 2:
            continue
        br = _bearing(lat, lon, b["lat"], b["lon"])
        out.append({"kind": "free", "dist_m": round(d), "bearing": round(br), "dir": _dir(br), "walk_min": max(1, round(d / 80)),
                    "range_m": (round(b["current_range_meters"]) if b.get("current_range_meters") else None),
                    "station": None, "near": _nearest_station_name(b["lat"], b["lon"]), "lat": b["lat"], "lon": b["lon"], "count": 1})
    for sid, i in _info.items():
        s = _status.get(sid)
        if not s or not _usable(s)[0]:
            continue
        eb = _ebikes(s)
        if eb <= 0:
            continue
        d = _dist_m(lat, lon, i["lat"], i["lon"])
        if d > radius_m * 2:
            continue
        br = _bearing(lat, lon, i["lat"], i["lon"])
        out.append({"kind": "station", "dist_m": round(d), "bearing": round(br), "dir": _dir(br), "walk_min": max(1, round(d / 80)),
                    "range_m": None, "station": i["name"], "station_id": sid, "chosen": sid in chosen_ids, "near": None,
                    "lat": i["lat"], "lon": i["lon"], "count": eb})
    out.sort(key=lambda x: x["dist_m"])
    return out


def _speak(usable, out, nearest, closer):
    """What Jarvis says for "how are the bikes"."""
    parts = []
    if usable:
        bits = []
        for r in usable[:2]:
            n = r["ebikes"] or 0
            bits.append(f"{_short(r['name'])} has {n} e-bike{'s' if n != 1 else ''}")
        parts.append(" and ".join(bits) + ".")
    if out:
        names = " and ".join(_short(r["name"]) for r in out[:2])
        parts.append(f"{names} {'is' if len(out) == 1 else 'are'} out of service.")
    if nearest and closer:
        if nearest["kind"] == "station":
            parts.append(f"There's also {nearest['count']} e-bike{'s' if nearest['count'] != 1 else ''} at {_short(nearest['station'])}, "
                         f"{_fmt_dist(nearest['dist_m'])} {_DIR_WORDS[nearest['dir']]}.")
        else:
            where = f", near {_short(nearest['near'])}" if nearest.get("near") else ""
            parts.append(f"There's also an e-bike {_fmt_dist(nearest['dist_m'])} to the {_DIR_WORDS[nearest['dir']]}{where}.")
    street = sum(1 for x in _last_free if x["kind"] == "free" and x["dist_m"] <= _last_radius)
    if street and not (nearest and closer and nearest["kind"] == "free"):
        parts.append(f"Plus {street} on the street within {_fmt_dist(_last_radius)}.")
    if not usable and not (nearest and closer) and not street:
        parts.append("No e-bikes nearby right now." if not out else "")
    return " ".join(p for p in parts if p).strip()


def refresh():
    global _notified_day
    _load_info()
    _load_status()
    loc = ctx.global_config["general"]["location"]
    radius = float(ctx.config.get("radius_m", 500) or 500)
    ids = _chosen_ids()
    rows = [_row(sid, loc["lat"], loc["lon"]) for sid in ids]
    rows = [r for r in rows if r]
    if not ctx.config.get("stations"):          # auto-picked: nearest first; user-chosen: keep their order (primary first)
        rows.sort(key=lambda r: r["dist_m"])
    for k, r in enumerate(rows):
        r["primary"] = k == 0                    # the owner's first choice, even when it is out of service
    usable = [r for r in rows if r["usable"]]
    out = [r for r in rows if not r["usable"]]
    free = _free_ebikes(loc["lat"], loc["lon"], radius, set(ids))
    global _last_free, _last_radius
    _last_free, _last_radius = free, radius
    nearest = free[0] if free else None
    best_station_d = min((r["dist_m"] for r in usable if (r["ebikes"] or 0) > 0), default=None)
    closer = bool(nearest) and (best_station_d is None or nearest["dist_m"] < best_station_d) and not (nearest["kind"] == "station" and nearest.get("chosen"))
    total = sum(r["ebikes"] or 0 for r in usable) + sum(1 for x in free if x["kind"] == "free" and x["dist_m"] <= radius)
    low = total < int(ctx.config.get("low_threshold", 2))
    spoken = _speak(usable, out, nearest, closer)
    with _lock:
        _state.update({"stations": usable, "out": out, "free_ebikes": free[:5],
                       "nearest_ebike": (dict(nearest, closer_than_stations=closer) if nearest else None),
                       "total_ebikes": total, "low": low, "spoken": spoken, "fetched_at": time.time(), "error": None})
    # morning heads-up, once per day
    now = datetime.now()
    if low and ctx.config.get("notify_low", True) and 6 <= now.hour < 10 and _notified_day != now.date():
        _notified_day = now.date()
        ctx.emit("bikes_low", {"total_ebikes": total, "stations": usable,
                               "text": f"Only {total} e-bike{'s' if total != 1 else ''} nearby right now."})


def start(ctx_):
    global ctx
    ctx = ctx_
    while True:
        try:
            refresh()
        except Exception as e:
            ctx.log(f"refresh failed: {e}")
            with _lock:
                _state["error"] = str(e)
        _wake.wait(ctx.config.get("refresh_s", 30))
        _wake.clear()


def state():
    with _lock:
        return dict(_state)


def api(action, params):
    if action == "nearby":
        _load_info()
        if not _status:
            _load_status()
        loc = ctx.global_config["general"]["location"]
        chosen = set(_chosen_ids())
        rows = _nearest(loc["lat"], loc["lon"], 15)
        for r in rows:
            r["chosen"] = r["id"] in chosen
        return {"stations": rows}
    if action == "set_stations":
        import re as _re
        ids = [str(i) for i in (params.get("ids") or []) if _re.match(r"^[A-Za-z0-9_-]{1,64}$", str(i))][:20]
        ctx.config["stations"] = ids
        ctx.save_config()
        _wake.set()
        return {"ok": True, "stations": ids}
    if action == "refresh":
        _wake.set()
        return {"ok": True}
    return {"ok": False, "error": f"unknown action {action}"}


def on_config():
    _wake.set()
