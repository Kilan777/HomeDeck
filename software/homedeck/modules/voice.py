"""HomeDeck voice module: "Jarvis" wake word -> speech to text -> local intents or Claude -> speech.

Pipeline (one thread):
  arecord (48 kHz / S32 / stereo) -> mono int16 @ 16 kHz -> openWakeWord ("hey_jarvis")
    -> on wake: chirp, record until ~0.65 s of silence (energy VAD, 12 s max)
    -> faster-whisper (CPU, int8) -> text
    -> local intents (timers, alarms, air quality, weather, bikes, guest mode, stop) else Claude (web search on)
    -> Groq Orpheus TTS (or piper, espeak-ng) streamed sentence by sentence -> aplay via ALSA softvol ("default")

Every heavy dependency is imported lazily and every failure is non-fatal: with nothing installed the
module still answers typed questions through api("ask") if an API key is present, and state().errors says
exactly what is missing. Other modules call say(text) to speak (alarms, timers, nudges).
"""
import json, os, re, shutil, signal, subprocess, tempfile, threading, time
from datetime import datetime

import numpy as np

NAME = "voice"

DEFAULTS = {
    "enabled": True,
    "mic_enabled": True,                 # privacy toggle: False closes the capture pipe entirely
    "wake_word": "hey_jarvis",           # openWakeWord pretrained model; the owner says "Jarvis"
    "wake_threshold": 0.5,
    "led_feedback": True,          # light bar reacts to wake / thinking / answering
    "wake_threshold_while_speaking": 0.7,   # barge-in: stricter while our own voice is on the speakers
    "follow_up_s": 5,                       # after an answer, keep listening this long for a follow-up (no wake word needed)
    "mic_gain": 16,
    "stt": {"engine": "auto", "model": "base.en", "language": "en"},   # auto = Groq Whisper when a Groq key exists (fast), else local faster-whisper
    "llm": {
        "provider": "",                  # "" = auto (anthropic/groq/gemini if that key is set, else local) | anthropic | groq | gemini | openai_compat | local
        "api_key": "",                   # Anthropic API key (or leave empty and set ANTHROPIC_API_KEY in the service env)
        "model": "claude-opus-5",
        "groq_key": "", "groq_model": "groq/compound",           # free tier at console.groq.com (legacy; routing uses the two below)
        "groq_fast_model": "qwen/qwen3.8-27b",                 # ~0.4 s answers: used unless the question needs the web
        "groq_search_model": "openai/gpt-oss-120b",              # bigger model with Groq's built-in browser search, 2-8 s
        # when a model fails (gone from the account, rate limited, timed out, empty answer) the next one gets a go
        # with more time; a model that answers "not found" is skipped for the rest of the session
        "groq_fallback_models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
        "gemini_key": "", "gemini_model": "gemini-2.0-flash",                # free tier at aistudio.google.com/apikey
        "custom": {"base_url": "https://openrouter.ai/api/v1", "key": "", "model": ""},   # any OpenAI-compatible endpoint
        "local": {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:1.5b"},      # Ollama on the CM4 (install/local_llm.sh)
        "web_search": True,
        "simulate_offline": False,        # test hook: behave as if the internet were down
        "max_tokens": 400,                # gpt-oss spends tokens on hidden reasoning; brevity comes from the trimmer below
        "max_sentences": 2,               # spoken answers are cut to this many sentences (5 when the question asks for detail)
        "system_prompt": (
            "You are Jarvis, the voice of HomeDeck, a home assistant with a screen that lives in the owner's home. "
            "Your replies are spoken aloud by a text-to-speech engine, so answer in one to three short sentences of "
            "plain conversational English: no markdown, no lists, no headings, no URLs, no emoji. Dates in words like September 28th, 2026, never digits with slashes or dashes. Dates in words like September 28th, 2026, never digits with slashes or dashes. Give the answer "
            "first. Use the room and location context you are given when it is relevant. If you looked something up, "
            "say the gist, not the sources. If you genuinely cannot help, say so in one sentence. "
            "You are speaking aloud. Answer in one or two short sentences unless asked for detail. No lists, no markdown. "
            "You cannot perform actions yourself: timers, alarms, reminders, lights, music and volume are handled by the device "
            "before you see the request. If a request sounds like such a command, say 'I didn't catch that, try again' instead of "
            "claiming it was done."
        ),
    },
    "tts": {"engine": "auto", "voice": "en_US-lessac-low", "espeak_voice": "en-us", "groq_voice": "daniel",
            "chirp": True, "gain_db": -5},           # auto = Groq Orpheus (~1 s, natural) whenever the key exists; Piper (6-7 s/sentence here) only offline
    "guest_enter_phrase": "jarvis guest mode",   # spoken phrase that hides personal data; exit phrase is general.guest_exit_phrase
    "history_len": 12,
    "vad": {"silence_s": 0.55, "max_utterance_s": 7, "min_utterance_s": 0.3},
    "mic_card": "sndrpigooglevoi",
    # which microphones to listen through: "" = automatic (the onboard mics, plus a USB microphone whenever one is
    # plugged in; both are scored for the wake word), "onboard" = built-in only, or a plughw name = that USB mic
    # (with the onboard mics). USB mics are opened through plughw so ALSA converts rate and channels for us.
    "mic_device": "",
    "mic_prefer_usb": True,        # record questions (and feed the mic taps) from the USB mic when one is in
    # acoustic echo cancellation: homedeck-aec reads the mics plus a loopback copy of everything the speakers play
    # and removes it (WebRTC AEC3), so the wake word and questions are heard over music and over Jarvis' own voice
    # Tuned on the device (2026-09-21): the echo reaches the mics 20-40 ms before the loopback copy, so the mic is
    # delayed 60 ms and the reference then leads by ~39 ms (delay hint 40). Noise suppression "low" scored best on the
    # wake model; a mono reference cancelled as well as stereo (19.3 vs 18.0 dB) at half the cost. Music alone never
    # scored above 0.09 after the canceller at volumes 40/55/70, so the wake threshold may drop to 0.4 while music plays.
    "aec": {"enabled": True, "binary": "/usr/local/bin/homedeck-aec",
            "delay_ms": 40, "mic_delay_ms": 60, "ns": 1, "stereo_ref": False,
            "music_wake_threshold": 0.4,      # wake threshold while the speakers are playing
            "speaking_threshold": 0.6, "speaking_onset_s": 0.2,    # barge-in while Jarvis talks, with AEC active
            # the USB microphone gets its own canceller instance: AEC3 estimates that mic's echo delay itself, so it
            # can be moved around; usb_delay_ms only keeps the loopback reference ahead of the echo (USB capture adds
            # 10-30 ms of its own latency). usb_gain is applied after ALSA's format conversion (1.0 = as recorded).
            "usb_gain": 1.0, "usb_delay_ms": 40},
}

MIC_RATE = 48000
MODEL_RATE = 16000
CHUNK = 1280                          # openWakeWord frame: 80 ms at 16 kHz

ctx = None                            # injected by server.py before start()
_lock = threading.Lock()
_speak_lock = threading.Lock()
_state = {
    "listening": False, "mic_enabled": True, "phase": "idle", "online": True,
    "last_transcript": "", "last_answer": "", "history": [], "errors": [],
    "deps": {"openwakeword": False, "faster_whisper": False, "anthropic": False, "piper": False, "espeak": False,
             "llm_ready": False, "llm_provider": "", "tts_engine_active": ""},
    "last_timings": {}, "speaking": False, "follow_up_open": False,
}
_history = []                         # [{"role": "user"|"assistant", "content": str}]
_net = {"online": True, "checked": 0.0}   # cached connectivity (see _online)
_last_source = {"v": "llm"}               # what answered the current turn, for the conversation log
_conv_lock = threading.Lock()
CONV_MAX = 5000
OFFLINE_MSG = "I'm offline right now, but timers, lights, music and math still work."
_speaking = threading.Event()
_capture = None                       # arecord Popen
_oww = None
_whisper = None
_llm = None


# ----------------------------------------------------------------------------- helpers
def _set_phase(p):
    with _lock:
        if _state["phase"] != p:
            _state["phase"] = p
            ctx.log(f"phase -> {p}")


def _err(msg):
    with _lock:
        if msg not in _state["errors"]:
            _state["errors"].append(msg)
    ctx.log(msg)


def _leds(pattern):
    m = ctx.module("leds") if ctx else None
    if ctx and not ctx.config.get("led_feedback", True):
        # owner turned off the light-bar reaction: never start a listen/think/answer pattern, but still return to idle
        if pattern != "idle":
            return
    if m and hasattr(m, "pattern"):
        try:
            m.pattern(pattern)
        except Exception as e:
            ctx.log(f"leds.pattern({pattern}) failed: {e}")


def _events_push(name, data=None):
    """Publish and mirror into the events ring the front-end polls."""
    ctx.emit(name, data or {})


# ----------------------------------------------------------------------------- audio capture
_capture_kind = "arecord"            # "aec" when homedeck-aec feeds the pipeline (16 kHz mono S16, already gained)
_aec_deaths = []                      # timestamps of helper exits; two within a minute -> fall back to arecord
_aec_disabled_until = 0.0
AEC_CONF = "/var/lib/homedeck/aec_runtime.conf"


def _aec_cfg():
    return ctx.config.get("aec", {}) or {}


def _write_aec_conf():
    a = _aec_cfg()
    txt = (f"delay_ms={int(a.get('delay_ms', 40))}\nmic_delay_ms={int(a.get('mic_delay_ms', 60))}\n"
           f"ns={int(a.get('ns', 1))}\ngain={float(ctx.config.get('mic_gain', 16))}\naec=1\ndump_s=6\n"
           f"stereo_ref={1 if a.get('stereo_ref') else 0}\n"
           f"gain2={float(a.get('usb_gain', 1.0))}\nmic2_delay_ms={int(a.get('usb_delay_ms', 40))}\n")
    try:
        with open(AEC_CONF, "w") as f:
            f.write(txt)
    except Exception as e:
        ctx.log(f"aec: could not write {AEC_CONF}: {e}")


def _aec_usable():
    a = _aec_cfg()
    return bool(a.get("enabled", True)) and os.path.isfile(a.get("binary", "")) and time.time() >= _aec_disabled_until


def _onboard_device():
    return f"hw:CARD={ctx.config.get('mic_card', 'sndrpigooglevoi')},DEV=0"


def _usb_capture_cards():
    """Capture cards other than the onboard I2S card and the loopback: USB microphones, as plughw devices so ALSA
    converts their rate and channel count for the pipeline. [{"device", "name", "id"}], in card order."""
    out = []
    try:
        with open("/proc/asound/cards") as f:
            txt = f.read()
    except Exception:
        return out
    onboard = ctx.config.get("mic_card", "sndrpigooglevoi")
    for m in re.finditer(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(.*)$", txt, re.M):
        idx, card_id, desc = m.group(1), m.group(2), m.group(3).strip()
        if card_id in (onboard, "Loopback") or card_id.startswith("vc4hdmi"):
            continue
        if not os.path.exists(f"/proc/asound/card{idx}/pcm0c"):     # no capture stream on this card
            continue
        out.append({"device": f"plughw:CARD={card_id},DEV=0", "name": (desc.split(" - ", 1)[-1].strip() or card_id), "id": card_id})
    return out


def _pick_mics():
    """What to listen through right now: (onboard device, USB device or None, USB mic name).
    mic_device "" = automatic (onboard mics plus the first USB microphone when one is plugged in); "onboard" = built-in
    only; a plughw name = that USB microphone, or any other one when it is missing, together with the onboard mics."""
    onboard = _onboard_device()
    want = (ctx.config.get("mic_device") or "").strip()
    if want == "onboard" or time.time() < _usb_dead["hold_until"]:
        return onboard, None, ""
    cards = _usb_capture_cards()
    if not cards:
        return onboard, None, ""
    pick = next((c for c in cards if c["device"] == want), cards[0])
    return onboard, pick["device"], pick["name"]


def mic_device():
    """ALSA device the fallback (plain arecord) capture would use: the USB mic when one is in and preferred."""
    onboard, usb, _ = _pick_mics()
    return usb if usb and ctx.config.get("mic_prefer_usb", True) else onboard


_capture_mics = ("", None)            # (onboard, usb) the running capture was opened with; the hotplug watcher compares
_dual = False                         # helper outputs two channels (onboard, USB); their sum is scored for the wake word
_reopen = {"pending": False}          # a deliberate restart: not a helper failure, and no retry backoff
_paused_until = 0.0                   # another module borrowed the microphones (speaker calibration); reopen after


def _mics_text():
    m = _state.get("mics") or {}
    if m.get("usb") and m.get("onboard"):
        return f"built-in mics + {m['usb']}"
    return m.get("usb") or "built-in mics"


def _open_capture():
    global _capture, _capture_kind, _capture_mics, _dual
    onboard, usb, usb_name = _pick_mics()
    _capture_mics = (onboard, usb)
    dev = onboard
    if _aec_usable():
        _write_aec_conf()
        args = [_aec_cfg().get("binary"), "--mic", onboard] + (["--mic2", usb] if usb else [])
        _capture = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)   # buffered: read(n) returns whole frames
        _capture_kind = "aec"
        _dual = bool(usb)
    else:
        dev = usb if (usb and ctx.config.get("mic_prefer_usb", True)) else onboard
        _capture = subprocess.Popen(
            ["arecord", "-q", "-D", dev, "-f", "S32_LE", "-r", str(MIC_RATE), "-c", "2", "-t", "raw"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        _capture_kind = "arecord"
        _dual = False
    with _lock:
        _state["aec_active"] = _capture_kind == "aec"
        _state["mics"] = {"onboard": _dual or dev == onboard, "usb": usb_name if (_dual or dev == usb) else "",
                          "usb_present": bool(usb), "both": _dual}
    return _capture


def list_capture_devices():
    """Choices for the Jarvis app: automatic, built-in only, or a specific USB microphone (always with the built-in)."""
    out = [{"device": "", "name": "Automatic: built-in mics, plus a USB microphone when plugged in", "onboard": True},
           {"device": "onboard", "name": "Built-in microphones only", "onboard": True}]
    for c in _usb_capture_cards():
        out.append({"device": c["device"], "name": f"Built-in + {c['name']}", "onboard": False})
    return out


def _restart_capture():
    """Drop the current capture so the pipeline reopens it (device change, or the helper needs new settings)."""
    global _capture
    c = _capture
    if c is not None and c.poll() is None:
        _reopen["pending"] = True
        try:
            c.terminate()
        except Exception:
            pass


_usb_dead = {"since": 0.0, "strikes": [], "hold_until": 0.0}


def _hotplug_loop():
    """Every 2 s: when a USB microphone appears, goes away, or the pick changes, reopen the capture with the new set.
    Also watches the helper's USB channel: if it reports the mic as gone (its channel then just repeats the
    built-in mics, which would silently put the fan noise on the question recording), the capture is reopened;
    after two failures in five minutes the USB mic is left out for five minutes so the built-in mics work alone."""
    while True:
        time.sleep(2)
        try:
            if _capture is None or _capture.poll() is not None:
                continue
            now = time.time()
            onboard, usb, name = _pick_mics()
            if now < _usb_dead["hold_until"]:
                usb, name = None, ""
            if (onboard, usb) != _capture_mics:
                ctx.log(f"USB microphone {('plugged in: ' + name) if usb else 'removed'}; reopening the microphones")
                if usb:
                    time.sleep(2.5)                 # a freshly plugged card lists before its audio interface is ready
                _restart_capture()
                continue
            fresh = now - _aec_stats.get("t", 0) < 3
            if _dual and fresh and _aec_stats.get("mic2_ok") is False:
                if not _usb_dead["since"]:
                    _usb_dead["since"] = now
                elif now - _usb_dead["since"] > 4:
                    _usb_dead["since"] = 0.0
                    _usb_dead["strikes"] = [t for t in _usb_dead["strikes"] if now - t < 300] + [now]
                    if len(_usb_dead["strikes"]) >= 2:
                        _usb_dead["hold_until"] = now + 300
                        ctx.log("USB microphone keeps failing; using the built-in mics alone for 5 minutes")
                    else:
                        ctx.log("USB microphone stopped delivering audio; reopening the microphones")
                    _restart_capture()
            else:
                _usb_dead["since"] = 0.0
        except Exception as e:
            ctx.log(f"mic hotplug check failed: {e}")


def _capture_died():
    """Called when the capture pipe closes: track helper failures and fall back to plain arecord if it keeps dying."""
    global _aec_disabled_until
    if _capture_kind != "aec" or _reopen["pending"]:
        return
    now = time.time()
    _aec_deaths.append(now)
    del _aec_deaths[:-3]
    if len([t for t in _aec_deaths if now - t < 60]) >= 2:
        _aec_disabled_until = now + 600
        ctx.log("aec: echo canceller stopped twice within a minute; using the plain microphone for 10 minutes")


def aec_reload():
    """Push the current delay/noise settings to the running helper without restarting anything."""
    _write_aec_conf()
    if _capture is not None and _capture_kind == "aec" and _capture.poll() is None:
        try:
            _capture.send_signal(signal.SIGHUP)
        except Exception:
            pass


# live numbers from the helper (UDP datagrams every 100 ms): reference / mic / output levels
_aec_stats = {"t": 0.0}


def _aec_stats_loop():
    import socket
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sk.bind(("127.0.0.1", 47811))
    except Exception as e:
        ctx.log(f"aec stats: {e}")
        return
    erle_avg = None
    while True:
        try:
            data, _ = sk.recvfrom(2048)
            j = json.loads(data.decode())
            j["t"] = time.time()
            # our own echo-reduction figure: mic vs output while the reference is clearly playing
            if j.get("ref_running") and j.get("ref", -120) > -60 and j.get("mic", -120) > -70:
                e = max(0.0, j["mic"] - j["out"])
                erle_avg = e if erle_avg is None else 0.9 * erle_avg + 0.1 * e
            j["erle_live"] = None if erle_avg is None else round(erle_avg, 1)
            _aec_stats.clear(); _aec_stats.update(j)
        except Exception:
            time.sleep(0.2)


_speech_peaks = []
_calib = {"running": False, "step": "", "result": None}


def _helper_dump(seconds):
    """Ask the running helper for an aligned mic/reference/output dump of `seconds`; returns int16 arrays or None."""
    try:
        with open(AEC_CONF) as f:
            conf = f.read()
        conf = re.sub(r"dump_s=\d+", f"dump_s={int(seconds)}", conf) if "dump_s=" in conf else conf + f"dump_s={int(seconds)}\n"
        with open(AEC_CONF, "w") as f:
            f.write(conf)
        _capture.send_signal(signal.SIGHUP); time.sleep(0.2)
        try:
            os.remove("/tmp/aecdump/done")
        except FileNotFoundError:
            pass
        _capture.send_signal(signal.SIGUSR1)
        t0 = time.time()
        while not os.path.exists("/tmp/aecdump/done"):
            if time.time() - t0 > seconds + 5:
                return None
            time.sleep(0.1)
        return [np.fromfile(f"/tmp/aecdump/{n}.raw", dtype=np.int16).astype(np.float64) for n in ("mic", "ref", "out")]
    except Exception as e:
        ctx.log(f"calibration dump failed: {e}")
        return None


def _db(x):
    return float(20 * np.log10(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)) / 32768 + 1e-12)) if len(x) else -120.0


def _calibrate():
    """Measure the room and the speaker-to-mic echo path, set the delay hint, and report plainly.
    1) 3 s of silence -> noise floor. 2) a gentle 4 s pink-noise burst at the current volume -> echo delay by
    cross-correlation and echo reduction with the canceller on. 3) advice on mic gain from real speech levels."""
    _calib.update({"running": True, "step": "Listening to the room", "result": None})
    try:
        a = _aec_cfg()
        quiet = _helper_dump(3)
        if quiet is None:
            raise RuntimeError("the microphone did not answer")
        noise_db = _db(quiet[0])
        _calib["step"] = "Playing a test sound"
        sr = 48000; n = sr * 4
        white = np.random.default_rng(7).standard_normal(n + 4096)
        b = np.array([0.049922035, -0.095993537, 0.050612699, -0.004408786]); av = np.array([1, -2.494956002, 2.017265875, -0.522189400])
        try:                                                             # pink noise via the standard 1/f IIR
            from scipy.signal import lfilter
            pink = lfilter(b, av, white)
        except Exception:
            spec = np.fft.rfft(white); f = np.arange(len(spec)); f[0] = 1
            pink = np.fft.irfft(spec / np.sqrt(f), len(white))
        pink = pink[4096:]; pink /= np.max(np.abs(pink)) + 1e-9
        fade = np.minimum(1, np.minimum(np.arange(n), n - 1 - np.arange(n)) / (0.25 * sr))
        pcm = (pink * fade * 0.18 * 32767).astype(np.int16)             # about -25 dBFS RMS: audible, not harsh
        import wave as _wave
        with _wave.open("/tmp/hd_cal_noise.wav", "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes(np.repeat(pcm, 2).tobytes())
        player = subprocess.Popen(["aplay", "-q", "-D", PLAY_DEVICE, "/tmp/hd_cal_noise.wav"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)
        dump = _helper_dump(4.5)
        player.wait(timeout=10)
        if dump is None:
            raise RuntimeError("could not record the test sound")
        mic, ref, out = dump
        if _db(ref) < -70:
            raise RuntimeError("the test sound did not reach the echo reference (loopback)")
        # echo delay: where the mic (already delayed by mic_delay_ms) best matches the reference
        m = mic - mic.mean(); r = ref - ref.mean(); L = 1 << int(np.ceil(np.log2(len(m) + 8000)))
        cc = np.fft.irfft(np.fft.rfft(m, L) * np.conj(np.fft.rfft(r, L)), L)
        lags = np.concatenate([np.arange(0, 6400), np.arange(-1600, 0)]); vals = np.concatenate([cc[:6400], cc[-1600:]])
        k = int(np.argmax(np.abs(vals))); lag_ms = float(lags[k] / 16.0)
        corr = float(abs(vals[k]) / (np.sqrt(np.sum(m ** 2) * np.sum(r ** 2)) + 1e-9))
        h = len(mic) // 3                                                    # skip the first third while it converges
        echo_db = _db(mic[h:]); out_db = _db(out[h:])
        erle = max(0.0, echo_db - out_db)
        coupling = echo_db - _db(ref[h:])                                    # how loud the speakers are in the mics
        mic_delay = int(a.get("mic_delay_ms", 60)); delay_hint = int(a.get("delay_ms", 40))
        if corr > 0.05:
            if lag_ms < 8:                      # reference would not lead the echo: delay the mic a little more
                mic_delay = int(min(200, mic_delay + (15 - lag_ms)))
                lag_ms = 15.0
            delay_hint = int(max(0, round(lag_ms)))
        gain = float(ctx.config.get("mic_gain", 16)); gain_advice = gain
        if len(_speech_peaks) >= 3:
            med = float(np.median(_speech_peaks))
            if med > 0:
                gain_advice = round(max(4.0, min(48.0, gain * 8000.0 / med)), 1)   # speech peaks near -12 dBFS
        if noise_db > -30:
            gain_advice = min(gain_advice, round(gain * 10 ** ((-34 - noise_db) / 20), 1))
        room = "quiet" if noise_db < -45 else "moderate" if noise_db < -32 else "noisy"
        if erle >= 20: verdict, hint = "Excellent", ""
        elif erle >= 12: verdict, hint = "Good", ""
        elif erle >= 6: verdict, hint = "Fair", "Some of the speaker sound still reaches the mics. Keep the device away from walls behind the speakers and turn the music down a little when talking from far away."
        else: verdict, hint = "Poor", "Speakers are rattling into the mics: add foam or gaskets between the speakers and the case, and make sure the mic holes are not next to a speaker opening."
        if room == "noisy" and not hint:
            hint = "The room is noisy (fan or appliances). Jarvis may need you to speak up a little."
        res = {"t": time.time(), "erle_db": round(erle, 1), "delay_ms": delay_hint, "mic_delay_ms": mic_delay,
               "noise_db": round(noise_db, 1), "room": room, "coupling_db": round(coupling, 1), "correlation": round(corr, 2),
               "mic_gain": gain, "mic_gain_suggested": gain_advice, "verdict": verdict, "hint": hint,
               "summary": f"Echo reduced by {erle:.0f} dB · delay {delay_hint} ms · room noise {room} · {'ready' if erle >= 12 else 'usable' if erle >= 6 else 'needs attention'}"}
        ctx.config.setdefault("aec", {}).update({"delay_ms": delay_hint, "mic_delay_ms": mic_delay, "calibration": res})
        ctx.save_config()
        aec_reload()
        ctx.log("calibration: " + res["summary"] + (f" (hint: {hint})" if hint else ""))
        _calib.update({"running": False, "step": "Done", "result": res})
    except Exception as e:
        ctx.log(f"calibration failed: {e}")
        _calib.update({"running": False, "step": "Failed", "result": {"error": str(e)}})
    finally:
        try:
            aec_reload()
        except Exception:
            pass


def ref_level():
    """Loudness of what the speakers are playing (dBFS, from the echo-canceller reference), or None if unknown.
    The LED music visualiser uses this once echo cancellation removes the music from the microphone."""
    if time.time() - _aec_stats.get("t", 0) > 1.0 or not _aec_stats.get("ref_running"):
        return None
    return _aec_stats.get("ref")


def ref_bands():
    """What the speakers play right now, as linear levels (int16 units): rms, bass, mid, treble; None when unknown."""
    if time.time() - _aec_stats.get("t", 0) > 1.0 or not _aec_stats.get("ref_running") or "rr" not in _aec_stats:
        return None
    return {"rms": _aec_stats["rr"], "bass": _aec_stats["rb"], "mid": _aec_stats["rm"], "treble": _aec_stats["rt"]}


def _speakers_loud():
    r = ref_level()
    return r is not None and r > -50


def _close_capture():
    global _capture
    if _capture:
        try:
            _capture.kill()
        except Exception:
            pass
        _capture = None


_dbg = {"mic_level": 0.0, "wake_score": 0.0, "wake_score_max": 0.0, "t": 0.0, "mic_level_onboard": None, "mic_level_usb": None}
def _rms(ch):
    return float(np.sqrt(np.mean(ch.astype(np.float32) ** 2)))


def _dbg_update(ch, score):
    """Live diagnostics for the Settings page: mic RMS (after gain, 0-32767) and the wake score (5 s peak-hold)."""
    now = time.time()
    rms = _rms(ch)
    _dbg["mic_level"] = round(rms, 1); _dbg["wake_score"] = round(score, 3)
    if _alt.get("chunk") is not None:
        _dbg["mic_level_onboard"] = round(_rms(_alt["onboard"]), 1); _dbg["mic_level_usb"] = round(_rms(_alt["usb"]), 1)
    else:
        _dbg["mic_level_onboard"] = _dbg["mic_level_usb"] = None
    if score > _dbg["wake_score_max"] or now - _dbg["t"] > 5:
        _dbg["wake_score_max"] = round(score, 3); _dbg["t"] = now


_mic_taps = []      # callables fn(chunk_int16, rms) run for every 80 ms mic frame; other modules subscribe (LED VU)


def add_mic_tap(fn):
    if fn not in _mic_taps:
        _mic_taps.append(fn)


def remove_mic_tap(fn):
    try:
        _mic_taps.remove(fn)
    except ValueError:
        pass


def _run_taps(ch):
    if not _mic_taps:
        return
    rms = float(np.sqrt(np.mean(ch.astype(np.float32) ** 2)))
    for fn in list(_mic_taps):
        try:
            fn(ch, rms)
        except Exception as e:
            ctx.log(f"mic tap {getattr(fn, '__name__', fn)} failed, removed: {e}")
            remove_mic_tap(fn)


_alt = {"chunk": None, "onboard": None, "usb": None, "mix": None,   # per-mic frames and their weighted sum when two mics run
        "nf_on": 300.0, "nf_usb": 300.0, "w_on": 1.0,                 # running noise floors and the onboard weight they give
        "peak": 3000.0, "agc": 1.0}                                   # slow-decaying loudness of the mix and the gain it earns


def _read_chunk():
    """Read one 80 ms frame: returns int16 mono @ 16 kHz (CHUNK samples) or None if the pipe died.
    With two mics the helper interleaves (onboard, USB); the preferred one is returned (questions are recorded from
    it) and the sum of both is kept in _alt["mix"] for the wake word, so either mic can hear "Hey Jarvis" at the cost
    of one model. (Tested offline: the sum still scores 0.9+ with 3-80 ms between the mics and one at 30 % level.
    A second full model would need another half core, which the CM4 does not have next to the kiosk and camera.)
    Every returned frame also goes to the registered mic taps (see add_mic_tap)."""
    if _capture_kind == "aec":
        width = 2 if _dual else 1
        raw = _capture.stdout.read(CHUNK * 2 * width) if _capture else b""
        if len(raw) < CHUNK * 2 * width:
            return None
        a = np.frombuffer(raw, dtype=np.int16)              # already 16 kHz with gain applied by the helper
        if _dual:
            a = a.reshape(-1, 2)
            onboard, usb = a[:, 0].copy(), a[:, 1].copy()
            ch, other = (usb, onboard) if ctx.config.get("mic_prefer_usb", True) else (onboard, usb)
            # the wake word hears the USB mic in full and the onboard mics scaled so their noise floor (fan, x16 gain)
            # matches the USB mic's: the quieter mic leads, the noisy one still adds speech it hears above its noise
            # noise floors: follow drops quickly, rises slowly (speech is brief, a fan that turned on is not)
            for key, r in (("nf_on", _rms(onboard)), ("nf_usb", _rms(usb))):
                r = max(r, 20.0); nf = _alt[key]
                _alt[key] = nf + (0.004 if r > nf else 0.05) * (r - nf)
            w = _alt["w_on"] = max(0.1, min(1.0, _alt["nf_usb"] / max(_alt["nf_on"], 1.0)))
            mixf = usb.astype(np.float32) + onboard.astype(np.float32) * w
            # far-field gain: speech from across the room reaches the USB mic quietly, and the wake model wants the
            # level the built-in mics used to give it (x16 gain, noise floor ~800-1500). The mix is lifted so its
            # noise floor sits at wake_agc_floor, whatever was said a moment ago (a peak tracker stayed at x1 for
            # 15 s after every question, so the next one from across the room was too quiet). Capped at x8.
            floor = max(_alt["nf_usb"] * (1 + w), 20.0)
            g = max(1.0, min(float(ctx.config.get("wake_agc_max", 8)), float(ctx.config.get("wake_agc_floor", 800)) / floor))
            _alt["agc"] = g
            mix = np.clip(mixf * g, -32768, 32767).astype(np.int16)
            _alt.update({"chunk": other, "onboard": onboard, "usb": usb, "mix": mix})
            if g > 1.0:                                              # the question is recorded from the same distance
                ch = np.clip(ch.astype(np.float32) * g, -32768, 32767).astype(np.int16)
        else:
            ch = a.copy()
            _alt.update({"chunk": None, "mix": None})
        _run_taps(ch)
        return ch
    _alt.update({"chunk": None, "mix": None})
    n_in = CHUNK * 3                        # 48 kHz -> 16 kHz is a factor of 3
    raw = _capture.stdout.read(n_in * 2 * 4) if _capture else b""
    if len(raw) < n_in * 8:
        return None
    a = np.frombuffer(raw, dtype=np.int32).reshape(-1, 2).astype(np.float32)
    mono = a.mean(axis=1)
    mono = mono.reshape(-1, 3).mean(axis=1)                # box-filter decimation
    # ICS-43434 MEMS mics are quiet (~1/50 full scale for speech); the wake-word model wants normal int16
    # speech levels, so apply a software gain (config mic_gain, default 16) with clipping.
    gain = float(ctx.config.get("mic_gain", 16)) if ctx else 16.0
    ch = np.clip(mono / 65536.0 * gain, -32768, 32767).astype(np.int16)
    _run_taps(ch)
    return ch


# ----------------------------------------------------------------------------- lazy deps
def _make_oww():
    import openwakeword
    from openwakeword.model import Model
    try:
        openwakeword.utils.download_models([ctx.config["wake_word"]])
    except Exception:
        pass
    # openwakeword API differs between releases: newer builds take wakeword_model_paths (file paths),
    # older ones take wakeword_models (names). Resolve the bundled hey_jarvis .onnx and try both.
    import glob, os as _os, openwakeword as _ow
    name = ctx.config["wake_word"]
    paths = glob.glob(_os.path.join(_os.path.dirname(_ow.__file__), "resources", "models", f"{name}*.onnx"))
    try:
        return Model(wakeword_model_paths=paths or [name])          # openwakeword >= 0.7 style
    except TypeError:
        return Model(wakeword_models=paths or [name], inference_framework="onnx")   # 0.5/0.6 style


def _load_oww():
    global _oww
    if _oww is not None:
        return _oww
    try:
        _oww = _make_oww()
        with _lock:
            _state["deps"]["openwakeword"] = True
        return _oww
    except Exception as e:
        _err(f"openwakeword unavailable ({e}); run install/voice_deps.sh")
        return None


def _wake_score(oww, ch, want):
    """Wake-word score for this frame. With two mics the model hears their sum, so a wake word reaching either mic
    counts. Returns (score, which) where which names the mic that was louder in this frame ("usb"/"onboard")."""
    frame = _alt.get("mix")
    sc = oww.predict(frame if frame is not None else ch)
    score = max([float(v) for k, v in sc.items() if k.startswith(want)] or [0.0])
    which = "onboard"
    if frame is not None and _dual:
        which = "usb" if _rms(_alt["usb"]) >= _rms(_alt["onboard"]) else "onboard"
    return score, which


def _reset_oww(oww):
    oww.reset()


def _load_whisper():
    global _whisper
    if _whisper is not None:
        return _whisper
    try:
        from faster_whisper import WhisperModel
        cfg = ctx.config["stt"]
        _whisper = WhisperModel(cfg.get("model", "base.en"), device="cpu", compute_type="int8")
        with _lock:
            _state["deps"]["faster_whisper"] = True
        return _whisper
    except Exception as e:
        _err(f"faster-whisper unavailable ({e}); run install/voice_deps.sh")
        return None


def _load_llm():
    global _llm
    if _llm is not None:
        return _llm
    try:
        import anthropic
        key = ctx.config["llm"].get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            _err("no Anthropic API key: set it in the Jarvis app or ANTHROPIC_API_KEY")
            return None
        _llm = anthropic.Anthropic(api_key=key, timeout=60.0)
        with _lock:
            _state["deps"]["anthropic"] = True
            _state["errors"] = [e for e in _state["errors"] if "API key" not in e]
        return _llm
    except ImportError as e:
        _err(f"anthropic SDK missing ({e}); pip install --break-system-packages anthropic")
        return None


def _piper_bin():
    d = os.path.join(ctx.data_dir, "piper")
    for c in (os.path.join(d, "piper", "piper"), os.path.join(d, "piper"), shutil.which("piper") or ""):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _refresh_deps():
    with _lock:
        _state["deps"]["piper"] = bool(_piper_bin() and os.path.isfile(
            os.path.join(ctx.data_dir, "piper", ctx.config["tts"]["voice"] + ".onnx")))
        _state["deps"]["espeak"] = bool(shutil.which("espeak-ng"))
    try:
        import openwakeword  # noqa: F401
        with _lock: _state["deps"]["openwakeword"] = True
    except Exception:
        pass
    try:
        import faster_whisper  # noqa: F401
        with _lock: _state["deps"]["faster_whisper"] = True
    except Exception:
        pass
    try:
        import anthropic  # noqa: F401
        with _lock: _state["deps"]["anthropic"] = bool(ctx.config["llm"].get("api_key") or os.environ.get("ANTHROPIC_API_KEY"))
    except Exception:
        pass
    try:
        pid = _provider(); ready = _provider_ready(pid)
        with _lock:
            _state["deps"]["llm_provider"] = pid; _state["deps"]["llm_ready"] = bool(ready)
    except Exception:
        pass


# ----------------------------------------------------------------------------- TTS
_groq_tts_block_until = 0.0        # Orpheus said no (terms not accepted / 4xx): don't retry for a while
_tts_seq = 0
PLAY_DEVICE = "default"            # ALSA softvol chain (install/audio_setup.sh); obeys the system volume


_DETAIL_WORDS = re.compile(r"\b(explain|detail|details|why|how does|how do|how did|tell me more|list|steps|elaborate|walk me through|in depth|more about)\b", re.I)
_FILLER = re.compile(r"^(let me know if( you need| there'?s)? anything else|is there anything else|hope (that|this) helps|"
                     r"feel free to ask|anything else i can (help|do)|happy to help|if you (have|need) (any )?(more|other|further) questions?)[^.!?]*[.!?]?$", re.I)


def _trim_answer(question, answer):
    """Keep spoken answers short: first N sentences (config llm.max_sentences, default 2), or up to 5 when the
    question asks for detail; drop trailing chatbot filler like 'Let me know if you need anything else'."""
    answer = re.sub(r"\s+", " ", answer or "").strip()
    if not answer:
        return answer
    limit = int(ctx.config["llm"].get("max_sentences", 2) or 2)
    if _DETAIL_WORDS.search(question or ""):
        limit = max(limit, 5)
    parts = [x.strip() for x in re.split(r"(?<=[.!?])\s+", answer) if x.strip()]
    parts = [x for x in parts if not _FILLER.match(x)] or parts
    return " ".join(parts[:limit]) if parts else answer


def _sentences(text):
    """Split spoken text into sentence-sized chunks so playback can start after the first one."""
    text = re.sub(r"\s+", " ", text or "").strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text)
    out, buf = [], ""
    for i, part in enumerate(parts):
        buf = (buf + " " + part).strip()
        if len(buf) >= 40 or i == len(parts) - 1:
            out.append(buf); buf = ""
    if buf:
        out.append(buf)
    return [x for x in out if x]


def _tts_groq(text, wav):
    """Groq Orpheus TTS -> wav. Returns True on success; remembers 4xx failures for 10 minutes."""
    global _groq_tts_block_until
    import urllib.request, urllib.error
    key = (ctx.config["llm"].get("groq_key") or "").strip()
    if not key or time.time() < _groq_tts_block_until:
        return False
    payload = {"model": "canopylabs/orpheus-v1-english", "voice": ctx.config["tts"].get("groq_voice", "daniel"),
               "input": text[:1500], "response_format": "wav"}
    req = urllib.request.Request("https://api.groq.com/openai/v1/audio/speech", data=json.dumps(payload).encode(), method="POST",
                                 headers={"User-Agent": "HomeDeck/1.0", "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
        if len(data) < 100 or not data.startswith(b"RIFF"):
            raise RuntimeError("no audio returned")
        with open(wav, "wb") as f:
            f.write(data)
        return True
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode(errors="replace")[:160]
        except Exception:
            pass
        if 400 <= e.code < 500:
            _groq_tts_block_until = time.time() + 600
            if "terms" in body:
                _err("Groq voice unavailable: accept the Orpheus terms in the Groq console to enable it; using Piper")
            else:
                _err(f"Groq voice failed ({e.code}); using Piper for 10 min")
        return False
    except Exception as e:
        ctx.log(f"groq tts failed: {e}")
        return False


def _tts_piper(text, wav):
    tts = ctx.config["tts"]
    piper = _piper_bin()
    model = os.path.join(ctx.data_dir, "piper", tts["voice"] + ".onnx")
    if not os.path.isfile(model):
        for fb in ("en_US-lessac-low.onnx", "en_US-lessac-medium.onnx"):   # configured voice missing/downloading: fastest present fallback
            fbp = os.path.join(ctx.data_dir, "piper", fb)
            if os.path.isfile(fbp):
                model = fbp; break
    if piper and os.path.isfile(model):
        r = subprocess.run([piper, "--model", model, "--output_file", wav, "--length_scale", "0.92", "--sentence_silence", "0.15"],
                           input=text.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        return r.returncode == 0 and os.path.isfile(wav)
    if shutil.which("espeak-ng"):
        subprocess.run(["espeak-ng", "-v", tts.get("espeak_voice", "en-us"), "-w", wav, text],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        return os.path.isfile(wav)
    _err("no TTS engine: install piper (install/voice_deps.sh) or espeak-ng")
    return False


def _synth(text, wav):
    """Text -> wav with the configured engine ('auto' prefers Groq, falls back to Piper). Returns engine name or None."""
    eng = ctx.config["tts"].get("engine", "auto")
    used = None
    if eng == "auto" and not _online():
        eng = "piper"
    if eng in ("auto", "groq") and _tts_groq(text, wav):
        used = "groq"
    elif _tts_piper(text, wav):
        used = "piper"
    if not used:
        return None
    # gentle high-pass protects the small full-range drivers from lows they can't reproduce (needs sox)
    if shutil.which("sox"):
        try:
            tmp = wav + ".hp.wav"
            subprocess.run(["sox", wav, tmp, "highpass", "120", "gain", str(float(ctx.config["tts"].get("gain_db", -5)))],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            if os.path.isfile(tmp) and os.path.getsize(tmp) > 44:
                os.replace(tmp, wav)
        except Exception:
            pass
    with _lock:
        _state["deps"]["tts_engine_active"] = used
    return used


_players = []                      # running aplay Popen objects (so barge-in can kill them)
_players_lock = threading.Lock()
_abort_speech = threading.Event()  # set by _stop_speaking(); say_stream stops between sentences
_speak_started_at = 0.0            # when the current playback began (echo guard for barge-in)
_follow_up_until = 0.0             # follow-up window deadline (0 = closed)
_STOP_WORDS = re.compile(r"^\W*(stop|cancel|never ?mind|nevermind|thanks?( you)?|thank you|that'?s (all|it)|that is all|no thanks?|okay|ok)\W*$", re.I)


def _play(wav):
    """Play a wav through the softvol device; the process is tracked so _stop_speaking() can kill it."""
    global _speak_started_at
    if _abort_speech.is_set():
        return
    p = subprocess.Popen(["aplay", "-q", "-D", PLAY_DEVICE, wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with _players_lock:
        _players.append(p)
        if len(_players) == 1:
            _speak_started_at = time.time()
    try:
        p.wait(timeout=120)
    except subprocess.TimeoutExpired:
        p.kill()
    finally:
        with _players_lock:
            if p in _players:
                _players.remove(p)


def _stop_speaking():
    """Barge-in: abort the current utterance immediately (kills aplay, skips remaining sentences)."""
    if not _speaking.is_set():
        return False
    _abort_speech.set()
    with _players_lock:
        procs = list(_players)
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass
    ctx.log("speech interrupted")
    return True


def _chirp():
    """Short 'go ahead' tone after the wake word (generated once into <data_dir>/sounds/chirp.wav)."""
    if not ctx.config["tts"].get("chirp", True):
        return
    path = os.path.join(ctx.data_dir, "sounds", "chirp.wav")
    try:
        if not os.path.isfile(path):
            import wave
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # a soft, quiet two-note blip (about -20 dB): a gentle "go ahead", not an alarm
            sr = 16000
            def note(freq, secs, amp):
                n = int(sr * secs); t = np.arange(n) / sr
                env = np.sin(np.pi * t / secs) ** 2            # smooth raised-sine envelope, no clicks
                return np.sin(2 * np.pi * freq * t) * env * amp
            pcm = np.concatenate([note(1046.5, 0.045, 0.07), np.zeros(int(sr * 0.015)), note(1318.5, 0.055, 0.06)])
            pcm = (pcm * 32767).astype(np.int16)
            with wave.open(path, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())
        subprocess.Popen(["aplay", "-q", "-D", PLAY_DEVICE, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        ctx.log(f"chirp failed: {e}")


def _wav_pcm(path, want=None):
    """Read a WAV -> (pcm_bytes, rate, channels, sampwidth). If want=(rate,ch,sw) differs, convert with sox.
    Applies a 5 ms fade-in/out (int16 only) so sentence boundaries never click."""
    import wave
    def read(pth):
        with wave.open(pth, "rb") as w:
            return w.readframes(w.getnframes()), w.getframerate(), w.getnchannels(), w.getsampwidth()
    pcm, rate, ch, sw = read(path)
    if want and (rate, ch, sw) != want and shutil.which("sox"):
        conv = path + ".conv.wav"
        subprocess.run(["sox", path, "-r", str(want[0]), "-c", str(want[1]), "-b", str(want[2] * 8), conv],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        if os.path.isfile(conv) and os.path.getsize(conv) > 44:
            pcm, rate, ch, sw = read(conv)
            try: os.remove(conv)
            except OSError: pass
    if sw == 2 and len(pcm) >= 4:
        a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        n = min(int(rate * ch * 0.005), len(a) // 2)
        if n > 0:
            ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
            a[:n] *= ramp; a[-n:] *= ramp[::-1]
        pcm = a.astype(np.int16).tobytes()
    return pcm, rate, ch, sw


def _reap_stale_players(max_age=60):
    """Kill any playback process older than max_age s: a stalled aplay would otherwise hold the sound device."""
    now = time.time()
    with _players_lock:
        for pl in list(_players):
            try:
                if pl.poll() is None and now - getattr(pl, "_hd_started", now) > max_age:
                    pl.kill(); _players.remove(pl)
            except Exception:
                pass


_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def _ordinal(n):
    n = int(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _speakable(text):
    """Turn written dates into spoken ones so the voice does not read digits: 2026-09-28 and 9/28/2026 become
    "September 28th, 2026", 9/28 becomes "September 28th", and 2026-09 "September 2026"."""
    def iso(m):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{_MONTHS[mo - 1]} {_ordinal(d)}, {y}" if 1 <= mo <= 12 and 1 <= d <= 31 else m.group(0)
    def us(m):
        mo, d, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return m.group(0)
        if y:
            y = int(y); y = y + 2000 if y < 100 else y
            return f"{_MONTHS[mo - 1]} {_ordinal(d)}, {y}"
        return f"{_MONTHS[mo - 1]} {_ordinal(d)}"
    def ym(m):
        y, mo = int(m.group(1)), int(m.group(2))
        return f"{_MONTHS[mo - 1]} {y}" if 1 <= mo <= 12 else m.group(0)
    t = re.sub(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", iso, text)
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", us, t)
    # month/day without a year only after a date word, so fractions and scores ("3/4", "21/30") stay as they are
    t = re.sub(r"(?:(?<=\bon )|(?<=\bby )|(?<=\bfrom )|(?<=\buntil )|(?<=\bsince )|(?<=\bafter )|(?<=\bbefore )|(?<=\bdue ))(\d{1,2})/(\d{1,2})(?!/)()\b", us, t)
    t = re.sub(r"\b(\d{4})-(\d{1,2})\b", ym, t)
    t = re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)? (January|February|March|April|May|June|July|August|September|October|November|December)\b",
               lambda m: f"the {_ordinal(m.group(1))} of {m.group(2)}", t)    # "28 September" reads oddly as digits
    return t


def say_stream(text, timings=None):
    """Speak text sentence by sentence through ONE aplay process: synthesise chunk N+1 while chunk N plays,
    write each sentence's PCM into the same pipe (no per-sentence device open/close pops)."""
    _reap_stale_players()
    global _tts_seq, _speak_started_at
    text = _speakable(re.sub(r"[*_#`>\[\]]", "", text or "").strip())
    if not text:
        return
    chunks = _sentences(text) or [text]
    completed = False
    with _speak_lock:
        _abort_speech.clear()
        _speaking.set()
        with _lock:
            _state["speaking"] = True
        _set_phase("speaking")
        _leds("answer")
        t_first = None
        player = None
        try:
            _tts_seq += 1
            base = os.path.join(tempfile.gettempdir(), f"homedeck_tts_{_tts_seq}")
            results = [None] * len(chunks)

            def synth(i):
                w = f"{base}_{i}.wav"
                results[i] = w if _synth(chunks[i], w) else None

            th = threading.Thread(target=synth, args=(0,), daemon=True); th.start(); th.join()
            fmt = None                       # (rate, channels, sampwidth) of the pipe, from the first sentence
            for i in range(len(chunks)):
                if _abort_speech.is_set():
                    break                                   # interrupted by the wake word
                nxt = None
                if i + 1 < len(chunks):
                    nxt = threading.Thread(target=synth, args=(i + 1,), daemon=True); nxt.start()
                if results[i]:
                    try:
                        pcm, rate, ch, sw = _wav_pcm(results[i], fmt)
                        if player is None:
                            fmt = (rate, ch, sw)
                            afmt = {1: "U8", 2: "S16_LE", 3: "S24_3LE", 4: "S32_LE"}.get(sw, "S16_LE")
                            player = subprocess.Popen(["aplay", "-q", "-D", PLAY_DEVICE, "-t", "raw", "-f", afmt, "-r", str(rate), "-c", str(ch)],
                                                      stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            player._hd_started = time.time()
                            with _players_lock:
                                _players.append(player)
                                _speak_started_at = time.time()
                            player.stdin.write(b"\x00" * int(rate * ch * sw * 0.15))   # 150 ms lead-in silence
                        if t_first is None:
                            t_first = time.time()
                            if timings is not None:
                                timings["tts"] = round(t_first - timings.get("_t_tts0", t_first), 2)
                        player.stdin.write(pcm)
                        player.stdin.flush()
                    except (BrokenPipeError, OSError):
                        break                               # player was killed (barge-in)
                    finally:
                        try: os.remove(results[i])
                        except OSError: pass
                if nxt:
                    nxt.join()
                    if _abort_speech.is_set() and results[i + 1]:
                        try: os.remove(results[i + 1])
                        except OSError: pass
            if player is not None and not _abort_speech.is_set():
                try:
                    r, c, w = fmt
                    player.stdin.write(b"\x00" * int(r * c * w * 0.10))              # 100 ms tail silence
                    player.stdin.close()
                    player.wait(timeout=120)
                except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                    pass
            completed = not _abort_speech.is_set()
        except Exception as e:
            _err(f"tts failed: {e}")
        finally:
            if player is not None:
                try:
                    if player.poll() is None:
                        player.kill()
                except Exception:
                    pass
                with _players_lock:
                    if player in _players:
                        _players.remove(player)
            _speaking.clear()
            _abort_speech.clear()
            with _lock:
                _state["speaking"] = False
            _set_phase("idle")
            _leds("idle")
    return completed


def say(text, blocking=True):
    """Speak text on the board's speakers. Safe to call from any module/thread."""
    if not blocking:
        threading.Thread(target=say_stream, args=(text,), daemon=True).start()
        return
    say_stream(text)


# ----------------------------------------------------------------------------- context + intents
# ----------------------------------------------------------------------------- conversation log (on disk)
def _conv_path():
    return os.path.join(ctx.data_dir, "conversations.jsonl")


def _conv_read():
    try:
        with _conv_lock, open(_conv_path(), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def _conv_trim():
    """Keep the newest CONV_MAX turns (called at start)."""
    try:
        with _conv_lock:
            with open(_conv_path(), encoding="utf-8") as f:
                lines = f.read().splitlines()
            if len(lines) > CONV_MAX:
                with open(_conv_path(), "w", encoding="utf-8") as f:
                    f.write("\n".join(lines[-CONV_MAX:]) + "\n")
    except FileNotFoundError:
        pass
    except Exception as e:
        ctx.log(f"conversation log trim failed: {e}")


def _conv_append(heard, answer, source):
    rec = {"t": round(time.time(), 2), "heard": str(heard or "")[:500], "answer": str(answer or "")[:1000], "source": source}
    try:
        with _conv_lock, open(_conv_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        ctx.log(f"conversation log write failed: {e}")


def _conv_clear():
    try:
        with _conv_lock:
            open(_conv_path(), "w").close()
    except Exception as e:
        ctx.log(f"conversation log clear failed: {e}")


_RECALL = re.compile(r"\b(what (did|have) (i|you|we) (ask|say|tell|answer|talk)|what was (that|the) (number|answer|thing|word|name)|"
                     r"remind me what (i|you|we)|what (were|was) (we|i) (talking|asking|saying)|(did|have) (i|we) (talk|ask|say|mention)|"
                     r"what did you (say|tell|answer)|(earlier|yesterday|this morning|last night|before|previously|the other day)\b.*\b"
                     r"(ask|asked|said|say|told|tell|talk|talked|conversation|answer|answered)|"
                     r"(ask|asked|said|say|told|tell|talk|talked|conversation|answer|answered)\b.*\b(earlier|yesterday|this morning|last night|before|previously|the other day))\b", re.I)
_FORGET_CONV = re.compile(r"\b(forget (our|the|this|that) conversation|clear (your|the|our|my) (history|conversation|conversations)|"
                          r"forget (everything|what) we (said|talked|discussed)|delete (our|the|your) (history|conversation))\b", re.I)
_STOP = set("a an the and or of to in on at for with about from by is are was were be do did does have has had you your yours i me my we our "
            "us it its that this those these what which who whom when where why how tell told say said ask asked asking answer answered "
            "talk talked talking remind earlier yesterday today morning night tonight before previously again other day last time thing "
            "number word name were was did have you please jarvis hey okay ok".split())


def _recall_turns(text):
    """Past turns relevant to a recall question: filtered by the time words in the question, ranked by keyword overlap."""
    t = (text or "").lower()
    now = time.time(); lt = time.localtime(now)
    day0 = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    if "yesterday" in t:
        lo, hi = day0 - 86400, day0
    elif "last night" in t:
        lo, hi = day0 - 86400 + 18 * 3600, day0 + 5 * 3600
    elif re.search(r"\b(today|this morning|earlier|tonight|this afternoon|this evening)\b", t):
        lo, hi = day0, now
    elif "the other day" in t:
        lo, hi = day0 - 7 * 86400, day0
    else:
        lo, hi = now - 7 * 86400, now
    words = [w for w in re.findall(r"[a-z0-9']{3,}", t) if w not in _STOP]
    turns = [r for r in _conv_read() if lo <= float(r.get("t", 0)) < hi and not _RECALL.search(r.get("heard", "")) and (r.get("answer") or "").strip()]
    if words:
        scored = []
        for r in turns:
            blob = (r.get("heard", "") + " " + r.get("answer", "")).lower()
            sc = sum(1 for w in words if w in blob)
            if sc:
                scored.append((sc, r["t"], r))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        picked = [r for _, _, r in scored[:8]]
        if not picked:
            picked = turns[-8:]                       # time words only ("what did I ask you yesterday")
    else:
        picked = turns[-8:]
    picked.sort(key=lambda r: r["t"])
    return picked


def _recall_context(turns):
    lines = []
    for r in turns:
        when = time.strftime("%a %I:%M %p", time.localtime(r["t"])).replace(" 0", " ")
        lines.append(f"[{when}] Owner asked: {r['heard']} / Jarvis answered: {r['answer']}")
    return "Earlier conversation between the owner and you (oldest first), use it to answer:\n" + "\n".join(lines)


# ----------------------------------------------------------------------------- connectivity
def _mark_online(ok):
    was = _net["online"]
    _net["online"], _net["checked"] = bool(ok), time.time()
    with _lock:
        _state["online"] = bool(ok)
    if was != bool(ok):
        ctx.log("back online" if ok else "offline: local intents, local speech recognition and Piper only")


def _probe_net():
    import urllib.request, urllib.error
    try:
        req = urllib.request.Request("https://api.groq.com/openai/v1/models", method="HEAD", headers={"User-Agent": "HomeDeck/1.0"})
        urllib.request.urlopen(req, timeout=2)
        return True
    except urllib.error.HTTPError:
        return True                                  # any HTTP answer means the network is there
    except Exception:
        return False


def _online():
    """Cached connectivity: 30 s while online, 10 s while offline so recovery is noticed quickly.
    The test hook llm.simulate_offline forces the offline path."""
    if ctx.config["llm"].get("simulate_offline"):
        if _net["online"] or not _net.get("simulated"):
            _mark_online(False); _net["simulated"] = True
        return False
    if _net.get("simulated"):
        _net["simulated"] = False; _net["checked"] = 0.0          # the hook was just switched off: probe for real
    if time.time() - _net["checked"] < (30 if _net["online"] else 10):
        return _net["online"]
    ok = _probe_net()
    _mark_online(ok)
    return ok


def _room_context():
    parts = []
    mem = ctx.module("memory")
    if mem and hasattr(mem, "context"):
        try:
            mc = mem.context()
            if mc: parts.append(mc)
        except Exception:
            pass
    g = ctx.global_config.get("general", {})
    loc = g.get("location", {})
    parts.append(f"Local time: {datetime.now().strftime('%A %I:%M %p, %B %d %Y')}.")
    if loc.get("city"):
        parts.append(f"Location: {loc.get('city')} {loc.get('zip', '')}.")
    s = ctx.module("sensors")
    if s and hasattr(s, "state"):
        try:
            st = s.state()
            for m in st.get("metrics", []):
                if m.get("value") is not None:
                    parts.append(f"{m['label']}: {m['value']} {m.get('unit', '')} ({m.get('status', {}).get('text', '')}).")
        except Exception:
            pass
        try:                                             # the day so far, so "was the CO2 high this morning" can be answered
            rep_ = s.api("report", {}) if hasattr(s, "api") else None
            if rep_ and rep_.get("ok") and rep_.get("text"):
                parts.append("Air today so far: " + rep_["text"])
        except Exception:
            pass
    w = ctx.module("weather")
    if w and hasattr(w, "state"):
        try:
            ws = w.state()
            if ws.get("summary"):
                parts.append(f"Weather: {ws['summary']}.")
        except Exception:
            pass
    return " ".join(parts)


_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "sixty": 60, "an": 1, "a": 1, "half": 0.5}


def _num(s):
    s = s.strip().lower()
    if s in _NUM:
        return _NUM[s]
    try:
        return float(s)
    except ValueError:
        return None


def _call(module, action, params):
    m = ctx.module(module)
    if not m or not hasattr(m, "api"):
        return None
    try:
        return m.api(action, params)
    except Exception as e:
        ctx.log(f"{module}.{action} failed: {e}")
        return {"ok": False, "error": str(e)}


_MATH_WORDS = [(r"\bwhat(?:'s| is| are)\b|\bhow much is\b|\bcalculate\b|\bcompute\b|\bequals?\b|\bplease\b", " "),
               (r"\bsquare root of\b", " sqrt "), (r"\bcube root of\b", " cbrt "), (r"\bsquared\b", " ^ 2 "), (r"\bcubed\b", " ^ 3 "),
               (r"\bto the power of\b|\bto the\b|\bpower\b", " ^ "), (r"\btimes\b|\bmultiplied by\b|\bx\b|×", " * "),
               (r"\bdivided by\b|\bover\b|÷", " / "), (r"\bplus\b", " + "), (r"\bminus\b|\bless\b|\btake away\b|−", " - "),
               (r"\bpercent of\b|% of\b", " %of "), (r"\bpercent\b", " % "), (r"\bof\b", " * "), (r"\bhalf of\b", " 0.5 * "), (r"\bdouble\b", " 2 * "),
               (r"\bpoint\b", "."), (r"\bnegative\b", " -"), (r",(?=\d{3})", "")]
_NUM_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
              "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
              "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
              "hundred": 100, "thousand": 1000, "million": 1000000}


def _math_eval(node):
    import ast, math
    if isinstance(node, ast.Expression): return _math_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)): return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _math_eval(node.operand); return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        a, b = _math_eval(node.left), _math_eval(node.right)
        if isinstance(node.op, ast.Add): return a + b
        if isinstance(node.op, ast.Sub): return a - b
        if isinstance(node.op, ast.Mult): return a * b
        if isinstance(node.op, ast.Div): return a / b
        if isinstance(node.op, ast.Mod): return a % b
        if isinstance(node.op, ast.Pow):
            if abs(b) > 64 or abs(a) > 1e9: raise ValueError("too big")
            return a ** b
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and len(node.args) == 1:
        v = _math_eval(node.args[0])
        if node.func.id == "sqrt": return math.sqrt(v)
        if node.func.id == "cbrt": return math.copysign(abs(v) ** (1 / 3), v)
    raise ValueError("unsupported")


def _math_intent(t):
    """Spoken arithmetic answered locally in a millisecond instead of a round trip to the model. None if it isn't math."""
    import ast, re as _re
    if _re.search(r"\b(timer|alarm|minutes?|hours?|seconds?|volume|degrees|remind|list|bikes?|weather|o'?clock|am|pm)\b", t):
        return None
    x = " " + t.replace("-", " - ") + " "
    x = _re.sub(r"\b(\d+)\s*%", r"\1 %", x)
    for pat, rep in _MATH_WORDS:
        x = _re.sub(pat, rep, x)
    x = _re.sub(r"\b(" + "|".join(_NUM_WORDS) + r")\b", lambda m: str(_NUM_WORDS[m.group(1)]), x)
    x = _re.sub(r"(\d+)\s*%of\s*(\d+(?:\.\d+)?)", r"(\1/100*\2)", x)
    x = _re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", x)
    x = _re.sub(r"\s+", " ", x).strip(" ?.!")
    if not _re.fullmatch(r"[\d\s\.\+\-\*/\^\(\)]*(sqrt|cbrt)?[\d\s\.\+\-\*/\^\(\)]+", x) or not _re.search(r"\d\s*[\+\-\*/\^]\s*[\d\(]|sqrt|cbrt", x):
        return None
    if _re.fullmatch(r"[\d\.\s]+", x):
        return None
    expr = x.replace("^", "**").replace("sqrt ", "sqrt(").replace("cbrt ", "cbrt(")
    if "sqrt(" in expr or "cbrt(" in expr:
        expr = expr + ")" * (expr.count("(") - expr.count(")"))
    try:
        v = _math_eval(ast.parse(expr, mode="eval"))
    except Exception:
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return "That doesn't have an answer."
    if abs(v - round(v)) < 1e-9 and abs(v) < 1e15:
        out = f"{int(round(v)):,}"
    else:
        out = f"{v:,.4f}".rstrip("0").rstrip(".")
    spoken = _re.sub(r"\s+", " ", t.replace("*", " times ").replace("/", " divided by ")).strip(" ?.!")
    spoken = _re.sub(r"^(what(?:'s| is| are)|how much is|calculate|compute)\s+", "", spoken)
    spoken = _re.sub(r"(\d)\s*x\s*(\d)", r"\1 times \2", spoken)              # "10 x 10" is read as "ten times ten"
    spoken = _re.sub(r"^(square|cube) root", r"the \1 root", spoken)
    return f"{out}. That's {spoken}."


def _local_intent(text):
    """Return a spoken reply for simple requests, or None to hand off to Claude."""
    t = text.lower().strip().rstrip(".!?")
    g = ctx.global_config.get("general", {})
    m = _math_intent(t)
    if m:
        _last_source["v"] = "math"
        return m

    # guest mode in/out (the phrases are the only trace of the feature)
    # the transcript never contains the wake word ("hey jarvis" is consumed before recording), so compare
    # with any leading "jarvis"/"hey jarvis" and punctuation stripped from both sides
    def _norm(x):
        x = re.sub(r"[^a-z0-9 ]", " ", (x or "").lower())
        x = re.sub(r"^\s*(hey\s+|ok\s+|okay\s+)?jarvis[\s,]*", "", x)
        return re.sub(r"\s+", " ", x).strip()
    tn = _norm(t)
    gep = _norm(ctx.config.get("guest_enter_phrase") or "")
    if gep and (gep in tn or tn in gep and len(tn) > 3):
        ctx.global_config["general"]["guest_mode"] = True; ctx.save_config()
        return "Okay."
    gxp = _norm(g.get("guest_exit_phrase") or "")
    if gxp and (gxp in tn or tn in gxp and len(tn) > 3):
        ctx.global_config["general"]["guest_mode"] = False; ctx.save_config()
        return "Welcome home."

    if re.search(r"\b(volume|louder|quieter|softer|turn it (up|down)|turn (up|down)|mute|unmute)\b", t):
        a = ctx.module("audio")
        if not a or not hasattr(a, "api"):
            return "I can't control the volume yet."
        # "the music"/"your voice" pick the target; otherwise music when it is playing, Jarvis' own volume when not
        if re.search(r"\b(music|song|spotify|youtube)\b", t):
            tg = "music"
        elif re.search(r"\b(your|you|jarvis|voice|speech)\b", t):
            tg = "jarvis"
        else:
            tg = "music" if _music_playing() else "jarvis"
        what = "Music" if tg == "music" else "My"
        if "unmute" in t:
            a.api("unmute", {"target": "all"}); return "Sound's back on."
        if re.search(r"\bmute\b", t):
            a.api("mute", {"target": "all"}); return "Muted."
        if re.search(r"\b(max|maximum|full|all the way up)\b", t):
            a.api("set_volume", {"pct": 100, "target": tg}); return f"{what} volume: full."
        if re.search(r"\b(min|minimum|lowest|all the way down)\b", t):
            a.api("set_volume", {"pct": 10, "target": tg}); return f"{what} volume 10 percent."
        # an amount: "20", "20%", "20 percent", "twenty percent", "by 20"
        amount = None
        m = re.search(r"\b(?:by\s+)?(\d{1,3}|" + "|".join(k for k in _NUM if k not in ("a", "an", "half")) + r")\s*(?:%|percent|per cent|points?)?\b", t)
        if m:
            n = _num(m.group(1))
            amount = int(n) if n is not None and n >= 1 else None
        up = re.search(r"\b(up|louder|raise|increase|higher|boost)\b", t)
        down = re.search(r"\b(down|quieter|softer|lower|decrease|reduce)\b", t)
        if up or down:
            step = amount if amount is not None else 10
            r = a.api("step", {"delta": step if up else -step, "target": tg})
            return f"{what} volume {r.get('volume_pct')}." if r.get("ok") else "I couldn't change the volume."
        if re.search(r"\bhalf\b", t):
            a.api("set_volume", {"pct": 50, "target": tg}); return f"{what} volume 50 percent."
        if amount is not None:
            r = a.api("set_volume", {"pct": max(0, min(100, amount)), "target": tg})
            return f"{what} volume {r.get('volume_pct')} percent." if r.get("ok") else "I couldn't change the volume."
        v = (a.music_volume() if tg == "music" else a.volume()) if hasattr(a, "volume") else None
        return f"{what} volume is {v} percent." if v is not None else "I couldn't read the volume."

    if re.fullmatch(r"(stop|cancel|dismiss|snooze|okay stop|that's enough|quiet|stop the music|stop music|stop playing)", t):
        # a bare "stop" means whatever is making noise: a ringing timer/alarm first, then music
        rg = _call("ringer", "stop", {})
        r = _call("alarms", "dismiss", {})
        _call("timers", "stop", {})
        if rg and rg.get("was_ringing"):
            return ""                       # silent: the ringing stopping is the reply
        sp = ctx.module("spotify")
        try:
            if sp and hasattr(sp, "is_playing") and sp.is_playing():
                sp.pause()
                ctx.emit("ui_home", {})         # leave the now-playing screen
                return ""                       # silent: the music stopping is the reply
        except Exception:
            pass
        return "Okay." if r is not None else ""

    tm_mod = ctx.module("timers")
    if tm_mod and hasattr(tm_mod, "intent"):
        try:
            r = tm_mod.intent(t)
            if r is not None:
                return r
        except Exception as e:
            ctx.log(f"timers intent failed: {e}")

    m = re.search(r"(?:set|wake me up with|create)\s+(?:an\s+)?alarm\s+(?:for|at)\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        ap = (m.group(3) or "").replace(".", "")
        if ap == "pm" and h < 12: h += 12
        if ap == "am" and h == 12: h = 0
        r = _call("alarms", "add", {"time": f"{h:02d}:{mi:02d}", "enabled": True})
        return f"Alarm set for {m.group(1)}{':' + m.group(2) if m.group(2) else ''} {ap}." if r else "I couldn't set an alarm."

    if re.search(r"\b(air quality|co2|carbon dioxide|how'?s the air|humidity|temperature in here|room temperature)\b", t) and \
            not re.search(r"\b(today|been|so far|this (morning|afternoon|evening)|earlier|history|lately|overnight|last night|report|summary|trend)\b", t):
        s = ctx.module("sensors")
        st = s.state() if s and hasattr(s, "state") else {}
        bits = [f"{m['label']} is {m['value']} {m.get('unit', '')}, {m.get('status', {}).get('text', '')}"
                for m in st.get("metrics", []) if m.get("value") is not None and m.get("key") in ("co2", "temp", "hum", "voc")]
        return ". ".join(bits) + "." if bits else "The air sensors aren't reporting right now."

    if re.search(r"\b(weather|forecast|temperature outside|rain|umbrella)\b", t):
        w = ctx.module("weather")
        ws = w.state() if w and hasattr(w, "state") else {}
        if ws.get("spoken") or ws.get("summary"):
            return ws.get("spoken") or ws.get("summary")
        return None  # let Claude look it up

    if re.search(r"\b(bikes?|lyft|bay ?wheels|e-?bikes?)\b", t) and not re.search(r"\b(remember|forget|lock|code|my bike|bike is|bike was)\b", t):
        b = ctx.module("bikes")
        bs = b.state() if b and hasattr(b, "state") else {}
        if bs.get("spoken") or bs.get("summary"):
            return bs.get("spoken") or bs.get("summary")
        st = bs.get("stations") or []
        if st:
            parts = [f"{x.get('ebikes', 0)} e-bike{'s' if x.get('ebikes', 0) != 1 else ''} at {x.get('name')}" for x in st[:2]]
            return " and ".join(parts) + "."
        return "I don't have bike data right now."

    if re.fullmatch(r"(go )?(home|home screen|show (the )?home( screen)?|back to home|close (the )?(music|player))", t):
        ctx.emit("ui_home", {}); return ""
    if re.fullmatch(r"(what time is it|what's the time|what is the time|time|what's the time right now|what time is it right now)", t):
        return "It's " + datetime.now().strftime("%I:%M %p").lstrip("0") + "."
    if re.fullmatch(r"(what's|what is|whats) (the date|today's date|the day|the date today|today)( today)?|what day is (it|today)|what day of the week is it|what's the day today", t):
        return "It's " + datetime.now().strftime("%A, %B %d").replace(" 0", " ") + "."
    return None


# ----------------------------------------------------------------------------- Claude
def _ask_claude(text):
    client = _load_llm()
    if client is None:
        return "I can't reach my brain right now. Add an Anthropic API key in the Jarvis app."
    cfg = ctx.config["llm"]
    g = ctx.global_config.get("general", {})
    loc = g.get("location", {})
    tools = []
    if cfg.get("web_search", True):
        tools.append({
            "type": "web_search_20260209", "name": "web_search", "max_uses": 3,
            "user_location": {"type": "approximate", "city": loc.get("city", ""), "region": "California",
                              "country": "US", "timezone": loc.get("timezone", "America/Los_Angeles")},
        })
    system = [
        {"type": "text", "text": cfg["system_prompt"], "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "Context: " + _room_context()},
    ]
    with _lock:
        msgs = list(_history[-ctx.config.get("history_len", 12):])
    msgs.append({"role": "user", "content": text})
    try:
        resp = client.beta.messages.create(
            model=cfg.get("model", "claude-opus-5"),
            max_tokens=int(cfg.get("max_tokens", 1024)),
            system=system,
            messages=msgs,
            tools=tools or anthropic_not_given(),
            output_config={"effort": "low"},          # spoken answers: fast and short
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",                        # policy declines re-run on a fallback model
        )
    except Exception as e:
        _err(f"claude request failed: {e}")
        return "Sorry, I couldn't get an answer right now."
    if resp.stop_reason == "refusal":
        return "I can't help with that one."
    answer = " ".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    answer = _trim_answer(text, re.sub(r"\s+", " ", answer))
    with _lock:
        _history.append({"role": "user", "content": text})
        _history.append({"role": "assistant", "content": answer or "..."})
        del _history[:-2 * ctx.config.get("history_len", 12)]
        _state["history"] = list(_history[-8:])
    return answer or "I didn't come up with anything."


def anthropic_not_given():
    import anthropic
    return anthropic.NOT_GIVEN


# ----------------------------------------------------------------------------- LLM providers (stdlib only)
PROVIDERS = [
    ("local", "Local (Ollama on the device, no key)", False),
    ("groq", "Groq (free key)", True),
    ("gemini", "Google Gemini (free key)", True),
    ("anthropic", "Anthropic Claude (paid key)", True),
    ("openai_compat", "Custom OpenAI-compatible", True),
]


def _provider():
    """Effective provider id: the configured one, else the first with a key, else local."""
    cfg = ctx.config["llm"]
    p = (cfg.get("provider") or "").strip()
    if p in dict((k, v) for k, v, _ in PROVIDERS):
        return p
    if cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if cfg.get("groq_key"):
        return "groq"
    if cfg.get("gemini_key"):
        return "gemini"
    return "local"


def _provider_ready(pid=None):
    cfg = ctx.config["llm"]; pid = pid or _provider()
    if pid == "anthropic":
        return bool(cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY"))
    if pid == "groq":
        return bool(cfg.get("groq_key"))
    if pid == "gemini":
        return bool(cfg.get("gemini_key"))
    if pid == "openai_compat":
        c = cfg.get("custom", {}); return bool(c.get("base_url") and c.get("model"))
    if pid == "local":
        return _ollama_up()
    return False


def _ollama_up(timeout=2):
    import urllib.request
    base = ctx.config["llm"].get("local", {}).get("base_url", "http://127.0.0.1:11434/v1").rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base
    try:
        with urllib.request.urlopen(root + "/api/tags", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _http_json(url, payload, headers=None, timeout=30):
    import urllib.request, urllib.error
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "HomeDeck/1.0", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:   # surface the provider's own message (never the key)
        body = ""
        try: body = e.read().decode(errors="replace")[:200]
        except Exception: pass
        raise RuntimeError(f"HTTP {e.code}: {body}") from None


def _chat_openai(base_url, key, model, system, msgs, timeout=30, tools=None):
    """OpenAI-compatible chat completions (Groq, OpenRouter, Ollama, LM Studio...). Returns text or raises."""
    payload = {"model": model, "max_tokens": int(ctx.config["llm"].get("max_tokens", 400)), "temperature": 0.4,
               "messages": [{"role": "system", "content": system}] + msgs}
    if tools:
        payload["tools"] = tools
    if "api.groq.com" in base_url and str(model).startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"          # otherwise gpt-oss burns max_tokens on hidden reasoning and returns nothing
    elif "api.groq.com" in base_url and str(model).startswith("qwen/"):
        payload["reasoning_effort"] = "none"         # qwen3 answers directly; thinking would add seconds for nothing
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    out = _http_json(base_url.rstrip("/") + "/chat/completions", payload, headers, timeout)
    return (out.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""


def _chat_gemini(key, model, system, msgs, timeout=30):
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]} for m in msgs]
    payload = {"system_instruction": {"parts": [{"text": system}]}, "contents": contents,
               "generationConfig": {"maxOutputTokens": int(ctx.config["llm"].get("max_tokens", 1024)), "temperature": 0.4}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    out = _http_json(url, payload, timeout=timeout)
    cands = out.get("candidates") or []
    if not cands:
        return ""
    return " ".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", [])).strip()


_SEARCH_HINTS = re.compile(r"\b(who|what|when|where|which|latest|news|today|tonight|tomorrow|yesterday|current|recent|price|cost|score|"
                           r"won|win|release|released|stock|how old|how much|how many|population|weather in|forecast for|"
                           r"open now|hours|near me|happened|election|president|ceo|定义)\b", re.I)
_DUNNO = re.compile(r"(don't|do not|cannot|can't|unable to)\s+(know|have|access|verify|provide|browse)|as of my|knowledge cutoff|"
                    r"no (real[- ]time|access to)|i'm not (sure|aware)|not able to", re.I)


_FRESH_HINTS = re.compile(r"\b(latest|news|today|tonight|tomorrow|yesterday|current(ly)?|recent(ly)?|right now|this (week|month|year)|"
                          r"price|cost|stock|score|who won|won the|release date|released|open now|opening hours|hours|near me|"
                          r"happened|election|forecast for|weather in|traffic|schedule|game (to)?night|playing (to)?night)\b", re.I)


def _needs_search(text):
    """Only questions that need fresh or live information go to the slower search model."""
    return bool(_FRESH_HINTS.search(text or ""))


def _ddg_search(q, n=5):
    """Free web search via DuckDuckGo's lite endpoint (the html one serves a bot challenge). Returns 'title: snippet' strings."""
    import urllib.request, urllib.parse, html as _html
    try:
        req = urllib.request.Request("https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": q}),
                                     headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=15) as r:
            page = r.read().decode(errors="replace")
    except Exception as e:
        ctx.log(f"search failed: {e}")
        return []
    clean = lambda x: _html.unescape(re.sub(r"<[^>]+>", " ", x)).strip()
    # rows alternate: a result-link anchor, then a result-snippet cell; sponsored rows carry "Sponsored link"
    links = re.findall(r"<a[^>]*class=['\"]result-link['\"][^>]*>(.*?)</a>(.{0,80})", page, re.S)
    snippets = [clean(x) for x in re.findall(r"<td[^>]*class=['\"]result-snippet['\"][^>]*>(.*?)</td>", page, re.S)]
    out, si = [], 0
    for title, tail in links:
        t = clean(title)
        if not t or t == "more info":
            continue
        if "Sponsored" in tail:
            continue
        sn = snippets[si] if si < len(snippets) else ""; si += 1
        out.append(f"{t}: {sn}"[:300])
        if len(out) >= n:
            break
    return out


_bad_models = set()                   # Groq models that answered "not found" this session: skipped until restart


def _groq_once(model, system, msgs, timeout, search):
    """One Groq call. gpt-oss models get Groq's built-in browser search when the question needs the web; if the
    tool is refused, the call is repeated with our own search snippets in the prompt instead."""
    cfg = ctx.config["llm"]
    base, key = "https://api.groq.com/openai/v1", cfg.get("groq_key", "")
    tools = [{"type": "browser_search"}] if (search and str(model).startswith("openai/gpt-oss")) else None
    try:
        return _chat_openai(base, key, model, system, msgs, timeout, tools=tools)
    except RuntimeError as e:
        msg = str(e)
        if tools and ("tool" in msg.lower() or "HTTP 400" in msg):
            ctx.log(f"llm {model}: browser search refused ({msg[:80]}); using search snippets instead")
            q = (msgs[-1]["content"] if msgs else "").split("\n\n", 1)[0]
            hits = _ddg_search(q)
            m2 = list(msgs)
            if hits:
                m2[-1] = {"role": "user", "content": q + "\n\nWeb search results (use if relevant, don't cite):\n- " + "\n- ".join(h[:300] for h in hits[:5])}
            return _chat_openai(base, key, model, system, m2, timeout)
        raise


def _chat(pid, system, msgs, force_search=False):
    cfg = ctx.config["llm"]
    if pid == "groq":
        question = (msgs[-1]["content"] if msgs else "").split("\n\n", 1)[0]      # the question only, not appended context
        want_search = force_search or (cfg.get("web_search", True) and _needs_search(question))
        fast, big = cfg.get("groq_fast_model", "qwen/qwen3.8-27b"), cfg.get("groq_search_model", "openai/gpt-oss-120b")
        # the chain: the model this question wants first, then the fallbacks, each with more time than the last
        chain = [(big, 30, True)] if want_search else [(fast, 12, False)]
        for m in [big] + list(cfg.get("groq_fallback_models") or []):
            if m not in [c[0] for c in chain]:
                chain.append((m, 40, want_search))
        chain = [c for c in chain if c[0] not in _bad_models] or chain[:1]
        _last_source["v"] = "search" if want_search else "llm"
        last_err = None
        for i, (model, timeout, search) in enumerate(chain):
            t = time.time()
            try:
                out = _groq_once(model, system, msgs, timeout, search)
            except RuntimeError as e:                    # an HTTP error still means the network is up
                _mark_online(True)
                last_err = e
                msg = str(e)
                if "model_not_found" in msg or "does not exist" in msg:
                    _bad_models.add(model)
                    ctx.log(f"llm {model} is not available on this account; skipping it from now on")
                else:
                    ctx.log(f"llm {model} failed ({msg[:100]})")
                continue
            except Exception as e:
                _mark_online(False)
                raise
            _mark_online(True)
            out = (out or "").strip()
            ctx.log(f"llm {model} {time.time() - t:.2f}s" + (" (fallback)" if i else ""))
            if out:
                return out
            ctx.log(f"llm {model} returned nothing; trying the next model")
        if last_err:
            raise last_err
        return ""
    if pid == "gemini":
        return _chat_gemini(cfg.get("gemini_key", ""), cfg.get("gemini_model", "gemini-2.0-flash"), system, msgs, 30)
    if pid == "openai_compat":
        c = cfg.get("custom", {})
        return _chat_openai(c.get("base_url", ""), c.get("key", ""), c.get("model", ""), system, msgs, 30)
    if pid == "local":
        c = cfg.get("local", {})
        _last_source["v"] = "local"
        return _chat_openai(c.get("base_url", "http://127.0.0.1:11434/v1"), "", c.get("model", "qwen2.5:1.5b"), system, msgs, 120)
    raise RuntimeError(f"unknown provider {pid}")


def _remember(text, answer):
    with _lock:
        _history.append({"role": "user", "content": text})
        _history.append({"role": "assistant", "content": answer or "..."})
        del _history[:-2 * ctx.config.get("history_len", 12)]
        _state["history"] = list(_history[-8:])


def _ask_llm(text, recall=None):
    """Route to the configured provider. Never raises; returns a short spoken sentence on failure.
    recall: past turns (from the conversation log) to hand the model as context for a recall question."""
    pid = _provider()
    if pid != "local" and not _online():
        # no internet: a local model answers if one is running, otherwise say what still works
        if _ollama_up(timeout=1):
            try:
                cfg = ctx.config["llm"]
                system = cfg["system_prompt"] + " Context: " + _room_context()
                with _lock:
                    msgs = list(_history[-ctx.config.get("history_len", 12):])
                msgs.append({"role": "user", "content": text + ("\n\n" + _recall_context(recall) if recall else "")})
                ans = _chat("local", system, msgs)
                ans = _trim_answer(text, re.sub(r"\s+", " ", (ans or "")).strip())
                if ans:
                    _remember(text, ans); ctx.log("offline: answered by the local model"); return ans
            except Exception as e:
                ctx.log(f"offline local model failed: {str(e)[:120]}")
        _last_source["v"] = "offline"
        ctx.log("offline: no model available for a general question")
        return OFFLINE_MSG
    if pid == "anthropic":
        return _ask_claude(text)
    if not _provider_ready(pid):
        if pid == "local":
            return "My local brain isn't running. Run the local model installer, or pick another provider in settings."
        return f"No key for {pid} yet. Add one in settings."
    cfg = ctx.config["llm"]
    system = cfg["system_prompt"] + " Context: " + _room_context()
    with _lock:
        msgs = list(_history[-ctx.config.get("history_len", 12):])
    msgs.append({"role": "user", "content": text + ("\n\n" + _recall_context(recall) if recall else "")})
    try:
        # groq/compound searches the web itself; feeding it our own results just bloats the request
        builtin = pid == "groq"          # groq routes to its own search model when the question needs the web
        results = _ddg_search(text) if cfg.get("web_search", True) and not builtin and _needs_search(text) else []
        results = [r[:300] for r in results[:5]]
        if results:
            msgs[-1] = {"role": "user", "content": text + "\n\nWeb search results (use if relevant, don't cite):\n- " + "\n- ".join(results)}
        answer = _chat(pid, system, msgs)
        if pid == "groq" and cfg.get("web_search", True) and _DUNNO.search(answer or ""):
            answer = _chat(pid, system, msgs, force_search=True) or answer     # fast model didn't know: ask the web model
        if cfg.get("web_search", True) and not builtin and not results and _DUNNO.search(answer or ""):
            results = _ddg_search(text)
            if results:
                msgs[-1] = {"role": "user", "content": text + "\n\nWeb search results (use if relevant, don't cite):\n- " + "\n- ".join(results)}
                answer = _chat(pid, system, msgs) or answer
    except Exception as e:
        _err(f"{pid} request failed: {str(e)[:160]}")
        return "Sorry, I couldn't get an answer right now."
    answer = re.sub(r"\s+", " ", (answer or "")).strip()
    answer = re.sub(r"【[^】]*】", "", answer)                # gpt-oss browser-search citations
    answer = re.sub(r"[*_#`>\[\]]", "", answer)
    answer = _trim_answer(text, answer)
    _remember(text, answer)
    return answer or "I didn't come up with anything."


def _first_clause(text):
    import re as _re
    parts = _re.split(r"[.!?]\s+", (text or "").strip(), maxsplit=1)
    return parts[0].strip() if parts and parts[0].strip() else text


def _intents_only(text):
    mem = ctx.module("memory")
    if mem and hasattr(mem, "intent"):
        try:
            r = mem.intent(text)
            if r is not None: return r
        except Exception: pass
    r = _local_intent(text)
    if r is not None: return r
    if hasattr(ctx, "modules"):
        for name, m in ctx.modules().items():
            if name == NAME or not hasattr(m, "intent"): continue
            try:
                r = m.intent(text)
            except Exception: r = None
            if r is not None:
                _last_source["v"] = name; return r           # "" = handled silently
    return None


def _finish_answer(text, reply):
    with _lock:
        _state["last_answer"] = reply
    return reply


def _answer(text):
    """Local intents first, then the configured LLM. Returns the reply text and logs the turn to the conversation file."""
    _last_source["v"] = "intent"
    reply = _answer_inner(text)
    _conv_append(text, reply, _last_source["v"])
    try:
        threading.Thread(target=_answer_card, args=(text, reply, _last_source["v"]), name="answer-card", daemon=True).start()
    except Exception:
        pass
    return reply


# ----------------------------------------------------------------------------- on-screen answer card
# After an answer is spoken the screen shows the gist for a few seconds: a maths question with its result in big
# type, or the main subject of a factual answer (a name, a place, a number) with a picture from Wikipedia.
CARD_SECONDS = 10


def _wiki_lookup(title):
    """Wikipedia REST summary for a title: (page title, thumbnail url or "", one-line description). Free, no key."""
    import urllib.request, urllib.parse
    hdr = {"User-Agent": "HomeDeck/1.0 (home assistant display)"}
    try:
        q = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": title, "srlimit": 1, "format": "json"})
        with urllib.request.urlopen(urllib.request.Request("https://en.wikipedia.org/w/api.php?" + q, headers=hdr), timeout=6) as r:
            hits = (json.load(r).get("query") or {}).get("search") or []
        page = hits[0]["title"] if hits else title
        u = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(page.replace(" ", "_"))
        with urllib.request.urlopen(urllib.request.Request(u, headers=hdr), timeout=6) as r:
            j = json.load(r)
        # the 960 px thumbnail (Wikimedia only serves a few standard widths; 640/800 answer 400): the original can be a
        # multi-megabyte photo the panel would take ages to show
        img = (j.get("thumbnail") or {}).get("source") or ""
        img = re.sub(r"/(\d+)px-", "/960px-", img) if "/thumb/" in img else ((j.get("originalimage") or {}).get("source") or img)
        return {"title": j.get("title") or page, "image": img, "caption": j.get("description") or "",
                "extract": j.get("extract") or "", "url": ((j.get("content_urls") or {}).get("desktop") or {}).get("page", "")}
    except Exception as e:
        ctx.log(f"card: wikipedia lookup failed ({str(e)[:80]})")
        return {"title": title, "image": "", "caption": "", "extract": "", "url": ""}


def _wiki_more(title, limit=6000):
    """Plain-text article body (intro plus the first sections) for the expanded card."""
    import urllib.request, urllib.parse
    hdr = {"User-Agent": "HomeDeck/1.0 (home assistant display)"}
    try:
        q = urllib.parse.urlencode({"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1, "titles": title, "format": "json"})
        with urllib.request.urlopen(urllib.request.Request("https://en.wikipedia.org/w/api.php?" + q, headers=hdr), timeout=8) as r:
            pages = (json.load(r).get("query") or {}).get("pages") or {}
        txt = next(iter(pages.values())).get("extract", "") if pages else ""
        txt = re.sub(r"\n{3,}", "\n\n", txt)
        txt = re.split(r"\n== (?:See also|References|External links|Notes|Further reading) ==", txt)[0]
        return txt[:limit].rsplit("\n", 1)[0] if len(txt) > limit else txt
    except Exception as e:
        ctx.log(f"card: wikipedia article failed ({str(e)[:80]})")
        return ""


def _card_headline(question, answer):
    """Ask the fast model for the one thing worth putting on screen (a name, place, number...), or NONE."""
    cfg = ctx.config["llm"]
    if _provider() != "groq" or not cfg.get("groq_key"):
        return ""
    owner = _owner_name()
    prompt = (f"Question: {question}\nAnswer: {answer}\n\nWhat is the single most important thing in the answer to show on a "
              "screen as a headline: the name of the person, place, thing, or the number or short fact that answers the question? "
              "Reply with only that headline, 1 to 5 words, copied from the answer, no punctuation, no explanation. "
              + (f"The person asking is called {owner}; never use their name as the headline. " if owner else "")
              + "If the answer is chit-chat, an opinion, a greeting, or nothing stands out, reply NONE.")
    try:
        out = _chat_openai("https://api.groq.com/openai/v1", cfg.get("groq_key", ""), cfg.get("groq_fast_model", "qwen/qwen3.8-27b"),
                           "You pick headlines for a small display. Reply with the headline only.", [{"role": "user", "content": prompt}], 8)
    except Exception as e:
        ctx.log(f"card: headline failed ({str(e)[:80]})"); return ""
    h = re.sub(r"[\"'.*_#`\[\]【】]", "", (out or "")).strip()
    if not h or h.upper().startswith("NONE") or len(h) > 48:
        return ""
    if owner and h.lower().strip() == owner.lower().strip():
        return ""
    # the headline has to come from the exchange itself, otherwise a made-up word turns into a random picture
    hay = (question + " " + answer).lower()
    if h.lower() not in hay and not all(w in hay for w in h.lower().split()):
        ctx.log(f"card: headline {h!r} is not in the answer; no card")
        return ""
    return h


def _owner_name():
    """The owner's name as the memory module knows it ("call me ..."), or ""."""
    try:
        mem = ctx.module("memory")
        if mem and hasattr(mem, "owner_name"):
            return str(mem.owner_name() or "")
        st = mem.state() if mem and hasattr(mem, "state") else {}
        return str(st.get("name") or st.get("owner") or (st.get("profile") or {}).get("name") or "")
    except Exception:
        return ""


def _answer_card(question, reply, source):
    """Build and push the answer_card event (kind math|fact) for the kiosk; silent when nothing is worth showing."""
    try:
        if not reply or reply in (OFFLINE_MSG,) or reply.startswith("Sorry, I couldn't"):
            return
        if re.search(r"(didn'?t|did not|don'?t|do not|couldn'?t|could not) (catch|understand|know|have|find|get that)|try again|i'?m not sure|"
                     r"no idea|not able to|can'?t help", reply, re.I):
            return                                       # "I did not catch that" is not a film
        card = None
        if source in ("intent", "math") and _math_intent(question.lower().strip().rstrip(".!?")) is not None:
            q = re.sub(r"^(what('s| is| are)|how much is|calculate|compute|tell me)\s+", "", question.strip().rstrip("?.!"), flags=re.I)
            q = re.sub(r"\btimes\b|\bmultiplied by\b", "×", q); q = re.sub(r"\bdivided by\b|\bover\b", "÷", q)
            q = re.sub(r"\bplus\b", "+", q); q = re.sub(r"\bminus\b", "−", q)
            big = re.split(r"[.!]\s", reply.strip(), maxsplit=1)[0].rstrip(".")   # "391" from "391. That's 17 times 23."
            card = {"kind": "math", "question": q, "answer": big, "spoken": reply}
        elif source == "games":
            g = ctx.module("games")
            last = (g.state().get("last") if g and hasattr(g, "state") else None) or {}
            if last.get("dice"):
                card = {"kind": "dice", "dice": last["dice"], "sides": last.get("sides", 6), "answer": reply}
            elif last.get("coin"):
                card = {"kind": "coin", "coin": last["coin"], "answer": reply}
        elif source in ("llm", "search", "recall"):
            head = _card_headline(question, reply)
            if not head:
                return
            card = {"kind": "fact", "title": head, "answer": reply, "question": question}
            if not re.fullmatch(r"[\d.,%$€£+\-\s]+(\s?\w+)?", head):     # numbers and units have no picture
                w = _wiki_lookup(head)
                if w.get("image") or w.get("extract"):
                    card.update({"image": w["image"], "caption": w["caption"], "extract": w["extract"], "page": w["title"], "url": w["url"]})
        if card:
            card["ttl"] = CARD_SECONDS
            _events_push("answer_card", card)
            ctx.log(f"card: {card['kind']} {card.get('title') or card.get('answer')!r}" + (" with picture" if card.get("image") else ""))
    except Exception as e:
        ctx.log(f"card failed: {e}")


def _answer_inner(text):
    reply = None
    if _FORGET_CONV.search(text or ""):
        _conv_clear()
        with _lock:
            _history.clear(); _state["history"] = []
        _last_source["v"] = "intent"
        return _finish_answer(text, "Done. I've cleared our conversation history.")
    fc = _first_clause(text)
    if fc != text:
        # a short command followed by picked-up noise: run the intents on the command alone first
        r = _intents_only(fc)
        if r is not None:
            return _finish_answer(text, r)
    if _RECALL.search(text or ""):
        turns = _recall_turns(text)
        if not turns:
            _last_source["v"] = "recall"
            return _finish_answer(text, "I can't find anything about that in our earlier conversations.")
        _last_source["v"] = "recall"
        ctx.log(f"recall: {len(turns)} earlier turn(s) handed to the model")
        return _finish_answer(text, _ask_llm(text, recall=turns))
    mem = ctx.module("memory")            # "call me…", "remember that…", "forget…" win over everything else
    if mem and hasattr(mem, "intent"):
        try: reply = mem.intent(text)
        except Exception as e: ctx.log(f"memory intent failed: {e}")
        if reply is not None:
            _last_source["v"] = "memory"
    if reply is None:
        reply = _local_intent(text)
    if reply is None and hasattr(ctx, "modules"):
        # offer the command to every module that implements intent(text) (lists, reminders, news, audio, ...)
        for name, m in ctx.modules().items():
            if name == NAME or not hasattr(m, "intent"):
                continue
            try:
                r = m.intent(text)
            except Exception as e:
                ctx.log(f"intent {name} failed: {e}"); r = None
            if r is not None:                    # "" is a valid silent reply (music transport)
                reply = r; _last_source["v"] = name; break
    if reply is None:
        reply = _ask_llm(text)
    with _lock:
        _state["last_answer"] = reply
        if not any(h.get("content") == text for h in _state["history"][-2:]):
            pass
    return reply


# ----------------------------------------------------------------------------- pipeline
_spec = {"thread": None, "box": None, "valid": False}     # transcription started during the silence window


def _speculate(frames):
    """Transcribe what has been said so far on a side thread while the recorder waits out the silence window.
    If no more speech arrives the result is ready the moment the recording ends, hiding most of the STT latency."""
    box = {}
    snap = np.concatenate(frames).astype(np.float32) / 32768.0
    def run():
        try:
            box["text"] = _transcribe(snap)
        except Exception as e:
            box["error"] = str(e)
    th = threading.Thread(target=run, daemon=True); th.start()
    _spec.update({"thread": th, "box": box, "valid": True})


def _transcribe_recorded(audio):
    """Use the speculative transcript when it is still valid, else transcribe the final audio."""
    sp = dict(_spec); _spec.update({"thread": None, "box": None, "valid": False})
    if sp["valid"] and sp["thread"] is not None:
        sp["thread"].join(timeout=8)
        if not sp["thread"].is_alive() and "text" in sp["box"]:
            return sp["box"]["text"], True
    return _transcribe(audio), False


def _record_utterance(prefix=None, start_timeout=4.0, noise0=300.0):
    """Collect int16 16 kHz audio until silence. Returns float32 audio or None.
    prefix: chunks already captured (follow-up mode starts recording once speech energy was seen);
    start_timeout: give up if nothing is said within this many seconds.
    Speech starts after two consecutive loud chunks (rejects the chirp and clicks) and ends after silence_s below a
    lower threshold (hysteresis), so a fan or music bed does not keep the mic open until the cap."""
    vad = ctx.config["vad"]
    frames, started, silent = list(prefix or []), bool(prefix), 0.0
    noise = max(60.0, float(noise0))
    loud, pre, peak = 0, 0, 0.0
    _spec.update({"thread": None, "box": None, "valid": False})
    t0 = time.time(); t_start = None
    while time.time() - t0 < vad["max_utterance_s"]:
        ch = _read_chunk()
        if ch is None:
            return None
        rms = float(np.sqrt(np.mean(ch.astype(np.float32) ** 2)))
        frames.append(ch)
        thr_start = max(noise * 3.0, 500.0)
        thr_end = max(noise * 2.0, 380.0, peak * 0.08)
        if not started:
            if rms > thr_start:
                loud += 1
                if loud >= 2:
                    started, silent, peak = True, 0.0, rms; t_start = time.time() - t0
            else:
                loud = 0
                pre += 1
                noise = (0.6 * noise + 0.4 * rms) if pre <= 6 else (0.9 * noise + 0.1 * rms)   # settle on the room fast
                if time.time() - t0 > start_timeout:      # nothing said
                    ctx.log(f"listen: nothing said (room {noise:.0f})")
                    return None
        else:
            peak = max(peak, rms)
            if rms > thr_end:
                silent = 0.0
                _spec["valid"] = False                       # more speech: whatever was speculated is stale
            else:
                silent += CHUNK / MODEL_RATE
                if silent >= 0.28 and not _spec["valid"] and (_spec["thread"] is None or not _spec["thread"].is_alive()):
                    _speculate(frames)
                if silent >= vad["silence_s"]:
                    break
    audio = np.concatenate(frames).astype(np.float32) / 32768.0
    ctx.log(f"listen: room {noise:.0f} peak {peak:.0f} start {t_start if t_start is None else round(t_start, 2)} len {len(audio) / MODEL_RATE:.2f}s")
    if t_start is not None and peak > 0:
        _speech_peaks.append(float(peak)); del _speech_peaks[:-20]      # real speech levels, for the calibration's gain advice
    if len(audio) / MODEL_RATE < vad["min_utterance_s"] + vad["silence_s"]:
        return None
    return audio


def _transcribe_groq(audio):
    """Hosted Whisper on Groq (whisper-large-v3-turbo): ~1 s instead of 5-10 s on the CM4. audio = float32 16 kHz mono."""
    import io, wave, urllib.request, urllib.error, uuid
    key = (ctx.config["llm"].get("groq_key") or "").strip()
    if not key:
        return None
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(pcm)
    boundary = "----hd" + uuid.uuid4().hex
    fields = {"model": "whisper-large-v3-turbo", "language": ctx.config["stt"].get("language", "en"), "response_format": "json", "temperature": "0",
              "prompt": ctx.config["stt"].get("prompt") or "Jarvis, set a timer, alarm, reminder, minutes, hours, Spotify, YouTube, e-bikes, Valencia, Dolores, BART, Muni, lights, volume, weather, air quality, CO2."}
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode() + buf.getvalue() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request("https://api.groq.com/openai/v1/audio/transcriptions", data=body, method="POST",
                                 headers={"User-Agent": "HomeDeck/1.0", "Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=20))
        return (r.get("text") or "").strip()
    except Exception as e:
        if not isinstance(e, urllib.error.HTTPError):
            _mark_online(False)
        ctx.log(f"groq whisper failed, falling back to local: {e}")
        return None


def _transcribe(audio):
    eng = ctx.config["stt"].get("engine", "auto")
    if eng == "auto" and not _online():
        eng = "local"                                # skip the 20 s hosted attempt, go straight to faster-whisper
    if eng in ("auto", "groq"):
        t = _transcribe_groq(audio)
        if t is not None:
            return t
        if eng == "groq":
            return ""
    model = _load_whisper()
    if model is None:
        return ""
    segs, _info = model.transcribe(audio, language=ctx.config["stt"].get("language", "en"), beam_size=1,
                                   vad_filter=True, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segs).strip()


_ambient = 300.0        # room level (rms after gain) tracked by the capture loop while nothing is happening
_DANGLING = re.compile(r"\b(times|plus|minus|divided by|multiplied by|over|to|at|for|the|a|an|and|or|of|in|on|by|with|is|are|"
                       r"what's|what is|how|set|play|add|remind me|call me|turn|make|tell me|about|from|into|than|per|x)[\s.,!?]*$", re.I)


def _run_turn(prefix=None, follow=False, noise=300.0):
    """One question/answer turn. follow=True: no chirp, energy-triggered (prefix chunks), stop-words end it silently.
    Speech is played on a separate thread so the capture loop keeps running (barge-in + follow-up)."""
    global _follow_up_until
    _follow_up_until = 0.0
    with _lock:
        _state["follow_up_open"] = False
    tm = {}
    t0 = time.time()
    if follow:
        _events_push("follow_up_speech", {"t": t0})
    else:
        _events_push("wake", {"t": t0})
    _set_phase("listening")
    _leds("listen")
    # duck the music (Alexa-style) for the whole turn: listening, thinking, the answer and the follow-up window.
    # Music plays through its own ALSA volume ("Music"), so Jarvis' voice on "default" stays at full level over it.
    _duck(True)
    if not follow:
        _chirp()
    audio = _record_utterance(prefix=prefix, start_timeout=2.5 if follow else 4.0, noise0=noise)
    tm["listen"] = round(time.time() - t0, 2)
    if audio is None:
        _set_phase("idle"); _leds("idle"); _duck(False)
        _events_push("follow_up_end", {}) if follow else None
        return
    _set_phase("thinking")
    _leds("think")
    t1 = time.time()
    text, spec_hit = _transcribe_recorded(audio)
    if text and _DANGLING.search(text) and not follow:
        # the sentence is not finished ("10 times", "remind me to"): the pause was mid-sentence, so listen on a little
        _set_phase("listening"); _leds("listen")
        more = _record_utterance(start_timeout=1.5, noise0=noise)
        _set_phase("thinking"); _leds("think")
        if more is not None:
            audio = np.concatenate([audio, more])
            text2, _ = _transcribe_recorded(audio)
            ctx.log(f"continued: {text!r} -> {text2!r}")
            text = text2 or text
    tm["stt"] = round(time.time() - t1, 2)
    if spec_hit:
        tm["stt_early"] = True
    with _lock:
        _state["last_transcript"] = text
    ctx.log(f"heard: {text!r}" + (" (follow-up)" if follow else ""))
    if not text or (follow and _STOP_WORDS.match(text)):
        _set_phase("idle"); _leds("idle"); _duck(False)
        _events_push("follow_up_end", {})
        return
    _events_push("transcript", {"text": text})
    t2 = time.time()
    reply = _answer(text)
    tm["llm"] = round(time.time() - t2, 2)
    _events_push("answer", {"text": reply})
    tm["_t_tts0"] = time.time()
    threading.Thread(target=_speak_turn, args=(reply, tm), name="voice-speak", daemon=True).start()


def _speak_turn(reply, tm):
    """Speak the answer, log the turn timings, then open the follow-up window (unless interrupted)."""
    global _follow_up_until
    completed = say_stream(reply, tm)            # fills tm["tts"] (time to first audio)
    tm.pop("_t_tts0", None)
    tm["total_to_speech"] = round(sum(v for k, v in tm.items() if k in ("listen", "stt", "llm", "tts")), 2)
    with _lock:
        _state["last_timings"] = tm
    ctx.log("turn: " + " ".join(f"{k} {v}s" for k, v in tm.items()))
    global _follow_up_request
    fu = float(ctx.config.get("follow_up_s", 5) or 0)
    asked = _follow_up_request if _follow_up_request > time.time() else 0.0
    _follow_up_request = 0.0
    if completed and (asked or (fu > 0 and (not _music_playing() or _capture_kind == "aec"))):
        _follow_up_until = max(time.time() + fu, asked) if asked else time.time() + fu
        with _lock:
            _state["follow_up_open"] = True
        _leds("listen")
        _events_push("follow_up", {"open": True, "until": _follow_up_until})
    elif completed:
        _duck(False)                              # turn over, no follow-up window: music back up
    elif not _speaking.is_set() and _state.get("phase") == "idle":
        _duck(False)                              # interrupted and nothing else took over


def _close_follow_up():
    """End a follow-up window (if any) and put the light bar back to its base state."""
    global _follow_up_until
    was_open = bool(_follow_up_until)
    _follow_up_until = 0.0
    with _lock:
        _state["follow_up_open"] = False
    _leds("idle")
    _duck(False)
    if was_open:
        _events_push("follow_up_end", {})


_nm = {"peak": 0.0, "t": 0.0}
def _near_miss(score, thr):
    """Log a wake score that came close but stayed under the threshold (one line per attempt), for far-field tuning."""
    now = time.time()
    if score >= 0.25 and score < thr:
        if score > _nm["peak"]:
            _nm["peak"] = score; _nm["t"] = now
    elif _nm["peak"] and now - _nm["t"] > 1.0:
        ctx.log(f"wake word nearly ({_nm['peak']:.2f} < {thr:.2f}); gain x{_alt['agc']:.1f}, onboard weight {_alt['w_on']:.2f}")
        _nm["peak"] = 0.0


def _duck(on):
    """Music down while Jarvis is busy, back up after (audio module, Music softvol). Never raises."""
    try:
        au = ctx.module("audio")
        if au and hasattr(au, "duck_music"):
            au.duck_music(on)
    except Exception as e:
        ctx.log(f"duck failed: {e}")


def _music_playing():
    try:
        sp = ctx.module("spotify")
        return bool(sp and hasattr(sp, "is_playing") and sp.is_playing())
    except Exception:
        return False


def _handle_wake():
    """Wake word heard: interrupt any speech, then run a normal turn."""
    _stop_speaking()
    _run_turn(noise=_ambient)


def _drain(n=4):
    """Discard chunks buffered in the arecord pipe while we were busy (avoids reacting to stale audio)."""
    for _ in range(n):
        if _read_chunk() is None:
            break


def _flush_oww(oww, seconds=2.0):
    """Push silence through the wake-word model and reset it. Model.reset() only clears the score buffer; the feature
    history (about 1.5 s of audio) still holds the "hey jarvis" that started the turn, and the first predictions after
    a turn would fire on it again, cutting off the answer as a barge-in."""
    try:
        zeros = np.zeros(CHUNK, dtype=np.int16)
        for _ in range(int(seconds / (CHUNK / MODEL_RATE))):
            oww.predict(zeros)
        oww.reset()
    except Exception as e:
        ctx.log(f"oww flush failed: {e}")


def _pipeline():
    global _oww, _follow_up_until
    backoff = 2
    while True:
        cfg = ctx.config
        enabled = cfg.get("enabled", True) and cfg.get("mic_enabled", True) and time.time() >= _paused_until
        with _lock:
            _state["mic_enabled"] = bool(cfg.get("mic_enabled", True))
        if not enabled:
            _close_capture()
            with _lock:
                _state["listening"] = False
            _set_phase("idle")
            time.sleep(1)
            continue
        oww = _load_oww()
        if oww is None:
            with _lock:
                _state["listening"] = False
            time.sleep(30)
            continue
        try:
            if _capture is None or _capture.poll() is not None:
                _open_capture()
                ctx.log(f"mic capture started through {_mics_text()}" + (" (echo cancellation on)" if _capture_kind == "aec" else ""))
            with _lock:
                _state["listening"] = True
            backoff = 2
            global _ambient
            noise = 300.0                        # running estimate of room level (after gain), for follow-up triggering
            hot = 0                              # consecutive loud chunks during a follow-up window
            while cfg.get("mic_enabled", True) and cfg.get("enabled", True) and time.time() >= _paused_until:
                ch = _read_chunk()
                if ch is None:
                    _capture_died()
                    raise RuntimeError(f"{_capture_kind} pipe closed")
                speaking = _speaking.is_set()
                # model keys carry a version suffix ("hey_jarvis_v0.1"); match by prefix
                score, heard_on = _wake_score(oww, ch, cfg["wake_word"])
                _dbg_update(ch, score)
                rms = _dbg["mic_level"]
                _ambient = noise
                if speaking:
                    # barge-in: stricter threshold, and ignore the first 300 ms of playback (speaker onset)
                    thr = float(cfg.get("wake_threshold_while_speaking", 0.7))
                    onset = 0.3
                    if _capture_kind == "aec":        # Jarvis' own voice is in the reference and removed from the mic
                        thr = float(_aec_cfg().get("speaking_threshold", 0.6)); onset = float(_aec_cfg().get("speaking_onset_s", 0.2))
                    if time.time() - _speak_started_at > onset and score >= thr:
                        ctx.log(f"wake word while speaking ({score:.2f}, louder on the {heard_on} mic)")
                        _reset_oww(oww)
                        _handle_wake()
                        _drain(); _flush_oww(oww); hot = 0
                    cfg = ctx.config
                    continue
                wthr = float(cfg.get("wake_threshold", 0.5))
                if _capture_kind == "aec" and _speakers_loud():
                    wthr = min(wthr, float(_aec_cfg().get("music_wake_threshold", wthr)))
                _near_miss(score, wthr)
                if score >= wthr:
                    ctx.log(f"wake word ({score:.2f}, louder on the {heard_on} mic)" if _dual else f"wake word ({score:.2f})")
                    _reset_oww(oww)
                    _handle_wake()
                    _drain(); _flush_oww(oww); hot = 0
                    cfg = ctx.config
                    continue
                # follow-up window: speech energy alone starts a new turn (no wake word needed)
                if _follow_up_until and time.time() < _follow_up_until:
                    if rms > max(noise * 3.0, 800):
                        hot += 1
                        if hot >= 2:
                            _reset_oww(oww)
                            _run_turn(prefix=[ch], follow=True, noise=noise)
                            _drain(); _flush_oww(oww); hot = 0
                    else:
                        hot = 0
                        noise = 0.95 * noise + 0.05 * rms
                elif _follow_up_until:            # window expired quietly
                    _close_follow_up()
                    hot = 0
                else:
                    noise = 0.95 * noise + 0.05 * rms
                cfg = ctx.config
        except Exception as e:
            _close_capture()
            with _lock:
                _state["listening"] = False
            if _reopen["pending"]:                 # a requested restart (mic plugged/unplugged, device picked): reopen now
                _reopen["pending"] = False
                continue
            _err(f"capture error: {e}; retrying in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)


# ----------------------------------------------------------------------------- module API
def start(c):
    global ctx
    ctx = c
    _refresh_deps()
    _conv_trim()
    with _lock:
        _state["online"] = True
    with _lock:
        _state["mic_enabled"] = bool(ctx.config.get("mic_enabled", True))
    ctx.on("say", lambda d: say((d or {}).get("text", ""), blocking=False))
    threading.Thread(target=_aec_stats_loop, name="aec-stats", daemon=True).start()
    threading.Thread(target=_hotplug_loop, name="mic-hotplug", daemon=True).start()
    _pipeline()


def state():
    with _lock:
        out = json.loads(json.dumps(_state))
    fresh = time.time() - _aec_stats.get("t", 0) < 1.5
    out["aec"] = {"active": _capture_kind == "aec" and fresh, "erle_db": _aec_stats.get("erle_live") if fresh else None,
                  "ref_db": _aec_stats.get("ref") if fresh else None, "playing": bool(fresh and _aec_stats.get("ref_running")),
                  "delay_ms": int(_aec_cfg().get("delay_ms", 40)), "mic_delay_ms": int(_aec_cfg().get("mic_delay_ms", 60)),
                  "calibration": _aec_cfg().get("calibration"),
                  "usb": {"ok": bool(_aec_stats.get("mic2_ok")), "erle_db": _aec_stats.get("erle2"), "delay_ms": _aec_stats.get("delay2"),
                          "level_db": _aec_stats.get("mic2"), "out_db": _aec_stats.get("out2")} if (fresh and _dual) else None}
    out.update({"mic_level": _dbg["mic_level"], "wake_score": _dbg["wake_score"], "wake_score_max": _dbg["wake_score_max"],
                "mic_level_onboard": _dbg["mic_level_onboard"], "mic_level_usb": _dbg["mic_level_usb"],
                "mix_onboard_weight": round(_alt["w_on"], 2) if _dual else None, "wake_gain": round(_alt["agc"], 2) if _dual else None,
                "speaking": _speaking.is_set(), "follow_up_open": bool(_follow_up_until and time.time() < _follow_up_until)})
    return out


def on_config():
    _refresh_deps()
    global _llm
    _llm = None                                  # pick up a changed API key


# ------------------------------------------------------------------ voice catalogue (piper voices from rhasspy/piper-voices)
VOICE_CATALOG = [
    ("en_US-lessac-medium", "Lessac, neutral (default)"), ("en_US-amy-medium", "Amy, warm"),
    ("en_US-kristin-medium", "Kristin, soft"), ("en_US-hfc_female-medium", "HFC female, clear"),
    ("en_US-ryan-high", "Ryan, deep"), ("en_US-joe-medium", "Joe, casual"), ("en_US-hfc_male-medium", "HFC male, clear"),
    ("en_US-libritts_r-medium", "LibriTTS, narrator"), ("en_GB-alan-medium", "Alan, British"),
    ("en_GB-jenny_dioco-medium", "Jenny, British"), ("en_GB-alba-medium", "Alba, Scottish"), ("en_GB-cori-high", "Cori, British, high quality"),
]
GROQ_VOICES = ["daniel", "austin", "troy", "autumn", "diana", "hannah"]   # canopylabs/orpheus-v1-english voice names
_voice_dl = {}   # voice id -> "downloading" | "ready" | "error: ..."

def _voice_path(vid):
    return os.path.join(ctx.data_dir, "piper", vid + ".onnx")

def _download_voice(vid):
    """Fetch <vid>.onnx and .onnx.json from Hugging Face into the piper dir (background thread)."""
    import urllib.request
    try:
        locale, name, quality = vid.split("-", 2)
        base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{locale.split('_')[0]}/{locale}/{name}/{quality}/{vid}"
        os.makedirs(os.path.join(ctx.data_dir, "piper"), exist_ok=True)
        for ext in (".onnx.json", ".onnx"):
            tmp = _voice_path(vid) + ext[5:] + ".part"
            urllib.request.urlretrieve(base + ext, tmp)
            os.replace(tmp, _voice_path(vid) + ext[5:])
        _voice_dl[vid] = "ready"
        ctx.log(f"voice {vid} downloaded")
    except Exception as e:
        _voice_dl[vid] = f"error: {e}"
        ctx.log(f"voice download failed {vid}: {e}")

def _voices():
    tts = ctx.config["tts"]
    have_key = bool((ctx.config["llm"].get("groq_key") or "").strip())
    groq_active = have_key and tts.get("engine", "auto") in ("auto", "groq")
    out = []
    for name in GROQ_VOICES:
        out.append({"id": f"groq:{name}", "label": f"Groq: {name.capitalize()} (fast, natural)",
                    "status": "ready" if have_key else "needs a Groq key", "current": groq_active and tts.get("groq_voice") == name})
    cur = tts.get("voice")
    for vid, label in VOICE_CATALOG + [("en_US-lessac-low", "Lessac low (fast offline fallback)")]:
        st = "ready" if os.path.isfile(_voice_path(vid)) else _voice_dl.get(vid, "not downloaded")
        out.append({"id": vid, "label": "Piper: " + label, "status": st, "current": (not groq_active) and vid == cur})
    return out


def ask_llm(text, system=None, max_tokens=None):
    """One-off model call for other modules (games, stories): no history, optional custom system prompt.
    Returns the text or None on failure."""
    pid = _provider()
    if pid == "anthropic" or not _provider_ready(pid) or (pid != "local" and not _online()):
        return None
    cfg = ctx.config["llm"]
    sysmsg = system or cfg["system_prompt"]
    try:
        out = _chat(pid, sysmsg, [{"role": "user", "content": text}])
        return re.sub(r"\s+", " ", (out or "")).strip() or None
    except Exception as e:
        ctx.log(f"ask_llm failed: {str(e)[:120]}")
        return None


_follow_up_request = 0.0     # a module asked for a longer window than the default (games); honoured after the reply is spoken


def open_follow_up(seconds=20.0):
    """Keep listening for `seconds` without a wake word (games waiting for an answer)."""
    global _follow_up_until, _follow_up_request
    _follow_up_until = time.time() + float(seconds)
    _follow_up_request = _follow_up_until
    with _lock:
        _state["follow_up_open"] = True
    _leds("listen")
    _events_push("follow_up", {"open": True, "until": _follow_up_until})
    return _follow_up_until


def api(action, params):
    if action == "stop":
        global _follow_up_until
        stopped = _stop_speaking()
        _follow_up_until = 0.0
        return {"ok": True, "stopped": stopped}
    if action == "follow_up":
        secs = max(2.0, min(120.0, float(params.get("seconds", 20) or 20)))
        return {"ok": True, "until": open_follow_up(secs)}
    if action == "voices":
        return {"ok": True, "voices": _voices()}
    if action == "set_voice":
        vid = str(params.get("id", ""))
        if vid.startswith("groq:"):
            name = vid[5:]
            if name not in GROQ_VOICES:
                return {"ok": False, "error": "unknown voice"}
            ctx.config["tts"]["groq_voice"] = name; ctx.config["tts"]["engine"] = "auto"; ctx.save_config()
            global _groq_tts_block_until
            _groq_tts_block_until = 0.0                      # a fresh pick should try Groq again right away
            return {"ok": True, "voice": vid, "status": "ready"}
        if not any(vid == v for v, _ in VOICE_CATALOG) and vid != "en_US-lessac-low":
            return {"ok": False, "error": "unknown voice"}
        ctx.config["tts"]["engine"] = "piper"
        if not os.path.isfile(_voice_path(vid)) and _voice_dl.get(vid) != "downloading":
            _voice_dl[vid] = "downloading"
            threading.Thread(target=_download_voice, args=(vid,), daemon=True).start()
        ctx.config["tts"]["voice"] = vid; ctx.save_config()
        return {"ok": True, "voice": vid, "status": _voice_dl.get(vid, "ready")}
    if action == "preview":
        say(str(params.get("text") or "Hi, I'm Jarvis. This is how I sound.")[:2000], blocking=False)
        return {"ok": True}
    if action == "providers":
        cur = _provider(); cfg = ctx.config["llm"]
        models = {"anthropic": cfg.get("model"), "groq": cfg.get("groq_model"), "gemini": cfg.get("gemini_model"),
                  "openai_compat": cfg.get("custom", {}).get("model"), "local": cfg.get("local", {}).get("model")}
        models["groq"] = cfg.get("groq_fast_model", "qwen/qwen3.8-27b") + " / " + cfg.get("groq_search_model", "groq/compound") + " for web"
        return {"ok": True, "current": cur, "providers": [
            {"id": pid, "label": label, "needs_key": nk, "configured": _provider_ready(pid), "model": models.get(pid), "current": pid == cur}
            for pid, label, nk in PROVIDERS]}
    if action == "llm_test":
        t0 = time.time(); pid = _provider()
        ans = _ask_llm(str(params.get("text") or "Say hello in five words.")[:2000])
        with _lock:                      # a test question shouldn't pollute the conversation
            if _history and _history[-2]["content"].startswith("Say hello in five words"):
                del _history[-2:]; _state["history"] = list(_history[-8:])
        _refresh_deps()
        return {"ok": not ans.startswith(("Sorry,", "No key", "My local brain")), "answer": ans, "ms": int((time.time() - t0) * 1000), "provider": pid}
    if action == "say":
        say(str(params.get("text", ""))[:2000], blocking=False)
        return {"ok": True}
    if action == "ask":
        text = str(params.get("text") or "").strip()[:2000]
        if not text:
            return {"ok": False, "error": "empty"}
        with _lock:
            _state["last_transcript"] = text
        _set_phase("thinking")
        reply = _answer(text)
        _set_phase("idle")
        if params.get("speak"):
            say(reply, blocking=False)
        return {"ok": True, "answer": reply}
    if action == "calibrate":
        if _calib.get("running"):
            return {"ok": False, "error": "calibration already running"}
        if _capture_kind != "aec" or _capture is None or _capture.poll() is not None:
            return {"ok": False, "error": "echo cancellation is not running (microphone off or helper missing)"}
        threading.Thread(target=_calibrate, name="aec-calibrate", daemon=True).start()
        return {"ok": True, "started": True}
    if action == "aec_reload":
        aec_reload()
        return {"ok": True}
    if action == "calibration_status":
        return {"ok": True, **_calib}
    if action == "capture_devices":
        return {"ok": True, "devices": list_capture_devices(), "current": (ctx.config.get("mic_device") or "")}
    if action == "set_capture_device":
        dev = str(params.get("device") or "").strip()
        known = [d["device"] for d in list_capture_devices()]
        if dev and dev not in known:
            return {"ok": False, "error": "unknown device"}
        ctx.config["mic_device"] = dev
        ctx.save_config()
        ctx.log(f"microphones: {dev or 'automatic'}")
        _restart_capture()
        return {"ok": True, "device": dev}
    if action == "card_more":                    # expanded answer card: the article text behind a fact
        title = str(params.get("title") or "").strip()[:120]
        if not title:
            return {"ok": False, "error": "no title"}
        w = _wiki_lookup(title)
        return {"ok": True, "title": w["title"], "image": w["image"], "caption": w["caption"], "url": w["url"],
                "text": _wiki_more(w["title"]) or w["extract"]}
    if action == "pause_capture":                # lend the microphones to another module (speaker calibration records the USB mic itself)
        global _paused_until
        secs = max(0.0, min(120.0, float(params.get("seconds", 20))))
        _paused_until = time.time() + secs
        if secs > 0:
            _restart_capture()                     # the loop closes the pipe and waits, the devices are free within a second
        return {"ok": True, "until": _paused_until, "mics": dict(_state.get("mics") or {}), "usb_device": _pick_mics()[1] or ""}
    if action == "resume_capture":
        _paused_until = 0.0
        return {"ok": True}
    if action == "aec_stats":                    # raw helper statistics (diagnostics)
        return {"ok": True, "capture": _capture_kind, "dual": _dual, **_aec_stats}
    if action == "mics":
        with _lock:
            m = dict(_state.get("mics") or {})
        return {"ok": True, "mics": m, "text": _mics_text(), "levels": {"onboard": _dbg["mic_level_onboard"], "usb": _dbg["mic_level_usb"]}}
    if action == "set_mic":
        ctx.config["mic_enabled"] = bool(params.get("enabled", True))
        ctx.save_config()
        with _lock:
            _state["mic_enabled"] = ctx.config["mic_enabled"]
        if not ctx.config["mic_enabled"]:
            _close_follow_up()
        return {"ok": True, "mic_enabled": ctx.config["mic_enabled"]}
    if action == "clear_history":
        with _lock:
            _history.clear(); _state["history"] = []
        return {"ok": True}
    if action == "history":
        limit = max(1, min(500, int(params.get("limit", 50) or 50)))
        q = str(params.get("q") or "").strip().lower()
        turns = _conv_read()
        if q:
            turns = [r for r in turns if q in (r.get("heard", "") + " " + r.get("answer", "")).lower()]
        turns = turns[-limit:]; turns.reverse()
        return {"ok": True, "turns": turns, "total": len(turns)}
    if action == "clear_conversations":
        _conv_clear()
        with _lock:
            _history.clear(); _state["history"] = []
        return {"ok": True}
    if action == "deps":
        _refresh_deps()
        return {"ok": True, "deps": state()["deps"]}
    return {"ok": False, "error": f"unknown action {action}"}
