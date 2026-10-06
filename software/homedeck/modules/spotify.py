"""Spotify: the CM4 is a Spotify Connect speaker (raspotify/librespot, see install/spotify_deps.sh)
and this module controls playback through the Spotify Web API using Authorization Code + PKCE,
so only a client_id is needed (no secret). Requires Spotify Premium for Connect playback.

Routes:  GET /spotify/login     -> redirects the browser to Spotify's consent page
         GET /spotify/callback  -> exchanges the code for tokens, saves them, redirects to /
API:     play {uri|context_uri}, pause, next, prev, volume {pct}, shuffle {on}, seek {ms}, playlists
Module-level helpers for other modules (alarms): play_uri(uri), pause(), is_playing()
"""
import base64, hashlib, json, os, secrets, threading, time, urllib.error, urllib.parse, urllib.request

NAME = "spotify"
DEFAULTS = {
    "client_id": "",                       # from developer.spotify.com, pasted in the Music app
    "device_name": "HomeDeck",             # LIBRESPOT_NAME in /etc/raspotify/conf
    "tokens": {"access": "", "refresh": "", "expires_at": 0},
    "poll_seconds": 3,
    "pending_login": {},                   # state -> {verifier, at} for sign-ins in flight (survives a restart)
}
SCOPES = ("user-read-playback-state user-modify-playback-state user-read-currently-playing user-read-recently-played "
          "playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private "
          "user-library-read user-library-modify user-follow-read user-read-playback-position")
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"

ctx = None
_lock = threading.Lock()
_state = {"configured": False, "authenticated": False, "device_online": False, "device_id": None,
          "now": None, "playlists": [], "error": None, "needs_reauth": False, "liked": None, "user_id": None}
_pkce = {}                 # state -> code_verifier for in-flight logins
# What librespot itself reports through the --onevent hook (install/spotify_event.sh). The Spotify Web API's player
# state can lag or desync from the speaker for minutes, so the local player is the source of truth for the current
# track, play/pause and position whenever it is the one playing.
_local = {"at": 0.0, "event": None, "track_id": None, "uri": None, "playing": False, "position_ms": 0, "pos_at": 0.0,
          "duration_ms": None, "shuffle": None, "repeat": None, "stopped": True}
_web_now = {"now": None, "at": 0.0}           # last /me/player/currently-playing snapshot and when it was taken
_track_meta = {}                              # track id -> {title, artist, album, art_url, duration_ms, uri, kind}
_playlists_at = 0
_backoff_until = 0                    # kept for state(); the real bookkeeping is per endpoint family below
_backoff = {}                         # "/me/player" -> time until which that endpoint family is not called (429 Retry-After)
BACKOFF_CAP = 600                     # never trust a Retry-After beyond 10 minutes: probe again, the limit lifts per endpoint


# ----------------------------------------------------------------- HTTP helpers
def _form_post(url, data, headers=None):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", **(headers or {})})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"{}")


def _token_valid():
    t = ctx.config["tokens"]
    return bool(t.get("access")) and time.time() < t.get("expires_at", 0) - 30


def _refresh():
    """Refresh the access token; returns True on success."""
    t = ctx.config["tokens"]
    if not t.get("refresh") or not ctx.config["client_id"]:
        return False
    try:
        j = _form_post(TOKEN_URL, {"grant_type": "refresh_token", "refresh_token": t["refresh"],
                                   "client_id": ctx.config["client_id"]})
        _store_tokens(j, keep_refresh=t["refresh"])
        return True
    except Exception as e:
        ctx.log(f"token refresh failed: {e}")
        _set_error("Spotify login expired, reconnect from the Music app")
        with _lock:
            _state["authenticated"] = False
        return False


def _store_tokens(j, keep_refresh=""):
    ctx.config["tokens"] = {"access": j["access_token"],
                            "refresh": j.get("refresh_token") or keep_refresh,
                            "expires_at": time.time() + int(j.get("expires_in", 3600))}
    ctx.save_config()
    with _lock:
        _state["authenticated"] = True
        _state["error"] = None
        _state["needs_reauth"] = False


def _call(method, path, body=None, params=None, retry=True):
    """Authenticated Web API call. Returns parsed JSON, {} for 204, or None on failure."""
    global _backoff_until
    fam = "/".join(path.split("?")[0].split("/")[:3])          # "/me/player/next" -> "/me/player"
    if time.time() < _backoff.get(fam, 0):
        return None
    if not _token_valid() and not _refresh():
        return None
    url = API + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": "Bearer " + ctx.config["tokens"]["access"],
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            with _lock:
                if _state["error"] and not _state["error"].lower().startswith("spotify unreachable") or (_state["error"] or "").startswith("No active"):
                    _state["error"] = None
            if not raw or not raw.strip():
                return {}
            try:
                return json.loads(raw)
            except ValueError:
                # 204/empty-ish bodies or non-JSON payloads: not an error for PUT/POST commands
                ctx.log(f"non-JSON reply from {path}: {raw[:60]!r}")
                return {} if method != "GET" else None
    except urllib.error.HTTPError as e:
        if e.code == 401 and retry and _refresh():
            return _call(method, path, body, params, retry=False)
        if e.code == 429:
            wait = min(BACKOFF_CAP, int(e.headers.get("Retry-After", "5")))
            if time.time() >= _backoff.get(fam, 0):               # log once per block, not once per call
                ctx.log(f"Spotify Web API rate limit on {fam}: waiting {wait} s (playback through the local player keeps working)")
            _backoff[fam] = time.time() + wait
            _backoff_until = max(_backoff.values())
            return None
        if e.code == 404 and method != "GET":
            _set_error("No active Spotify device. Is raspotify running on the HomeDeck?")
            return None
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", str(e))
        except Exception:
            msg = str(e)
        if e.code == 403 and ("scope" in msg.lower() or _needs_new_scope(method, path)):
            # token was issued before a scope was added (e.g. recently-played): needs one re-authorise, not an error banner
            with _lock:
                _state["needs_reauth"] = True
            return None
        _set_error(f"Spotify: {msg}")
        return None
    except Exception as e:
        _set_error(f"Spotify unreachable: {e}")
        return None


def _needs_new_scope(method, path):
    """Endpoints that only work with the scopes added later (library-modify, playlist-modify, follow): a 403 there
    means the token predates them, so ask for a reconnect instead of showing a raw error."""
    if path.startswith("/me/following"):
        return True
    if method in ("PUT", "DELETE") and path.startswith("/me/tracks"):
        return True
    if method in ("POST", "DELETE") and path.startswith("/playlists/") and (path.endswith("/tracks") or path.endswith("/items")):
        return True
    return False


def _set_error(msg):
    with _lock:
        _state["error"] = msg


# ----------------------------------------------------------------- PKCE login routes
def _route_login(req):
    cid = ctx.config["client_id"]
    if not cid:
        return req.send(400, "text/plain", "Set the Spotify Client ID in the Music app first")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    st = secrets.token_urlsafe(16)
    _pkce[st] = verifier
    pend = {k: v for k, v in (ctx.config.get("pending_login") or {}).items() if time.time() - v.get("at", 0) < 900}
    pend[st] = {"verifier": verifier, "at": time.time()}
    ctx.config["pending_login"] = pend; ctx.save_config()
    scheme = "https" if req.headers.get("X-Forwarded-Proto") == "https" else "http"
    redirect = f"{scheme}://{req.headers.get('Host')}/spotify/callback"
    q = urllib.parse.urlencode({"client_id": cid, "response_type": "code", "redirect_uri": redirect,
                                "scope": SCOPES, "code_challenge_method": "S256", "code_challenge": challenge,
                                "state": st})
    req.send_response(302); req.send_header("Location", AUTH_URL + "?" + q); req.send_header("Content-Length", "0"); req.end_headers()


def _login_failed(req, why):
    host = (req.headers.get("Host") or "").lower()
    if host.startswith("127.0.0.1") or host.startswith("localhost"):
        page = (f"<!doctype html><meta charset=utf-8><title>Spotify</title><body style='margin:0;background:#101218;color:#f5f5f7;font:17px Inter,system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh'>"
                f"<div style='text-align:center;max-width:520px;padding:24px'><h2 style='margin:0 0 10px'>Spotify sign-in didn't finish</h2><p style='color:#bbb;margin:0 0 22px'>{why}. Open Music and tap Connect on this screen to try again.</p>"
                f"<a href='{KIOSK_HOME}' style='display:inline-block;padding:12px 22px;border-radius:999px;background:#0a84ff;color:#fff;text-decoration:none;font-weight:600'>Back to HomeDeck</a></div>")
        return req.send(200, "text/html", page)
    return req.send(400, "text/plain", f"Spotify login failed: {why}")


