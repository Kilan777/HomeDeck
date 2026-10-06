"""Sleep sounds: rain, ocean, white/pink/brown noise and a fan hum, generated once with numpy into
<data_dir>/sounds/sleep_<name>.wav, streamed seamlessly to the shared ALSA "default" device, with a sleep timer that
fades the system volume out over the last minute and then restores it.

Voice: "play rain sounds", "white noise for 45 minutes", "ocean sounds until my alarm", "stop the sounds".
API: start {sound, minutes | until_alarm}, stop, set_timer {minutes | until_alarm}, sounds.
"""
import os, re, subprocess, threading, time, wave

import numpy as np

NAME = "sleep"
DEFAULTS = {"default_sound": "rain", "default_minutes": 45, "fade_s": 60, "loop_s": 60}
SOUNDS = [("rain", "Rain"), ("ocean", "Ocean"), ("white", "White noise"), ("pink", "Pink noise"), ("brown", "Brown noise"), ("hum", "Fan hum")]
RATE = 48000
ctx = None
_lock = threading.Lock()
_s = {"active": False, "sound": None, "ends_at": None, "started_at": None, "prev_volume": None, "fading": False, "error": None}
_proc = None
_writer = None
_stop_evt = threading.Event()
_timer_thread = None


# ------------------------------------------------------------------ sound synthesis
def _norm(x, dbfs=-18.0):
    rms = float(np.sqrt(np.mean(x ** 2))) or 1e-9
    x = x * (10 ** (dbfs / 20) / rms)
    return np.clip(x, -0.95, 0.95)


def _lowpass(x, cutoff, order=2):
    """Zero-phase low-pass via the FFT (Butterworth magnitude); fine for shaping noise, no scipy needed."""
    n = len(x)
    X = np.fft.rfft(x.astype(np.float32))
    f = np.fft.rfftfreq(n, 1.0 / RATE)
    H = 1.0 / np.sqrt(1.0 + (f / float(cutoff)) ** (2 * order))
    return np.fft.irfft(X * H, n=n).astype(np.float32)


def _pink(n, rng):
    """Voss-McCartney pink noise: sum of octave-spaced random rows."""
    rows = 16
    out = np.zeros(n, dtype=np.float32)
    for r in range(rows):
        step = 2 ** r
        vals = rng.standard_normal(n // step + 2).astype(np.float32)
        out += np.repeat(vals, step)[:n]
    return out / np.sqrt(rows)


def _brown(n, rng):
    x = np.cumsum(rng.standard_normal(n).astype(np.float32))
    x -= _lowpass(x, 0.5)                       # remove the wander so it does not drift off scale
    return x


def _seamless(x, secs=2.0):
    """Crossfade the tail into the head so the loop point is inaudible."""
    k = int(RATE * secs)
    fade = np.linspace(0, 1, k, dtype=np.float32)
    head = x[:k] * fade + x[-k:] * (1 - fade)
    return np.concatenate([head, x[k:-k]])


def _synth(name, secs):
    rng = np.random.default_rng(abs(hash(name)) % (2 ** 32))
    n = int(RATE * secs) + int(RATE * 2)
    if name == "white":
        x = rng.standard_normal(n).astype(np.float32)
        x = _lowpass(x, 9000) * 0.6 + x * 0.4           # take the sizzle off
    elif name == "pink":
        x = _pink(n, rng)
    elif name == "brown":
        x = _brown(n, rng)
    elif name == "hum":
        t = np.arange(n) / RATE
        x = _lowpass(rng.standard_normal(n).astype(np.float32), 350)
        x = _norm(x, -18) + 0.045 * np.sin(2 * np.pi * 120 * t).astype(np.float32) + 0.02 * np.sin(2 * np.pi * 60 * t).astype(np.float32)
    elif name == "ocean":
        base = _brown(n, rng)
        base = _lowpass(base, 900)
        t = np.arange(n) / RATE
        swell = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(2 * np.pi * t / 10.5)) ** 1.6 * (0.7 + 0.3 * np.sin(2 * np.pi * t / 37 + 1.3))
        hiss = _lowpass(rng.standard_normal(n).astype(np.float32), 4000) - _lowpass(rng.standard_normal(n).astype(np.float32), 800)
        x = base * swell.astype(np.float32) + 0.25 * hiss * (swell.astype(np.float32) ** 2)
    else:                                                # rain
        w = rng.standard_normal(n).astype(np.float32)
        body = _lowpass(w, 6000) - _lowpass(w, 500)      # band-passed steady rain
        body = _norm(body, -20)
        drops = np.zeros(n, dtype=np.float32)
        count = int(secs * 40)
        pos = rng.integers(0, n - 4000, count)
        for p in pos:
            ln = int(rng.integers(300, 1600)); amp = float(rng.uniform(0.05, 0.22))
            env = np.exp(-np.linspace(0, 6, ln)).astype(np.float32)
            drops[p:p + ln] += amp * env * rng.standard_normal(ln).astype(np.float32)
        drops = _lowpass(drops, 5000)
        x = body + drops
    x = _norm(x.astype(np.float32), -18)
    return _seamless(x)


