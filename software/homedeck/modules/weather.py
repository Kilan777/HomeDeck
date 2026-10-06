"""Weather module: Open-Meteo forecast (no API key) + RainViewer radar frame list.

state() shape:
  current: {temp, apparent, humidity, wind, code, is_day, text, icon}
  hourly:  [{time, temp, rain_pct, code, icon}]         next 24 h
  daily:   [{date, hi, lo, rain_pct, code, icon, text, sunrise, sunset}]  7 days
  advice:  one-liner
  radar:   {host, frames: [{time, path}], nowcast: [...]}
  units:   "imperial" | "metric"
  fetched_at, error
"""
import json, math, os, threading, time, urllib.request, urllib.parse
from datetime import datetime

NAME = "weather"
DEFAULTS = {"refresh_s": 600, "radar_refresh_s": 300}

_state = {"current": None, "hourly": [], "daily": [], "advice": "", "radar": None,
          "units": "imperial", "fetched_at": None, "error": None}
_lock = threading.Lock()
_wake = threading.Event()

# WMO weather interpretation codes -> (text, icon key). Icon keys: the app maps them to emoji.
CODES = {
    0: ("Clear", "sun"), 1: ("Mostly clear", "sun"), 2: ("Partly cloudy", "partly"), 3: ("Overcast", "cloud"),
    45: ("Fog", "fog"), 48: ("Icy fog", "fog"),
    51: ("Light drizzle", "drizzle"), 53: ("Drizzle", "drizzle"), 55: ("Heavy drizzle", "drizzle"),
    56: ("Freezing drizzle", "sleet"), 57: ("Freezing drizzle", "sleet"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "sleet"), 67: ("Freezing rain", "sleet"),
    71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"), 77: ("Snow grains", "snow"),
    80: ("Showers", "rain"), 81: ("Showers", "rain"), 82: ("Violent showers", "rain"),
    85: ("Snow showers", "snow"), 86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm, hail", "storm"), 99: ("Thunderstorm, hail", "storm"),
}


def describe(code):
    return CODES.get(code, ("Unknown", "cloud"))


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "HomeDeck/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _fmt_hour(iso, clock_24h):
    """'2026-09-18T16:00' -> '4 PM' or '16:00'."""
    try:
        d = datetime.fromisoformat(iso)
    except Exception:
        return iso
    if clock_24h:
        return d.strftime("%H:%M")
    h = d.hour % 12 or 12
    return f"{h} {'AM' if d.hour < 12 else 'PM'}"


def _advice(current, hourly, daily, units):
    """One practical sentence built from the next 12 hours and today's extremes."""
    unit = "°F" if units == "imperial" else "°C"
    for h in hourly[:12]:
        if h["rain_pct"] is not None and h["rain_pct"] >= 50:
            return f"Rain likely around {h['label']}, bring a jacket."
    if current and current["code"] in (95, 96, 99):
        return "Thunderstorms now, stay in."
    if daily:
        hi, lo = daily[0]["hi"], daily[0]["lo"]
        hot = 85 if units == "imperial" else 29
        cold = 45 if units == "imperial" else 7
        if hi is not None and hi >= hot:
            return f"Hot today, high of {round(hi)}{unit}. Drink water."
        if lo is not None and lo <= cold:
            return f"Cold morning, low of {round(lo)}{unit}. Layer up."
        if current and current["code"] in (45, 48):
            return "Foggy out, lights on if you ride."
        if current and current["wind"] is not None and current["wind"] >= (20 if units == "imperial" else 32):
            return "Windy today, hold onto your hat."
        if hi is not None and lo is not None:
            return f"Dry day, {round(lo)} to {round(hi)}{unit}."
    return ""


