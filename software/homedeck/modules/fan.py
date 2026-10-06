"""Fan on J21: 5 V fan switched by a low-side driver on GPIO25 (high = on).

Speed control uses gpiozero's PWMOutputDevice (lgpio backend, hardware-timed) when available; otherwise
the fan is plain on/off through pinctrl. Auto mode follows the CM4 temperature with hysteresis:
starts at auto.on_c, stops at auto.off_c, ramps linearly to 100 % at auto.full_c. At night (display
module reports night) the speed is capped at 50 % so it stays quiet.
"""
import subprocess, threading, time

NAME = "fan"
DEFAULTS = {
    "mode": "auto",                                   # auto | on | off
    "auto": {"on_c": 52, "off_c": 45, "full_c": 62},  # hysteresis + ramp, degrees C
    "min_pct": 35,                                    # fans stall below this duty
    "manual_pct": 60,                                 # speed used in "on" mode
    "night_cap_pct": 50,
}
GPIO = 25
THERMAL = "/sys/class/thermal/thermal_zone0/temp"

ctx = None
_lock = threading.Lock()
_state = {"mode": "auto", "running": False, "pct": 0, "temp_c": None, "driver": "none", "error": None}
_pwm = None          # gpiozero PWMOutputDevice or None
_driver = "none"
_last_pct = None


# ------------------------------------------------------------------ hardware
def _open():
    """Pick a driver: gpiozero PWM if importable and the pin can be claimed, else pinctrl on/off."""
    global _pwm, _driver
    try:
        from gpiozero import PWMOutputDevice
        _pwm = PWMOutputDevice(GPIO, frequency=25000, initial_value=0)
        _driver = "gpiozero-pwm"
        return
    except Exception as e:
        ctx.log(f"gpiozero PWM unavailable ({e}); falling back to pinctrl on/off")
    try:
        subprocess.run(["pinctrl", "set", str(GPIO), "op", "dl"], check=True, capture_output=True, timeout=3)
        _driver = "pinctrl-onoff"
    except Exception as e:
        _driver = "none"
        with _lock:
            _state["error"] = f"no fan driver: {e}"


def _apply(pct):
    """Drive the pin. pct 0 = off; otherwise clamp to [min_pct, 100]."""
    global _last_pct
    pct = int(round(max(0, min(100, pct))))
    if pct and pct < int(ctx.config.get("min_pct", 35)):
        pct = int(ctx.config.get("min_pct", 35))
    if pct == _last_pct:
        return
    try:
        if _driver == "gpiozero-pwm":
            _pwm.value = pct / 100.0
        elif _driver == "pinctrl-onoff":
            subprocess.run(["pinctrl", "set", str(GPIO), "op", "dh" if pct else "dl"], check=True, capture_output=True, timeout=3)
            pct = 100 if pct else 0
        else:
            return
        with _lock:
            _state["error"] = None
    except Exception as e:
        with _lock:
            _state["error"] = f"fan drive failed: {e}"
        return
    was = _last_pct
    _last_pct = pct
    with _lock:
        _state.update({"pct": pct, "running": pct > 0})
    if (was or 0) == 0 and pct > 0:
        ctx.log(f"fan on at {pct}%")
    elif (was or 0) > 0 and pct == 0:
        ctx.log("fan off")


def _read_temp():
    try:
        with open(THERMAL) as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        return None


def _night():
    d = ctx.module("display")
    try:
        return bool(d and d.state().get("night"))
    except Exception:
        return False


# ------------------------------------------------------------------ control loop
def _target(temp, running):
    """Auto-mode duty from temperature with hysteresis; returns 0..100."""
    a = ctx.config.get("auto", DEFAULTS["auto"])
    on_c, off_c, full_c = float(a.get("on_c", 58)), float(a.get("off_c", 50)), float(a.get("full_c", 70))
    if temp is None:
        return 0
    if running:
        if temp <= off_c:
            return 0
    elif temp < on_c:
        return 0
    lo = int(ctx.config.get("min_pct", 35))
    if full_c <= on_c:
        return 100
    frac = (temp - on_c) / (full_c - on_c)
    return int(round(lo + max(0.0, min(1.0, frac)) * (100 - lo)))


def start(c):
    global ctx
    ctx = c
    _open()
    with _lock:
        _state["driver"] = _driver
    while True:
        try:
            cfg = ctx.config
            mode = cfg.get("mode", "auto")
            temp = _read_temp()
            with _lock:
                _state["temp_c"] = temp
                _state["mode"] = mode
                running = _state["running"]
            if mode == "off":
                pct = 0
            elif mode == "on":
                pct = int(cfg.get("manual_pct", 60))
            else:
                pct = _target(temp, running)
            if pct and _night():
                pct = min(pct, int(cfg.get("night_cap_pct", 50)))
            _apply(pct)
        except Exception as e:
            with _lock:
                _state["error"] = str(e)
        time.sleep(5)


def state():
    with _lock:
        return dict(_state)


def api(action, params):
    if action == "set_mode":
        mode = params.get("mode", "auto")
        if mode not in ("auto", "on", "off"):
            return {"ok": False, "error": "mode must be auto, on or off"}
        ctx.config["mode"] = mode
        ctx.save_config()
        ctx.log(f"fan mode -> {mode}")
        return {"ok": True, "mode": mode}
    if action == "set_pct":
        pct = int(max(0, min(100, int(params.get("pct", 60)))))
        ctx.config["manual_pct"] = pct
        ctx.save_config()
        if ctx.config.get("mode") == "on":
            _apply(pct)
        return {"ok": True, "pct": pct}
    return {"ok": False, "error": f"unknown action {action}"}


def intent(text):
    """Spoken fan control: "turn the fan on/off", "fan to 60 percent", "fan auto", "is the fan on"."""
    import re
    t = (text or "").lower()
    if not re.search(r"\bfan\b", t):
        return None
    if re.search(r"\b(is the fan|fan status|is it running|what's the fan|how's the fan)\b", t):
        s = state(); return f"The fan is {'running at ' + str(s.get('pct')) + ' percent' if s.get('running') else 'off'}, {s.get('mode')} mode, {s.get('temp_c')} degrees."
    m = re.search(r"(\d{1,3})\s*(%|percent)", t)
    if m:
        pct = max(0, min(100, int(m.group(1)))); api("set_mode", {"mode": "on"}); api("set_pct", {"pct": pct}); return f"Fan at {pct} percent."
    if re.search(r"\b(auto|automatic)\b", t):
        api("set_mode", {"mode": "auto"}); return "Fan on automatic."
    if re.search(r"\b(off|stop)\b", t):
        api("set_mode", {"mode": "off"}); return "Fan off."
    if re.search(r"\b(on|start|turn on)\b", t):
        api("set_mode", {"mode": "on"}); return "Fan on."
    if re.search(r"\b(is|status|running|what)\b", t):
        s = state(); return f"The fan is {'running at ' + str(s.get('pct')) + ' percent' if s.get('running') else 'off'}, {s.get('mode')} mode, {s.get('temp_c')} degrees."
    return None