def _path(name):
    return os.path.join(ctx.data_dir, "sounds", f"sleep_{name}.wav")


def _ensure(name):
    p = _path(name)
    if os.path.isfile(p) and os.path.getsize(p) > RATE:
        return p
    os.makedirs(os.path.dirname(p), exist_ok=True)
    t = time.time()
    pcm = (_synth(name, int(ctx.config.get("loop_s", 60))) * 32767).astype(np.int16)
    with wave.open(p + ".tmp", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm.tobytes())
    os.replace(p + ".tmp", p)
    ctx.log(f"generated {name} ({len(pcm) / RATE:.0f} s) in {time.time() - t:.1f} s")
    return p


# ------------------------------------------------------------------ playback
def _audio():
    return ctx.module("audio")


def _volume():
    a = _audio()
    try:
        return a.volume() if a and hasattr(a, "volume") else None
    except Exception:
        return None


def _set_volume(pct):
    a = _audio()
    try:
        if a and hasattr(a, "set_volume"):
            a.set_volume(int(max(0, min(100, pct))))
    except Exception:
        pass


def _writer_loop(path, stop_evt):
    """Feed the loop to a raw-PCM aplay over a pipe: seamless, and a fade-in on the first two seconds."""
    global _proc
    with wave.open(path, "rb") as w:
        data = w.readframes(w.getnframes())
    pcm = np.frombuffer(data, dtype=np.int16)
    slice_n = RATE // 2
    try:
        _proc = subprocess.Popen(["aplay", "-q", "-D", "default", "-t", "raw", "-f", "S16_LE", "-r", str(RATE), "-c", "1"],
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        with _lock:
            _s["error"] = f"aplay failed: {e}"; _s["active"] = False
        return
    i = 0; first = True
    try:
        while not stop_evt.is_set():
            chunk = pcm[i:i + slice_n]
            if len(chunk) < slice_n:
                chunk = np.concatenate([chunk, pcm[:slice_n - len(chunk)]]); i = slice_n - len(pcm[i:i + slice_n])
            else:
                i += slice_n
            if first:
                first = False
                ramp = np.linspace(0, 1, len(chunk), dtype=np.float32) ** 2
                chunk = (chunk.astype(np.float32) * ramp).astype(np.int16)
            _proc.stdin.write(chunk.tobytes())
    except Exception as e:
        if not stop_evt.is_set():
            ctx.log(f"playback ended: {e}")
    finally:
        try:
            _proc.stdin.close()
        except Exception:
            pass
        try:
            _proc.terminate(); _proc.wait(timeout=2)
        except Exception:
            try: _proc.kill()
            except Exception: pass


def _timer_loop(stop_evt):
    fade_s = float(ctx.config.get("fade_s", 60))
    while not stop_evt.is_set():
        with _lock:
            ends = _s["ends_at"]; active = _s["active"]
        if not active:
            return
        if ends:
            left = ends - time.time()
            if left <= 0:
                ctx.log("sleep timer done")
                stop(reason="timer")
                return
            if left <= fade_s:
                with _lock:
                    fading = _s["fading"]; prev = _s["prev_volume"]
                if not fading:
                    with _lock:
                        _s["fading"] = True; _s["fade_from"] = _volume() or prev or 30
                frac = max(0.0, left / fade_s)
                target = int(round((_s.get("fade_from") or 30) * frac))
                if target < 2: target = 2
                if _volume() != target:
                    _set_volume(target)
        stop_evt.wait(1.0)


def _next_alarm_ts():
    try:
        al = ctx.module("alarms")
        st = al.state() if al and hasattr(al, "state") else {}
        n = (st or {}).get("next_alarm")
        return float(n["at"]) if n and n.get("at") else None
    except Exception:
        return None


def _start_playback(sound=None, minutes=None, until_alarm=False):
    global _writer, _timer_thread, _stop_evt
    sound = (sound or ctx.config.get("default_sound", "rain")).lower()
    if sound not in dict(SOUNDS):
        return {"ok": False, "error": f"unknown sound {sound}"}
    if until_alarm:
        at = _next_alarm_ts()
        if not at or at - time.time() < 120:
            return {"ok": False, "error": "no upcoming alarm"}
        ends = at
    elif minutes is not None and float(minutes) > 0:
        ends = time.time() + float(minutes) * 60
    else:
        ends = time.time() + float(ctx.config.get("default_minutes", 45)) * 60
    try:
        path = _ensure(sound)
    except Exception as e:
        return {"ok": False, "error": f"could not build sound: {e}"}
    was_active = _s["active"]
    prev = _s["prev_volume"] if was_active else _volume()
    _teardown()
    try:
        sp = ctx.module("spotify")
        if sp and hasattr(sp, "is_playing") and sp.is_playing():
            sp.pause()
    except Exception:
        pass
    with _lock:
        _s.update({"active": True, "sound": sound, "ends_at": ends, "started_at": time.time(), "prev_volume": prev, "fading": False, "error": None})
        _s.pop("fade_from", None)
    if was_active and prev is not None:
        _set_volume(prev)                                   # a sound switched mid-fade: back to the pre-sleep level
    _stop_evt = threading.Event()
    _writer = threading.Thread(target=_writer_loop, args=(path, _stop_evt), daemon=True); _writer.start()
    _timer_thread = threading.Thread(target=_timer_loop, args=(_stop_evt,), daemon=True); _timer_thread.start()
    ctx.emit("sleep_started", {"sound": sound, "ends_at": ends})
    ctx.log(f"playing {sound} until {time.strftime('%H:%M', time.localtime(ends))}")
    return {"ok": True, **state()}


def _teardown():
    global _writer, _timer_thread
    _stop_evt.set()
    w, t = _writer, _timer_thread
    _writer = _timer_thread = None
    for th in (w, t):
        if th and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=3)
    subprocess.run(["pkill", "-f", "aplay -q -D default -t raw -f S16_LE -r 48000 -c 1"], capture_output=True)


