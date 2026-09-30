"""LEDs: one WS2812B chain on SPI0 MOSI: the onboard 10-LED bar first, then the external strips on J17.

Patterns: off, solid(color), listen, think, answer, alert, sunrise(progress), notify, error.
Other modules call ctx.module("leds").pattern("listen") etc. The 5V_PERIPH rail that feeds the
bar may be dead or /dev/spidev0.0 absent; every SPI failure is swallowed so the rest keeps running.

Layout: "segments" lists the stretches of the chain that are actually visible through the enclosure, e.g.
[{"name": "Left", "start": 12, "end": 35, "reverse": false}, {"name": "Right", "start": 41, "end": 64, "reverse": true}].
Patterns are drawn on one logical canvas as long as all the segments together and then mapped onto them in order
(a segment with "reverse" is filled end to start, so an animation keeps flowing the same way across both strips).
Everything outside the segments stays dark, the onboard bar included. With no segments configured the old
behaviour applies: one run from strip_start to the end, with the bar dark ("bar_mode": "off") or mirroring it.

Two overlays run while the strip is otherwise idle (lamp or dark): a timer fill that grows as the soonest timer
runs, and a music-reactive VU while Spotify plays. Jarvis patterns and the alarm sunrise take over and the
overlays resume after. The mapping tool (identify / chase / test_segments) paints physical LEDs directly and
always hands the strip back to its base state when its time is up.
"""
import math, threading, time

NAME = "leds"
DEFAULTS = {"enabled": True, "brightness": 60, "night_brightness": 10, "count": 10,
            "strip_start": 10,                   # LEDs before the external strip (used when no segments are set)
            "bar_mode": "off",                   # onboard bar: "off" (dark) or "mirror" (copy of the strip)
            "segments": [],                      # visible stretches: [{name, start, end, reverse}], physical indices
            "timer_fill": True, "timer_color": [255, 140, 40],
            "music_reactive": True,
            "lamp": {"on": False, "color": [255, 170, 90], "brightness": 60}}   # steady light the strip returns to

ctx = None
_lock = threading.Lock()
_current = {"name": "off", "kw": {}, "since": 0.0}
_spi = None
_spi_err = None
_fps = 30


# ------------------------------------------------------------------ SPI transport
def _open_spi():
    global _spi, _spi_err
    if _spi is not None:
        return _spi
    try:
        import spidev
        s = spidev.SpiDev()
        s.open(0, 0)
        s.max_speed_hz = 2400000     # 3 SPI bits per WS2812 bit -> 800 kHz
        s.mode = 0
        _spi = s
        _spi_err = None
    except Exception as e:           # no spidev module, no device, or permissions
        _spi_err = str(e)
        _spi = None
    return _spi


def _encode(pixels):
    """pixels: list of (r,g,b) 0-255 -> SPI byte list (GRB order, 100 = 0 bit, 110 = 1 bit)."""
    bits = []
    for r, g, b in pixels:
        for byte in (g, r, b):
            for k in range(7, -1, -1):
                bits.append("110" if (byte >> k) & 1 else "100")
    s = "".join(bits)
    s += "0" * ((8 - len(s) % 8) % 8)
    data = [int(s[i:i + 8], 2) for i in range(0, len(s), 8)]
    return data + [0] * 40            # >50 us low = latch


def _push(pixels):
    s = _open_spi()
    if s is None:
        return False
    try:
        s.xfer(_encode(pixels))
        return True
    except Exception as e:
        global _spi, _spi_err
        _spi_err = str(e)
        try:
            s.close()
        except Exception:
            pass
        _spi = None
        return False


# ------------------------------------------------------------------ chain geometry
def _count():
    return max(1, min(500, int((ctx.config if ctx else DEFAULTS).get("count", DEFAULTS["count"]))))


def _clean_segments(raw, n_total):
    """Validate a segments list: whole numbers inside the chain, start <= end, no overlaps, in chain order."""
    out = []
    for s in (raw or []):
        try:
            a, b = int(s.get("start")), int(s.get("end"))
        except (TypeError, ValueError, AttributeError):
            continue
        a = max(0, min(n_total - 1, a))
        b = max(0, min(n_total - 1, b))
        if b < a:
            a, b = b, a
        out.append({"name": (str(s.get("name") or "").strip() or f"{a}-{b}")[:24],
                    "start": a, "end": b, "reverse": bool(s.get("reverse"))})
    out.sort(key=lambda s: s["start"])
    merged = []
    for s in out:                                   # drop overlaps: a later segment starts after the previous ends
        if merged and s["start"] <= merged[-1]["end"]:
            s["start"] = merged[-1]["end"] + 1
            if s["start"] > s["end"]:
                continue
        merged.append(s)
    return merged


