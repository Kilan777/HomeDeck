"""System-wide volume for the speakers.

The PCM5102A DAC + TPA3118 amp on the "sndrpigooglevoi" card has no hardware mixer, so volume lives in an
ALSA softvol plugin ("HomeDeck" control, written by install/audio_setup.sh into /etc/asound.conf). Everything
that plays through pcm "default" (= plug -> softvol -> hw) obeys it: Jarvis, timers, Spotify (raspotify device
"homedeck"). Config: default_volume applied at boot, night_max_pct caps the level while the display is in night mode.

TODO: modules/alarms.py still opens the card directly ("plughw:CARD=sndrpigooglevoi,DEV=0") for its alarm tone,
so alarms bypass this control until that device string is changed to "default".
"""
import json, math, os, subprocess, tempfile, threading, time

NAME = "audio"
DEFAULTS = {"default_volume": 55, "night_max_pct": 35, "card": "sndrpigooglevoi", "control": "HomeDeck",
            # 10-band equaliser (alsaequal "equal" mixer, install/audio_setup.sh). bass/treble are the user's tone
            # controls in dB; room is the correction measured with the USB microphone ("Calibrate" in the Music app).
            "eq": {"bass": 0, "treble": 0, "room": [0] * 10, "room_enabled": True},
            # music ducking: Spotify and the browser play through pcm "homedeck_music", which has its own softvol
            # ("Music"); while Jarvis listens, thinks, answers and waits for a follow-up it is pulled down by duck_db
            # and restored after. Speech, timers and alarms play on "default" and stay at full level.
            "music_control": "Music", "duck_db": 14,
            # the music volume (Music softvol) is independent of the Jarvis/system volume (HomeDeck softvol)
            "music_volume": 70}
_music = {"base": None, "ducked": False}

ctx = None
_lock = threading.Lock()
_s = {"volume_pct": None, "muted": False, "device": "default", "control_present": False, "error": None,
      "music_pct": None, "music_muted": False, "music_ducked": False, "music_error": None}
_pre_mute = 55


def _amixer(*args):
    card = str(ctx.config.get("card", DEFAULTS["card"]))
    return subprocess.run(["amixer", "-c", card, *args], capture_output=True, text=True, timeout=5)


def _control_present():
    r = _amixer("sget", str(ctx.config.get("control", "HomeDeck")))
    return r.returncode == 0 and "Playback" in (r.stdout or "")


