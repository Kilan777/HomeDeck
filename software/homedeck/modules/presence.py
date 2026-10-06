"""Presence: is anyone home? Pings the listed phones on the LAN; manual Home/Away override.

Emits "arrived_home" / "left_home" on transitions. Other modules call presence.is_home().
"""
import re, subprocess, threading, time

NAME = "presence"
DEFAULTS = {"mode": "auto", "phones": [], "away_after_min": 10, "poll_s": 30}

ctx = None
_lock = threading.Lock()
_s = {"home": True, "mode": "auto", "last_seen": {}, "since": time.time(), "auto_home": True}


def _mac_to_ip(mac):
    """Look the MAC up in the neighbour table (phone must have talked to the router/us recently)."""
    try:
        out = subprocess.run(["ip", "neigh"], capture_output=True, text=True, timeout=3).stdout
        for line in out.splitlines():
            if mac.lower() in line.lower():
                return line.split()[0]
    except Exception:
        pass
    return None


def _ping(ip):
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "2", ip], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _probe():
    now = time.time()
    for p in ctx.config.get("phones", []):
        name = p.get("name") or p.get("ip") or p.get("mac") or "?"
        ip = p.get("ip")
        if not ip and p.get("mac"):
            ip = _mac_to_ip(p["mac"])
        if not ip:
            continue
        if _ping(ip):
            with _lock:
                _s["last_seen"][name] = now
        elif p.get("mac"):
            # a phone in deep sleep may not answer pings but still be in the ARP table as REACHABLE
            try:
                out = subprocess.run(["ip", "neigh", "show", ip], capture_output=True, text=True, timeout=3).stdout
                if "REACHABLE" in out:
                    with _lock:
                        _s["last_seen"][name] = now
            except Exception:
                pass


def is_home():
    return bool(_s["home"])


def state():
    with _lock:
        out = dict(_s)
        out["last_seen"] = dict(_s["last_seen"])
    out["mode"] = ctx.config.get("mode", "auto") if ctx else "auto"
    out["phones"] = ctx.config.get("phones", []) if ctx else []
    return out


def api(action, params):
    if action == "set_mode":
        mode = params.get("mode", "auto")
        if mode not in ("auto", "home", "away"):
            return {"ok": False, "error": "mode must be auto|home|away"}
        ctx.config["mode"] = mode
        ctx.save_config()
        _evaluate()
        return {"ok": True, "mode": mode}
    if action == "set_phones":
        ok_ip = lambda v: bool(re.match(r"^[0-9]{1,3}(\.[0-9]{1,3}){3}$", str(v))) or bool(re.match(r"^[A-Za-z0-9.-]{1,63}$", str(v)))
        ok_mac = lambda v: bool(re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", str(v)))
        phones = []
        for p in (params.get("phones") or [])[:10]:
            if not isinstance(p, dict):
                continue
            q = {"name": str(p.get("name") or "phone")[:40]}
            if p.get("ip") and ok_ip(p["ip"]): q["ip"] = str(p["ip"])
            if p.get("mac") and ok_mac(p["mac"]): q["mac"] = str(p["mac"]).lower()
            if "ip" in q or "mac" in q:
                phones.append(q)
        ctx.config["phones"] = phones
        ctx.save_config()
        return {"ok": True, "phones": phones}
    if action == "probe":
        _probe(); _evaluate()
        return state()
    return {"ok": False, "error": f"unknown action {action}"}


def _evaluate():
    now = time.time()
    mode = ctx.config.get("mode", "auto")
    away_s = ctx.config.get("away_after_min", 10) * 60
    with _lock:
        seen = any(now - t < away_s for t in _s["last_seen"].values())
        auto_home = seen if ctx.config.get("phones") else True   # no phones configured -> assume home
        _s["auto_home"] = auto_home
        new = {"home": True, "away": False}.get(mode, auto_home)
        changed = new != _s["home"]
        if changed:
            _s["home"] = new
            _s["since"] = now
    if changed:
        ctx.log("presence: " + ("home" if new else "away"))
        ctx.emit("arrived_home" if new else "left_home", {"mode": mode})


def on_config():
    _evaluate()


def start(c):
    global ctx
    ctx = c
    while True:
        try:
            _probe()
            _evaluate()
        except Exception as e:
            ctx.log(f"presence loop error: {e}")
        time.sleep(ctx.config.get("poll_s", 30))
