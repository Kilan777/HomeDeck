"""Wi-Fi: see the current network, scan, join a new network with a password, forget saved ones.
Wraps NetworkManager's nmcli (the service runs as root). Passwords are passed to nmcli and never stored or returned
by this module; NetworkManager keeps them in its own connection files.
"""
import re, subprocess, threading, time

NAME = "wifi"
DEFAULTS = {"iface": "wlan0"}
ctx = None
_lock = threading.Lock()
_s = {"ssid": None, "ip": None, "signal": None, "connected": False, "saved": [], "networks": [], "scanned_at": 0,
      "busy": False, "last_result": None, "error": None}


def _nm(args, timeout=20):
    r = subprocess.run(["nmcli", "-t", "--escape", "no"] + args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else f"nmcli exit {r.returncode}")
    return r.stdout


def _iface():
    return ctx.config.get("iface", "wlan0") if ctx else "wlan0"


def _refresh_status():
    ssid = ip = None; signal = None; saved = []
    try:
        for line in _nm(["-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi", "list", "--rescan", "no"], 10).splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[0] == "yes":
                ssid = parts[1]; signal = int(parts[2] or 0); break
    except Exception as e:
        _s["error"] = str(e)
    try:
        for line in _nm(["-f", "IP4.ADDRESS", "dev", "show", _iface()], 10).splitlines():
            if line.startswith("IP4.ADDRESS"):
                ip = line.split(":", 1)[1].split("/")[0]; break
    except Exception:
        pass
    try:
        for line in _nm(["-f", "NAME,TYPE", "connection", "show"], 10).splitlines():
            name, _, typ = line.partition(":")
            if typ == "802-11-wireless":
                saved.append(name)
    except Exception:
        pass
    with _lock:
        _s.update({"ssid": ssid, "ip": ip, "signal": signal, "connected": bool(ssid and ip), "saved": saved})


def _scan():
    nets = {}
    out = _nm(["-f", "SSID,SIGNAL,SECURITY,ACTIVE", "dev", "wifi", "list", "--rescan", "yes"], 25)
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 4 or not parts[0]:
            continue
        ssid, sig, sec, active = parts[0], int(parts[1] or 0), parts[2], parts[3] == "yes"
        cur = nets.get(ssid)
        if cur is None or sig > cur["signal"]:
            nets[ssid] = {"ssid": ssid, "signal": sig, "secured": bool(sec and sec != "--"), "active": active or (cur or {}).get("active", False)}
    lst = sorted(nets.values(), key=lambda n: (-int(n["active"]), -n["signal"]))
    with _lock:
        _s["networks"] = lst; _s["scanned_at"] = time.time()
    return lst


def _connect(ssid, password):
    """Join a network: reuse a saved profile when there is one, else create it. Blocks until NetworkManager reports."""
    with _lock:
        _s["busy"] = True; _s["last_result"] = None
    try:
        saved = ssid in _s["saved"]
        if saved and not password:
            _nm(["connection", "up", "id", ssid], 45)
        else:
            if saved:
                _nm(["connection", "delete", "id", ssid], 15)
            args = ["dev", "wifi", "connect", ssid, "ifname", _iface()]
            if password:
                args += ["password", password]
            _nm(args, 60)
        time.sleep(2)
        _refresh_status()
        ok = _s["ssid"] == ssid
        msg = f"Connected to {ssid}" if ok else f"Joined {ssid} but no address yet"
        with _lock:
            _s["last_result"] = {"ok": ok, "ssid": ssid, "message": msg}
        ctx.log(f"wifi: {msg}")
        ctx.emit("wifi_changed", {"ssid": _s["ssid"], "ip": _s["ip"]})
    except Exception as e:
        err = str(e)
        if "Secrets were required" in err or "no secrets" in err.lower() or "802-11-wireless-security" in err:
            err = "Wrong password"
        ctx.log(f"wifi: connect to {ssid!r} failed: {err}")
        with _lock:
            _s["last_result"] = {"ok": False, "ssid": ssid, "message": err}
        try:
            _refresh_status()
        except Exception:
            pass
    finally:
        with _lock:
            _s["busy"] = False


def state():
    with _lock:
        return dict(_s)


def api(action, params):
    if action == "status":
        _refresh_status()
        return {"ok": True, **state()}
    if action == "scan":
        try:
            return {"ok": True, "networks": _scan()}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if action == "connect":
        ssid = str(params.get("ssid") or "").strip()
        password = str(params.get("password") or "")
        if not ssid:
            return {"ok": False, "error": "no network name"}
        if _s["busy"]:
            return {"ok": False, "error": "already connecting"}
        threading.Thread(target=_connect, args=(ssid, password), daemon=True).start()
        return {"ok": True, "started": True}
    if action == "forget":
        ssid = str(params.get("ssid") or "").strip()
        try:
            _nm(["connection", "delete", "id", ssid], 15)
            _refresh_status()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": f"unknown action {action}"}


def start(c):
    global ctx
    ctx = c
    while True:
        try:
            _refresh_status()
        except Exception as e:
            ctx.log(f"wifi status: {e}")
        time.sleep(30)
