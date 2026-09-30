"""Flight radar: live aircraft around home from the adsb.lol aggregated ADS-B feed (no key), with airline and route
per callsign from adsbdb, short position trails, and a spoken "what's that plane" answer.

Polling is demand driven: 10 s while the app is open (the page calls api "poke"), 60 s for the home tile, and
nothing at all when the app is closed and the tile is hidden in Settings > Home screen.
"""
import json, math, re, threading, time, urllib.request, urllib.error

NAME = "flights"
DEFAULTS = {"radius_nm": 15, "max_radius_nm": 60, "tile_within_nm": 3, "poll_open_s": 10, "poll_idle_s": 60}
ctx = None
_lock = threading.Lock()
_s = {"aircraft": [], "count": 0, "updated_at": None, "source": None, "error": None, "radius_nm": 15, "home": None}
_trails = {}            # hex -> [(lat, lon, t), ...] newest last
_last_seen = {}         # hex -> t
_poke_until = 0.0
_wake = threading.Event()
_routes = {}            # callsign -> {"t": epoch, "data": {...} or None}
_route_queue = []
_route_lock = threading.Lock()
_backoff_until = 0.0

UA = "HomeDeck/1.0"
FEEDS = [("adsb.lol", "https://api.adsb.lol/v2/point/{lat}/{lon}/{r}"),
         ("airplanes.live", "https://api.airplanes.live/v2/point/{lat}/{lon}/{r}")]
AIRPORTS = [("SFO", "San Francisco Intl", 37.6190, -122.3750), ("OAK", "Oakland", 37.7213, -122.2208),
            ("SJC", "San Jose", 37.3639, -121.9290), ("SQL", "San Carlos", 37.5119, -122.2495),
            ("HWD", "Hayward", 37.6592, -122.1220), ("PAO", "Palo Alto", 37.4611, -122.1150),
            ("NUQ", "Moffett", 37.4161, -122.0490), ("CCR", "Concord", 37.9897, -122.0569), ("LVK", "Livermore", 37.6934, -121.8200)]
AIRLINES = {"UAL": ("United", "UA"), "DAL": ("Delta", "DL"), "AAL": ("American", "AA"), "SWA": ("Southwest", "WN"),
            "ASA": ("Alaska", "AS"), "JBU": ("JetBlue", "B6"), "SKW": ("SkyWest", "OO"), "FDX": ("FedEx", "FX"),
            "UPS": ("UPS", "5X"), "FFT": ("Frontier", "F9"), "NKS": ("Spirit", "NK"), "HAL": ("Hawaiian", "HA"),
            "QXE": ("Horizon", "QX"), "ENY": ("Envoy", "MQ"), "RPA": ("Republic", "YX"), "ACA": ("Air Canada", "AC"),
            "WJA": ("WestJet", "WS"), "BAW": ("British Airways", "BA"), "VIR": ("Virgin Atlantic", "VS"),
            "DLH": ("Lufthansa", "LH"), "AFR": ("Air France", "AF"), "KLM": ("KLM", "KL"), "UAE": ("Emirates", "EK"),
            "QTR": ("Qatar Airways", "QR"), "SIA": ("Singapore Airlines", "SQ"), "CPA": ("Cathay Pacific", "CX"),
            "JAL": ("Japan Airlines", "JL"), "ANA": ("ANA", "NH"), "KAL": ("Korean Air", "KE"), "AAR": ("Asiana", "OZ"),
            "EVA": ("EVA Air", "BR"), "CAL": ("China Airlines", "CI"), "CCA": ("Air China", "CA"), "CES": ("China Eastern", "MU"),
            "QFA": ("Qantas", "QF"), "ANZ": ("Air New Zealand", "NZ"), "AMX": ("Aeromexico", "AM"), "VOI": ("Volaris", "Y4"),
            "TAI": ("TACA", "TA"), "AVA": ("Avianca", "AV"), "CMP": ("Copa", "CM"), "SWR": ("Swiss", "LX"), "IBE": ("Iberia", "IB"),
            "THY": ("Turkish Airlines", "TK"), "ETH": ("Ethiopian", "ET"), "AIC": ("Air India", "AI"), "PAL": ("Philippine Airlines", "PR"),
            "FJI": ("Fiji Airways", "FJ"), "GTI": ("Atlas Air", "5Y"), "ABX": ("ABX Air", "GB"), "CKS": ("Kalitta", "K4"),
            "SCX": ("Sun Country", "SY"), "AAY": ("Allegiant", "G4"), "MXY": ("Breeze", "MX"), "CJT": ("Cargojet", "W8")}