def fetch_forecast():
    g = ctx.global_config["general"]
    loc, units = g["location"], g.get("units", "imperial")
    clock_24h = g.get("clock_24h", False)
    params = {
        "latitude": loc["lat"], "longitude": loc["lon"], "timezone": loc.get("timezone", "auto"),
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code,is_day",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,sunrise,sunset",
        "forecast_days": 7,
    }
    if units == "imperial":
        params.update({"temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch"})
    else:
        params.update({"wind_speed_unit": "kmh"})
    data = _get("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params))

    c = data["current"]
    text, icon = describe(c["weather_code"])
    if not c.get("is_day") and icon == "sun":
        icon = "moon"
    current = {"temp": c["temperature_2m"], "apparent": c["apparent_temperature"], "humidity": c["relative_humidity_2m"],
               "wind": c["wind_speed_10m"], "code": c["weather_code"], "is_day": bool(c.get("is_day", 1)),
               "text": text, "icon": icon}

    # hourly: from the current hour onwards, 24 entries
    hh = data["hourly"]
    now_iso = c["time"][:13]  # "YYYY-MM-DDTHH"
    start = next((i for i, t in enumerate(hh["time"]) if t[:13] >= now_iso), 0)
    # sunrise/sunset per day so night hours get the moon icon
    dd = data["daily"]
    sun = {dd["time"][i]: (dd["sunrise"][i], dd["sunset"][i]) for i in range(len(dd["time"]))}
    hourly = []
    for i in range(start, min(start + 24, len(hh["time"]))):
        t, i_ = describe(hh["weather_code"][i])
        rise_set = sun.get(hh["time"][i][:10])
        if i_ == "sun" and rise_set and not (rise_set[0] <= hh["time"][i] <= rise_set[1]):
            i_ = "moon"
        hourly.append({"time": hh["time"][i], "label": _fmt_hour(hh["time"][i], clock_24h),
                       "temp": hh["temperature_2m"][i], "rain_pct": hh["precipitation_probability"][i],
                       "code": hh["weather_code"][i], "icon": i_})

    daily = []
    for i in range(len(dd["time"])):
        t, i_ = describe(dd["weather_code"][i])
        daily.append({"date": dd["time"][i], "hi": dd["temperature_2m_max"][i], "lo": dd["temperature_2m_min"][i],
                      "rain_pct": dd["precipitation_probability_max"][i], "code": dd["weather_code"][i],
                      "icon": i_, "text": t, "sunrise": dd["sunrise"][i], "sunset": dd["sunset"][i]})

    return {"current": current, "hourly": hourly, "daily": daily,
            "advice": _advice(current, hourly, daily, units), "units": units,
            "fetched_at": time.time(), "error": None}


def fetch_radar():
    d = _get("https://api.rainviewer.com/public/weather-maps.json")
    past = [{"time": f["time"], "path": f["path"]} for f in d.get("radar", {}).get("past", [])]
    nowcast = [{"time": f["time"], "path": f["path"]} for f in d.get("radar", {}).get("nowcast", [])]
    return {"host": d.get("host", "https://tilecache.rainviewer.com"), "frames": past[-8:], "nowcast": nowcast}


def _cache_path():
    return os.path.join(ctx.data_dir, "weather_cache.json")


def _save_cache(fc):
    try:
        tmp = _cache_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(fc, f)
        os.replace(tmp, _cache_path())
    except Exception as e:
        ctx.log(f"weather cache save failed: {e}")


def _load_cache():
    """Last good forecast from disk, so a restart or a network hiccup never leaves the screen without weather."""
    try:
        with open(_cache_path()) as f:
            fc = json.load(f)
        if time.time() - float(fc.get("fetched_at") or 0) < 12 * 3600:
            with _lock:
                _state.update(fc); _state["stale"] = True
            ctx.log("weather: showing the cached forecast until the first fetch")
    except FileNotFoundError:
        pass
    except Exception as e:
        ctx.log(f"weather cache load failed: {e}")


def sun_is_up(lat, lon, when=None):
    """Local sunrise/sunset maths (NOAA approximation) for day/night when no forecast has arrived yet."""
    t = time.gmtime(when or time.time())
    n = t.tm_yday; hour = t.tm_hour + t.tm_min / 60
    g = 2 * math.pi / 365 * (n - 1 + (hour - 12) / 24)
    decl = 0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    tst = hour * 60 + eqt + 4 * lon                          # true solar time, minutes
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    cos_zen = math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)
    return cos_zen > math.cos(math.radians(90.833))


def _sun_fallback():
    """Keep current.is_day right even with a stale or missing forecast (the sky and night styling depend on it)."""
    try:
        loc = ctx.global_config["general"]["location"]
        up = sun_is_up(float(loc["lat"]), float(loc["lon"]))
    except Exception:
        return
    with _lock:
        cur = _state.get("current")
        if cur is None:
            _state["current"] = {"is_day": up, "code": None, "temp": None, "text": "", "icon": "sun" if up else "moon"}
        elif _state.get("stale") or not _state.get("fetched_at") or time.time() - float(_state.get("fetched_at") or 0) > 1800:
            cur["is_day"] = up


def start(ctx_):
    global ctx
    ctx = ctx_
    last_radar = 0
    _load_cache()
    _sun_fallback()
    retry = [15, 30, 60, 120, 300]
    fails = 0
    while True:
        try:
            fc = None
            for attempt in range(2):                          # the Open-Meteo host sometimes stalls one TLS handshake
                try:
                    fc = fetch_forecast(); break
                except Exception as e:
                    if attempt == 1:
                        raise
                    time.sleep(3)
            with _lock:
                _state.update(fc); _state["stale"] = False; _state["error"] = None
            _save_cache(fc)
            fails = 0
        except Exception as e:
            fails += 1
            ctx.log(f"forecast fetch failed ({fails}): {e}")
            with _lock:
                _state["error"] = str(e)
        _sun_fallback()
        if time.time() - last_radar > ctx.config.get("radar_refresh_s", 300):
            try:
                r = fetch_radar()
                with _lock:
                    _state["radar"] = r
                last_radar = time.time()
            except Exception as e:
                ctx.log(f"radar fetch failed: {e}")
        wait = ctx.config.get("refresh_s", 600) if fails == 0 else retry[min(fails - 1, len(retry) - 1)]
        _wake.wait(wait)
        _wake.clear()


def state():
    with _lock:
        return dict(_state)


def api(action, params):
    if action == "refresh":
        _wake.set()
        return {"ok": True}
    if action == "geocode":
        # street address -> lat/lon via OpenStreetMap Nominatim (free, needs a User-Agent, 1 req/s)
        import urllib.request, urllib.parse, json as _json
        q = str(params.get("address") or "").strip()[:200]
        if not q:
            return {"ok": False, "error": "empty address"}
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 1, "addressdetails": 1})
        req = urllib.request.Request(url, headers={"User-Agent": "HomeDeck/1.0"})
        try:
            r = _json.load(urllib.request.urlopen(req, timeout=10))
        except Exception as e:
            return {"ok": False, "error": f"lookup failed: {e}"}
        if not r:
            return {"ok": False, "error": "address not found"}
        a = r[0].get("address", {})
        return {"ok": True, "lat": float(r[0]["lat"]), "lon": float(r[0]["lon"]), "display": r[0].get("display_name"),
                "city": a.get("city") or a.get("town") or a.get("village") or "", "zip": a.get("postcode") or ""}
    return {"ok": False, "error": f"unknown action {action}"}


def on_config():
    """Location or units changed: refetch now."""
    _wake.set()
