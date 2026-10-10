"""Display: backlight brightness from ambient light, night mode, idle dimming, screen off, presence wake.

Backlight: /sys/class/backlight/panel_backlight@1 (brightness 0-31, bl_power 0=on 4=off), may be absent
(then we just track the value; the shell dims the page via CSS from brightness_pct).
Light source: BH1750 on I2C6 at 0x23 if fitted, else the camera module's lux estimate.
"""
import threading, os, subprocess, time

NAME = "display"
DEFAULTS = {"power_button": {"long_press_s": 3},
    "auto_brightness": True, "min_pct": 5, "max_pct": 100,
    "night": {"enabled": True, "start": "22:30", "end": "07:00", "pct": 3},
    "sleep_after_s": 300, "off_after_s": 0, "wake_on_presence": True,
    "lux_dark": 5, "lux_bright": 400,          # lux range mapped onto min_pct..max_pct
}

ctx = None
BL = "/sys/class/backlight/panel_backlight@1"
_lock = threading.Lock()
_s = {"brightness_pct": 60, "night": False, "screen_off": False, "lux": None, "lux_source": None,
      "idle_s": 0, "override_until": 0, "override_pct": None, "backlight_present": False, "sleeping": False}
_last_touch = time.time()
_smooth = 60.0


# ------------------------------------------------------------------ light sensing
def _read_bh1750():
    try:
        from smbus2 import SMBus
        with SMBus(6) as bus:
            bus.write_byte(0x23, 0x20)          # one-time high-res mode
            time.sleep(0.18)
            d = bus.read_i2c_block_data(0x23, 0x00, 2)
        return ((d[0] << 8) | d[1]) / 1.2, "bh1750"
    except Exception:
        return None, None


def _read_lux():
    lux, src = _read_bh1750()
    if lux is None:
        cam = ctx.module("camera")
        try:
            v = cam.state().get("lux") if cam else None
            if v is not None:
                lux, src = float(v), "camera"
        except Exception:
            pass
    return lux, src


# ------------------------------------------------------------------ backlight
def _bl_present():
    return os.path.isdir(BL)


def _bl_write(pct, off):
    try:
        if not _bl_present():
            return
        with open(os.path.join(BL, "bl_power"), "w") as f:
            f.write("4" if off else "0")
        if not off:
            v = max(1, min(31, round(31 * pct / 100)))
            with open(os.path.join(BL, "brightness"), "w") as f:
                f.write(str(v))
    except Exception as e:
        ctx.log(f"backlight write failed: {e}")


# ------------------------------------------------------------------ helpers
def _in_night():
    n = ctx.config.get("night", {})
    if not n.get("enabled", True):
        return False
    now = time.localtime()
    cur = now.tm_hour * 60 + now.tm_min
    def m(s):
        h, mm = s.split(":"); return int(h) * 60 + int(mm)
    a, b = m(n.get("start", "22:30")), m(n.get("end", "07:00"))
    return (a <= cur or cur < b) if a > b else (a <= cur < b)


def _target_pct(lux):
    cfg = ctx.config
    if _s["override_pct"] is not None and time.time() < _s["override_until"]:
        return _s["override_pct"]
    if _in_night():
        return cfg.get("night", {}).get("pct", 3)
    if not cfg.get("auto_brightness", True):
        return cfg.get("max_pct", 100)
    if lux is None:                                          # no light reading (camera off or frozen): a calm middle
        return cfg.get("no_lux_pct", 60)
    lo, hi = cfg.get("lux_dark", 5), cfg.get("lux_bright", 400)
    f = 0.0 if lux <= lo else 1.0 if lux >= hi else (lux - lo) / (hi - lo)
    f = f ** 0.5                                            # perceptual-ish curve
    return cfg.get("min_pct", 5) + f * (cfg.get("max_pct", 100) - cfg.get("min_pct", 5))


_manual_off = {"on": False}


def _wake(reason):
    if _manual_off["on"] and reason == "presence":
        return                                   # the owner turned the screen off: movement must not undo that
    global _last_touch
    _last_touch = time.time()
    with _lock:
        was_off = _s["screen_off"]
        _s["screen_off"] = False
        _manual_off["on"] = False
        _s["sleeping"] = False
    if was_off:
        ctx.log(f"screen woke ({reason})")


# ------------------------------------------------------------------ public
def state():
    with _lock:
        out = dict(_s)
    out["idle_s"] = int(time.time() - _last_touch)
    out["viewport"] = dict(_viewport)
    out["override_pct"] = out["override_pct"] if time.time() < out["override_until"] else None
    return out