def stop(reason="user"):
    with _lock:
        was = _s["active"]; prev = _s["prev_volume"]; sound = _s["sound"]
        _s.update({"active": False, "ends_at": None, "fading": False})
    if not was:
        return {"ok": True, "active": False}
    _teardown()
    if prev is not None:
        _set_volume(prev)
    with _lock:
        _s["prev_volume"] = None
    ctx.emit("sleep_stopped", {"sound": sound, "reason": reason})
    return {"ok": True, "active": False}


def set_timer(minutes=None, until_alarm=False):
    if not _s["active"]:
        return {"ok": False, "error": "nothing playing"}
    if until_alarm:
        at = _next_alarm_ts()
        if not at:
            return {"ok": False, "error": "no upcoming alarm"}
        ends = at
    else:
        ends = time.time() + float(minutes or ctx.config.get("default_minutes", 45)) * 60
    with _lock:
        if _s["fading"] and _s["prev_volume"] is not None:
            _set_volume(_s.get("fade_from") or _s["prev_volume"])
        _s["ends_at"] = ends; _s["fading"] = False; _s.pop("fade_from", None)
    return {"ok": True, **state()}


# ------------------------------------------------------------------ public
def state():
    with _lock:
        out = {k: _s.get(k) for k in ("active", "sound", "ends_at", "started_at", "fading", "error")}
    out["remaining_s"] = max(0, int(out["ends_at"] - time.time())) if out["active"] and out["ends_at"] else None
    out["label"] = dict(SOUNDS).get(out["sound"]) if out["sound"] else None
    out["sounds"] = [{"id": k, "label": v} for k, v in SOUNDS]
    out["next_alarm_at"] = _next_alarm_ts()
    return out


def api(action, params):
    params = params or {}
    if action == "start":
        return _start_playback(params.get("sound"), params.get("minutes"), bool(params.get("until_alarm")))
    if action == "stop":
        return stop()
    if action == "set_timer":
        return set_timer(params.get("minutes"), bool(params.get("until_alarm")))
    if action == "sounds":
        return {"ok": True, "sounds": [{"id": k, "label": v} for k, v in SOUNDS]}
    if action == "status":
        return {"ok": True, **state()}
    return {"ok": False, "error": f"unknown action {action}"}


