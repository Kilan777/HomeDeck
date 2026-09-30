"""YouTube: search (yt-dlp, no API key) and play videos on the device's screen.

The page-side player is the YouTube IFrame API inside the YouTube app (web/apps/youtube.js). This module does the
searching, keeps the watch history, tracks what is playing (so the home tile and voice know), pauses Spotify when a
video starts, and turns "play X on YouTube" from voice or the phone into a "youtube_play" event the app reacts to.
"""
import json, os, re, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

NAME = "youtube"
DEFAULTS = {"max_results": 15, "search_timeout_s": 15, "max_height": 720, "max_fps": 30, "resolve_timeout_s": 25}
ctx = None
_lock = threading.Lock()
_s = {"playing": False, "current": None, "history": [], "error": None, "available": None, "hb": 0.0}
_cache = {}                     # query -> (t, results)
_resolved = {}                  # video id -> (t, info dict with stream urls); YouTube urls stay valid for hours
_stream_lock = threading.Lock()
_stream_proc = None             # the one ffmpeg remux allowed at a time
_pool = ThreadPoolExecutor(max_workers=2)
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _hist_path():
    return os.path.join(ctx.data_dir, "youtube_history.json")


def _load_history():
    try:
        with open(_hist_path()) as f:
            h = json.load(f)
        if isinstance(h, list):
            with _lock:
                _s["history"] = h[:50]
    except Exception:
        pass


def _save_history():
    try:
        with _lock:
            h = list(_s["history"])
        tmp = _hist_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(h, f)
        os.replace(tmp, _hist_path())
    except Exception as e:
        ctx.log(f"history save failed: {e}")


def _fmt_entry(e):
    vid = e.get("id") or ""
    dur = e.get("duration")
    return {"id": vid, "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
            "duration": int(dur) if isinstance(dur, (int, float)) else None, "views": e.get("view_count"),
            "live": bool(e.get("live_status") == "is_live") or (dur is None and e.get("view_count") is None),
            "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg" if vid else ""}


def _search_blocking(q, n):
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True, "noplaylist": True,
            "default_search": "ytsearch", "socket_timeout": 8}
    with yt_dlp.YoutubeDL(opts) as y:
        r = y.extract_info(f"ytsearch{n}:{q}", download=False)
    out = []
    for e in (r or {}).get("entries", []) or []:
        if e and e.get("id"):
            out.append(_fmt_entry(e))
    return out


def search(q):
    q = (q or "").strip()
    if not q:
        return {"ok": False, "error": "empty search"}
    key = q.lower()
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 600:
        return {"ok": True, "results": hit[1], "cached": True}
    n = int(ctx.config.get("max_results", 15))
    fut = _pool.submit(_search_blocking, q, n)
    try:
        res = fut.result(timeout=float(ctx.config.get("search_timeout_s", 15)))
    except FutTimeout:
        with _lock:
            _s["error"] = "YouTube search timed out"
        return {"ok": False, "error": "YouTube search timed out, try again"}
    except ImportError:
        with _lock:
            _s["available"] = False; _s["error"] = "yt-dlp not installed"
        return {"ok": False, "error": "YouTube search is unavailable: yt-dlp is not installed"}
    except Exception as e:
        ctx.log(f"search failed: {str(e)[:160]}")
        with _lock:
            _s["error"] = "YouTube search is unavailable right now"
        return {"ok": False, "error": "YouTube search is unavailable right now"}
    with _lock:
        _s["error"] = None; _s["available"] = True
    _cache[key] = (time.time(), res)
    if len(_cache) > 60:
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:20]:
            _cache.pop(k, None)
    return {"ok": True, "results": res}


def _video_meta(vid):
    """Title/channel for a bare id: look in the cache and history first, else a quick flat lookup."""
    for _, res in _cache.values():
        for r in res:
            if r["id"] == vid:
                return r
    for h in _s["history"]:
        if h.get("id") == vid:
            return h
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True, "socket_timeout": 6}) as y:
            e = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
        return _fmt_entry(e) if e else {"id": vid, "title": "", "channel": "", "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"}
    except Exception:
        return {"id": vid, "title": "", "channel": "", "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"}