TYPES = {"B738": "Boeing 737-800", "B737": "Boeing 737-700", "B739": "Boeing 737-900", "B38M": "Boeing 737 MAX 8",
         "B39M": "Boeing 737 MAX 9", "B752": "Boeing 757-200", "B763": "Boeing 767-300", "B764": "Boeing 767-400",
         "B772": "Boeing 777-200", "B77L": "Boeing 777-200LR", "B77W": "Boeing 777-300ER", "B788": "Boeing 787-8",
         "B789": "Boeing 787-9", "B78X": "Boeing 787-10", "B744": "Boeing 747-400", "B748": "Boeing 747-8",
         "A319": "Airbus A319", "A320": "Airbus A320", "A321": "Airbus A321", "A20N": "Airbus A320neo", "A21N": "Airbus A321neo",
         "A332": "Airbus A330-200", "A333": "Airbus A330-300", "A339": "Airbus A330-900", "A343": "Airbus A340-300",
         "A346": "Airbus A340-600", "A359": "Airbus A350-900", "A35K": "Airbus A350-1000", "A388": "Airbus A380",
         "E170": "Embraer 170", "E175": "Embraer 175", "E75L": "Embraer 175", "E75S": "Embraer 175", "E190": "Embraer 190",
         "E195": "Embraer 195", "CRJ2": "CRJ-200", "CRJ7": "CRJ-700", "CRJ9": "CRJ-900", "DH8D": "Dash 8 Q400",
         "AT76": "ATR 72", "C172": "Cessna 172", "C182": "Cessna 182", "C208": "Cessna Caravan", "PC12": "Pilatus PC-12",
         "SR22": "Cirrus SR22", "SR20": "Cirrus SR20", "T6": "Texan II", "P28A": "Piper Cherokee", "BE36": "Bonanza",
         "GLF6": "Gulfstream G650", "GLF5": "Gulfstream G550", "GL7T": "Global 7500", "CL35": "Challenger 350",
         "C56X": "Citation Excel", "C68A": "Citation Latitude", "E55P": "Phenom 300", "LJ35": "Learjet 35", "H60": "Black Hawk",
         "EC35": "Eurocopter EC135", "R44": "Robinson R44", "R66": "Robinson R66", "B06": "Bell 206", "AS50": "AStar"}
_COMPASS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]


def _home():
    loc = (ctx.global_config.get("general", {}) or {}).get("location", {}) if ctx else {}
    try:
        return float(loc.get("lat")), float(loc.get("lon"))
    except Exception:
        return 37.7749, -122.4194