def _segments():
    """(segments, configured). Configured segments win; otherwise the whole external run, as before."""
    n_total = _count()
    segs = _clean_segments(ctx.config.get("segments"), n_total)
    if segs:
        return segs, True
    start = max(0, min(n_total - 1, int(ctx.config.get("strip_start", DEFAULTS["strip_start"]))))
    return [{"name": "Strip", "start": start, "end": n_total - 1, "reverse": False}], False


def _seg_len(segs):
    return sum(s["end"] - s["start"] + 1 for s in segs)


def _paint(logical, segs, n_total, configured):
    """Lay the logical canvas onto the chain: one slice per segment, reversed where asked. Everything else dark."""
    frame = [(0, 0, 0)] * n_total
    i = 0
    for s in segs:
        ln = s["end"] - s["start"] + 1
        chunk = list(logical[i:i + ln])
        i += ln
        if len(chunk) < ln:
            chunk += [(0, 0, 0)] * (ln - len(chunk))
        if s["reverse"]:
            chunk.reverse()
        frame[s["start"]:s["start"] + ln] = chunk
    if not configured and ctx.config.get("bar_mode", "off") == "mirror" and logical:
        n_bar = segs[0]["start"]
        for i in range(n_bar):                      # the old bar mirror, only without configured segments
            frame[i] = logical[min(len(logical) - 1, int(i * len(logical) / max(1, n_bar)))]
    return frame


# ------------------------------------------------------------------ colour helpers
def _scale(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def _lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _brightness_factor():
    cfg = ctx.config if ctx else DEFAULTS
    pct = cfg.get("brightness", 60)
    disp = ctx.module("display") if ctx else None
    try:
        if disp and disp.state().get("night"):
            pct = cfg.get("night_brightness", 10)
    except Exception:
        pass
    return max(0.0, min(1.0, pct / 100.0))


# ------------------------------------------------------------------ pattern renderers: (t, n, kw) -> pixels
def _p_off(t, n, kw):
    return [(0, 0, 0)] * n


def _p_solid(t, n, kw):
    c = tuple(kw.get("color", (255, 255, 255)))
    return [c] * n


def _p_listen(t, n, kw):
    """Blue breathing with a soft sweep back and forth."""
    breath = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 2.2))
    pos = (0.5 + 0.5 * math.sin(t * 1.4)) * (n - 1)
    out = []
    for i in range(n):
        d = abs(i - pos)
        glow = max(0.0, 1.0 - d / 2.5)
        base = (20, 60, 255)
        out.append(_scale(_lerp((5, 15, 60), base, glow), breath))
    return out


def _p_think(t, n, kw):
    """Three chasing dots in violet."""
    out = [(4, 2, 12)] * n
    for k in range(3):
        pos = int((t * 8 + k * n / 3) % n)
        out[pos] = (140, 60, 255)
        out[(pos - 1) % n] = (60, 25, 120)
    return out


def _p_answer(t, n, kw):
    """Green pulse that fades out over ~1.5 s, then off."""
    if t > 1.6:
        return [(0, 0, 0)] * n
    f = math.sin(min(t, 1.6) / 1.6 * math.pi)
    return [_scale((30, 220, 80), f)] * n


def _p_alert(t, n, kw):
    """Amber flash x3 (0.25 s on / 0.25 s off), then off."""
    if t > 1.5:
        return [(0, 0, 0)] * n
    on = int(t / 0.25) % 2 == 0
    return [(255, 150, 10) if on else (0, 0, 0)] * n


def _p_sunrise(t, n, kw):
    """progress 0..1: deep red -> orange -> warm white, brightness rising, filling from the centre."""
    p = max(0.0, min(1.0, float(kw.get("progress", 0.0))))
    if p < 0.5:
        col = _lerp((60, 4, 0), (255, 90, 0), p / 0.5)
    else:
        col = _lerp((255, 90, 0), (255, 215, 160), (p - 0.5) / 0.5)
    bright = 0.05 + 0.95 * p
    out = []
    mid = (n - 1) / 2
    for i in range(n):
        reach = abs(i - mid) / (mid + 0.5)          # 0 centre .. 1 edge
        lit = 1.0 if reach <= p + 0.15 else max(0.0, 1 - (reach - p) * 4)
        out.append(_scale(col, bright * lit))
    return out