def parse_id(text):
    """Video id from a YouTube link (watch?v=, youtu.be/, shorts/, embed/) or a bare 11-char id; None otherwise."""
    t = (text or "").strip()
    if _ID_RE.match(t):
        return t
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})", t)
    return m.group(1) if m else None


def _note_played(v):
    with _lock:
        _s["current"] = {"id": v["id"], "title": v.get("title", ""), "channel": v.get("channel", ""), "thumb": v.get("thumb", ""), "t": time.time()}
        _s["history"] = [h for h in _s["history"] if h.get("id") != v["id"]]
        _s["history"].insert(0, {"id": v["id"], "title": v.get("title", ""), "channel": v.get("channel", ""), "thumb": v.get("thumb", ""), "t": time.time()})
        del _s["history"][50:]
    _save_history()


def play(vid=None, q=None):
    """Resolve what to play (id or first search hit), remember it, and tell the app to start it."""
    v = None
    if vid:
        v = _video_meta(vid)
    elif q:
        pid = parse_id(q)
        if pid:
            v = _video_meta(pid)
        else:
            r = search(q)
            if not r.get("ok"):
                return r
            if not r["results"]:
                return {"ok": False, "error": f"No videos found for {q}"}
            v = r["results"][0]
    if not v:
        return {"ok": False, "error": "nothing to play"}
    _note_played(v)
    ctx.emit("youtube_play", {"id": v["id"], "title": v.get("title", ""), "channel": v.get("channel", "")})
    ctx.log(f"play {v['id']} {v.get('title', '')[:60]!r}")
    return {"ok": True, "video": v}


def _pause_spotify():
    try:
        sp = ctx.module("spotify")
        if sp and hasattr(sp, "is_playing") and sp.is_playing():
            sp.api("pause", {})
            ctx.log("paused Spotify for a video")
    except Exception as e:
        ctx.log(f"spotify pause failed: {e}")


def _pick_formats(info):
    """Best H.264 video-only stream within max_height (preferring <= max_fps: the CM4 decodes 720p30 comfortably,
    720p60 not), the best AAC audio, or a progressive mp4 when that is all there is."""
    cfg = ctx.config
    maxh, maxfps = int(cfg.get("max_height", 720)), int(cfg.get("max_fps", 30))
    fs = [f for f in (info.get("formats") or []) if f.get("url") and str(f.get("protocol", "")).startswith("http") and not str(f.get("protocol", "")).startswith("http_dash")]
    vids = [f for f in fs if str(f.get("vcodec") or "none").startswith("avc1") and (f.get("acodec") in (None, "none")) and (f.get("height") or 0) <= maxh]
    auds = [f for f in fs if (f.get("vcodec") in (None, "none")) and str(f.get("acodec") or "").startswith("mp4a")]
    prog = [f for f in fs if str(f.get("vcodec") or "none").startswith("avc1") and str(f.get("acodec") or "none") != "none" and (f.get("height") or 0) <= maxh]
    calm = [f for f in vids if (f.get("fps") or 30) <= maxfps]
    v = max(calm or vids, key=lambda f: ((f.get("height") or 0), (f.get("tbr") or 0))) if (calm or vids) else None
    a = max(auds, key=lambda f: ((0 if "drc" in str(f.get("format_id", "")) else 1), (f.get("abr") or 0))) if auds else None
    if v and a:
        return {"video_url": v["url"], "audio_url": a["url"], "height": v.get("height"), "fps": v.get("fps"), "kbps": round((v.get("tbr") or 0) + (a.get("abr") or 0))}
    if prog:
        pv = max(prog, key=lambda f: (f.get("height") or 0))
        return {"progressive_url": pv["url"], "height": pv.get("height"), "fps": pv.get("fps"), "kbps": round(pv.get("tbr") or 0)}
    return None