def _init_control():
    """softvol controls only exist after the pcm has been opened once: play 0.2 s of silence through it."""
    try:
        silence = b"\x00" * (48000 * 2 * 2 // 5)
        subprocess.run(["aplay", "-q", "-D", "homedeck", "-f", "S16_LE", "-r", "48000", "-c", "2", "-t", "raw"],
                       input=silence, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except Exception as e:
        ctx.log(f"softvol init failed: {e}")
    return _control_present()


def _read_volume():
    r = _amixer("sget", str(ctx.config.get("control", "HomeDeck")))
    import re
    m = re.search(r"\[(\d{1,3})%\]", r.stdout or "")
    return int(m.group(1)) if m else None


def set_volume(pct, target="jarvis"):
    """Set 0-100 for target "jarvis" (speech, timers, alarms: the HomeDeck softvol) or "music" (Spotify, browser:
    the Music softvol). Clamps to the night cap when the display is in night mode. Returns the applied value or None."""
    try:
        pct = int(round(float(pct)))
    except (TypeError, ValueError):
        return None
    pct = max(0, min(100, pct))
    d = ctx.module("display")
    try:
        if d and d.state().get("night"):
            pct = min(pct, int(ctx.config.get("night_max_pct", 35)))
    except Exception:
        pass
    if target == "music":
        return _set_music(pct)
    ctl = str(ctx.config.get("control", "HomeDeck"))
    r = _amixer("sset", ctl, f"{pct}%")
    if r.returncode != 0:
        if not _init_control():
            with _lock:
                _s["error"] = "volume control missing: run install/audio_setup.sh"; _s["control_present"] = False
            return None
        r = _amixer("sset", ctl, f"{pct}%")
    with _lock:
        _s["volume_pct"] = pct; _s["muted"] = pct == 0; _s["control_present"] = True; _s["error"] = None
    return pct


def volume():
    with _lock:
        return _s["volume_pct"]


def music_volume():
    with _lock:
        return _s.get("music_pct")


def _set_music(pct):
    """Music base level 0-100; while ducked the control sits duck_db below it. Persisted as music_volume."""
    ctl = str(ctx.config.get("music_control", "Music"))
    steps = int(round(float(ctx.config.get("duck_db", 14)) / 40.0 * 100))
    level = max(0, pct - steps) if _music["ducked"] else pct
    r = _amixer("sset", ctl, str(level))
    if r.returncode != 0:
        with _lock:
            _s["music_error"] = "Music control missing: run install/audio_setup.sh"
        return None
    _music["base"] = pct
    if ctx.config.get("music_volume") != pct:
        ctx.config["music_volume"] = pct
        try:
            ctx.save_config()
        except Exception:
            pass
    with _lock:
        _s["music_pct"] = pct; _s["music_muted"] = pct == 0; _s["music_error"] = None
    return pct


def _music_raw():
    """Raw value (0-100, 0.4 dB per step) of the Music softvol, or None when the control is missing."""
    import re
    r = _amixer("sget", str(ctx.config.get("music_control", "Music")))
    m = re.search(r"(?:Front Left|Mono):(?: Playback)? (\d+) \[", r.stdout or "")
    return int(m.group(1)) if (r.returncode == 0 and m) else None


def duck_music(on):
    """Lower the music path while Jarvis is busy (on=True), or put it back (on=False). Idempotent. Returns False
    only when the Music control does not exist (install/audio_setup.sh not run since the music path was added)."""
    on = bool(on)
    if _music["ducked"] == on:
        return True
    base = _music["base"] if _music["base"] is not None else int(ctx.config.get("music_volume", 70))
    _music["ducked"] = on
    ok = _set_music(base) is not None
    with _lock:
        _s["music_ducked"] = on
    return ok


# ----------------------------------------------------------------------------- equaliser
# caps Eq10 bands as alsaequal names them; its gain ports run -48..+24 dB, mapped to 0..100 % (0 dB = 66.7 %)
EQ_BANDS = [("00. 31 Hz", 31.25), ("01. 63 Hz", 62.5), ("02. 125 Hz", 125), ("03. 250 Hz", 250), ("04. 500 Hz", 500),
            ("05. 1 kHz", 1000), ("06. 2 kHz", 2000), ("07. 4 kHz", 4000), ("08. 8 kHz", 8000), ("09. 16 kHz", 16000)]
EQ_LABELS = ["31 Hz", "63 Hz", "125 Hz", "250 Hz", "500 Hz", "1 kHz", "2 kHz", "4 kHz", "8 kHz", "16 kHz"]
TONE_MAX = 8                      # dB either way for bass and treble
ROOM_CUT, ROOM_BOOST = -6.0, 4.0  # limits for the measured correction (a cheap mic colours the measurement too)
_eq = {"available": None, "bands_db": [0.0] * 10, "calibration": {"running": False, "step": "", "result": None, "error": None}}


def _eq_cfg():
    e = json.loads(json.dumps(DEFAULTS["eq"])); e.update(ctx.config.get("eq") or {})
    room = list(e.get("room") or [])
    e["room"] = [float(x) for x in (room + [0] * 10)[:10]]
    e["bass"] = max(-TONE_MAX, min(TONE_MAX, float(e.get("bass") or 0)))
    e["treble"] = max(-TONE_MAX, min(TONE_MAX, float(e.get("treble") or 0)))
    return e


def _eq_present():
    if _eq["available"] is None:
        try:
            r = subprocess.run(["amixer", "-D", "equal", "scontrols"], capture_output=True, text=True, timeout=5)
            _eq["available"] = r.returncode == 0 and "31 Hz" in (r.stdout or "")
        except Exception:
            _eq["available"] = False
    return _eq["available"]


def _eq_curve(e=None):
    """The ten band gains in dB: tone controls on top of the room correction, then shifted down so no band boosts
    above 0 dB (the equaliser runs at 16 bit in front of the volume control; a boost there would clip loud music)."""
    e = e or _eq_cfg()
    b, t = e["bass"], e["treble"]
    tone = [b, b, 0.5 * b, 0, 0, 0, 0, 0.5 * t, t, t]
    room = e["room"] if e.get("room_enabled", True) else [0.0] * 10
    bands = [tone[i] + room[i] for i in range(10)]
    head = max(0.0, max(bands))
    return [round(x - head, 2) for x in bands]


def _eq_write(bands):
    ok = True
    for (name, _), db in zip(EQ_BANDS, bands):
        pct = int(round((max(-48.0, min(24.0, db)) + 48.0) / 72.0 * 100))
        r = subprocess.run(["amixer", "-q", "-D", "equal", "sset", name, str(pct)], capture_output=True, text=True, timeout=5)
        ok = ok and r.returncode == 0
    return ok


def eq_apply():
    """Push the configured curve to the equaliser. Returns False when the plugin is missing."""
    if not _eq_present():
        return False
    bands = _eq_curve()
    if _eq_write(bands):
        with _lock:
            _eq["bands_db"] = bands
        return True
    return False


def _pink(seconds, sr=48000, level_dbfs=-18.0, seed=11):
    """Pink noise, int16 stereo interleaved, faded in and out (equal energy per octave: a flat target for the bands)."""
    import numpy as np
    n = int(sr * seconds)
    white = np.random.default_rng(seed).standard_normal(n + 8192)
    spec = np.fft.rfft(white); f = np.arange(len(spec), dtype=np.float64); f[0] = 1
    pink = np.fft.irfft(spec / np.sqrt(f), len(white))[8192:]
    pink /= np.sqrt(np.mean(pink ** 2)) + 1e-9
    pink *= 10 ** (level_dbfs / 20)
    fade = np.minimum(1, np.minimum(np.arange(n), n - 1 - np.arange(n)) / (0.2 * sr))
    mono = np.clip(pink * fade, -0.99, 0.99)
    return (np.repeat(mono, 2) * 32767).astype(np.int16).tobytes()


def _band_levels(x, sr=48000):
    """Octave-band levels (dB, arbitrary reference) around the ten equaliser centres, Welch-style averaging."""
    import numpy as np
    x = np.asarray(x, dtype=np.float64); n = 8192
    if len(x) < n:
        return [-120.0] * 10
    win = np.hanning(n); acc = np.zeros(n // 2 + 1); k = 0
    for i in range(0, len(x) - n, n // 2):
        acc += np.abs(np.fft.rfft(x[i:i + n] * win)) ** 2; k += 1
    psd = acc / max(k, 1); f = np.fft.rfftfreq(n, 1 / sr)
    out = []
    for _, fc in EQ_BANDS:
        m = (f >= fc / math.sqrt(2)) & (f < fc * math.sqrt(2))
        out.append(float(10 * np.log10(psd[m].sum() + 1e-9)))
    return out


def _record(dev, seconds, path):
    return subprocess.Popen(["arecord", "-q", "-D", dev, "-f", "S16_LE", "-r", "48000", "-c", "1", "-t", "raw", "-d", str(int(seconds)), path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _calibrate():
    """Measure the speakers through the USB microphone and set the room correction.
    1) borrow the mics from the voice module, 2) 3 s of silence -> noise floor per band, 3) 6 s of pink noise
    at a moderate level with the equaliser flat -> band levels, 4) deviation from flat where the band is clearly
    above the noise floor -> correction (smoothed, limited), saved as eq.room and applied. Plain-language result.
    The USB mic's own colour is part of the measurement, which is why the correction is limited to -8/+4 dB."""
    import numpy as np
    cal = _eq["calibration"]
    cal.update({"running": True, "step": "Getting the microphone", "result": None, "error": None})
    voice = ctx.module("voice")
    restore_vol = None
    try:
        if not _eq_present():
            raise RuntimeError("the equaliser is not installed (run install/audio_setup.sh)")
        r = voice.api("pause_capture", {"seconds": 45}) if voice else {}
        dev = (r or {}).get("usb_device") or ""
        if not dev:
            raise RuntimeError("plug the USB microphone in and put it where you usually listen from")
        time.sleep(2.0)                                            # the voice pipeline lets go of the devices
        tmp = tempfile.mkdtemp(prefix="hdcal")
        cal["step"] = "Listening to the room"
        p = _record(dev, 3, f"{tmp}/quiet.raw")
        if p.wait(timeout=10) != 0:
            raise RuntimeError("could not record from the USB microphone: " + (p.stderr.read().decode(errors="ignore").strip()[:120] or "arecord failed"))
        quiet = np.fromfile(f"{tmp}/quiet.raw", dtype=np.int16)
        cal["step"] = "Playing a test sound"
        cur = volume() or 0
        if cur < 60:                                               # the USB mic's own noise sits only ~5 dB under quiet
            restore_vol = cur                                      # playback at 50 %, so the test has to be fairly loud:
            _amixer("sset", str(ctx.config.get("control", "HomeDeck")), "60%")   # straight to the mixer, past the night cap
        ctx.log(f"speaker calibration: test at volume {max(cur, 60)} % through {dev}")
        _eq_write([0.0] * 10)                                      # measure the speakers, not the current correction
        pink = _pink(6.5, level_dbfs=-14.0)                       # loud enough to clear the mic's noise, peaks well under clipping
        rec = _record(dev, 7, f"{tmp}/pink.raw")
        time.sleep(0.3)
        play = subprocess.Popen(["aplay", "-q", "-D", "default", "-f", "S16_LE", "-r", "48000", "-c", "2", "-t", "raw"], stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            play.communicate(pink, timeout=20)
        except Exception:
            play.kill()
        rec.wait(timeout=15)
        got = np.fromfile(f"{tmp}/pink.raw", dtype=np.int16)
        cal["step"] = "Working it out"
        if len(got) < 48000 * 4:
            raise RuntimeError("the recording was too short")
        sig = got[48000 * 1: 48000 * 6]                            # steady part, fades excluded
        if float(np.sqrt(np.mean(sig.astype(np.float64) ** 2))) < 40:
            raise RuntimeError("the microphone heard almost nothing; is it switched on and near the speakers?")
        lv, nz = _band_levels(sig), _band_levels(quiet)
        snr = [round(lv[i] - nz[i], 1) for i in range(10)]
        rms = float(np.sqrt(np.mean(sig.astype(np.float64) ** 2)))
        ctx.log(f"speaker calibration: signal rms {rms:.0f}, band signal-to-noise dB {snr}")
        if int(np.abs(sig).max()) >= 32700:
            ctx.log("speaker calibration: the microphone clipped; results are rough")
        # take the room's own noise out of each band, and only trust bands the test sound clearly rose above
        lv = [10 * math.log10(max(10 ** (lv[i] / 10) - 10 ** (nz[i] / 10), 1e-9)) if snr[i] >= 3 else lv[i] for i in range(10)]
        reliable = [snr[i] >= 6.0 for i in range(10)]
        reliable[0] = False                                        # 31 Hz: below what these small speakers and the mic do
        core = [lv[i] for i in range(3, 8) if reliable[i]]         # 250 Hz .. 4 kHz (the body of speech and music) set "flat"
        if len(core) < 3:
            raise RuntimeError(f"the test sound was buried in room noise (only {sum(reliable)} of 10 bands were clear); "
                               "turn the volume up, move the microphone closer or quieten the room")
        ref = float(np.median(core))
        dev_db = [round(lv[i] - ref, 1) if reliable[i] else None for i in range(10)]
        raw = [max(ROOM_CUT, min(ROOM_BOOST, -d)) if d is not None else 0.0 for d in dev_db]
        corr = []
        for i in range(10):                                        # smooth across neighbours so no single band sticks out
            a = raw[i - 1] if i > 0 else raw[i]; c = raw[i + 1] if i < 9 else raw[i]
            corr.append(round(0.25 * a + 0.5 * raw[i] + 0.25 * c, 1) if reliable[i] else 0.0)
        e = dict(ctx.config.get("eq") or {}); e["room"] = corr; e["room_enabled"] = True
        ctx.config["eq"] = e; ctx.save_config()
        strong = sorted([(corr[i], i) for i in range(1, 9) if reliable[i]], key=lambda t: -abs(t[0]))[:2]
        bits = [f"{'cut' if c < 0 else 'lifted'} {EQ_LABELS[i]} by {abs(c):.0f} dB" for c, i in strong if abs(c) >= 1.5]
        text = ("Measured at the microphone: " + " and ".join(bits) + ".") if bits else "The speakers already sound even at the microphone; only small corrections."
        if dev_db[9] is not None and dev_db[9] < -12:
            text += " The very top (16 kHz) is far down at that spot, more than an equaliser can fix."
        cal["result"] = {"measured_db": dev_db, "correction_db": corr, "noise_floor_db": round(float(np.median(nz)), 1), "text": text,
                         "when": time.time(), "mic": dev}
        ctx.log(f"speaker calibration: {text} measured={dev_db} correction={corr}")
    except Exception as ex:
        cal["error"] = str(ex); ctx.log(f"speaker calibration failed: {ex}")
    finally:
        try:
            eq_apply()
        except Exception:
            pass
        if restore_vol is not None:
            set_volume(restore_vol)
        try:
            if voice:
                voice.api("resume_capture", {})
        except Exception:
            pass
        cal.update({"running": False, "step": ""})


def state():
    with _lock:
        out = dict(_s)
        bands = list(_eq["bands_db"])
    e = _eq_cfg()
    out["eq"] = {"available": bool(_eq["available"]), "bass": e["bass"], "treble": e["treble"], "room": e["room"],
                 "room_enabled": e.get("room_enabled", True), "bands_db": bands, "labels": EQ_LABELS,
                 "calibration": dict(_eq["calibration"])}
    return out


def api(action, params):
    global _pre_mute
    # target "jarvis" (default: speech, timers, alarms) or "music" (Spotify, browser); "all" for mute/unmute
    target = str(params.get("target") or "jarvis")
    if action == "set_volume":
        v = set_volume(params.get("pct"), target)
        if v is None:
            return {"ok": False, "error": (_s.get("music_error") if target == "music" else _s["error"]) or "bad value"}
        if v > 0 and target != "music":
            _pre_mute = v
        return {"ok": True, "volume_pct": v, "target": target}
    if action == "mute":
        ok = True
        if target in ("jarvis", "all"):
            cur = volume() or 0
            if cur > 0:
                _pre_mute = cur
            ok = set_volume(0) is not None and ok
        if target in ("music", "all"):
            cur = music_volume() or 0
            if cur > 0:
                _music["pre_mute"] = cur
            ok = set_volume(0, "music") is not None and ok
        return {"ok": ok, "volume_pct": volume(), "music_pct": music_volume(), "muted": True}
    if action == "unmute":
        ok = True
        if target in ("jarvis", "all"):
            ok = set_volume(_pre_mute or int(ctx.config.get("default_volume", 55))) is not None and ok
        if target in ("music", "all"):
            ok = set_volume(_music.get("pre_mute") or int(DEFAULTS["music_volume"]), "music") is not None and ok
        return {"ok": ok, "volume_pct": volume(), "music_pct": music_volume(), "muted": False}
    if action == "step":
        cur = (music_volume() if target == "music" else volume()) or 0
        v = set_volume(cur + int(params.get("delta", 10)), target)
        return {"ok": v is not None, "volume_pct": v, "target": target}
    if action == "duck":
        ok = duck_music(bool(params.get("on", True)))
        return {"ok": ok, "ducked": _music["ducked"], "error": None if ok else "Music control missing (run install/audio_setup.sh)"}
    if action == "set_eq":
        e = dict(ctx.config.get("eq") or {})
        for k in ("bass", "treble"):
            if k in params:
                try:
                    e[k] = max(-TONE_MAX, min(TONE_MAX, float(params[k])))
                except (TypeError, ValueError):
                    return {"ok": False, "error": f"bad {k}"}
        if "room_enabled" in params:
            e["room_enabled"] = bool(params["room_enabled"])
        ctx.config["eq"] = e; ctx.save_config()
        ok = eq_apply()
        return {"ok": ok, "eq": state()["eq"], "error": None if ok else "equaliser not available (run install/audio_setup.sh)"}
    if action == "reset_eq":
        ctx.config["eq"] = json.loads(json.dumps(DEFAULTS["eq"])); ctx.save_config()
        _eq["calibration"]["result"] = None
        return {"ok": eq_apply(), "eq": state()["eq"]}
    if action == "calibrate":
        if _eq["calibration"]["running"]:
            return {"ok": False, "error": "calibration already running"}
        threading.Thread(target=_calibrate, name="speaker-calibrate", daemon=True).start()
        return {"ok": True, "started": True}
    if action == "calibration_status":
        return {"ok": True, **_eq["calibration"]}
    return {"ok": False, "error": f"unknown action {action}"}


def _pin(n, level):
    subprocess.run(["pinctrl", "set", str(n), "op", "dh" if level else "dl"], capture_output=True, timeout=5)


# Pop-free power sequencing. Pins: GPIO4 = AMP_SDZ (amp enable, 10k pull-down: off at reset), GPIO5 = AMP_MUTE
# (high = muted), GPIO24 = DAC_XSMT (DAC soft-mute, low = muted, 10k pull-up). The pop came from switching the amp on
# unmuted while the DAC had no I2S clock (at boot) and from the amp losing its enable mid-signal (at reboot).
def _amp_always_on():
    """Boot: amp enabled but muted, DAC soft-muted, then start the I2S clocks with a second of silence and only
    unmute once the DAC is running. The amp then stays enabled so later playback never pops it on/off."""
    try:
        _pin(5, 1); _pin(24, 0)                  # mute both stages first
        _pin(4, 1)                               # enable the amp while muted
        time.sleep(0.05)
        play = subprocess.Popen(["aplay", "-q", "-D", "default", "-f", "S16_LE", "-r", "48000", "-c", "2", "-t", "raw"],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def feed():
            try:
                play.communicate(b"\x00" * (48000 * 4 * 12 // 10), timeout=10)   # 1.2 s of silence
            except Exception:
                play.kill()
        t = threading.Thread(target=feed, daemon=True); t.start()
        time.sleep(0.35); _pin(24, 1)            # DAC clocked and settled: release its soft-mute
        time.sleep(0.25); _pin(5, 0)             # then the amp
        t.join(12)
    except Exception:
        pass


def shutdown():
    """Service stop or reboot: mute the DAC and the amp, then disable the amp, before the clocks and rails go away."""
    try:
        _pin(5, 1); _pin(24, 0)
        time.sleep(0.06)
        _pin(4, 0)
    except Exception:
        pass


def start(c):
    global ctx, _pre_mute
    ctx = c
    _amp_always_on()
    _pre_mute = int(ctx.config.get("default_volume", 55))
    # the card can take a moment to appear at boot
    for _ in range(10):
        if _control_present() or _init_control():
            break
        time.sleep(3)
    if set_volume(ctx.config.get("default_volume", 55)) is None:
        ctx.log("softvol control not available; volume control disabled until install/audio_setup.sh has run")
    if _music_raw() is None:
        # softvol controls only exist once their pcm has been opened since boot: open the music path with silence
        try:
            subprocess.run(["aplay", "-q", "-D", "homedeck_music", "-f", "S16_LE", "-r", "48000", "-c", "2", "-t", "raw"],
                           input=b"\x00" * (48000 * 2 * 2 // 5), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except Exception as e:
            ctx.log(f"music path init failed: {e}")
    if _music_raw() is not None:
        set_volume(ctx.config.get("music_volume", DEFAULTS["music_volume"]), "music")
    else:
        ctx.log("Music control missing: no separate music volume and no ducking (run install/audio_setup.sh)")
    if eq_apply():
        ctx.log(f"equaliser applied: {_eq['bands_db']}")
    else:
        ctx.log("equaliser not available (install/audio_setup.sh installs libasound2-plugin-equal); bass/treble disabled")
    last_night = None
    while True:
        try:
            d = ctx.module("display")
            night = bool(d.state().get("night")) if d else False
            if night and last_night is False:
                cap = int(ctx.config.get("night_max_pct", 35))
                if (volume() or 0) > cap:
                    set_volume(cap)
            last_night = night
            v = _read_volume()
            if v is not None:
                with _lock:
                    _s["volume_pct"] = v; _s["muted"] = v == 0
        except Exception as e:
            ctx.log(f"audio loop: {e}")
        time.sleep(5)