def _p_notify(t, n, kw):
    """Soft white blink twice, then off."""
    if t > 1.2:
        return [(0, 0, 0)] * n
    f = 0.5 + 0.5 * math.sin(t * 2 * math.pi / 0.6 - math.pi / 2)
    return [_scale((200, 200, 220), f)] * n


def _p_error(t, n, kw):
    if t > 2.0:
        return [(0, 0, 0)] * n
    f = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 12))
    return [_scale((255, 20, 10), f)] * n


_PATTERNS = {"off": _p_off, "solid": _p_solid, "listen": _p_listen, "think": _p_think, "answer": _p_answer,
             "alert": _p_alert, "sunrise": _p_sunrise, "notify": _p_notify, "error": _p_error}
_ONE_SHOT = {"answer": 1.7, "alert": 1.6, "notify": 1.3, "error": 2.1}   # auto-return to off after this long


# ------------------------------------------------------------------ mapping tool (identify / chase / segment test)
# Paints physical LEDs directly so the owner can see which ones show through the enclosure. Always time-limited:
# "until" is a hard watchdog, so the strip can never be left stuck on a single pixel.
_manual = {"mode": None, "until": 0.0, "index": 0, "color": (255, 255, 255), "ms": 400, "t0": 0.0}
_SEG_TEST_COLORS = [(0, 120, 255), (255, 120, 0), (30, 200, 90), (200, 40, 255), (255, 220, 0), (0, 220, 220)]


def _manual_frame(now, n_total):
    """Frame for the mapping tool, or None when it is not running."""
    m = dict(_manual)
    if not m["mode"] or now >= m["until"]:
        if m["mode"]:
            _manual["mode"] = None
        return None
    frame = [(0, 0, 0)] * n_total
    f = max(0.35, _brightness_factor())            # always bright enough to spot through the enclosure
    if m["mode"] == "identify":
        if 0 <= m["index"] < n_total:
            frame[m["index"]] = _scale(m["color"], f)
    elif m["mode"] == "chase":
        step = max(0.05, m["ms"] / 1000.0)
        idx = int((now - m["t0"]) / step) % n_total
        _manual["index"] = idx
        frame[idx] = _scale((255, 255, 255), f)
        if idx > 0:
            frame[idx - 1] = _scale((255, 255, 255), f * 0.25)     # a short tail makes the direction obvious
    elif m["mode"] == "segtest":
        segs, _ = _segments()
        for k, s in enumerate(segs):
            col = _scale(_SEG_TEST_COLORS[k % len(_SEG_TEST_COLORS)], f)
            for i in range(s["start"], s["end"] + 1):
                frame[i] = col
    return frame


# ------------------------------------------------------------------ overlays (only while the strip is idle)
_overlay = {"name": None}          # "timer" | "music" | None, for state()
_last_frame = []                   # last strip colours pushed, for the debug_frame api
_last_chain = []                   # last full physical chain frame, for the debug_frame api
_music = {"level": 0.0, "bass": 0.0, "mid": 0.0, "treble": 0.0, "floor": 300.0, "peak": 2000.0,
          "bpk": 1.0, "mpk": 1.0, "tpk": 1.0, "at": 0.0, "tapped": False}