def _resolve_blocking(vid):
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, "socket_timeout": 10}) as y:
        info = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    fmt = _pick_formats(info or {})
    out = {"id": vid, "title": info.get("title") or "", "channel": info.get("channel") or info.get("uploader") or "",
           "duration": info.get("duration"), "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg", "live": info.get("is_live") is True,
           "stream_ok": bool(fmt) and not info.get("is_live")}
    if fmt:
        out.update(fmt)
    return out


def resolve(vid):
    hit = _resolved.get(vid)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    fut = _pool.submit(_resolve_blocking, vid)
    try:
        info = fut.result(timeout=float(ctx.config.get("resolve_timeout_s", 25)))
    except FutTimeout:
        return {"id": vid, "stream_ok": False, "error": "YouTube took too long to answer"}
    except Exception as e:
        ctx.log(f"resolve {vid} failed: {str(e)[:160]}")
        return {"id": vid, "stream_ok": False, "error": "This video can't be streamed directly"}
    _resolved[vid] = (time.time(), info)
    if len(_resolved) > 40:
        for k in sorted(_resolved, key=lambda k: _resolved[k][0])[:10]:
            _resolved.pop(k, None)
    return info


def _public(info):
    return {k: v for k, v in info.items() if k not in ("video_url", "audio_url", "progressive_url")}


def _kill_stream():
    global _stream_proc
    with _stream_lock:
        p, _stream_proc = _stream_proc, None
    if p and p.poll() is None:
        try:
            p.kill(); p.wait(timeout=3)
        except Exception:
            pass


def _chunk(req, data):
    req.wfile.write(b"%x\r\n" % len(data)); req.wfile.write(data); req.wfile.write(b"\r\n"); req.wfile.flush()


def _route_stream(req):
    """GET /youtube/stream?id=<id>&t=<seconds>: fragmented MP4 remuxed on the fly by ffmpeg (no re-encode), chunked.
    Seeking is done by the player by reloading with t=. One stream at a time; the previous one is killed."""
    global _stream_proc
    vid = parse_id(req.query.get("id", "") or "")
    if not vid:
        return req.send(400, "text/plain", "bad id")
    try:
        t0 = max(0.0, float(req.query.get("t", "0") or 0))
    except ValueError:
        t0 = 0.0
    info = resolve(vid)
    if not info.get("stream_ok"):
        return req.send(503, "application/json", json.dumps({"ok": False, "error": info.get("error") or "no direct stream"}).encode())
    net = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5", "-user_agent", "Mozilla/5.0"]
    seek = ["-ss", f"{t0:.2f}"] if t0 > 0.5 else []
    if info.get("progressive_url"):
        cmd = ["ffmpeg", "-loglevel", "error", "-nostdin"] + net + seek + ["-i", info["progressive_url"], "-c", "copy"]
    else:
        cmd = ["ffmpeg", "-loglevel", "error", "-nostdin"] + net + seek + ["-i", info["video_url"]] + net + seek + ["-i", info["audio_url"],
               "-map", "0:v:0", "-map", "1:a:0", "-c", "copy"]
    cmd += ["-movflags", "frag_keyframe+empty_moov+default_base_moof", "-frag_duration", "1000000", "-f", "mp4", "pipe:1"]
    _kill_stream()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    with _stream_lock:
        _stream_proc = p
    ctx.log(f"stream {vid} from {t0:.0f}s ({info.get('height')}p{info.get('fps') or ''} ~{info.get('kbps')} kbps)")
    req.send_response(200)
    req.send_header("Content-Type", "video/mp4")
    req.send_header("Cache-Control", "no-store")
    req.send_header("Transfer-Encoding", "chunked")
    req.send_header("X-Content-Type-Options", "nosniff")
    req.end_headers()
    sent = 0
    try:
        while True:
            data = p.stdout.read(65536)
            if not data:
                break
            _chunk(req, data); sent += len(data)
        if sent == 0:
            err = (p.stderr.read() or b"")[:200].decode("utf-8", "replace")
            ctx.log(f"stream {vid} produced nothing: {err}")
        req.wfile.write(b"0\r\n\r\n"); req.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        with _stream_lock:
            mine = _stream_proc is p
            if mine:
                _stream_proc = None
        if p.poll() is None:
            try:
                p.kill(); p.wait(timeout=3)
            except Exception:
                pass
        ctx.log(f"stream {vid} ended after {sent // 1024} kB")


