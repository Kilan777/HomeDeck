"""Ringtones for timers and alarms, the way a phone does it.

Five tones are generated once with numpy into <data_dir>/sounds/ring_<name>.wav (48 kHz mono, seamless loops);
any extra ring_*.wav dropped into that folder is offered too. Playback streams the loop into one aplay on the shared
ALSA "default" device (dmix + softvol), so it mixes with everything else and obeys the system volume control; while
ringing the system volume is set to the configured level for that kind and restored on stop.

api: start {kind: timer|alarm, label, say}, stop, preview {tone, volume}, list, set {...}
state(): {ringing, kind, label, since, tones}
events: "ringing" {kind, label}, "ringing_stopped" {kind, label}
Only one thing rings at a time; a new start replaces the current one.
"""
import glob, os, subprocess, threading, time, wave

import numpy as np

NAME = "ringer"
DEFAULTS = {"timer_tone": "Chime", "alarm_tone": "Gentle", "timer_volume": 60, "alarm_volume": 70,
            "say_label": True, "max_ring_s": {"timer": 300, "alarm": 600}, "escalate": True}
RATE = 48000

ctx = None
_lock = threading.Lock()
_s = {"ringing": False, "kind": None, "label": None, "since": None, "tone": None, "prev_volume": None, "preview": False}
_stop_evt = threading.Event()
_proc = None
_thread = None
BUILTIN = ["Chime", "Marimba", "Classic", "Digital", "Gentle"]


# ------------------------------------------------------------------ tone synthesis
def _env(n, a=0.005, d=0.25, s=0.0, r=0.2, sr=RATE):
    """Simple ADSR-ish envelope for a note of n samples (attack/decay/release in seconds)."""
    t = np.arange(n) / sr
    dur = n / sr
    e = np.ones(n, dtype=np.float32)
    e *= np.minimum(1.0, t / max(a, 1e-4))
    e *= np.where(t < a + d, 1.0 - (1.0 - s) * np.clip((t - a) / max(d, 1e-4), 0, 1), s if s > 0 else np.exp(-(t - a - d) * 3.0))
    e *= np.minimum(1.0, (dur - t) / max(r, 1e-4))
    return e.astype(np.float32)


def _note(freq, secs, amp=0.5, harmonics=((1, 1.0),), env=None, sr=RATE):
    n = int(secs * sr)
    t = np.arange(n) / sr
    sig = np.zeros(n, dtype=np.float32)
    for mult, w in harmonics:
        sig += w * np.sin(2 * np.pi * freq * mult * t)
    e = env if env is not None else _env(n)
    return (amp * sig * e).astype(np.float32)


def _place(buf, start_s, snd, sr=RATE):
    i = int(start_s * sr)
    j = min(len(buf), i + len(snd))
    buf[i:j] += snd[:j - i]


def _bell(f, secs, amp):
    n = int(secs * RATE); t = np.arange(n) / RATE
    e = np.exp(-t * 2.2) * np.minimum(1.0, t / 0.004)
    sig = (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 2.0 * t) * np.exp(-t * 4)
           + 0.25 * np.sin(2 * np.pi * f * 2.99 * t) * np.exp(-t * 6))
    return (amp * sig * e).astype(np.float32)