def _mic_tap(ch, rms):
    """Runs on the voice capture thread for every 80 ms frame: level + three bands, all smoothed. numpy only."""
    import numpy as np
    m = _music
    m["at"] = time.time()
    # with echo cancellation the music is removed from the mics: follow the speaker reference instead
    ref = None
    try:
        v = ctx.module("voice")
        ref = v.ref_bands() if v is not None and hasattr(v, "ref_bands") else None
    except Exception:
        ref = None
    if ref is not None:
        rms = float(ref["rms"])
    # noise floor: follows quiet quickly, loud slowly
    if rms < m["floor"]:
        m["floor"] = 0.9 * m["floor"] + 0.1 * rms
    else:
        m["floor"] = 0.998 * m["floor"] + 0.002 * rms
    # dynamic range: peak decays so a quiet passage still moves
    m["peak"] = max(rms, m["peak"] * 0.995, m["floor"] * 3 + 200)
    lvl = (rms - m["floor"] * 1.5) / max(1.0, m["peak"] - m["floor"] * 1.5)
    lvl = max(0.0, min(1.0, lvl))
    m["level"] = m["level"] + (lvl - m["level"]) * (0.55 if lvl > m["level"] else 0.25)
    if ref is not None:
        b, mid, t = float(ref["bass"]), float(ref["mid"]), float(ref["treble"])
    else:
        x = ch.astype(np.float32)
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))      # 1280 samples -> 12.5 Hz bins
        b, mid, t = float(spec[3:20].mean()), float(spec[20:160].mean()), float(spec[160:640].mean())
    for key, val, pk in (("bass", b, "bpk"), ("mid", mid, "mpk"), ("treble", t, "tpk")):
        m[pk] = max(val, m[pk] * 0.993, 1.0)
        v = max(0.0, min(1.0, (val - m[pk] * 0.12) / (m[pk] * 0.88)))
        m[key] = m[key] + (v - m[key]) * (0.6 if v > m[key] else 0.3)


def _hsv(h, s, v):
    h = (h % 360) / 60.0
    i = int(h); f = h - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]
    return (int(r * 255), int(g * 255), int(b * 255))


def _music_active():
    """Spotify is playing, Jarvis is idle and quiet, the sleep-sounds player is not running, mic frames are fresh."""
    if not ctx.config.get("music_reactive", True):
        return False
    try:
        sp = ctx.module("spotify")
        if not (sp and hasattr(sp, "is_playing") and sp.is_playing()):
            return False
        v = ctx.module("voice")
        if v is not None:
            if getattr(v, "_state", {}).get("phase", "idle") != "idle":
                return False
            sp_ev = getattr(v, "_speaking", None)
            if sp_ev is not None and sp_ev.is_set():
                return False
        sl = ctx.module("sleep")
        if sl is not None and hasattr(sl, "is_playing") and sl.is_playing():
            return False
    except Exception:
        return False
    return time.time() - _music["at"] < 1.0


def _p_music(t, n, kw):
    """Symmetric VU from the centre: bass sets the brightness, the hue drifts slowly, treble adds a white tip."""
    m = _music
    base = kw.get("base") or [(0, 0, 0)] * n
    lvl = m["level"]
    if lvl < 0.02:
        return [_scale(c, 0.2) for c in base]
    mid = (n - 1) / 2.0
    reach = lvl * (mid + 0.5)                                    # pixels lit each side of the centre
    hue = (t * 6.0) % 360                                        # a full cycle a minute
    bright = 0.35 + 0.65 * (0.5 * m["bass"] + 0.5 * lvl)
    out = []
    for i in range(n):
        d = abs(i - mid)
        if d <= reach:
            edge = max(0.0, min(1.0, reach - d))                 # anti-aliased tip
            col = _hsv(hue + d * 3.0, 0.9 - 0.4 * m["treble"] * (d / max(1.0, reach)), bright * (0.55 + 0.45 * edge))
            out.append(col)
        else:
            out.append(_scale(base[i], 0.2))
    return out


def _timer_running():
    """The soonest running timer as (elapsed_fraction, remaining_s) or None."""
    if not ctx.config.get("timer_fill", True):
        return None
    try:
        tm = ctx.module("timers")
        rows = tm.state().get("timers") if tm and hasattr(tm, "state") else None
    except Exception:
        return None
    if not rows:
        return None
    r = rows[0]
    total = max(1, int(r.get("total") or 0))
    remaining = max(0, float(r.get("remaining") or 0))
    return max(0.0, min(1.0, 1.0 - remaining / total)), remaining


def _p_timerfill(t, n, kw):
    """The strip fills from its start as the timer runs; a brighter head pixel; the last tenth pulses gently."""
    p = float(kw.get("progress", 0.0))
    col = tuple(kw.get("color", (255, 140, 40)))
    base = kw.get("base") or [(0, 0, 0)] * n
    filled = p * n
    pulse = 1.0
    if p >= 0.9:
        pulse = 0.7 + 0.3 * (0.5 + 0.5 * math.sin(t * 2 * math.pi))     # 1 Hz breathing near the end
    out = []
    for i in range(n):
        if i + 1 <= filled:
            f = 0.75 * pulse
            if i == int(filled) - 1 or (i == n - 1 and filled >= n):   # head pixel
                f = 1.0 * pulse
            out.append(_scale(col, f))
        elif i < filled:                                                 # partial head pixel
            out.append(_lerp(_scale(base[i], 0.3), col, filled - i))
        else:
            out.append(_scale(base[i], 0.3))
    return out