def _route_callback(req):
    q = req.query
    st = q.get("state", "")
    pend = ctx.config.get("pending_login") or {}
    verifier = _pkce.pop(st, None) or (pend.get(st) or {}).get("verifier")
    if st in pend:
        pend = dict(pend); pend.pop(st, None); ctx.config["pending_login"] = pend; ctx.save_config()
    if "error" in q or not verifier or "code" not in q:
        return _login_failed(req, q.get("error", "the sign-in session expired or the service restarted"))
    scheme = "https" if req.headers.get("X-Forwarded-Proto") == "https" else "http"
    redirect = f"{scheme}://{req.headers.get('Host')}/spotify/callback"
    try:
        j = _form_post(TOKEN_URL, {"grant_type": "authorization_code", "code": q["code"], "redirect_uri": redirect,
                                   "client_id": ctx.config["client_id"], "code_verifier": verifier})
        _store_tokens(j)
        ctx.log("Spotify connected")
    except urllib.error.HTTPError as e:
        return _login_failed(req, f"token exchange failed (HTTP {e.code}); check the Client ID and redirect URI")
    host = (req.headers.get("Host") or "").lower()
    dest = KIOSK_HOME if (host.startswith("127.0.0.1") or host.startswith("localhost")) else "/"
    req.send_response(302); req.send_header("Location", dest); req.send_header("Content-Length", "0"); req.end_headers()


ROUTES = {"/login": _route_login, "/callback": _route_callback}


# ----------------------------------------------------------------- sign-in on the device's own screen
# The kiosk Chromium exposes DevTools on 127.0.0.1:9222. We send it to Spotify's sign-in and, on every page of that
# flow (they are separate documents), inject the HomeDeck on-screen keyboard and a "Back to HomeDeck" button, since
# the panel has no keyboard of its own. Ends when the tab is back on the HomeDeck UI or after six minutes.
CDP = "http://127.0.0.1:9222"
KIOSK_HOME = "http://localhost:8080/?kiosk=1"
DEVICE_LOGIN = "http://127.0.0.1:8080/spotify/login"       # 127.0.0.1, not localhost: it must match the registered redirect URI
_device_login = {"active": False, "since": 0, "status": "idle"}


def _cdp_page():
    tabs = json.load(urllib.request.urlopen(CDP + "/json", timeout=3))
    pages = [t for t in tabs if t.get("type") == "page"]
    return pages[0] if pages else None


class _WS:
    """Minimal WebSocket client for DevTools on localhost (no dependency: the service's venv sees the user's
    site-packages only when run as that user, so websocket-client is not reliably importable as root)."""
    def __init__(self, url, origin, timeout=8):
        import socket, struct
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {u.path or '/'} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nOrigin: {origin}\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("websocket handshake failed")
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise RuntimeError("websocket upgrade refused: " + head.split(b"\r\n")[0].decode(errors="replace"))
        self.buf = rest

    def _recv_exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text):
        import struct
        data = text.encode(); mask = os.urandom(4)
        hdr = bytearray([0x81])
        if len(data) < 126: hdr.append(0x80 | len(data))
        elif len(data) < 65536: hdr.append(0x80 | 126); hdr += struct.pack(">H", len(data))
        else: hdr.append(0x80 | 127); hdr += struct.pack(">Q", len(data))
        self.sock.sendall(bytes(hdr) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        import struct
        while True:
            b0, b1 = self._recv_exact(2)
            op, ln = b0 & 0x0F, b1 & 0x7F
            if ln == 126: ln = struct.unpack(">H", self._recv_exact(2))[0]
            elif ln == 127: ln = struct.unpack(">Q", self._recv_exact(8))[0]
            if b1 & 0x80: self._recv_exact(4)          # server frames are not masked, but be safe
            payload = self._recv_exact(ln)
            if op == 0x1: return payload.decode()
            if op == 0x8: raise RuntimeError("websocket closed by peer")
            # ping/pong/binary: ignore

    def close(self):
        try: self.sock.close()
        except Exception: pass


def _cdp_call(page, method, params=None, timeout=8):
    ws = _WS(page["webSocketDebuggerUrl"], CDP, timeout)
    try:
        ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            r = json.loads(ws.recv())
            if r.get("id") == 1:
                if "error" in r:
                    raise RuntimeError(r["error"].get("message", "cdp error"))
                return r.get("result", {})
    finally:
        ws.close()


def _cdp_eval(page, expr):
    r = _cdp_call(page, "Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": False})
    return (r.get("result") or {}).get("value")


def _is_local(url):
    return url.startswith("http://localhost") or url.startswith("http://127.0.0.1")


_BACK_BTN = """(function(){ if (document.getElementById('hd-back')) return; var b=document.createElement('button'); b.id='hd-back'; b.textContent='Back to HomeDeck';
b.style.cssText='position:fixed;top:10px;left:10px;z-index:2147483001;padding:10px 16px;border:0;border-radius:999px;background:rgba(20,22,28,.92);color:#fff;font:600 15px Inter,system-ui,sans-serif;box-shadow:0 4px 18px rgba(0,0,0,.45);cursor:pointer';
b.onclick=function(){ location.href=%s; }; (document.body||document.documentElement).appendChild(b); })();"""


def _inject(page):
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "keyboard.js")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    _cdp_eval(page, src)
    _cdp_eval(page, _BACK_BTN % json.dumps(KIOSK_HOME))


def _device_login_watch():
    deadline = time.time() + 6 * 60
    injected_for = None
    try:
        while time.time() < deadline and _device_login["active"]:
            time.sleep(0.5)
            try:
                page = _cdp_page()
                if not page:
                    continue
                url = page.get("url", "")
                if _is_local(url):
                    if "/spotify/login" not in url and time.time() - _device_login["since"] > 3:
                        _device_login["status"] = "done" if _state["authenticated"] else "back"
                        break                                   # back on the HomeDeck UI (callback done, or Back pressed)
                    continue
                has = _cdp_eval(page, "!!window.__hdKbd && !!document.getElementById('hd-back')")
                if not has:
                    _inject(page)
                    if injected_for != url:
                        injected_for = url
                        ctx.log(f"spotify device login: keyboard on {url.split('?')[0][:80]}")
            except Exception as e:
                ctx.log(f"spotify device login watcher: {e}")
                time.sleep(1)
        else:
            if _device_login["active"]:
                _device_login["status"] = "timeout"
                try:
                    page = _cdp_page()
                    if page and not _is_local(page.get("url", "")):
                        _cdp_call(page, "Page.navigate", {"url": KIOSK_HOME})
                except Exception:
                    pass
    finally:
        _device_login["active"] = False


def device_login():
    """Start the on-screen sign-in: navigate the kiosk to the login route and watch the flow."""
    if not ctx.config.get("client_id"):
        return {"ok": False, "error": "Set the Spotify Client ID first"}
    page = _cdp_page()
    if not page:
        return {"ok": False, "error": "The device screen isn't available"}
    if _device_login["active"]:
        return {"ok": True, "already": True}
    _device_login.update({"active": True, "since": time.time(), "status": "signing_in"})
    threading.Thread(target=_device_login_watch, daemon=True, name="spotify-device-login").start()
    _cdp_call(page, "Page.navigate", {"url": DEVICE_LOGIN})
    ctx.log("spotify device login started")
    return {"ok": True}


# ----------------------------------------------------------------- polling
def _find_device():
    j = _call("GET", "/me/player/devices")
    if j is None:
        return
    name = ctx.config["device_name"].lower()
    dev = next((d for d in j.get("devices", []) if d.get("name", "").lower() == name), None)
    with _lock:
        _state["device_online"] = dev is not None
        _state["device_id"] = dev["id"] if dev else None


def _poll_now():
    j = _call("GET", "/me/player/currently-playing", params={"additional_types": "track,episode"})
    now = None
    if j:
        item = j.get("item") or {}
        images = (item.get("album") or item.get("show") or {}).get("images") or []
        now = {"title": item.get("name"),
               "artist": ", ".join(a["name"] for a in item.get("artists", [])) or (item.get("show") or {}).get("publisher"),
               "album": (item.get("album") or item.get("show") or {}).get("name"),
               "art_url": images[0]["url"] if images else None,
               "progress_ms": j.get("progress_ms"), "duration_ms": item.get("duration_ms"),
               "playing": bool(j.get("is_playing")), "device": (j.get("device") or {}).get("name"),
               "shuffle": j.get("shuffle_state"), "volume": (j.get("device") or {}).get("volume_percent"),
               "uri": item.get("uri"), "context_uri": (j.get("context") or {}).get("uri"),
               "repeat": j.get("repeat_state"), "kind": item.get("type"), "id": item.get("id")}
        now["liked"] = _liked_flag(item.get("uri")) if item.get("type") == "track" else None
    with _lock:
        _web_now["now"] = now; _web_now["at"] = time.time()
    _merge_now()


def _parse_local_meta(p):
    """track_changed events carry the full item: cache it so the merge has a title and art without a Web API call."""
    tid = p.get("TRACK_ID")
    if not tid or not p.get("NAME"):
        return
    covers = [c for c in (p.get("COVERS") or "").split("\n") if c.strip()]
    artists = [a for a in (p.get("ARTISTS") or "").split("\n") if a.strip()]
    kind = "episode" if (p.get("ITEM_TYPE") or "").lower() == "episode" else "track"
    _track_meta[tid] = {"title": p.get("NAME"), "artist": ", ".join(artists) or p.get("SHOW_NAME") or "",
                        "album": p.get("ALBUM") or p.get("SHOW_NAME") or "", "art_url": covers[0] if covers else None,
                        "duration_ms": int(p.get("DURATION_MS") or 0) or None, "uri": p.get("URI") or f"spotify:{kind}:{tid}",
                        "kind": kind, "id": tid}