_SOUND_RE = re.compile(r"\b(rain|rainfall|thunder ?storm|storm|ocean|waves|sea|beach|white noise|pink noise|brown noise|fan (?:hum|noise|sound|sounds)|hum|static|noise|sleep sounds?|sleeping sounds?|nature sounds?|ambient sounds?)\b")
_NUMS = {"five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "forty-five": 45, "sixty": 60, "ninety": 90,
         "one": 1, "two": 2, "an": 1, "a": 1, "half an": 0.5, "half": 0.5}


def _pick(t):
    if re.search(r"\b(rain|rainfall|storm)\b", t): return "rain"
    if re.search(r"\b(ocean|waves|sea|beach)\b", t): return "ocean"
    if re.search(r"\bwhite noise\b|\bstatic\b", t): return "white"
    if re.search(r"\bpink\b", t): return "pink"
    if re.search(r"\bbrown\b", t): return "brown"
    if re.search(r"\b(fan|hum)\b", t): return "hum"
    return ctx.config.get("default_sound", "rain")


def _duration(t):
    """(minutes, until_alarm)"""
    if re.search(r"\buntil (my|the) alarm\b|\btill (my|the) alarm\b|\buntil morning\b", t):
        return None, True
    m = re.search(r"\bfor\s+(\d+|[a-z]+(?: [a-z]+)?)\s*(minutes?|min|hours?|hr)\b", t)
    if not m:
        m = re.search(r"\b(\d+|[a-z]+)\s*(minutes?|min|hours?|hr)\b", t)
    if m:
        raw = m.group(1)
        n = float(raw) if raw.isdigit() else _NUMS.get(raw)
        if n is not None:
            return (n * 60 if m.group(2).startswith("h") else n), False
    return None, False


def intent(text):
    t = (text or "").lower().strip().rstrip(".!?")
    if not _SOUND_RE.search(t):
        return None
    if re.search(r"\b(stop|turn off|end|cancel|kill|enough|quiet)\b", t) and not re.search(r"\bplay\b", t):
        if _s["active"]:
            stop(); return ""
        return None if not re.search(r"\b(sleep|noise|sound)", t) else "Nothing is playing."
    if re.search(r"\b(how long|time left|when does)\b", t) and _s["active"]:
        st = state(); return f"{st['label']} for another {max(1, st['remaining_s'] // 60)} minutes."
    if re.search(r"\b(play|start|put on|turn on|some|i want|let me hear|sleep|go to bed)\b", t) or re.search(r"^(rain|ocean|white noise|pink noise|brown noise)\b", t):
        if re.search(r"\b(music|song|playlist|spotify)\b", t) and not re.search(r"\b(noise|sound)", t):
            return None                                     # "play rain by X" style requests are music
        minutes, until = _duration(t)
        r = _start_playback(_pick(t), minutes, until)
        if not r.get("ok"):
            return "There's no alarm set, so tell me how long." if "alarm" in (r.get("error") or "") else "I couldn't start that."
        return ""
    if re.search(r"\b(longer|extend|another)\b", t) and _s["active"]:
        minutes, until = _duration(t)
        set_timer((minutes or 30) + (state()["remaining_s"] or 0) / 60, until); return ""
    return None


def _on_transcript(d):
    """A bare 'stop' is swallowed by the voice module before module intents run; catch it here while we play."""
    try:
        t = (d or {}).get("text", "").lower().strip().rstrip(".!?")
        if _s["active"] and re.fullmatch(r"(okay |ok |hey )?(stop|cancel|that's enough|quiet|stop playing|turn (it|that) off)", t):
            stop()
    except Exception:
        pass


def start(c):
    """Module entry: blocks as the module thread. Sounds are generated once in the background so the first request is instant."""
    global ctx
    ctx = c
    ctx.on("transcript", _on_transcript)
    ctx.on("alarm_ringing", lambda d: stop(reason="alarm") if _s["active"] else None)
    def build_all():
        for k, _ in SOUNDS:
            try:
                _ensure(k)
            except Exception as e:
                ctx.log(f"could not build {k}: {e}")
    threading.Thread(target=build_all, daemon=True).start()
    while True:
        time.sleep(3600)