# ------------------------------------------------------------------ public API
def _base():
    """What the bar shows when nothing else is going on: the lamp colour if the lamp is on, else off."""
    lamp = (ctx.config.get("lamp") or {}) if ctx else {}
    if lamp.get("on"):
        f = max(0.0, min(1.0, float(lamp.get("brightness", 60)) / 100.0))
        c = tuple(int(x * f) for x in (lamp.get("color") or [255, 170, 90])[:3])
        return "solid", {"color": c, "lamp": True}
    return "off", {}


def pattern(name, **kw):
    """Switch the bar to a named pattern. "off"/"idle" mean "back to the base state" (lamp or dark)."""
    if name in ("off", "idle") and not kw.get("force_off"):
        name, kw = _base()
    if name not in _PATTERNS:
        name = "off"
    with _lock:
        if _current["name"] == "sunrise" and name == "sunrise":
            _current["kw"] = kw               # progress update, keep timing
        else:
            _current.update({"name": name, "kw": kw, "since": time.time()})
    return {"ok": True, "pattern": name}


def state():
    with _lock:
        cur = dict(_current)
    return {"pattern": cur["name"], "lamp": (ctx.config.get("lamp") if ctx else None), "enabled": bool(ctx.config.get("enabled", True)) if ctx else True,
            "brightness": ctx.config.get("brightness") if ctx else None,
            "spi_error": _spi_err, "progress": cur["kw"].get("progress"),
            "count": _count() if ctx else None,
            "segments": (_clean_segments(ctx.config.get("segments"), _count()) if ctx else []),
            "mapping": _manual["mode"], "mapping_index": _manual["index"],
            "overlay": _overlay["name"], "music_level": round(_music["level"], 2),
            "timer_fill": bool(ctx.config.get("timer_fill", True)) if ctx else True,
            "music_reactive": bool(ctx.config.get("music_reactive", True)) if ctx else True}


def _color(v, default=(255, 255, 255)):
    try:
        r, g, b = [max(0, min(255, int(x))) for x in list(v)[:3]]
        return (r, g, b)
    except Exception:
        return tuple(default)


def _pct(v, default):
    try:
        return max(0, min(100, int(float(v))))
    except Exception:
        return default