_viewport = {}
# ------------------------------------------------------------------ power button (J18 / GPIO3 via the gpio-shutdown overlay)
# The overlay exposes the button as a Linux input device (KEY_POWER). logind is told to ignore the key
# (install: HandlePowerKey=ignore) so we can do: short press = screen off/on, long press (3 s) = clean shutdown.
def _power_button_thread():
    import struct, glob, os
    dev = None
    for _ in range(30):
        m = glob.glob("/dev/input/by-path/*shutdown_button*-event")
        if m: dev = m[0]; break
        time.sleep(2)
    if not dev:
        ctx.log("power button: no input device"); return
    fmt = "llHHi"; size = struct.calcsize(fmt)
    down_at = None
    long_s = float((ctx.config.get("power_button") or {}).get("long_press_s", 3))
    try:
        with open(dev, "rb") as f:
            while True:
                data = f.read(size)
                if len(data) < size: break
                _, _, etype, code, value = struct.unpack(fmt, data)
                if etype != 1 or code != 116:          # EV_KEY, KEY_POWER
                    continue
                if value == 1:
                    down_at = time.time()
                elif value == 0 and down_at is not None:
                    held = time.time() - down_at; down_at = None
                    if held >= long_s:
                        ctx.log("power button: long press -> shutdown")
                        v = ctx.module("voice")
                        try:
                            if v and hasattr(v, "say"): v.say("Shutting down.")
                        except Exception: pass
                        subprocess.run(["systemctl", "poweroff"], timeout=10)
                    else:
                        with _lock:
                            off = not _s["screen_off"]
                            _s["screen_off"] = off
                            _manual_off["on"] = off
                        _bl_write(_s["brightness_pct"], off)
                        if not off: _wake("power button")
                        ctx.log(f"power button: short press -> screen {'off' if off else 'on'}")
    except Exception as e:
        ctx.log(f"power button reader stopped: {e}")


def _persist_orientation(tr):
    """Write the transform where the session can pick it up before the UI exists: a plain file for kiosk.sh and a
    kanshi profile so the compositor rotates the output the moment the session starts (no portrait desktop flash)."""
    try:
        with open(os.path.join(ctx.data_dir, "orientation"), "w") as f:
            f.write(tr + "\n")
    except Exception as e:
        ctx.log(f"orientation file: {e}")
    try:
        import pwd
        home = pwd.getpwnam("kilan").pw_dir
        d = os.path.join(home, ".config", "kanshi"); os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "config"), "w") as f:
            f.write("profile homedeck {\n    output DSI-1 enable transform " + tr + "\n}\n")
        for pth in (d, os.path.join(d, "config")):
            os.chown(pth, pwd.getpwnam("kilan").pw_uid, pwd.getpwnam("kilan").pw_gid)
    except Exception as e:
        ctx.log(f"kanshi config: {e}")


def _apply_orientation(name):
    tr = {"landscape": "90", "landscape_flipped": "270", "portrait_flipped": "180"}.get(name, "normal")
    _persist_orientation(tr)
    env = {"XDG_RUNTIME_DIR": "/run/user/1000", "WAYLAND_DISPLAY": "wayland-0", "PATH": "/usr/bin:/bin"}
    try:
        out = subprocess.run(["wlr-randr"], capture_output=True, text=True, timeout=5, env=env).stdout
        name_out = next((l.split()[0] for l in out.splitlines() if l and not l.startswith(" ")), "DSI-1")
        subprocess.run(["wlr-randr", "--output", name_out, "--transform", tr], capture_output=True, timeout=5, env=env)
        return True
    except Exception as e:
        ctx.log(f"orientation: {e}"); return False