def _gen(name):
    if name == "Chime":                              # soft bell arpeggio, C major, 4 s
        L = 4.0; buf = np.zeros(int(L * RATE), dtype=np.float32)
        for i, f in enumerate([523.25, 659.25, 783.99, 1046.5]):
            _place(buf, 0.15 + i * 0.32, _bell(f, 2.2, 0.32))
        _place(buf, 2.2, _bell(783.99, 1.6, 0.22))
        return buf
    if name == "Marimba":                            # woody rising phrase, 4 s
        L = 4.0; buf = np.zeros(int(L * RATE), dtype=np.float32)
        def mar(f, secs, amp):
            n = int(secs * RATE); t = np.arange(n) / RATE
            e = np.exp(-t * 6.0) * np.minimum(1.0, t / 0.002)
            sig = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 4.0 * t) * np.exp(-t * 18)
            return (amp * sig * e).astype(np.float32)
        for i, f in enumerate([392.0, 493.88, 587.33, 783.99, 587.33, 493.88]):
            _place(buf, 0.1 + i * 0.28, mar(f, 0.9, 0.45))
        _place(buf, 2.3, mar(392.0, 1.2, 0.4)); _place(buf, 2.65, mar(587.33, 1.2, 0.35))
        return buf
    if name == "Classic":                            # phone-style double beep, 4 s
        L = 4.0; buf = np.zeros(int(L * RATE), dtype=np.float32)
        for k in range(2):
            for j in range(2):
                n = int(0.14 * RATE); t = np.arange(n) / RATE
                e = np.minimum(1.0, t / 0.006) * np.minimum(1.0, (0.14 - t) / 0.02)
                sig = 0.32 * (np.sin(2 * np.pi * 1046.5 * t) + 0.5 * np.sin(2 * np.pi * 1318.5 * t)) * e
                _place(buf, 0.2 + k * 1.6 + j * 0.24, sig.astype(np.float32))
        return buf
    if name == "Digital":                            # gentle synth pulse, 4 s
        L = 4.0; buf = np.zeros(int(L * RATE), dtype=np.float32)
        for i in range(8):
            n = int(0.3 * RATE); t = np.arange(n) / RATE
            f = [659.25, 659.25, 880.0, 659.25][i % 4]
            e = np.minimum(1.0, t / 0.01) * np.exp(-t * 7)
            sig = 0.3 * (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 0.5 * t) + 0.15 * np.sign(np.sin(2 * np.pi * f * t)) * np.exp(-t * 20)) * e
            _place(buf, 0.1 + i * 0.45, sig.astype(np.float32))
        return buf
    # Gentle: slow warm pad swell for waking, 6 s
    L = 6.0; n = int(L * RATE); t = np.arange(n) / RATE
    swell = 0.5 - 0.5 * np.cos(2 * np.pi * t / L)          # rises and falls across the loop, seamless
    sig = np.zeros(n, dtype=np.float32)
    for f, w in ((261.63, 1.0), (329.63, 0.8), (392.0, 0.7), (523.25, 0.45), (130.81, 0.5)):
        vib = 1.0 + 0.004 * np.sin(2 * np.pi * 5.5 * t)
        sig += w * np.sin(2 * np.pi * f * vib * t)
    sig *= (0.28 * swell).astype(np.float32)
    shimmer = 0.06 * np.sin(2 * np.pi * 1046.5 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * t / 3.0)) * swell
    return (sig + shimmer).astype(np.float32)


def _loopify(x, k=int(0.05 * RATE)):
    """Crossfade the tail into the head so the loop point is inaudible."""
    if len(x) <= 2 * k:
        return x
    fade = np.linspace(0, 1, k, dtype=np.float32)
    head = x[:k] * fade + x[-k:] * (1 - fade)
    return np.concatenate([head, x[k:-k]])


def _path(name):
    return os.path.join(ctx.data_dir, "sounds", f"ring_{name}.wav")


def _ensure(name):
    p = _path(name)
    if os.path.isfile(p):
        return p
    os.makedirs(os.path.dirname(p), exist_ok=True)
    x = _loopify(_gen(name))
    peak = float(np.max(np.abs(x))) or 1.0
    x = x / peak * 0.5                                            # about -6 dBFS; the softvol sets the real level
    pcm = (x * 32767).astype("<i2")
    with wave.open(p, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm.tobytes())
    return p


def _ensure_all():
    for n in BUILTIN:
        try:
            _ensure(n)
        except Exception as e:
            ctx.log(f"could not generate tone {n}: {e}")


def tones():
    """Built-in tones first, then any custom ring_*.wav in the sounds folder."""
    names = list(BUILTIN)
    for p in sorted(glob.glob(os.path.join(ctx.data_dir, "sounds", "ring_*.wav"))):
        n = os.path.basename(p)[5:-4]
        if n not in names:
            names.append(n)
    return names