def api(action, params):
    if action == "pattern":
        name = str(params.get("name", "off"))[:20]
        kw = {}
        if "color" in params: kw["color"] = _color(params["color"])
        if "progress" in params:
            try: kw["progress"] = max(0.0, min(1.0, float(params["progress"])))
            except Exception: pass
        return pattern(name, **kw)
    if action == "off":
        return pattern("off")
    if action == "lamp":
        # {on, color:[r,g,b], brightness:0-100} -> persisted; the bar shows it whenever idle
        lamp = dict(ctx.config.get("lamp") or {})
        if "on" in params: lamp["on"] = bool(params["on"])
        if "color" in params: lamp["color"] = list(_color(params["color"], (255, 170, 90)))
        if "brightness" in params: lamp["brightness"] = _pct(params["brightness"], 60)
        ctx.config["lamp"] = lamp; ctx.save_config()
        with _lock:
            cur = _current["name"]
        if cur in ("off", "solid"):
            pattern("idle")
        return {"ok": True, "lamp": lamp}
    if action == "set_brightness":
        ctx.config["brightness"] = _pct(params.get("pct", 60), 60); ctx.save_config()
        return {"ok": True}
    if action == "test":
        pattern("alert")
        return {"ok": True}
    if action == "set_options":
        # {timer_fill, music_reactive, bar_mode, timer_color}
        if "timer_fill" in params: ctx.config["timer_fill"] = bool(params["timer_fill"])
        if "music_reactive" in params: ctx.config["music_reactive"] = bool(params["music_reactive"])
        if "bar_mode" in params and params["bar_mode"] in ("off", "mirror"): ctx.config["bar_mode"] = params["bar_mode"]
        if "timer_color" in params: ctx.config["timer_color"] = list(_color(params["timer_color"], (255, 140, 40)))
        ctx.save_config()
        return {"ok": True, "timer_fill": ctx.config.get("timer_fill", True), "music_reactive": ctx.config.get("music_reactive", True), "bar_mode": ctx.config.get("bar_mode", "off")}
    if action == "debug_frame":
        return {"ok": True, "overlay": _overlay["name"], "pattern": _current["name"], "strip": list(_last_frame),
                "chain": list(_last_chain), "manual": _manual["mode"], "manual_index": _manual["index"],
                "music": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in _music.items()}}
    # ---- mapping tool: which LEDs are visible through the enclosure
    if action == "segments":
        segs, configured = _segments()
        return {"ok": True, "count": _count(), "configured": configured,
                "segments": _clean_segments(ctx.config.get("segments"), _count()), "effective": segs}
    if action == "set_segments":
        segs = _clean_segments(params.get("segments"), _count())
        ctx.config["segments"] = segs
        if segs:
            ctx.config["bar_mode"] = "off"          # the onboard bar is hidden in the enclosure: never light it
        ctx.save_config()
        _manual["mode"] = None                      # back to normal rendering straight away
        ctx.log(f"leds: {len(segs)} visible segment(s): " + ", ".join(f"{s['name']} {s['start']}-{s['end']}" + ("R" if s["reverse"] else "") for s in segs) if segs else "leds: segments cleared")
        return {"ok": True, "segments": segs}
    if action == "identify":
        try:
            idx = int(params.get("index", 0))
        except (TypeError, ValueError):
            return {"ok": False, "error": "index must be a number"}
        n_total = _count()
        if idx < 0:                                  # index -1 simply stops the tool
            _manual["mode"] = None
            return {"ok": True, "stopped": True}
        idx = max(0, min(n_total - 1, idx))
        secs = max(1.0, min(600.0, float(params.get("seconds", 30) or 30)))
        _manual.update({"mode": "identify", "index": idx, "color": _color(params.get("color"), (255, 255, 255)),
                        "until": time.time() + secs, "t0": time.time()})
        return {"ok": True, "index": idx, "seconds": secs}
    if action == "chase":
        if not bool(params.get("on", True)):
            _manual["mode"] = None
            return {"ok": True, "chasing": False}
        ms = max(80, min(3000, int(float(params.get("ms", 400) or 400))))
        _manual.update({"mode": "chase", "ms": ms, "t0": time.time(), "until": time.time() + 300, "index": 0})
        return {"ok": True, "chasing": True, "ms": ms}
    if action == "test_segments":
        secs = max(1.0, min(30.0, float(params.get("seconds", 3) or 3)))
        segs, _c = _segments()
        _manual.update({"mode": "segtest", "until": time.time() + secs, "t0": time.time()})
        return {"ok": True, "seconds": secs,
                "segments": [{"name": s["name"], "start": s["start"], "end": s["end"],
                              "color": _SEG_TEST_COLORS[k % len(_SEG_TEST_COLORS)]} for k, s in enumerate(segs)]}
    if action == "manual_off":
        _manual["mode"] = None
        return {"ok": True}
    return {"ok": False, "error": f"unknown action {action}"}


