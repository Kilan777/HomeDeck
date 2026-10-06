"""Guest card: the Wi-Fi as a scannable QR code plus a few house notes, and "Jarvis, give me the wifi" which shows the
QR full screen for a minute. Reads the active Wi-Fi profile from NetworkManager as root; the passphrase is only ever
encoded into the QR (and returned in plain text when guest.show_password is switched on). Never logged.
"""
import re, subprocess, threading, time

NAME = "guest"
DEFAULTS = {"notes": ["Bathroom: second door on the left", "Trash goes out Tuesday night"], "show_password": False,
            "show_seconds": 60}
ctx = None
_lock = threading.Lock()
_cache = {"t": 0, "ssid": None, "psk": None, "sec": None}


def _nm(args, timeout=8):
    r = subprocess.run(["nmcli"] + args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or f"nmcli exit {r.returncode}")
    return r.stdout


def _active_wifi():
    """(ssid, passphrase, security) of the connection that is up on the Wi-Fi interface, cached for a minute."""
    if time.time() - _cache["t"] < 60 and _cache["ssid"]:
        return _cache["ssid"], _cache["psk"], _cache["sec"]
    name = None
    for line in _nm(["-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"]).splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == "802-11-wireless" and parts[2]:
            name = parts[0]; break
    if not name:
        raise RuntimeError("not connected to Wi-Fi")
    ssid = _nm(["-g", "802-11-wireless.ssid", "connection", "show", name]).strip() or name
    kmgmt = _nm(["-g", "802-11-wireless-security.key-mgmt", "connection", "show", name]).strip()
    psk = ""
    if kmgmt:
        psk = _nm(["-s", "-g", "802-11-wireless-security.psk", "connection", "show", name]).strip()
    sec = "nopass" if not kmgmt else ("WPA" if "psk" in kmgmt or "sae" in kmgmt else "WEP" if "wep" in kmgmt else "WPA")
    with _lock:
        _cache.update({"t": time.time(), "ssid": ssid, "psk": psk, "sec": sec})
    return ssid, psk, sec


def _esc(v):
    return re.sub(r'([\\;,":])', r"\\\1", v or "")


def wifi_string(ssid, psk, sec):
    if sec == "nopass" or not psk:
        return f"WIFI:T:nopass;S:{_esc(ssid)};;"
    return f"WIFI:T:{sec};S:{_esc(ssid)};P:{_esc(psk)};;"


def _qr_svg(text):
    import qrcode, qrcode.image.svg as svg
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=1, box_size=10)
    q.add_data(text); q.make(fit=True)
    img = q.make_image(image_factory=svg.SvgPathImage)
    out = img.to_string().decode() if isinstance(img.to_string(), bytes) else img.to_string()
    # transparent background, dark modules; the page colours the plate behind it
    out = re.sub(r"<\?xml[^>]*>\s*", "", out)
    out = out.replace("fill=\"#000000\"", "fill=\"currentColor\"").replace("fill:#000000", "fill:currentColor")
    if "currentColor" not in out:
        out = out.replace("<path ", "<path fill=\"currentColor\" ", 1)
    return out


def card():
    ssid, psk, sec = _active_wifi()
    out = {"ok": True, "ssid": ssid, "secured": sec != "nopass" and bool(psk), "qr_svg": _qr_svg(wifi_string(ssid, psk, sec)),
           "notes": list(ctx.config.get("notes") or []), "show_password": bool(ctx.config.get("show_password", False)),
           "show_seconds": int(ctx.config.get("show_seconds", 60))}
    if out["show_password"]:
        out["password"] = psk
    return out


def state():
    with _lock:
        return {"ssid": _cache["ssid"], "notes": list(ctx.config.get("notes") or []) if ctx else [],
                "show_password": bool(ctx.config.get("show_password", False)) if ctx else False}


def show(seconds=None):
    secs = int(seconds or ctx.config.get("show_seconds", 60))
    ctx.emit("show_wifi", {"seconds": secs})
    return secs


def api(action, params):
    if action == "card":
        try:
            return card()
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if action == "show":
        try:
            return {"ok": True, "seconds": show(params.get("seconds"))}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if action == "set_notes":
        notes = params.get("notes")
        if isinstance(notes, str):
            notes = [n.strip() for n in notes.splitlines()]
        ctx.config["notes"] = [n for n in (notes or []) if n][:20]
        ctx.save_config()
        return {"ok": True, "notes": ctx.config["notes"]}
    if action == "set_options":
        if "show_password" in params:
            ctx.config["show_password"] = bool(params["show_password"])
        if "show_seconds" in params:
            ctx.config["show_seconds"] = max(10, min(600, int(params["show_seconds"])))
        ctx.save_config()
        return {"ok": True}
    return {"ok": False, "error": f"unknown action {action}"}


_ASK = re.compile(r"\b(give me the wi ?fi|what'?s the wi ?fi( password| code)?|what is the wi ?fi( password| code)?|show( me)? the wi ?fi|"
                  r"wi ?fi (qr|code|password|please)|the wi ?fi password|wi ?fi qr code|share the wi ?fi|guest wi ?fi)\b", re.I)


def intent(text):
    t = (text or "").strip().rstrip(".!?")
    if not re.search(r"\bwi ?fi\b", t, re.I):
        return None
    if re.search(r"\b(connect|join|scan for|find|networks?|forget|disconnect|switch)\b", t, re.I):
        return None                              # Settings > Wi-Fi territory
    if _ASK.search(t) or re.search(r"\bwi ?fi\b", t, re.I):
        try:
            secs = show()
        except Exception as e:
            return f"I couldn't read the Wi-Fi details: {e}"
        return "Here's the Wi-Fi." if secs else ""
    return None


def start(c):
    global ctx
    ctx = c
    while True:
        try:
            _active_wifi()
        except Exception:
            pass
        time.sleep(120)