# ------------------------------------------------------------------ playback
def _load_pcm(path):
    with wave.open(path, "rb") as w:
        ch, sw, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        data = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError("only 16-bit wav tones are supported")
    pcm = np.frombuffer(data, dtype=np.int16)
    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1).astype(np.int16)
    if sr != RATE:                                                  # nearest-sample resample for custom files
        idx = (np.arange(int(len(pcm) * RATE / sr)) * sr / RATE).astype(np.int64)
        pcm = pcm[np.minimum(idx, len(pcm) - 1)]
    return pcm


def _writer(path, stop_evt, fade_in_s=1.5):
    global _proc
    try:
        pcm = _load_pcm(path)
    except Exception as e:
        ctx.log(f"ringer: cannot read {path}: {e}")
        return
    slice_n = RATE // 4
    try:
        _proc = subprocess.Popen(["aplay", "-q", "-D", "default", "-t", "raw", "-f", "S16_LE", "-r", str(RATE), "-c", "1"],
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        ctx.log(f"ringer: aplay failed: {e}")
        return
    i = 0; written = 0; fade_n = int(fade_in_s * RATE)
    try:
        while not stop_evt.is_set():
            chunk = pcm[i:i + slice_n]
            if len(chunk) < slice_n:
                rest = slice_n - len(chunk)
                chunk = np.concatenate([chunk, pcm[:rest]]); i = rest
            else:
                i += slice_n
            if written < fade_n:
                ramp = np.clip((written + np.arange(len(chunk))) / fade_n, 0, 1).astype(np.float32) ** 2
                chunk = (chunk.astype(np.float32) * ramp).astype(np.int16)
            written += len(chunk)
            _proc.stdin.write(chunk.tobytes())
    except Exception as e:
        if not stop_evt.is_set():
            ctx.log(f"ringer: playback ended: {e}")
    finally:
        try:
            _proc.stdin.close()
        except Exception:
            pass
        try:
            _proc.terminate(); _proc.wait(timeout=2)
        except Exception:
            try:
                _proc.kill()
            except Exception:
                pass


def _audio():
    return ctx.module("audio")


def _set_volume(pct):
    a = _audio()
    if a and hasattr(a, "set_volume"):
        try:
            a.set_volume(int(max(0, min(100, pct))))
        except Exception:
            pass


def _volume():
    a = _audio()
    try:
        return a.volume() if a and hasattr(a, "volume") else None
    except Exception:
        return None


def _leds(name):
    l = ctx.module("leds")
    if l and hasattr(l, "pattern"):
        try:
            l.pattern(name)
        except Exception:
            pass


def _escalator(kind, target, stop_evt):
    """Alarms start at 40 percent of the target level and reach it over 30 s."""
    t0 = time.time()
    while not stop_evt.is_set():
        frac = min(1.0, (time.time() - t0) / 30.0)
        _set_volume(int(round(target * (0.4 + 0.6 * frac))))
        if frac >= 1.0:
            return
        stop_evt.wait(2.0)


def _watchdog(kind, stop_evt):
    mx = ctx.config.get("max_ring_s", {})
    limit = float(mx.get(kind, 300) if isinstance(mx, dict) else mx)
    if stop_evt.wait(limit):
        return
    ctx.log(f"ringer: {kind} rang for {int(limit)} s with no answer, stopping")
    stop(reason="timeout")


def ring(kind="timer", label="", say=None, tone=None, volume=None, preview=False):
    """Start ringing (replaces whatever rings now). Returns the tone name used."""
    global _thread
    kind = "alarm" if kind == "alarm" else "timer"
    cfg = ctx.config
    tone = tone or cfg.get(f"{kind}_tone") or DEFAULTS[f"{kind}_tone"]
    if tone not in tones():
        tone = DEFAULTS[f"{kind}_tone"]
    vol = int(volume if volume is not None else cfg.get(f"{kind}_volume", DEFAULTS[f"{kind}_volume"]))
    path = _ensure(tone) if tone in BUILTIN else _path(tone)
    was = _s["ringing"]
    prev = _s["prev_volume"] if was else _volume()
    _stop_playback()                                             # replace, keeping the original volume to restore
    with _lock:
        _s.update({"ringing": True, "kind": kind, "label": label or "", "since": time.time(), "tone": tone,
                   "prev_volume": prev, "preview": bool(preview)})
    _stop_evt.clear()
    stop_evt = _stop_evt
    if kind == "alarm" and cfg.get("escalate", True) and not preview:
        _set_volume(int(round(vol * 0.4)))
        threading.Thread(target=_escalator, args=(kind, vol, stop_evt), daemon=True).start()
    else:
        _set_volume(vol)
    _thread = threading.Thread(target=_writer, args=(path, stop_evt), daemon=True)
    _thread.start()
    if not preview:
        threading.Thread(target=_watchdog, args=(kind, stop_evt), daemon=True).start()
        _leds("alert")
        ctx.emit("ringing", {"kind": kind, "label": label or "", "tone": tone})
        ctx.log(f"ringing: {kind} {label!r} with {tone} at {vol}%")
    if say and not preview:
        v = ctx.module("voice")
        if v and hasattr(v, "say"):
            try:
                v.say(say)
            except Exception as e:
                ctx.log(f"say failed: {e}")
    return tone


def _stop_playback():
    global _proc
    _stop_evt.set()
    p = _proc
    if p and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass
    th = _thread
    if th and th.is_alive():
        th.join(timeout=2)


def stop(reason="stop"):
    """Stop ringing, restore the volume and the light bar. Returns True if something was ringing."""
    with _lock:
        was = _s["ringing"]; kind = _s["kind"]; label = _s["label"]; prev = _s["prev_volume"]; preview = _s["preview"]
        _s.update({"ringing": False, "kind": None, "label": None, "since": None, "tone": None, "prev_volume": None, "preview": False})
    _stop_playback()
    if was:
        if prev is not None:
            _set_volume(prev)
        if not preview:
            _leds("idle")
            ctx.emit("ringing_stopped", {"kind": kind, "label": label, "reason": reason})
            ctx.log(f"ringing stopped ({reason})")
    return was


def is_ringing():
    return bool(_s["ringing"] and not _s["preview"])


def say_label():
    return bool(ctx.config.get("say_label", True))


# ------------------------------------------------------------------ public
def state():
    with _lock:
        out = {k: _s[k] for k in ("ringing", "kind", "label", "since", "tone")}
    if _s["preview"]:
        out["ringing"] = False
    cfg = ctx.config
    out.update({"timer_tone": cfg.get("timer_tone"), "alarm_tone": cfg.get("alarm_tone"),
                "timer_volume": cfg.get("timer_volume"), "alarm_volume": cfg.get("alarm_volume"),
                "say_label": cfg.get("say_label", True), "tones": tones()})
    return out


def api(action, params):
    if action == "start":
        tone = ring(params.get("kind", "timer"), params.get("label", ""), params.get("say"))
        return {"ok": True, "tone": tone}
    if action == "stop":
        return {"ok": True, "was_ringing": stop()}
    if action == "preview":
        tone = params.get("tone") or ctx.config.get("timer_tone")
        if tone not in tones():
            return {"ok": False, "error": "unknown tone"}
        vol = params.get("volume")
        ring("timer", "", None, tone=tone, volume=vol, preview=True)
        threading.Timer(float(params.get("seconds", 4)), lambda: stop() if _s["preview"] else None).start()
        return {"ok": True, "tone": tone}
    if action == "list":
        return {"ok": True, "tones": tones()}
    if action == "set":
        changed = {}
        for k in ("timer_tone", "alarm_tone"):
            if k in params and params[k] in tones():
                ctx.config[k] = params[k]; changed[k] = params[k]
        for k in ("timer_volume", "alarm_volume"):
            if k in params:
                try:
                    ctx.config[k] = int(max(5, min(100, int(params[k])))); changed[k] = ctx.config[k]
                except (TypeError, ValueError):
                    pass
        if "say_label" in params:
            ctx.config["say_label"] = bool(params["say_label"]); changed["say_label"] = ctx.config["say_label"]
        ctx.save_config()
        return {"ok": True, **changed}
    if action == "set_live_volume":                              # slider drag during a preview
        if _s["preview"]:
            _set_volume(int(params.get("volume", 60)))
        return {"ok": True}
    return {"ok": False, "error": f"unknown action {action}"}


def start(c):
    global ctx
    ctx = c
    _ensure_all()