def start(c):
    global ctx, _last_frame, _last_chain
    ctx = c
    last_pixels = None
    tap_tried = 0.0
    t_overlay = time.time()
    while True:
        try:
            now = time.time()
            n_total = _count()
            segs, configured = _segments()                   # re-read: the owner can remap while it runs
            n = max(1, _seg_len(segs))                       # pixels on the logical canvas
            if not _music["tapped"] and now - tap_tried > 5:
                tap_tried = now
                v = ctx.module("voice")
                if v is not None and hasattr(v, "add_mic_tap"):
                    v.add_mic_tap(_mic_tap); _music["tapped"] = True
            manual = _manual_frame(now, n_total)
            if manual is not None:                           # mapping tool: paint physical LEDs, skip everything else
                _overlay["name"] = "mapping"
                _last_chain = manual
                if manual != last_pixels:
                    _push(manual)
                    last_pixels = manual
                time.sleep(0.05)
                continue
            with _lock:
                name, kw, since = _current["name"], dict(_current["kw"]), _current["since"]
            t = now - since
            if name in _ONE_SHOT and t > _ONE_SHOT[name]:
                bname, bkw = _base()
                with _lock:
                    if _current["name"] == name:
                        _current.update({"name": bname, "kw": bkw, "since": now})
                name, kw, t = bname, bkw, 0
            overlay = None
            if name in ("off", "solid") and ctx.config.get("enabled", True):
                base_px = _PATTERNS[name](t, n, kw)
                if _music_active():
                    overlay = "music"
                    strip = _p_music(now - t_overlay, n, {"base": base_px})
                else:
                    tr = _timer_running()
                    if tr is not None:
                        overlay = "timer"
                        strip = _p_timerfill(now - t_overlay, n, {"progress": tr[0], "color": _color(ctx.config.get("timer_color"), (255, 140, 40)), "base": base_px})
                    else:
                        strip = base_px
            elif not ctx.config.get("enabled", True):
                strip = [(0, 0, 0)] * n
            else:
                strip = _PATTERNS[name](t, n, kw)
            _overlay["name"] = overlay
            f = _brightness_factor()
            strip = [_scale(p, f) for p in strip]
            _last_frame = strip
            pixels = _paint(strip, segs, n_total, configured)
            _last_chain = pixels
            # only touch SPI when the frame changed or every 1 s as a keep-alive
            if pixels != last_pixels or int(t * 1) != int((t - 1 / _fps) * 1):
                _push(pixels)
                last_pixels = pixels
            if overlay == "music":
                time.sleep(0.05)                                 # 20 Hz is plenty and keeps the CM4 cool
            elif overlay == "timer":
                time.sleep(0.1)
            else:
                time.sleep(1.0 / _fps if name not in ("off", "solid") else 0.25)
        except Exception as e:
            ctx.log(f"led loop error: {e}")
            time.sleep(1)


# ------------------------------------------------------------------ voice control ("Jarvis, lights to blue")
_COLORS = {"white": (255, 245, 230), "warm": (255, 160, 70), "warm white": (255, 160, 70), "soft white": (255, 200, 140),
           "daylight": (255, 245, 230), "cool white": (200, 225, 255), "red": (255, 20, 0), "orange": (255, 110, 0),
           "amber": (255, 140, 0), "yellow": (255, 220, 0), "green": (30, 200, 90), "teal": (0, 200, 180), "cyan": (0, 220, 255),
           "blue": (0, 120, 255), "purple": (150, 40, 255), "violet": (150, 40, 255), "pink": (255, 60, 140), "magenta": (255, 0, 200),
           "night light": (120, 20, 0), "ocean": (0, 140, 255), "forest": (30, 200, 90), "rose": (255, 60, 120)}

def _lamp_set(**kw):
    lamp = dict(ctx.config.get("lamp") or {})
    lamp.update(kw); ctx.config["lamp"] = lamp; ctx.save_config()
    pattern("idle")
    return lamp

def intent(text):
    """Spoken light commands. Returns a short reply or None when the text is not about the lights."""
    import re
    t = (text or "").lower().strip()
    if not re.search(r"\b(light|lights|lamp|light bar|led|leds|strip)\b", t):
        return None
    lamp = ctx.config.get("lamp") or {}
    m = re.search(r"(\d{1,3})\s*(%|percent)", t)
    if m:
        pct = max(1, min(100, int(m.group(1)))); _lamp_set(on=True, brightness=pct); return f"Lights at {pct} percent."
    if re.search(r"\b(off|out|kill)\b", t):
        _lamp_set(on=False); return "Lights off."
    for name in sorted(_COLORS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(name) + r"\b", t):
            _lamp_set(on=True, color=list(_COLORS[name])); return f"Lights set to {name}."
    if re.search(r"\b(dim|dimmer|lower|down|darker)\b", t):
        pct = max(5, int(lamp.get("brightness", 60)) - 20); _lamp_set(on=True, brightness=pct); return f"Dimmed to {pct} percent."
    if re.search(r"\b(bright|brighter|up|higher|max|full)\b", t):
        pct = min(100, int(lamp.get("brightness", 60)) + 20); _lamp_set(on=True, brightness=pct); return f"Lights at {pct} percent."
    if re.search(r"\b(on|turn on|switch on)\b", t):
        _lamp_set(on=True); return "Lights on."
    if re.search(r"\b(what|status|are the)\b", t):
        return f"The lights are {'on at ' + str(lamp.get('brightness', 60)) + ' percent' if lamp.get('on') else 'off'}."
    return None
