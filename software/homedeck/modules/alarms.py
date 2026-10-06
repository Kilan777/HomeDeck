"""Alarms with LED sunrise, light-retry ("keep ringing until the light is on") and a morning routine.

Alarm record (config["alarms"]):
  {id, time "07:00", days [0-6, Mon=0] ([] = one-off), enabled, label, sound "default"|"spotify:..."|path,
   sunrise_min 20, light_retry {enabled, lux_threshold, retry_after_min, max_retries}, routine true}
Events: "alarm_ringing" {id,label}, "alarm_stopped" {id}, "routine" {text}
"""
import datetime as dt, os, subprocess, threading, time, uuid, wave

NAME = "alarms"
DEFAULTS = {
    "alarms": [],
    "routine": {"enabled": True, "spoken": True},
    "auto_dismiss_min": 10,          # stop ringing on its own after this long (retries still apply)
}

ctx = None
_lock = threading.Lock()
_s = {"ringing": False, "ringing_id": None, "snoozed_until": None, "retries": 0, "routine_last": None,
      "next_alarm": None, "fired": {}, "light_pending": None}
_player = None            # subprocess playing the sound
_stop_flag = threading.Event()


# ------------------------------------------------------------------ sound
def _default_wav():
    """Rising two-tone beep loop, 8 s, generated once with numpy."""
    p = os.path.join(ctx.data_dir, "sounds", "alarm.wav")
    if os.path.isfile(p):
        return p
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        import numpy as np
        sr = 22050
        t = np.arange(sr * 8) / sr
        beat = 0.5                                        # seconds per beep
        idx = (t // beat).astype(int)
        freq = np.where(idx % 2 == 0, 880.0, 1174.7)      # A5 / D6 alternating
        rise = 1.0 + 0.5 * (t / 8.0)                      # pitch rises over the loop
        env = (t % beat) < 0.32                           # beep then gap
        sig = 0.35 * np.sin(2 * np.pi * freq * rise * t) * env
        fade = np.minimum(1.0, (t % beat) / 0.02)         # click-free attack
        pcm = (sig * fade * 32767).astype("<i2")
        with wave.open(p, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())
    except Exception as e:
        ctx.log(f"could not generate alarm.wav: {e}")
    return p


def _play(sound, label="Alarm"):
    """Start the alarm sound until _stop_sound(): a Spotify URI plays music, anything else rings the chosen tone."""
    global _player
    _stop_sound()
    _stop_flag.clear()
    if isinstance(sound, str) and sound.startswith("spotify:"):
        sp = ctx.module("spotify")
        if sp and hasattr(sp, "play_uri"):
            try:
                sp.play_uri(sound)
                _s["spotify_alarm"] = True
                return
            except Exception as e:
                ctx.log(f"spotify alarm failed, using tone: {e}")
    _s["spotify_alarm"] = False
    r = ctx.module("ringer")
    if r and hasattr(r, "ring"):
        try:
            line = f"{label}. It's {time.strftime('%-I:%M %p').lower()}." if (r.say_label() and label) else None
            r.ring("alarm", label, line)
            return
        except Exception as e:
            ctx.log(f"ringer failed, using the old tone: {e}")
    path = _default_wav() if sound in (None, "", "default") or not os.path.isfile(str(sound)) else sound

    def loop():
        global _player
        while not _stop_flag.is_set():
            try:
                _player = subprocess.Popen(["aplay", "-q", "-D", "default", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                _player.wait()
            except Exception as e:
                ctx.log(f"aplay failed: {e}")
                _stop_flag.wait(5)
    threading.Thread(target=loop, daemon=True).start()


def _stop_sound():
    global _player
    _stop_flag.set()
    if _player and _player.poll() is None:
        try:
            _player.terminate()
        except Exception:
            pass
    _player = None
    r = ctx.module("ringer")
    if r and hasattr(r, "stop"):
        try:
            if r.state().get("kind") == "alarm":
                r.stop()
        except Exception:
            pass
    if _s.get("spotify_alarm"):                       # only a music alarm pauses Spotify; a tone alarm leaves music alone
        _s["spotify_alarm"] = False
        sp = ctx.module("spotify")
        if sp and hasattr(sp, "pause"):
            try:
                sp.pause()
            except Exception:
                pass


# ------------------------------------------------------------------ helpers
def _lux():
    d = ctx.module("display")
    try:
        v = d.state().get("lux") if d else None
        return float(v) if v is not None else None
    except Exception:
        return None


def _next_fire(a, now=None):
    """Next datetime this alarm should ring, or None."""
    now = now or dt.datetime.now()
    try:
        h, m = [int(x) for x in a.get("time", "07:00").split(":")]
    except Exception:
        return None
    days = a.get("days") or []
    for d in range(0, 8):
        cand = (now + dt.timedelta(days=d)).replace(hour=h, minute=m, second=0, microsecond=0)
        if cand <= now:
            continue
        if not days or cand.weekday() in days:
            return cand
    return None


def _leds(name, **kw):
    l = ctx.module("leds")
    if l and hasattr(l, "pattern"):
        try:
            l.pattern(name, **kw)
        except Exception:
            pass


def _say(text):
    v = ctx.module("voice")
    if v and hasattr(v, "say"):
        try:
            v.say(text)
        except Exception as e:
            ctx.log(f"say failed: {e}")


def _ring(a, retry=False):
    with _lock:
        _s["ringing"] = True
        _s["ringing_id"] = a["id"]
        _s["snoozed_until"] = None
        _s["ring_started"] = time.time()
    _play(a.get("sound", "default"), a.get("label") or "Alarm")
    _leds("alert")
    ctx.emit("alarm_ringing", {"id": a["id"], "label": a.get("label", "Alarm"), "retry": retry})
    ctx.log(f"alarm ringing: {a.get('label', a['id'])}{' (light retry)' if retry else ''}")


def _stop_ring(reason):
    with _lock:
        aid = _s["ringing_id"]
        _s["ringing"] = False
        _s["ringing_id"] = None
    _stop_sound()
    _leds("off")
    ctx.emit("alarm_stopped", {"id": aid, "reason": reason})


def _arm_light_retry(a):
    lr = a.get("light_retry") or {}
    if not lr.get("enabled", True):
        return
    with _lock:
        _s["light_pending"] = {"id": a["id"], "at": time.time() + 60 * lr.get("retry_after_min", 3),
                               "threshold": lr.get("lux_threshold", 30), "max": lr.get("max_retries", 5)}


def _routine(a):
    """Morning summary from weather / bikes / calendar, spoken and shown as a popup."""
    if not (a.get("routine", True) and ctx.config.get("routine", {}).get("enabled", True)):
        return
    parts = [f"Good morning. It's {dt.datetime.now().strftime('%-I:%M %p')}."]
    try:
        w = ctx.module("weather").state()
        cur = w.get("current") or {}
        today = (w.get("daily") or [{}])[0]
        if cur.get("temp") is not None:
            parts.append(f"It's {round(cur['temp'])} degrees and {cur.get('summary', '').lower()}".rstrip() + ".")
        if today.get("high") is not None:
            parts.append(f"High of {round(today['high'])}, low of {round(today.get('low', 0))}.")
        if today.get("precip_chance") not in (None, 0):
            parts.append(f"{today['precip_chance']} percent chance of rain.")
    except Exception:
        pass
    try:
        b = ctx.module("bikes").state()
        st = (b.get("stations") or [{}])[0]
        if st.get("name"):
            parts.append(f"{st.get('ebikes', 0)} e-bikes and {st.get('bikes', 0)} bikes at {st['name']}.")
            if b.get("low"):
                parts.append("That's low, leave early.")
    except Exception:
        pass
    try:
        c = ctx.module("calendar").state()
        evs = c.get("today") or []
        if evs:
            first = evs[0]
            parts.append(f"You have {len(evs)} event{'s' if len(evs) != 1 else ''} today, first is {first.get('title')} at {first.get('start_str', '')}.")
        else:
            parts.append("Nothing on the calendar today.")
    except Exception:
        pass
    try:
        aq = ctx.module("sensors").state()
        co2 = (aq.get("scd40") or {}).get("co2_ppm")
        if co2 and co2 > 1000:
            parts.append(f"CO2 is {co2}, open a window.")
    except Exception:
        pass
    text = " ".join(parts)
    with _lock:
        _s["routine_last"] = {"t": time.time(), "text": text}
    ctx.emit("routine", {"text": text})
    if ctx.config.get("routine", {}).get("spoken", True):
        _say(text)


# ------------------------------------------------------------------ public
def state():
    with _lock:
        out = {k: _s.get(k) for k in ("ringing", "ringing_id", "snoozed_until", "retries", "routine_last", "next_alarm", "light_pending")}
    out["alarms"] = ctx.config.get("alarms", []) if ctx else []
    return out


def api(action, params):
    alarms = ctx.config.setdefault("alarms", [])
    if action == "save":
        a = dict(params.get("alarm") or params)
        a.pop("alarm", None)
        a["id"] = str(a.get("id") or uuid.uuid4().hex[:8])[:16]
        # validate the fields that reach the scheduler, the player and the LED sunrise
        import re as _re
        if not _re.match(r"^\d{2}:\d{2}$", str(a.get("time", "07:00"))) or not (0 <= int(a["time"][:2]) < 24 and 0 <= int(a["time"][3:]) < 60):
            return {"ok": False, "error": "time must be HH:MM"}
        try:
            a["days"] = sorted({int(d) for d in (a.get("days") or []) if 0 <= int(d) <= 6})
        except (TypeError, ValueError):
            return {"ok": False, "error": "days must be 0-6"}
        a["label"] = str(a.get("label") or "Alarm")[:60]
        try:
            a["sunrise_min"] = max(0, min(120, int(a.get("sunrise_min", 20))))
        except (TypeError, ValueError):
            a["sunrise_min"] = 20
        snd = str(a.get("sound") or "default")
        if not (snd == "default" or _re.match(r"^spotify:(track|album|playlist|artist|show|episode):[A-Za-z0-9]+$", snd)
                or (snd.endswith(".wav") and os.path.realpath(snd).startswith(os.path.realpath(os.path.join(ctx.data_dir, "sounds")) + os.sep))):
            snd = "default"                     # only the built-in tone, a Spotify URI, or a wav inside the sounds folder
        a["sound"] = snd
        lr = a.get("light_retry") if isinstance(a.get("light_retry"), dict) else {}
        try:
            a["light_retry"] = {"enabled": bool(lr.get("enabled", True)), "lux_threshold": max(0, min(10000, float(lr.get("lux_threshold", 30)))),
                                "retry_after_min": max(1, min(60, float(lr.get("retry_after_min", 3)))), "max_retries": max(0, min(20, int(lr.get("max_retries", 5))))}
        except (TypeError, ValueError):
            a["light_retry"] = {"enabled": True, "lux_threshold": 30, "retry_after_min": 3, "max_retries": 5}
        a["routine"] = bool(a.get("routine", True)); a["enabled"] = bool(a.get("enabled", True))
        a.setdefault("time", "07:00"); a.setdefault("days", [0, 1, 2, 3, 4]); a.setdefault("enabled", True)
        a.setdefault("label", "Alarm"); a.setdefault("sound", "default"); a.setdefault("sunrise_min", 20)
        a.setdefault("light_retry", {"enabled": True, "lux_threshold": 30, "retry_after_min": 3, "max_retries": 5})
        a.setdefault("routine", True)
        for i, x in enumerate(alarms):
            if x.get("id") == a["id"]:
                alarms[i] = a; break
        else:
            alarms.append(a)
        ctx.save_config(); _recompute()
        return {"ok": True, "alarm": a}
    if action == "delete":
        ctx.config["alarms"] = [x for x in alarms if x.get("id") != params.get("id")]
        ctx.save_config(); _recompute()
        return {"ok": True}
    if action == "toggle":
        for x in alarms:
            if x.get("id") == params.get("id"):
                x["enabled"] = bool(params.get("enabled", not x.get("enabled", True)))
        ctx.save_config(); _recompute()
        return {"ok": True}
    if action == "snooze":
        try:
            mins = max(1.0, min(120.0, float(params.get("min", 9))))
        except (TypeError, ValueError):
            mins = 9.0
        with _lock:
            aid = _s["ringing_id"]
            _s["snoozed_until"] = time.time() + 60 * mins
        _stop_ring("snooze")
        with _lock:
            _s["ringing_id"] = aid          # remember which alarm to re-ring
        return {"ok": True, "snoozed_until": _s["snoozed_until"]}
    if action == "dismiss":
        with _lock:
            aid = _s["ringing_id"]
        a = next((x for x in alarms if x.get("id") == aid), None)
        _stop_ring("dismiss")
        if a:
            _arm_light_retry(a)
            threading.Thread(target=_routine, args=(a,), daemon=True).start()
        return {"ok": True}
    if action == "stop":                    # hard stop: no light retries
        _stop_ring("stop")
        with _lock:
            _s["light_pending"] = None; _s["retries"] = 0; _s["snoozed_until"] = None
        return {"ok": True}
    if action == "test":                    # ring the alarm tone for 5 s
        r = ctx.module("ringer")
        if r and hasattr(r, "api"):
            return r.api("preview", {"tone": r.state().get("alarm_tone"), "volume": r.state().get("alarm_volume"), "seconds": 5})
        _play("default"); _leds("alert")
        threading.Timer(5, _stop_sound).start()
        return {"ok": True}
    if action == "sunrise_test":
        prog = float(params.get("progress", 0.5))
        _leds("sunrise", progress=prog)
        return {"ok": True}
    return {"ok": False, "error": f"unknown action {action}"}


def _recompute():
    now = dt.datetime.now()
    best = None
    for a in ctx.config.get("alarms", []):
        if not a.get("enabled", True):
            continue
        nf = _next_fire(a, now)
        if nf and (best is None or nf < best[1]):
            best = (a, nf)
    with _lock:
        _s["next_alarm"] = {"id": best[0]["id"], "label": best[0].get("label", "Alarm"), "at": best[1].timestamp(),
                            "at_str": best[1].strftime("%a %H:%M")} if best else None
    return best


def on_config():
    _recompute()


def start(c):
    global ctx
    ctx = c
    _default_wav()
    _recompute()
    while True:
        try:
            now = time.time()
            nowdt = dt.datetime.now()
            alarms = ctx.config.get("alarms", [])
            # 1. sunrise ramps and firing
            for a in alarms:
                if not a.get("enabled", True):
                    continue
                nf = _next_fire(a, nowdt)
                if not nf:
                    continue
                secs = (nf - nowdt).total_seconds()
                sun = 60 * float(a.get("sunrise_min", 0) or 0)
                if sun and 0 < secs <= sun and not _s["ringing"]:
                    _leds("sunrise", progress=1 - secs / sun)
                # fire when within the last second (loop runs every 1 s); guard against double fire
                key = f"{a['id']}@{nf.isoformat()}"
                if secs <= 1 and _s["fired"].get(a["id"]) != key:
                    _s["fired"][a["id"]] = key
                    with _lock:
                        _s["retries"] = 0; _s["light_pending"] = None
                    _ring(a)
                    if not a.get("days"):                       # one-off: disable after firing
                        a["enabled"] = False; ctx.save_config()
            # 2. snooze expiry
            with _lock:
                su, rid = _s["snoozed_until"], _s["ringing_id"]
            if su and now >= su and not _s["ringing"]:
                a = next((x for x in alarms if x.get("id") == rid), None)
                with _lock:
                    _s["snoozed_until"] = None
                if a:
                    _ring(a, retry=True)
            # 3. auto-dismiss after N minutes of ringing (treated like dismiss: light retry still applies)
            if _s["ringing"] and now - _s.get("ring_started", now) > 60 * ctx.config.get("auto_dismiss_min", 10):
                a = next((x for x in alarms if x.get("id") == _s["ringing_id"]), None)
                _stop_ring("timeout")
                if a:
                    _arm_light_retry(a)
            # 4. light retry: still dark after retry_after_min -> ring again
            with _lock:
                lp = _s["light_pending"]
            if lp and not _s["ringing"] and now >= lp["at"]:
                lux = _lux()
                a = next((x for x in alarms if x.get("id") == lp["id"]), None)
                if lux is not None and lux >= lp["threshold"]:
                    with _lock:
                        _s["light_pending"] = None; _s["retries"] = 0
                    ctx.log("light is on, alarm retries cleared")
                elif a and _s["retries"] < lp["max"]:
                    with _lock:
                        _s["retries"] += 1
                        _s["light_pending"] = None
                    _ring(a, retry=True)
                    _arm_light_retry(a)          # arm the next one; dismiss re-arms too
                else:
                    with _lock:
                        _s["light_pending"] = None
            if int(now) % 30 == 0:
                _recompute()
        except Exception as e:
            ctx.log(f"alarm loop error: {e}")
        time.sleep(1)