def _fetch_track_meta(tid):
    """Fill the cache from the Web API for a track we only know by id (playing/paused events)."""
    if tid in _track_meta:
        return
    j = _call("GET", f"/tracks/{tid}")
    if not j:
        return
    images = (j.get("album") or {}).get("images") or []
    _track_meta[tid] = {"title": j.get("name"), "artist": ", ".join(a["name"] for a in j.get("artists", [])),
                        "album": (j.get("album") or {}).get("name"), "art_url": images[0]["url"] if images else None,
                        "duration_ms": j.get("duration_ms"), "uri": j.get("uri"), "kind": "track", "id": tid}
    _merge_now()


def _local_event(p):
    """A librespot player event (env vars from the onevent hook). Updates the local truth and re-merges."""
    ev = (p.get("PLAYER_EVENT") or "").lower()
    now = time.time()
    tid = p.get("TRACK_ID") or None
    pos = p.get("POSITION_MS")
    with _lock:
        _local["at"] = now; _local["event"] = ev
        if ev == "track_changed":
            _parse_local_meta(p)
            _local["track_id"] = tid; _local["uri"] = p.get("URI") or _local["uri"]
            _local["duration_ms"] = int(p.get("DURATION_MS") or 0) or _local["duration_ms"]
        elif ev in ("playing", "paused", "seeked", "position_correction", "loading"):
            if tid:
                if tid != _local["track_id"]:
                    _local["track_id"] = tid; _local["uri"] = None; _local["duration_ms"] = None
            if pos is not None:
                try: _local["position_ms"] = int(pos)
                except ValueError: pass
                _local["pos_at"] = now
            if ev == "playing":
                _local["playing"] = True; _local["stopped"] = False
            elif ev == "paused":
                _local["playing"] = False; _local["stopped"] = False
            elif ev == "loading":
                _local["stopped"] = False
        elif ev in ("stopped", "end_of_track", "unavailable"):
            _local["playing"] = False
            if ev == "stopped":
                _local["stopped"] = True
        elif ev == "shuffle_changed":
            _local["shuffle"] = (p.get("SHUFFLE") or "").lower() == "true"
        elif ev == "repeat_changed":
            rep = (p.get("REPEAT") or "").lower() == "true"; rep_track = (p.get("REPEAT_TRACK") or "").lower() == "true"
            _local["repeat"] = "track" if rep_track else ("context" if rep else "off")
        elif ev == "session_disconnected":
            _local["playing"] = False; _local["stopped"] = True
    if tid and tid not in _track_meta and ev in ("playing", "paused", "loading", "seeked"):
        threading.Thread(target=_fetch_track_meta, args=(tid,), daemon=True).start()
    _merge_now()


def _local_progress():
    if _local["playing"]:
        return int(_local["position_ms"] + (time.time() - _local["pos_at"]) * 1000)
    return int(_local["position_ms"])


def _merge_now():
    """Compose _state['now'] from the local player and the Web API snapshot.
    The Web API wins only when music is playing somewhere other than this speaker."""
    with _lock:
        web = _web_now["now"]
        mine = ctx.config.get("device_name", "HomeDeck").lower() if ctx else "homedeck"
        web_elsewhere = bool(web and web.get("playing") and (web.get("device") or "").lower() not in ("", mine))
        loc_ok = bool(_local["track_id"]) and not _local["stopped"]
        if loc_ok and not web_elsewhere:
            tid = _local["track_id"]
            meta = _track_meta.get(tid)
            if not meta and web and web.get("id") == tid:
                meta = web
            if meta is None:
                meta = {"title": "Loading…", "artist": "", "album": "", "art_url": None, "duration_ms": _local["duration_ms"],
                        "uri": _local["uri"] or f"spotify:track:{tid}", "kind": "track", "id": tid}
            same_web = bool(web and web.get("id") == tid)
            now = {"title": meta.get("title"), "artist": meta.get("artist"), "album": meta.get("album"), "art_url": meta.get("art_url"),
                   "progress_ms": _local_progress(),
                   "duration_ms": _local["duration_ms"] or meta.get("duration_ms"),
                   "playing": bool(_local["playing"]), "device": ctx.config.get("device_name", "HomeDeck") if ctx else "HomeDeck",
                   "shuffle": _local["shuffle"] if _local["shuffle"] is not None else (web or {}).get("shuffle"),
                   "volume": (web or {}).get("volume"),
                   "uri": meta.get("uri") or _local["uri"], "context_uri": (web or {}).get("context_uri") if same_web else None,
                   "repeat": _local["repeat"] if _local["repeat"] is not None else (web or {}).get("repeat"),
                   "kind": meta.get("kind", "track"), "id": tid,
                   "liked": (web or {}).get("liked") if same_web else None, "source": "local"}
        elif web:
            now = dict(web); now["source"] = "web"
        else:
            now = None
        _state["now"] = now
    # the liked lookup may hit the Web API (and takes the lock itself), so it runs after the lock is released
    if now and now.get("source") == "local" and now.get("liked") is None and now.get("kind") == "track" and now.get("uri"):
        try:
            liked = _liked_flag(now["uri"])
        except Exception:
            liked = None
        with _lock:
            cur = _state.get("now")
            if cur and cur.get("id") == now.get("id"):
                cur["liked"] = liked



# ----------------------------------------------------------------- go-librespot (local Spotify Connect speaker)
# The speaker process on this device exposes a local HTTP API and an event websocket. Transport commands go there
# directly (no Web API "activation" needed after a restart), and its events are the source of truth for the current
# track, position and play state. The Web API stays for library, search, likes and for music playing elsewhere.
GL_BASE = "http://127.0.0.1:3678"
_gl = {"up": False, "at": 0.0, "device_id": None, "volume": None, "volume_steps": 100, "context_uri": None,
       "vol_pushed": None, "vol_from_gl": None, "ws_thread": None}