ROUTES = {"/stream": _route_stream}


def state():
    with _lock:
        return {"playing": _s["playing"], "current": dict(_s["current"]) if _s["current"] else None,
                "history": list(_s["history"][:12]), "error": _s["error"], "available": _s["available"]}


def api(action, params):
    if action == "search":
        return search(params.get("q"))
    if action == "play":
        vid = params.get("id") or parse_id(params.get("q") or "")
        return play(vid=vid, q=None if vid else params.get("q"))
    if action == "playing":
        st = params.get("state", "playing")
        with _lock:
            _s["playing"] = st == "playing"
            _s["hb"] = time.time()
            if params.get("id") and (not _s["current"] or _s["current"].get("id") != params["id"]):
                _s["current"] = {"id": params["id"], "title": params.get("title", ""), "channel": params.get("channel", ""), "t": time.time()}
            if st in ("ended", "stopped"):
                _s["playing"] = False
        if st == "playing":
            _pause_spotify()
        return {"ok": True}
    if action == "stop":
        with _lock:
            _s["playing"] = False; _s["current"] = None
        _kill_stream()
        ctx.emit("youtube_stop", {})
        return {"ok": True}
    if action == "resolve":
        vid = parse_id(params.get("id") or "")
        if not vid:
            return {"ok": False, "error": "bad id"}
        info = resolve(vid)
        return {"ok": True, **_public(info)}
    if action == "history":
        with _lock:
            return {"ok": True, "history": list(_s["history"])}
    if action == "clear_history":
        with _lock:
            _s["history"] = []
        _save_history()
        return {"ok": True}
    return {"ok": False, "error": f"unknown action {action}"}


_INTENT = [re.compile(p, re.I) for p in (
    r"^(?:please\s+)?(?:play|watch|search(?: for)?|look up|find)\s+(.+?)\s+on youtube$",
    r"^(?:please\s+)?search youtube for\s+(.+)$",
    r"^(?:please\s+)?(?:play|open)\s+youtube\s+(?:video\s+)?(.+)$",
    r"^(?:please\s+)?youtube\s+(.+)$",
    r"^(.+?)\s+on youtube$",
)]
_STOP = re.compile(r"^(?:please\s+)?(?:stop|close|pause)\s+(?:the\s+)?(?:youtube|video)(?:\s+please)?$", re.I)


def intent(text):
    t = (text or "").strip().rstrip(".!?").lower()
    if not t:
        return None
    if _STOP.match(t):
        api("stop", {})
        return ""
    if "youtube" not in t:
        return None
    for rx in _INTENT:
        m = rx.match(t)
        if m:
            q = m.group(1).strip().strip("\"'")
            if not q or q in ("it", "something", "a video"):
                return "What should I look for on YouTube?"
            r = play(q=q)
            if r.get("ok"):
                return ""
            return r.get("error") or "I couldn't find that on YouTube."
    return None


def start(c):
    global ctx
    ctx = c
    _load_history()
    try:
        import yt_dlp  # noqa: F401
        with _lock:
            _s["available"] = True
    except Exception:
        with _lock:
            _s["available"] = False; _s["error"] = "yt-dlp not installed (sudo /opt/homedeck/venv/bin/pip install yt-dlp)"
        ctx.log("yt-dlp not importable; search disabled")
    while True:
        time.sleep(5)
        with _lock:
            stale = _s["playing"] and time.time() - _s["hb"] > 15
            if stale:
                _s["playing"] = False
        if stale:
            ctx.log("no heartbeat from the player for 15 s; marked stopped")
            _kill_stream()