def _haversine_nm(lat1, lon1, lat2, lon2):
    r = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _compass(deg):
    return _COMPASS[int(((deg or 0) + 22.5) // 45) % 8]


def _get_json(url, timeout=10, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": UA, "Accept": "application/json",
                                                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw.strip() else {}


# ----------------------------------------------------------------------------- routes / airlines
def _airline_from_callsign(cs):
    m = re.match(r"^([A-Z]{3})(\d{1,4}[A-Z]?)$", cs or "")
    if not m:
        return None, None, None
    name, iata = AIRLINES.get(m.group(1), (None, None))
    return name, iata, m.group(2)


def _route_worker():
    while True:
        cs = None
        with _route_lock:
            if _route_queue:
                cs = _route_queue.pop(0)
        if cs is None:
            time.sleep(1.0)
            continue
        data = None
        try:
            j = _get_json(f"https://api.adsbdb.com/v0/callsign/{cs}", timeout=10)
            fr = (j.get("response") or {}).get("flightroute") or {}
            if fr:
                o, d, al = fr.get("origin") or {}, fr.get("destination") or {}, fr.get("airline") or {}
                data = {"airline": al.get("name"), "iata": al.get("iata"), "flight_iata": fr.get("callsign_iata"),
                        "from": {"iata": o.get("iata_code"), "city": o.get("municipality"), "name": o.get("name")},
                        "to": {"iata": d.get("iata_code"), "city": d.get("municipality"), "name": d.get("name")}}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(20)
                with _route_lock:
                    _route_queue.insert(0, cs)
                continue
        except Exception:
            pass
        with _route_lock:
            _routes[cs] = {"t": time.time(), "data": data}
        time.sleep(0.6)      # polite spacing


def _route_for(cs):
    """Cached route for a callsign, queuing a lookup when unknown. Airline callsigns only (ABC123)."""
    if not re.match(r"^[A-Z]{3}\d{1,4}[A-Z]?$", cs or ""):
        return None
    with _route_lock:
        ent = _routes.get(cs)
        if ent and time.time() - ent["t"] < (86400 if ent["data"] else 6 * 3600):
            return ent["data"]
        if cs not in _route_queue and len(_route_queue) < 40:
            _route_queue.append(cs)
    return None


# ----------------------------------------------------------------------------- fetch
def _fetch(radius):
    global _backoff_until
    if time.time() < _backoff_until:
        return None, "rate limited"
    lat, lon = _home()
    err = None
    for name, tmpl in FEEDS:
        try:
            j = _get_json(tmpl.format(lat=f"{lat:.4f}", lon=f"{lon:.4f}", r=int(radius)), timeout=10)
            ac = j.get("ac") or j.get("aircraft") or []
            if isinstance(ac, list):
                return (name, ac), None
        except urllib.error.HTTPError as e:
            err = f"{name}: HTTP {e.code}"
            if e.code == 429:
                _backoff_until = time.time() + 60
        except Exception as e:
            err = f"{name}: {e}"
    return None, err or "no feed answered"


def _shape(raw, lat0, lon0):
    now = time.time()
    out = []
    for a in raw:
        try:
            alat, alon = a.get("lat"), a.get("lon")
            if alat is None or alon is None:
                continue
            hx = a.get("hex")
            cs = (a.get("flight") or "").strip().upper()
            alt = a.get("alt_baro")
            if alt == "ground":
                alt = 0
            alt = int(alt) if isinstance(alt, (int, float)) else None
            dist = a.get("dst")
            dist = float(dist) if isinstance(dist, (int, float)) else _haversine_nm(lat0, lon0, alat, alon)
            brg = a.get("dir")
            brg = float(brg) if isinstance(brg, (int, float)) else _bearing(lat0, lon0, alat, alon)
            tr = _trails.setdefault(hx, [])
            if not tr or tr[-1][0] != alat or tr[-1][1] != alon:
                tr.append((alat, alon, now))
                del tr[:-6]
            _last_seen[hx] = now
            route = _route_for(cs)
            airline, iata, num = _airline_from_callsign(cs)
            if route and route.get("airline"):
                airline = route["airline"]
            if route and route.get("iata"):
                iata = route["iata"]
            flight_label = f"{iata} {num}" if iata and num else (cs or a.get("r") or hx.upper())
            tcode = (a.get("t") or "").upper() or None
            sq = a.get("squawk")
            out.append({"hex": hx, "callsign": cs or None, "reg": a.get("r"), "type": tcode, "type_name": TYPES.get(tcode) or a.get("desc"),
                        "airline": airline, "flight": flight_label, "alt_ft": alt, "gs_kt": round(float(a["gs"])) if isinstance(a.get("gs"), (int, float)) else None,
                        "track": round(float(a["track"])) if isinstance(a.get("track"), (int, float)) else None,
                        "vrate": int(a["baro_rate"]) if isinstance(a.get("baro_rate"), (int, float)) else None,
                        "lat": alat, "lon": alon, "dist_nm": round(dist, 2), "bearing": round(brg), "compass": _compass(brg),
                        "squawk": sq, "emergency": sq in ("7500", "7600", "7700") or bool(a.get("emergency") and a.get("emergency") != "none"),
                        "category": a.get("category"), "seen": a.get("seen"),
                        "route": route, "trail": [(p[0], p[1]) for p in tr]})
        except Exception:
            continue
    out.sort(key=lambda x: x["dist_nm"])
    # forget trails of aircraft not seen for 10 minutes
    for hx in [h for h, t in _last_seen.items() if now - t > 600]:
        _trails.pop(hx, None); _last_seen.pop(hx, None)
    return out


def _refresh():
    radius = max(1, min(int(ctx.config.get("max_radius_nm", 60)), int(_s["radius_nm"])))
    res, err = _fetch(radius)
    lat0, lon0 = _home()
    with _lock:
        _s["home"] = {"lat": lat0, "lon": lon0}
        if res is None:
            _s["error"] = err
            return
        name, raw = res
        _s["aircraft"] = _shape(raw, lat0, lon0)
        _s["count"] = len(_s["aircraft"])
        _s["updated_at"] = time.time()
        _s["source"] = name
        _s["error"] = None


def _tile_hidden():
    try:
        hidden = (ctx.global_config.get("general", {}) or {}).get("home_hidden") or []
        return "flights" in hidden
    except Exception:
        return False


# ----------------------------------------------------------------------------- public
def state():
    with _lock:
        out = dict(_s)
        out["aircraft"] = list(_s["aircraft"])
    out["airports"] = [{"iata": a[0], "name": a[1], "lat": a[2], "lon": a[3]} for a in AIRPORTS]
    out["open"] = time.time() < _poke_until
    return out


def _fmt_alt(ft):
    if ft is None:
        return "unknown altitude"
    if ft <= 0:
        return "on the ground"
    return f"{int(round(ft, -2)):,} feet"


def describe(a, units="imperial"):
    """One spoken sentence about an aircraft."""
    who = a.get("airline")
    flight = a.get("flight") or a.get("callsign") or "an aircraft"
    r = a.get("route") or {}
    frm, to = (r.get("from") or {}).get("city"), (r.get("to") or {}).get("city")
    parts = []
    head = f"{who} {a['flight'].split(' ')[-1]}" if who and a.get("flight") and " " in a["flight"] else (f"{who} flight {flight}" if who else flight)
    parts.append(head)
    if frm and to:
        parts.append(f"from {frm} to {to}")
    elif to:
        parts.append(f"to {to}")
    if a.get("type_name"):
        parts.append(f"a {a['type_name']}")
    parts.append(f"at {_fmt_alt(a.get('alt_ft'))}")
    if a.get("vrate") and abs(a["vrate"]) > 300:
        parts.append("climbing" if a["vrate"] > 0 else "descending")
    if a.get("track") is not None:
        parts.append(f"heading {_compass(a['track'])}")
    d = a.get("dist_nm") or 0
    if units == "metric":
        km = d * 1.852
        parts.append(f"{km:.1f} kilometres away to the {a.get('compass')}" if km >= 1 else f"{int(km * 1000)} metres away to the {a.get('compass')}")
    else:
        mi = d * 1.15078
        parts.append(f"{mi:.1f} miles away to the {a.get('compass')}" if mi >= 0.95 else f"about {int(round(mi * 5280, -2))} feet away to the {a.get('compass')}")
    return ", ".join(parts[:2]) + (", " + ", ".join(parts[2:]) if len(parts) > 2 else "") + "."


def intent(text):
    t = (text or "").lower().strip().rstrip(".!?")
    if not re.search(r"\b(plane|planes|aircraft|jet|flight|flights|flying over|overhead|helicopter)\b", t):
        return None
    if not re.search(r"\b(what|which|where|any|how many|who|is there|whose)\b", t):
        return None
    global _poke_until
    _poke_until = max(_poke_until, time.time() + 30)
    if not _s["updated_at"] or time.time() - _s["updated_at"] > 20:
        try:
            _refresh()
        except Exception:
            pass
    units = (ctx.global_config.get("general", {}) or {}).get("units", "imperial")
    with _lock:
        ac = list(_s["aircraft"])
    if _s.get("error") and not ac:
        return "I can't reach the flight data right now."
    if not ac:
        return "Nothing is flying nearby right now."
    if re.search(r"\bhow many\b", t):
        near = [a for a in ac if a["dist_nm"] <= 4.35]
        span = f"{round(_s['radius_nm'] * 1.852)} kilometres" if units == "metric" else f"{round(_s['radius_nm'] * 1.15078)} miles"
        return f"{len(ac)} aircraft within {span}, {len(near)} of them within five." if near else f"{len(ac)} aircraft within {span}, none very close."
    # "that plane" = the closest one that is airborne; ties broken by the lowest altitude
    airborne = [a for a in ac if (a.get("alt_ft") or 0) > 0] or ac
    airborne.sort(key=lambda a: (a["dist_nm"], a.get("alt_ft") or 0))
    a = airborne[0]
    # make sure a route lookup had a chance if the callsign is an airline's
    if a.get("callsign") and not a.get("route"):
        for _ in range(6):
            r = _route_for(a["callsign"])
            if r is not None:
                a["route"] = r
                if r.get("airline"):
                    a["airline"] = r["airline"]
                break
            time.sleep(0.5)
    if re.search(r"\bwhere\b.*\bgoing\b|\bwhere is .* (headed|going)\b", t):
        r = a.get("route") or {}
        to = (r.get("to") or {}).get("city")
        return f"{(a.get('airline') + ' ' + a['flight'].split(' ')[-1]) if a.get('airline') and ' ' in a['flight'] else a['flight']} is going to {to}." if to else f"I don't have a destination for {a['flight']}."
    return describe(a, units)


def api(action, params):
    global _poke_until
    if action == "poke":
        _poke_until = time.time() + 180
        _wake.set()
        return {"ok": True}
    if action == "refresh":
        _refresh()
        return {"ok": True, "count": _s["count"], "error": _s["error"]}
    if action == "set_range":
        try:
            r = int(float(params.get("nm", 15)))
        except Exception:
            return {"ok": False, "error": "bad range"}
        r = max(1, min(int(ctx.config.get("max_radius_nm", 60)), r))
        with _lock:
            _s["radius_nm"] = r
            _s["aircraft"] = [a for a in _s["aircraft"] if a["dist_nm"] <= r]     # no stale wider set while the refetch runs
            _s["count"] = len(_s["aircraft"])
        ctx.config["radius_nm"] = r
        ctx.save_config()
        _poke_until = time.time() + 180
        _wake.set()
        return {"ok": True, "radius_nm": r}
    if action == "describe":
        hx = params.get("hex")
        with _lock:
            a = next((x for x in _s["aircraft"] if x["hex"] == hx), None)
        if not a:
            return {"ok": False, "error": "not in view"}
        units = (ctx.global_config.get("general", {}) or {}).get("units", "imperial")
        return {"ok": True, "text": describe(a, units)}
    return {"ok": False, "error": f"unknown action {action}"}


def start(c):
    global ctx
    ctx = c
    with _lock:
        _s["radius_nm"] = int(ctx.config.get("radius_nm", 15))
    threading.Thread(target=_route_worker, daemon=True, name="flights-routes").start()
    while True:
        try:
            open_now = time.time() < _poke_until
            if open_now or not _tile_hidden():
                _refresh()
            else:
                with _lock:
                    _s["aircraft"] = []; _s["count"] = 0
        except Exception as e:
            ctx.log(f"refresh failed: {e}")
        wait = ctx.config.get("poll_open_s", 10) if time.time() < _poke_until else ctx.config.get("poll_idle_s", 60)
        _wake.wait(max(3, float(wait)))
        _wake.clear()