def _gl_call(method, path, body=None, timeout=4.0):
    """Local API call. Returns parsed JSON ({} for empty bodies) or None when the speaker is not reachable."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(GL_BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            _gl["up"] = True; _gl["at"] = time.time()
            if not raw.strip():
                return {}
            try:
                j = json.loads(raw)
            except ValueError:
                return {}
            return {} if j is None else j          # the API answers "null" for commands: success, no payload
    except urllib.error.HTTPError as e:
        _gl["up"] = True; _gl["at"] = time.time()
        try:
            msg = e.read().decode(errors="replace")[:200]
        except Exception:
            msg = str(e)
        if ctx: ctx.log(f"go-librespot {method} {path} -> HTTP {e.code} {msg}")
        return None
    except Exception:
        if _gl["up"] and ctx:
            ctx.log("go-librespot not reachable")
        _gl["up"] = False
        return None


def _gl_up():
    return _gl["up"] and time.time() - _gl["at"] < 30


def _gl_track_meta(t):
    if not t or not t.get("uri"):
        return None
    tid = t["uri"].split(":")[-1]
    kind = "episode" if ":episode:" in t["uri"] else "track"
    meta = {"title": t.get("name"), "artist": ", ".join(t.get("artist_names") or []), "album": t.get("album_name"),
            "art_url": t.get("album_cover_url"), "duration_ms": t.get("duration"), "uri": t["uri"], "kind": kind, "id": tid}
    _track_meta[tid] = meta
    return tid, meta


def _gl_apply_status(st):
    """Fold a /status document into the local truth."""
    now = time.time()
    with _lock:
        _gl["device_id"] = st.get("device_id") or _gl["device_id"]
        _gl["volume"] = st.get("volume"); _gl["volume_steps"] = st.get("volume_steps") or 100
        _gl["context_uri"] = st.get("context_uri")
        _local["at"] = now; _local["event"] = "status"
        t = st.get("track") or {}
        tm = _gl_track_meta(t)
        if tm:
            tid, meta = tm
            _local["track_id"] = tid; _local["uri"] = meta["uri"]; _local["duration_ms"] = meta.get("duration_ms")
            _local["position_ms"] = int(t.get("position") or 0); _local["pos_at"] = now
        else:
            _local["track_id"] = None; _local["uri"] = None
        _local["stopped"] = bool(st.get("stopped")) or not tm
        _local["playing"] = bool(tm) and not st.get("stopped") and not st.get("paused")
        _local["shuffle"] = bool(st.get("shuffle_context"))
        _local["repeat"] = "track" if st.get("repeat_track") else ("context" if st.get("repeat_context") else "off")
        _state["device_online"] = True
        if _gl["device_id"]:
            _state["device_id"] = _gl["device_id"]
    _merge_now()


def _gl_status():
    st = _gl_call("GET", "/status", timeout=2.0)
    if st is not None:
        _gl_apply_status(st)
    return st


def _gl_volume_to_pct(v):
    steps = max(1, int(_gl["volume_steps"] or 100))
    return int(round(100.0 * int(v) / steps))


def _gl_event(ev):
    """One websocket event from go-librespot."""
    typ = ev.get("type"); d = ev.get("data") or {}
    now = time.time()
    with _lock:
        _local["at"] = now; _local["event"] = typ
        if typ == "metadata":
            tm = _gl_track_meta(d)
            if tm:
                tid, meta = tm
                if tid != _local["track_id"]:
                    _local["position_ms"] = int(d.get("position") or 0); _local["pos_at"] = now
                _local["track_id"] = tid; _local["uri"] = meta["uri"]; _local["duration_ms"] = meta.get("duration_ms")
                _local["stopped"] = False
        elif typ in ("will_play", "playing", "paused", "not_playing"):
            uri = d.get("uri")
            if uri:
                tid = uri.split(":")[-1]
                if tid != _local["track_id"]:
                    _local["track_id"] = tid; _local["uri"] = uri; _local["duration_ms"] = None
                    _local["position_ms"] = 0; _local["pos_at"] = now
            _gl["context_uri"] = d.get("context_uri") or _gl["context_uri"]
            if typ == "playing":
                _local["playing"] = True; _local["stopped"] = False
                _local["position_ms"] = _local_progress() if _local["playing"] else _local["position_ms"]; _local["pos_at"] = now
            elif typ == "paused":
                _local["position_ms"] = _local_progress(); _local["pos_at"] = now
                _local["playing"] = False; _local["stopped"] = False
            elif typ == "not_playing":
                _local["playing"] = False
            else:
                _local["stopped"] = False
        elif typ == "seek":
            _local["position_ms"] = int(d.get("position") or 0); _local["pos_at"] = now
        elif typ == "stopped":
            _local["playing"] = False; _local["stopped"] = True
        elif typ == "inactive":
            _local["playing"] = False; _local["stopped"] = True
        elif typ == "shuffle_context":
            _local["shuffle"] = bool(d.get("value"))
        elif typ == "repeat_context":
            _local["repeat"] = "context" if d.get("value") else ("track" if _local["repeat"] == "track" else "off")
        elif typ == "repeat_track":
            _local["repeat"] = "track" if d.get("value") else ("context" if _local["repeat"] == "context" else "off")
        elif typ == "volume":
            _gl["volume"] = d.get("value"); _gl["volume_steps"] = d.get("max") or _gl["volume_steps"]
    if typ == "volume" and d.get("value") is not None:
        pct = _gl_volume_to_pct(d["value"])
        _gl["vol_from_gl"] = pct
        au = ctx.module("audio") if ctx else None
        try:
            cur = au.music_volume() if au and hasattr(au, "music_volume") else None
            if au and (cur is None or abs(int(cur) - pct) > 2):
                au.set_volume(pct, "music")                      # the phone's Spotify volume is the music volume
        except Exception as e:
            ctx.log(f"volume sync from speaker failed: {e}")
    if typ in ("playing", "paused", "stopped", "metadata", "will_play", "inactive", "active", "playback_ready"):
        _merge_now()
        if typ in ("active", "playback_ready", "will_play"):
            threading.Thread(target=_gl_status, daemon=True).start()


def _gl_ws_loop():
    """Keep an event websocket to go-librespot open; resync from /status on every (re)connect."""
    import socket
    backoff = 2
    while True:
        try:
            ws = _WS("ws://127.0.0.1:3678/events", "http://127.0.0.1:3678", timeout=5)
            ws.sock.settimeout(45)
            backoff = 2
            _gl["up"] = True; _gl["at"] = time.time()
            _gl_status()
            if ctx: ctx.log("go-librespot events connected")
            while True:
                try:
                    msg = ws.recv()
                except socket.timeout:
                    _gl_status()                      # idle: cheap resync keeps the state honest
                    continue
                _gl["at"] = time.time()
                try:
                    ev = json.loads(msg)
                except ValueError:
                    continue
                if isinstance(ev, dict):
                    try:
                        _gl_event(ev)
                    except Exception as e:
                        ctx.log(f"go-librespot event {ev.get('type')} failed: {e}")
        except Exception as e:
            if ctx:
                ctx.log(f"go-librespot events disconnected: {e!r}")
            _gl["up"] = False
            with _lock:
                _local["playing"] = False
            _merge_now()
        time.sleep(backoff)
        backoff = min(30, backoff * 2)


def _gl_push_volume():
    """HomeDeck volume changed (knob, voice, phone app): tell the speaker so Spotify clients show the same level."""
    au = ctx.module("audio") if ctx else None
    if not au or not hasattr(au, "volume") or not _gl_up():
        return
    try:
        pct = au.music_volume() if hasattr(au, "music_volume") else au.volume()   # Spotify mirrors the music volume
    except Exception:
        return
    if pct is None:
        return
    pct = int(pct)
    if _gl["vol_pushed"] is not None and abs(_gl["vol_pushed"] - pct) <= 2:
        return
    if _gl["vol_from_gl"] is not None and abs(_gl["vol_from_gl"] - pct) <= 2:
        _gl["vol_pushed"] = pct
        return
    steps = max(1, int(_gl["volume_steps"] or 100))
    if _gl_call("POST", "/player/volume", {"volume": int(round(pct * steps / 100.0))}) is not None:
        _gl["vol_pushed"] = pct


def _music_elsewhere():
    """True when the Web API says music is playing on another device (then transport goes through the Web API)."""
    web = _web_now["now"]
    mine = ctx.config.get("device_name", "HomeDeck").lower() if ctx else "homedeck"
    return bool(web and web.get("playing") and (web.get("device") or "").lower() not in ("", mine))


def _use_local():
    return _gl_up() and not _music_elsewhere()


def _gl_play(uri, skip_to=None, position_ms=None, paused=False):
    body = {"uri": uri}
    if skip_to: body["skip_to_uri"] = skip_to
    if position_ms: body["position"] = int(position_ms)
    if paused: body["paused"] = True
    r = None
    for attempt in range(4):                      # right after the speaker (re)starts it answers 409 while it settles
        r = _gl_call("POST", "/player/play", body)
        if r is not None or not _gl["up"]:
            break
        time.sleep(1.5)
    if r is not None:
        threading.Thread(target=_gl_status, daemon=True).start()
    return r is not None


def _refresh_playlists():
    global _playlists_at
    j = _call("GET", "/me/playlists", params={"limit": 30})
    if j is None:
        return
    pls = [{"name": p["name"], "uri": p["uri"], "art_url": (p.get("images") or [{}])[0].get("url"),
            "tracks": (p.get("tracks") or {}).get("total")} for p in j.get("items", []) if p]
    with _lock:
        _state["playlists"] = pls
    _playlists_at = time.time()
    try:                                                     # cached so a restart during a rate-limit block still shows them
        ctx.config["playlists_cache"] = pls; ctx.save_config()
    except Exception:
        pass


def start(c):
    global ctx
    ctx = c
    n = 0
    cached = ctx.config.get("playlists_cache") or []
    if cached:
        with _lock:
            _state["playlists"] = list(cached)
    while True:
        cfg = ctx.config
        with _lock:
            _state["configured"] = bool(cfg["client_id"])
            _state["authenticated"] = bool(cfg["tokens"].get("refresh"))
        if _gl["ws_thread"] is None:
            _gl["ws_thread"] = threading.Thread(target=_gl_ws_loop, name="spotify-local", daemon=True); _gl["ws_thread"].start()
        try:
            if _gl_status() is not None:       # cheap local call; also refreshes the liveness stamp
                _gl_push_volume()
        except Exception as e:
            ctx.log(f"local player poll error: {e}")
        if _state["authenticated"] and _token_valid() or (_state["authenticated"] and _refresh()):
            # The Web API is rate limited per app (a 429 with a Retry-After of an hour or more has happened), and the
            # local player already tells us what is playing here. So the Web API is only asked every 30 s while the
            # local player is up (to notice music on another device), every 10 s when it is not, the device list
            # every 5 minutes, and playlists every 10 minutes.
            every = 30 if _gl_up() else 10
            try:
                if n % max(1, every // max(1, cfg.get("poll_seconds", 3))) == 0:
                    _poll_now()
                if n % max(1, 300 // max(1, cfg.get("poll_seconds", 3))) == 0:
                    _find_device()
                if time.time() - _playlists_at > 600:
                    _refresh_playlists()
            except Exception as e:
                ctx.log(f"poll error: {e}")
        n += 1
        time.sleep(max(1, cfg.get("poll_seconds", 3)))


def state():
    with _lock:
        out = dict(_state)
        now = out.get("now")
        lim = [t for t in _backoff.values() if t > time.time()]
        out["rate_limited_until"] = max(lim) if lim else None
        out["rate_limited"] = sorted(f for f, t in _backoff.items() if t > time.time())
        if now:
            now = dict(now)
            t = time.time()
            if now.get("source") == "local":
                now["progress_ms"] = _local_progress()
            elif now.get("playing") and _web_now["at"]:
                now["progress_ms"] = int((now.get("progress_ms") or 0) + (t - _web_now["at"]) * 1000)
            if now.get("duration_ms"):
                now["progress_ms"] = max(0, min(int(now["duration_ms"]), int(now.get("progress_ms") or 0)))
            now["fetched_at"] = t
            out["now"] = now
        return out


# ----------------------------------------------------------------- control
def _ensure_device():
    """Transfer playback to the HomeDeck device if it exists and is not the active one."""
    _find_device()
    dev = _state["device_id"]
    if not dev:
        _set_error("HomeDeck speaker not found on Spotify. Check raspotify and Premium.")
        return None
    now = _state["now"]
    if not now or (now.get("device") or "").lower() != ctx.config["device_name"].lower():
        _call("PUT", "/me/player", body={"device_ids": [dev], "play": False})
        time.sleep(0.5)
    return dev


_URI_RE = None
def _uri_ok(u):
    global _URI_RE
    import re
    if _URI_RE is None:
        _URI_RE = re.compile(r"^spotify:(track|album|playlist|artist|show|episode):[A-Za-z0-9]{8,64}$")
    return u is None or (isinstance(u, str) and bool(_URI_RE.match(u)))


def play_uri(uri=None, context_uri=None):
    """Start playback on the HomeDeck. uri = a track, context_uri = playlist/album/artist."""
    if not _uri_ok(uri) or not _uri_ok(context_uri):
        _set_error("invalid Spotify URI")
        return False
    if _gl_up():
        if context_uri:
            return _gl_play(context_uri, skip_to=uri if uri and uri.startswith("spotify:track:") else None)
        if uri:
            return _gl_play(uri)
        return _gl_call("POST", "/player/resume") is not None
    dev = _ensure_device()
    if not dev:
        return False
    body = {}
    if context_uri or (uri and not uri.startswith("spotify:track:")):
        body["context_uri"] = context_uri or uri
    elif uri:
        body["uris"] = [uri]
    r = _call("PUT", "/me/player/play", body=body or None, params={"device_id": dev})
    return r is not None


def queue_uri(uri):
    """Add a track to the playback queue on the HomeDeck device."""
    if not uri or not _uri_ok(uri) or not uri.startswith("spotify:track:"):
        _set_error("only tracks can be queued")
        return False
    if _use_local():
        return _gl_call("POST", "/player/add_to_queue", {"uri": uri}) is not None
    dev = _ensure_device()
    if not dev:
        return False
    return _call("POST", "/me/player/queue", params={"uri": uri, "device_id": dev}) is not None


def pause():
    if _use_local():
        return _gl_call("POST", "/player/pause") is not None
    return _call("PUT", "/me/player/pause") is not None


def resume():
    if _use_local():
        r = _gl_call("POST", "/player/resume")
        if r is not None:
            return True
    return _call("PUT", "/me/player/play") is not None


def next_track():
    if _use_local():
        return _gl_call("POST", "/player/next") is not None
    return _call("POST", "/me/player/next") is not None


def prev_track():
    if _use_local():
        return _gl_call("POST", "/player/prev") is not None
    return _call("POST", "/me/player/previous") is not None


def seek_ms(ms):
    if _use_local():
        return _gl_call("POST", "/player/seek", {"position": int(ms)}) is not None
    return _call("PUT", "/me/player/seek", params={"position_ms": int(ms)}) is not None


def set_shuffle(on):
    if _use_local():
        return _gl_call("POST", "/player/shuffle_context", {"shuffle_context": bool(on)}) is not None
    return _call("PUT", "/me/player/shuffle", params={"state": "true" if on else "false"}) is not None


def is_playing():
    now = _state.get("now")
    return bool(now and now.get("playing"))


# ----------------------------------------------------------------- recent / search
_recent = {"at": 0, "items": []}

def _item_row(item, kind=None):
    """Normalise a track/album/playlist object into a small dict for the UI."""
    if not item:
        return None
    kind = kind or item.get("type")
    images = (item.get("album") or item).get("images") or []
    artist = ", ".join(a["name"] for a in item.get("artists", [])) if item.get("artists") else (item.get("owner") or {}).get("display_name")
    return {"type": kind, "name": item.get("name"), "artist": artist, "uri": item.get("uri"),
            "art_url": images[-1]["url"] if images else None}


def recent(force=False):
    if not force and time.time() - _recent["at"] < 300:
        return _recent["items"]
    j = _call("GET", "/me/player/recently-played", params={"limit": 12})
    if j is None:
        return _recent["items"]
    seen, out = set(), []
    for it in j.get("items", []):
        row = _item_row(it.get("track"), "track")
        if row and row["uri"] not in seen:
            seen.add(row["uri"]); out.append(row)
    _recent.update({"at": time.time(), "items": out})
    return out


def search(q, types="track,album,playlist", limit=8):
    q = (q or "").strip()[:120]
    if not q:
        return []
    j = _call("GET", "/search", params={"q": q, "type": types, "limit": limit})
    if not j:
        return []
    out = []
    for kind in ("track", "playlist", "album"):
        for it in (j.get(kind + "s") or {}).get("items") or []:
            row = _item_row(it, kind)
            if row: out.append(row)
    return out


# ----------------------------------------------------------------- library, drill-down, player extras
_cache = {}                     # key -> (at, value); library lists are cached for a few minutes
_liked_cache = {}               # track uri -> (at, bool)


def _cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    v = fn()
    if v is not None:
        _cache[key] = (time.time(), v)
    return v


def _drop_cache(prefix):
    for k in [k for k in _cache if k.startswith(prefix)]:
        _cache.pop(k, None)


def _sid(uri):
    return (uri or "").split(":")[-1]


def _me():
    if _state.get("user_id"):
        return _state["user_id"]
    j = _call("GET", "/me")
    if j and j.get("id"):
        with _lock:
            _state["user_id"] = j["id"]
    return _state.get("user_id")


_liked_set = {"at": 0, "uris": set()}


def _liked_uris():
    """The newest 200 liked tracks as a set (the /me/tracks/contains endpoint is refused for this app)."""
    if time.time() - _liked_set["at"] < 180:
        return _liked_set["uris"]
    uris = set()
    for off in (0, 50, 100, 150):
        page = liked_tracks(off, 50)
        if not page:
            return _liked_set["uris"]
        uris.update(t["uri"] for t in page["items"])
        if not page.get("next"):
            break
    _liked_set.update({"at": time.time(), "uris": uris})
    return uris


def _liked_flag(uri):
    if not uri:
        return None
    hit = _liked_cache.get(uri)
    if hit and time.time() - hit[0] < 180:
        return hit[1]
    return uri in _liked_uris()


def liked_contains(uris):
    """Which of these track uris are saved. Returns {uri: bool}."""
    liked = _liked_uris()
    out = {}
    for u in uris:
        hit = _liked_cache.get(u)
        out[u] = hit[1] if hit and time.time() - hit[0] < 180 else (u in liked)
    return out


def _track_row(t, extra=None):
    """Full track row for lists: art, artists, album, duration, uri, explicit."""
    if not t or not t.get("uri"):
        return None
    album = t.get("album") or {}
    images = album.get("images") or (t.get("show") or {}).get("images") or []
    row = {"type": t.get("type", "track"), "name": t.get("name"), "uri": t.get("uri"), "id": t.get("id"),
           "artist": ", ".join(a["name"] for a in t.get("artists", [])) or (t.get("show") or {}).get("publisher"),
           "artist_uri": (t.get("artists") or [{}])[0].get("uri"),
           "album": album.get("name") or (t.get("show") or {}).get("name"), "album_uri": album.get("uri") or (t.get("show") or {}).get("uri"),
           "art_url": images[-1]["url"] if images else None, "duration_ms": t.get("duration_ms"), "explicit": bool(t.get("explicit")),
           "is_local": bool(t.get("is_local"))}
    if t.get("type") == "episode":
        row["resume_ms"] = (t.get("resume_point") or {}).get("resume_position_ms")
        row["release_date"] = t.get("release_date")
    if extra:
        row.update(extra)
    return row


def _paged(path, params, limit, offset, key="items"):
    j = _call("GET", path, params={**(params or {}), "limit": limit, "offset": offset})
    if j is None:
        return None
    return {"items": j.get(key) or [], "total": j.get("total"), "next": bool(j.get("next"))}


def liked_tracks(offset=0, limit=50):
    def fn():
        r = _paged("/me/tracks", {}, limit, offset)
        if r is None: return None
        rows = [_track_row(it.get("track")) for it in r["items"]]
        return {"items": [x for x in rows if x], "total": r["total"], "next": r["next"]}
    return _cached(f"liked:{offset}:{limit}", 180, fn)


def saved_albums(offset=0, limit=50):
    def fn():
        r = _paged("/me/albums", {}, limit, offset)
        if r is None: return None
        rows = [_item_row(it.get("album"), "album") for it in r["items"]]
        for row, it in zip(rows, r["items"]):
            if row: row["total_tracks"] = (it.get("album") or {}).get("total_tracks")
        return {"items": [x for x in rows if x], "total": r["total"], "next": r["next"]}
    return _cached(f"albums:{offset}:{limit}", 180, fn)


def followed_artists(after=None, limit=50):
    def fn():
        params = {"type": "artist", "limit": limit}
        if after: params["after"] = after
        j = _call("GET", "/me/following", params=params)
        if j is None: return None
        a = j.get("artists") or {}
        rows = [_item_row(x, "artist") for x in a.get("items") or []]
        return {"items": [x for x in rows if x], "total": a.get("total"), "next": bool((a.get("cursors") or {}).get("after")),
                "after": (a.get("cursors") or {}).get("after")}
    return _cached(f"artists:{after}:{limit}", 180, fn)


def saved_shows(offset=0, limit=50):
    def fn():
        r = _paged("/me/shows", {}, limit, offset)
        if r is None: return None
        rows = []
        for it in r["items"]:
            sh = it.get("show") or {}
            row = _item_row(sh, "show")
            if row: row["artist"] = sh.get("publisher"); rows.append(row)
        return {"items": rows, "total": r["total"], "next": r["next"]}
    return _cached(f"shows:{offset}:{limit}", 180, fn)


def all_playlists(offset=0, limit=50):
    def fn():
        r = _paged("/me/playlists", {}, limit, offset)
        if r is None: return None
        me = _me()
        rows = []
        for p in r["items"]:
            if not p: continue
            rows.append({"type": "playlist", "name": p["name"], "uri": p["uri"], "id": p.get("id"), "art_url": (p.get("images") or [{}])[0].get("url"),
                         "tracks": (p.get("tracks") or {}).get("total"), "owner": (p.get("owner") or {}).get("display_name"),
                         "editable": bool(me and ((p.get("owner") or {}).get("id") == me or p.get("collaborative")))})
        return {"items": rows, "total": r["total"], "next": r["next"]}
    return _cached(f"playlists:{offset}:{limit}", 180, fn)


def playlist_detail(uri, offset=0, limit=50):
    pid = _sid(uri)
    def fn():
        head = _cached(f"plhead:{pid}", 300, lambda: _call("GET", f"/playlists/{pid}", params={"fields": "name,uri,images,owner(display_name,id),collaborative,tracks(total),description"}))
        r = _paged(f"/playlists/{pid}/items", {"additional_types": "track,episode"}, limit, offset)
        if r is None: return None
        rows = [_track_row(it.get("item") or it.get("track")) for it in r["items"] if it]
        me = _me()
        info = {"name": (head or {}).get("name"), "uri": uri, "art_url": ((head or {}).get("images") or [{}])[0].get("url"),
                "owner": ((head or {}).get("owner") or {}).get("display_name"), "total": (head or {}).get("tracks", {}).get("total") or r["total"],
                "description": (head or {}).get("description") or "",
                "editable": bool(me and (((head or {}).get("owner") or {}).get("id") == me or (head or {}).get("collaborative")))}
        return {"info": info, "items": [x for x in rows if x], "total": r["total"], "next": r["next"], "offset": offset}
    return _cached(f"pl:{pid}:{offset}:{limit}", 120, fn)


def album_detail(uri):
    aid = _sid(uri)
    def fn():
        j = _call("GET", f"/albums/{aid}", params={})
        if j is None: return None
        images = j.get("images") or []
        info = {"name": j.get("name"), "uri": j.get("uri"), "art_url": images[0]["url"] if images else None,
                "artist": ", ".join(a["name"] for a in j.get("artists", [])), "artist_uri": (j.get("artists") or [{}])[0].get("uri"),
                "year": (j.get("release_date") or "")[:4], "total": j.get("total_tracks")}
        rows = []
        for t in (j.get("tracks") or {}).get("items") or []:
            row = _track_row({**t, "album": {"name": j.get("name"), "uri": j.get("uri"), "images": images}})
            if row: rows.append(row)
        return {"info": info, "items": rows, "total": len(rows), "next": False}
    return _cached(f"album:{aid}", 600, fn)


def artist_detail(uri):
    aid = _sid(uri)
    def fn():
        a = _call("GET", f"/artists/{aid}")
        albums = _call("GET", f"/artists/{aid}/albums", params={"include_groups": "album,single", "limit": 10})
        if a is None: return None
        top = _call("GET", "/search", params={"q": f"artist:\"{a.get('name', '')}\"", "type": "track", "limit": 10})
        top = {"tracks": [t for t in ((top or {}).get("tracks") or {}).get("items") or [] if any(x.get("id") == aid for x in t.get("artists", []))]}
        images = a.get("images") or []
        info = {"name": a.get("name"), "uri": a.get("uri"), "art_url": images[0]["url"] if images else None,
                "followers": (a.get("followers") or {}).get("total"), "genres": a.get("genres") or []}
        rows = [_track_row(t) for t in (top or {}).get("tracks") or []]
        seen, albs = set(), []
        for al in (albums or {}).get("items") or []:
            key = (al.get("name") or "").lower()
            if key in seen: continue
            seen.add(key)
            row = _item_row(al, "album")
            if row: row["year"] = (al.get("release_date") or "")[:4]; row["group"] = al.get("album_group") or al.get("album_type"); albs.append(row)
        return {"info": info, "items": [x for x in rows if x], "albums": albs, "total": len(rows), "next": False}
    return _cached(f"artist:{aid}", 600, fn)


def show_detail(uri, offset=0, limit=30):
    sid = _sid(uri)
    def fn():
        head = _cached(f"showhead:{sid}", 600, lambda: _call("GET", f"/shows/{sid}", params={}))
        r = _paged(f"/shows/{sid}/episodes", {}, limit, offset)
        if r is None: return None
        images = (head or {}).get("images") or []
        info = {"name": (head or {}).get("name"), "uri": uri, "art_url": images[0]["url"] if images else None,
                "artist": (head or {}).get("publisher"), "total": (head or {}).get("total_episodes")}
        rows = []
        for ep in r["items"]:
            if not ep: continue
            row = _track_row({**ep, "type": "episode", "show": head or {}})
            if row: rows.append(row)
        return {"info": info, "items": rows, "total": r["total"], "next": r["next"], "offset": offset}
    return _cached(f"show:{sid}:{offset}", 300, fn)


def search_full(q, types="track,artist,album,playlist,show", limit=6):
    q = (q or "").strip()[:120]
    if not q:
        return {}
    j = _call("GET", "/search", params={"q": q, "type": types, "limit": limit})
    if not j:
        return {}
    out = {}
    for kind in ("track", "artist", "album", "playlist", "show"):
        rows = []
        for it in (j.get(kind + "s") or {}).get("items") or []:
            row = _track_row(it) if kind == "track" else _item_row(it, kind)
            if row:
                if kind == "show": row["artist"] = it.get("publisher")
                if kind == "album": row["year"] = (it.get("release_date") or "")[:4]
                rows.append(row)
        if rows:
            out[kind + "s"] = rows
    return out


def queue_list():
    j = _call("GET", "/me/player/queue")
    if j is None:
        return None
    cur = _track_row(j.get("currently_playing")) if j.get("currently_playing") else None
    rows = [_track_row(t) for t in j.get("queue") or []]
    return {"current": cur, "items": [x for x in rows if x][:30]}


def devices():
    j = _call("GET", "/me/player/devices")
    if j is None:
        return None
    mine = ctx.config["device_name"].lower()
    return [{"id": d.get("id"), "name": d.get("name"), "type": d.get("type"), "active": bool(d.get("is_active")),
             "volume": d.get("volume_percent"), "homedeck": (d.get("name") or "").lower() == mine} for d in j.get("devices", [])]


def transfer(device_id, play=True):
    if not device_id:
        return False
    if _gl_up() and device_id == _gl["device_id"] and _local["track_id"] and not _music_elsewhere():
        return resume() if play else True         # already ours: just make sure it plays
    return _call("PUT", "/me/player", body={"device_ids": [device_id], "play": bool(play)}) is not None


def set_like(uri, on=True):
    if not uri or not uri.startswith("spotify:track:"):
        return False
    r = _call("PUT" if on else "DELETE", "/me/tracks", params={"ids": _sid(uri)})
    if r is None:
        return False
    _liked_cache[uri] = (time.time(), bool(on))
    (_liked_set["uris"].add if on else _liked_set["uris"].discard)(uri)
    _drop_cache("liked:")
    with _lock:
        if _state["now"] and _state["now"].get("uri") == uri:
            _state["now"]["liked"] = bool(on)
    return True


def set_repeat(mode):
    if mode not in ("off", "context", "track"):
        return False
    if _use_local():
        ok = _gl_call("POST", "/player/repeat_context", {"repeat_context": mode == "context"}) is not None
        ok = _gl_call("POST", "/player/repeat_track", {"repeat_track": mode == "track"}) is not None and ok
        if ok:
            with _lock:
                _local["repeat"] = mode
                if _state["now"]: _state["now"]["repeat"] = mode
        return ok
    r = _call("PUT", "/me/player/repeat", params={"state": mode})
    if r is not None:
        with _lock:
            if _state["now"]: _state["now"]["repeat"] = mode
    return r is not None


def add_to_playlist(playlist_uri, uri):
    if not uri or not playlist_uri or not playlist_uri.startswith("spotify:playlist:"):
        return False
    r = _call("POST", f"/playlists/{_sid(playlist_uri)}/tracks", body={"uris": [uri]})
    if r is None:
        return False
    _drop_cache(f"pl:{_sid(playlist_uri)}"); _drop_cache("playlists:")
    return True


def remove_from_playlist(playlist_uri, uri):
    if not uri or not playlist_uri:
        return False
    r = _call("DELETE", f"/playlists/{_sid(playlist_uri)}/tracks", body={"tracks": [{"uri": uri}]})
    if r is None:
        return False
    _drop_cache(f"pl:{_sid(playlist_uri)}"); _drop_cache("playlists:")
    return True


def play_in_context(context_uri, uri=None, position=None, position_ms=None):
    """Play a track inside a playlist/album/show so next/previous follow that list. Liked Songs has no context uri
    on the API, so the caller passes context_uri=None with a list of uris instead (see play_uris)."""
    if not _uri_ok(context_uri) or not _uri_ok(uri):
        _set_error("invalid Spotify URI"); return False
    if _gl_up() and (uri or position is None):
        return _gl_play(context_uri, skip_to=uri, position_ms=position_ms)
    dev = _ensure_device()
    if not dev:
        return False
    body = {"context_uri": context_uri}
    if uri:
        body["offset"] = {"uri": uri}
    elif position is not None:
        body["offset"] = {"position": int(position)}
    if position_ms:
        body["position_ms"] = int(position_ms)
    return _call("PUT", "/me/player/play", body=body, params={"device_id": dev}) is not None


def play_uris(uris, start=0):
    uris = [u for u in uris if _uri_ok(u) and u and u.startswith("spotify:track:")]
    if not uris:
        return False
    uris = uris[start:start + 200] + uris[:start] if start else uris[:200]
    if _gl_up():
        # the local player takes one uri: play the first, queue the next few
        if not _gl_play(uris[0]):
            return False
        for u in uris[1:40]:
            _gl_call("POST", "/player/add_to_queue", {"uri": u}, timeout=2)
        return True
    dev = _ensure_device()
    if not dev:
        return False
    return _call("PUT", "/me/player/play", body={"uris": uris}, params={"device_id": dev}) is not None


def play_liked(start_uri=None):
    """Liked Songs: collect up to 200 saved tracks and play them as a uri list (newest first)."""
    uris = []
    for off in (0, 50, 100, 150):
        page = liked_tracks(off, 50)
        if not page: break
        uris += [t["uri"] for t in page["items"]]
        if not page.get("next"): break
    if not uris:
        return False
    uid = _state.get("user_id") or _me()
    if isinstance(uid, dict):
        uid = uid.get("id")
    if _gl_up() and uid:
        # Liked Songs is a real context for the speaker: next/previous then walk the whole collection
        return _gl_play(f"spotify:user:{uid}:collection", skip_to=start_uri if start_uri in uris else None)
    start = uris.index(start_uri) if start_uri in uris else 0
    return play_uris(uris, start)


# ----------------------------------------------------------------- voice intents
import re as _re
_INTENTS = [
    ("whats_playing", _re.compile(r"\b(what'?s|what is|which song is) (playing|this|on)\b", _re.I)),
    ("pause", _re.compile(r"^(pause|stop)( the)?( music| song| playback| spotify)?$", _re.I)),
    ("resume", _re.compile(r"^(resume|continue|unpause|play)( the)?( music| song| playback)?$", _re.I)),
    ("next", _re.compile(r"^(next|skip)( this)?( song| track)?$", _re.I)),
    ("prev", _re.compile(r"^(previous|last|go back)( song| track)?$", _re.I)),
    ("shuffle_on", _re.compile(r"\bshuffle (on|mode)\b|\bturn on shuffle\b", _re.I)),
    ("shuffle_off", _re.compile(r"\bshuffle off\b|\bturn off shuffle\b", _re.I)),
    ("add_playlist", _re.compile(r"^(?:add|put|save) (?:this|the current|that)?\s*(?:song|track)?\s*(?:to|in|into|on) (?:my |the )?(.+?)(?: playlist)?(?: on spotify)?$", _re.I)),
    ("queue", _re.compile(r"^(?:queue(?: up)?|add)\s+(.+?)(?:\s+to (?:the |my )?queue)?$|^play\s+(.+?)\s+next$", _re.I)),
    ("like", _re.compile(r"^(?:like|save|heart|favou?rite)( this| the)?( song| track)?$|^add (this|the current)? ?(song|track)? ?to (my )?(liked|favou?rites|library)", _re.I)),
    ("unlike", _re.compile(r"^(?:unlike|unsave|remove|dislike)( this| the)?( song| track)?( from (my )?(liked|library|favou?rites))?$", _re.I)),
    ("liked_songs", _re.compile(r"^play (?:my )?(?:liked|saved|favou?rite) (?:songs|tracks|music)$", _re.I)),
    ("repeat", _re.compile(r"\b(?:turn on repeat|repeat (?:on|this|the song|the track|the playlist|the album|one|all)|loop (?:this|the song|the track|this playlist|the playlist|it))\b", _re.I)),
    ("repeat_off", _re.compile(r"\b(?:turn off repeat|repeat off|stop repeating|stop looping)\b", _re.I)),
    ("play_album", _re.compile(r"^play (?:the )?album (.+)$", _re.I)),
    ("play_artist", _re.compile(r"^play (?:some |something by |songs by |music by |the artist )(.+)$", _re.I)),
    ("play_playlist", _re.compile(r"^play (?:my |the )?(?:playlist )?(.+?)(?: playlist)?$", _re.I)),
]


def _now_text():
    now = _state.get("now")
    if not now or not now.get("title"):
        return "Nothing is playing right now."
    return f"Now playing {now['title']} by {now.get('artist') or 'an unknown artist'}."


def intent(text):
    if _re.search(r"\byou ?tube\b", (text or ""), _re.I):
        return None
    """Voice commands for music. Returns a spoken reply or None if the text is not about music."""
    t = (text or "").strip().rstrip(".!?").strip()
    low = t.lower()
    if not any(w in low for w in ("play", "pause", "stop", "resume", "next", "skip", "previous", "shuffle", "song", "music", "spotify", "track", "queue",
                                  "repeat", "loop", "like", "unlike", "save", "heart", "favourite", "favorite", "liked", "playlist", "album", "put this")):
        return None
    if not _state.get("authenticated") or not ctx.config.get("client_id"):
        return "Spotify isn't connected yet. Open the Music app to connect."
    for name, rx in _INTENTS:
        m = rx.search(t)
        if not m:
            continue
        if name == "whats_playing":
            return _now_text()
        if name == "pause":
            return "" if pause() else "I couldn't pause Spotify."
        if name == "resume":
            return "" if play_uri() else (_state.get("error") or "I couldn't resume playback.")
        if name == "next":
            return "" if next_track() else "I couldn't skip."
        if name == "prev":
            return "" if prev_track() else "I couldn't go back."
        if name == "shuffle_on":
            return "Shuffle on." if set_shuffle(True) else "Couldn't change shuffle."
        if name == "shuffle_off":
            return "Shuffle off." if set_shuffle(False) else "Couldn't change shuffle."
        if name in ("like", "unlike"):
            now = _state.get("now")
            if not now or not now.get("uri") or now.get("kind") != "track":
                return "Nothing is playing to save."
            ok = set_like(now["uri"], name == "like")
            if not ok and _state.get("needs_reauth"):
                return "Reconnect Spotify in the Spotify app first, then I can save songs."
            return (f"Saved {now['title']} to your Liked Songs." if name == "like" else f"Removed {now['title']} from your Liked Songs.") if ok else "I couldn't change that."
        if name == "add_playlist":
            want = (m.group(1) or "").strip().lower()
            if not want or _re.search(r"\b(shopping|to-?do|grocery|queue|liked|library|favou?rites)\b", want):
                continue                       # lists module / other intents
            now = _state.get("now")
            if not now or not now.get("uri"):
                return "Nothing is playing to add."
            pls = (all_playlists(0, 50) or {}).get("items") or []
            editable = [p for p in pls if p.get("editable")]
            hit = next((p for p in editable if p["name"].lower() == want), None) or next((p for p in editable if want in p["name"].lower()), None) \
                or next((p for p in editable if all(w in p["name"].lower() for w in want.split())), None)
            if not hit:
                return f"I couldn't find a playlist of yours called {want}."
            if add_to_playlist(hit["uri"], now["uri"]):
                return f"Added to {hit['name']}."
            return "Reconnect Spotify in the Spotify app first, then I can edit playlists." if _state.get("needs_reauth") else "I couldn't add it."
        if name == "liked_songs":
            return "" if play_liked() else (_state.get("error") or "I couldn't play your liked songs.")
        if name == "repeat":
            mode = "track" if _re.search(r"\b(this|the song|the track|one|it)\b", low) else "context"
            return ("Repeating this song." if mode == "track" else "Repeat on.") if set_repeat(mode) else "Couldn't change repeat."
        if name == "repeat_off":
            return "Repeat off." if set_repeat("off") else "Couldn't change repeat."
        if name == "play_album":
            want = m.group(1).strip()
            res = (search_full(want, "album", 3) or {}).get("albums") or []
            if not res:
                return f"I couldn't find an album called {want}."
            return f"Playing {res[0]['name']}" + (f" by {res[0]['artist']}." if res[0].get("artist") else ".") if play_uri(context_uri=res[0]["uri"]) else (_state.get("error") or "I couldn't start that album.")
        if name == "play_artist":
            want = m.group(1).strip()
            res = (search_full(want, "artist", 3) or {}).get("artists") or []
            if not res:
                continue                       # fall through to the generic play
            return f"Playing {res[0]['name']}." if play_uri(context_uri=res[0]["uri"]) else (_state.get("error") or "I couldn't play that artist.")
        if name == "queue":
            want = (m.group(1) or m.group(2) or "").strip()
            if not want or _re.search(r"\bto (my |the )?(shopping|to-?do)?\s*list\b", low):
                continue                       # "add X to my list" belongs to the lists module
            res = search(want, "track", 3)
            pick = next((r for r in res if r["type"] == "track"), None)
            if not pick:
                return f"I couldn't find {want} on Spotify."
            if not queue_uri(pick["uri"]):
                return _state.get("error") or "I couldn't add that to the queue."
            return f"Queued {pick['name']}" + (f" by {pick['artist']}." if pick.get("artist") else ".")
        if name == "play_playlist":
            want = m.group(1).strip()
            if not want or want.lower() in ("music", "something", "some music", "spotify"):
                return "Playing." if play_uri() else (_state.get("error") or "I couldn't start playback.")
            asked_playlist = bool(_re.search(r"\bmy\b|\bplaylist\b", low))
            if not _state["playlists"]:
                _refresh_playlists()
            pls = _state["playlists"]
            wl = want.lower()
            hit = next((p for p in pls if p["name"].lower() == wl), None) or next((p for p in pls if wl in p["name"].lower()), None)
            if hit and (asked_playlist or hit["name"].lower() == wl):   # "play my chill" or an exact playlist name
                return f"Playing your playlist {hit['name']}." if play_uri(context_uri=hit["uri"]) else (_state.get("error") or "I couldn't start that playlist.")
            res = search(want, "track,playlist,album", 5)
            if not res:
                return f"I couldn't find {want} on Spotify."
            pick = next((r for r in res if r["type"] == "track"), res[0]) if not asked_playlist else next((r for r in res if r["type"] == "playlist"), res[0])
            ok = play_uri(uri=pick["uri"]) if pick["type"] == "track" else play_uri(context_uri=pick["uri"])
            if not ok:
                return _state.get("error") or "I couldn't start playback."
            return f"Playing {pick['name']}" + (f" by {pick['artist']}." if pick.get("artist") else ".")
    return None


def api(action, p):
    if action == "local_event":
        try:
            _local_event({k: (v if isinstance(v, str) else str(v)) for k, v in (p or {}).items()})
            return {"ok": True}
        except Exception as e:
            ctx.log(f"local_event failed: {e}")
            return {"ok": False, "error": str(e)}
    if action == "device_login":
        return device_login()
    if action == "device_login_status":
        return {"ok": True, **_device_login}
    if action == "recent":
        return {"ok": True, "items": recent(force=bool(p.get("force")))}
    if action == "search":
        return {"ok": True, "items": search(p.get("q", ""))}
    if action == "play":
        ok = play_uri(p.get("uri"), p.get("context_uri"))
        return {"ok": ok, "error": None if ok else _state["error"]}
    if action == "queue":
        ok = queue_uri(p.get("uri"))
        return {"ok": ok, "error": None if ok else _state["error"]}
    if action == "pause":
        return {"ok": pause()}
    if action == "resume":
        return {"ok": resume()}
    if action == "next":
        return {"ok": next_track()}
    if action == "prev":
        return {"ok": prev_track()}
    if action == "volume":
        pct = max(0, min(100, int(p.get("pct", 50))))
        if _use_local():
            steps = max(1, int(_gl["volume_steps"] or 100))
            return {"ok": _gl_call("POST", "/player/volume", {"volume": int(round(pct * steps / 100.0))}) is not None}
        return {"ok": _call("PUT", "/me/player/volume", params={"volume_percent": pct}) is not None}
    if action == "shuffle":
        return {"ok": set_shuffle(bool(p.get("on")))}
    if action == "seek":
        try:
            ms = max(0, min(24 * 3600 * 1000, int(p.get("ms", 0))))
        except (TypeError, ValueError):
            return {"ok": False, "error": "ms must be a number"}
        return {"ok": seek_ms(ms)}
    if action == "playlists":
        _refresh_playlists(); _drop_cache("playlists:")
        return {"ok": True, "playlists": _state["playlists"]}
    if action == "library":
        kind = p.get("kind", "playlists"); off = int(p.get("offset", 0) or 0)
        fn = {"liked": lambda: liked_tracks(off), "albums": lambda: saved_albums(off), "artists": lambda: followed_artists(p.get("after")),
              "shows": lambda: saved_shows(off), "playlists": lambda: all_playlists(off)}.get(kind)
        if not fn:
            return {"ok": False, "error": "unknown library kind"}
        r = fn()
        if r is None:
            return {"ok": False, "error": _state.get("error") or "Spotify didn't answer", "needs_reauth": _state.get("needs_reauth")}
        if kind == "liked":
            liked = liked_contains([t["uri"] for t in r["items"]])
            for t in r["items"]: t["liked"] = True
        return {"ok": True, **r}
    if action == "detail":
        uri = str(p.get("uri") or ""); off = int(p.get("offset", 0) or 0)
        if not _uri_ok(uri) or not uri:
            return {"ok": False, "error": "bad uri"}
        kind = uri.split(":")[1]
        r = {"playlist": lambda: playlist_detail(uri, off), "album": lambda: album_detail(uri), "artist": lambda: artist_detail(uri),
             "show": lambda: show_detail(uri, off)}.get(kind, lambda: None)()
        if r is None:
            return {"ok": False, "error": _state.get("error") or "Spotify didn't answer", "needs_reauth": _state.get("needs_reauth")}
        liked = liked_contains([t["uri"] for t in r["items"] if t.get("type") == "track"])
        for t in r["items"]:
            if t.get("type") == "track": t["liked"] = liked.get(t["uri"])
        return {"ok": True, "kind": kind, **r}
    if action == "search_full":
        r = search_full(p.get("q", ""))
        if "tracks" in r:
            liked = liked_contains([t["uri"] for t in r["tracks"]])
            for t in r["tracks"]: t["liked"] = liked.get(t["uri"])
        return {"ok": True, **r}
    if action == "play_context":
        ok = play_in_context(p.get("context_uri"), p.get("uri"), p.get("position"), p.get("position_ms"))
        return {"ok": ok, "error": None if ok else _state["error"]}
    if action == "play_liked":
        ok = play_liked(p.get("uri"))
        return {"ok": ok, "error": None if ok else _state["error"]}
    if action == "play_uris":
        ok = play_uris(list(p.get("uris") or []), int(p.get("start", 0) or 0))
        return {"ok": ok, "error": None if ok else _state["error"]}
    if action == "repeat":
        return {"ok": set_repeat(p.get("mode", "off"))}
    if action == "like":
        ok = set_like(p.get("uri"), bool(p.get("on", True)))
        return {"ok": ok, "error": None if ok else _state["error"]}
    if action == "liked_contains":
        return {"ok": True, "liked": liked_contains(list(p.get("uris") or []))}
    if action == "queue_list":
        r = queue_list()
        return {"ok": r is not None, **(r or {}), "error": None if r is not None else _state["error"]}
    if action == "devices":
        r = devices()
        return {"ok": r is not None, "devices": r or [], "error": None if r is not None else _state["error"]}
    if action == "transfer":
        ok = transfer(p.get("device_id"), p.get("play", True))
        return {"ok": ok, "error": None if ok else _state["error"]}
    if action == "add_to_playlist":
        ok = add_to_playlist(p.get("playlist_uri"), p.get("uri"))
        return {"ok": ok, "error": None if ok else _state["error"]}
    if action == "remove_from_playlist":
        ok = remove_from_playlist(p.get("playlist_uri"), p.get("uri"))
        return {"ok": ok, "error": None if ok else _state["error"]}
    if action == "logout":
        ctx.config["tokens"] = {"access": "", "refresh": "", "expires_at": 0}
        ctx.save_config()
        with _lock:
            _state.update(authenticated=False, now=None, playlists=[], device_online=False, user_id=None)
        _cache.clear(); _liked_cache.clear()
        return {"ok": True}
    return {"ok": False, "error": f"unknown action {action}"}