def api(action, params):
    if action == "set_orientation":
        name = params.get("orientation", "portrait")
        if name not in ("portrait", "landscape", "landscape_flipped", "portrait_flipped"):
            return {"ok": False, "error": "unknown orientation"}
        ctx.global_config["general"]["orientation"] = name; ctx.save_config()
        return {"ok": _apply_orientation(name), "orientation": name}
    if action == "viewport":
        for k in ("w", "h", "dpr"):
            try: _viewport[k] = float(params.get(k)) if params.get(k) is not None else None
            except (TypeError, ValueError): _viewport[k] = None
        _viewport["ua"] = str(params.get("ua") or "")[:120]; _viewport["t"] = time.time()
        return {"ok": True}
    if action == "touch":
        _wake("touch")
        return {"ok": True}
    if action == "screen_off":
        with _lock:
            _s["screen_off"] = not _s["screen_off"] if params.get("toggle", True) else bool(params.get("off", True))
            _manual_off["on"] = _s["screen_off"]
        _bl_write(_s["brightness_pct"], _s["screen_off"])
        return {"ok": True, "screen_off": _s["screen_off"]}
    if action == "set_brightness":
        global _smooth
        pct = max(1, min(100, float(params.get("pct", 50))))
        _smooth = float(pct)                                        # the 1 s loop must not drag it back toward the old level
        _wake("brightness")
        with _lock:
            _s["override_pct"] = pct
            _s["override_until"] = time.time() + 6 * 3600     # a manual setting sticks until "Auto" is tapped (or 6 h)
            _s["brightness_pct"] = int(pct)
            off = _s["screen_off"]
        _bl_write(int(pct), off)                                # apply now, not on the next 5 s tick
        return {"ok": True, "pct": pct}
    if action == "clear_override":
        with _lock:
            _s["override_pct"] = None
        return {"ok": True}
    return {"ok": False, "error": f"unknown action {action}"}


def start(c):
    global ctx, _smooth
    ctx = c
    threading.Thread(target=_power_button_thread, name="power-button", daemon=True).start()
    _s["backlight_present"] = _bl_present()
    try:
        _persist_orientation({"landscape": "90", "landscape_flipped": "270", "portrait_flipped": "180"}.get(ctx.global_config.get("general", {}).get("orientation", "portrait"), "normal"))
    except Exception:
        pass
    if ctx.config.get("wake_on_presence", True):
        ctx.on("presence_seen", lambda d: _wake("presence"))
    ctx.on("alarm_ringing", lambda d: _wake("alarm"))
    last_lux = 0
    last_bl_try = 0.0
    bl_logged = False
    while True:
        try:
            now = time.time()
            # The Touch Display 2 backlight is a PWM in the panel's own controller (I2C 0x45). Now and then that
            # controller comes up refusing commands after a reboot (pwm-backlight probe -EIO), leaving no brightness
            # control; a software reboot does not power-cycle the panel, unplugging power does. Retry the driver
            # every 2 minutes in case it recovers, and say what to do meanwhile (the page dims itself via CSS).
            if not _s["backlight_present"] and now - last_bl_try > 120:
                last_bl_try = now
                try:
                    with open("/sys/bus/platform/drivers/pwm-backlight/bind", "w") as f:
                        f.write(os.path.basename(BL))
                except OSError:
                    pass
                present = _bl_present()
                with _lock:
                    _s["backlight_present"] = present
                    _s["backlight_hint"] = None if present else ("The screen's brightness control did not start. Unplug the "
                                                                 "HomeDeck's power for 10 seconds and plug it back in.")
                if present:
                    ctx.log("backlight control came up on retry")
                elif not bl_logged:
                    bl_logged = True
                    # Without the backlight the DSI panel driver never probes either, so the screen stays black and an
                    # on-screen hint is useless: alert the phone. Happens after some warm reboots (the panel keeps power
                    # through a reboot and its controller can come back hung); unplugging power for 10 s fixes it.
                    n = ctx.module("notify")
                    detail = ("screen did not start: panel controller not answering (backlight probe -EIO); "
                              "unplug power for 10 s")
                    if n and hasattr(n, "problem"):
                        n.problem(f"display: {detail}")
                    else:
                        ctx.log(detail)
            if now - last_lux >= 5:
                lux, src = _read_lux()
                with _lock:
                    _s["lux"], _s["lux_source"] = (round(lux, 1) if lux is not None else None), src
                last_lux = now
            idle = now - _last_touch
            cfg = ctx.config
            target = _target_pct(_s["lux"])
            sleeping = cfg.get("sleep_after_s", 300) and idle > cfg.get("sleep_after_s", 300)
            if sleeping:
                target = min(target, max(1, cfg.get("min_pct", 5)))
            off_after = cfg.get("off_after_s", 0)
            auto_off = bool(off_after) and idle > off_after
            if _s["override_pct"] is not None and time.time() < _s["override_until"] and not sleeping:
                _smooth = float(target)                              # a manual choice applies at once, no easing back
            else:
                _smooth += (target - _smooth) * 0.3                  # ambient changes ease in
            with _lock:
                _s["brightness_pct"] = round(_smooth)
                _s["night"] = _in_night()
                _s["sleeping"] = bool(sleeping)
                if auto_off and not _s["screen_off"]:
                    _s["screen_off"] = True
                off = _s["screen_off"]
                pct = _s["brightness_pct"]
            _bl_write(pct, off)
        except Exception as e:
            ctx.log(f"display loop error: {e}")
        time.sleep(1)
