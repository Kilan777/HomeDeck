"""Remote-access login: Google Sign-In (OAuth 2.0 authorization code + PKCE), 30-day sessions, device tokens.

The device's own kiosk (localhost) never sees a login. Any other client must carry a valid session cookie
(hd_session) or an X-HomeDeck-Token header. Caddy terminates HTTPS in front and proxies from 127.0.0.1.

Routes (all under /auth/):  /login  /start  /callback  /logout
Config (auth): enabled, public_host, google_client_id, google_client_secret, allowed_emails, session_days, secret, tokens
Emits: "auth_event" {kind: login|denied|failure|logout|rate_limited, email?, ip}
"""
import base64, hashlib, hmac, json, os, secrets, threading, time, urllib.parse, urllib.request

NAME = "auth"
DEFAULTS = {
    "enabled": False,
    "public_host": "jarvis.example.com",
    "google_client_id": "",
    "google_client_secret": "",
    "allowed_emails": [],
    "session_days": 30,
    "secret": "",              # generated on first run
    "tokens": [],              # [{name, hash, created}] device tokens for native apps
}
COOKIE = "hd_session"
FAIL_LIMIT, FAIL_WINDOW = 5, 600      # 5 failures per IP per 10 min

ctx = None
_lock = threading.Lock()
_sessions = {}      # session id -> {email, ip, created, expires}
_pending = {}       # oauth state -> {verifier, created}
_failures = {}      # ip -> [timestamps]
_state = {"last_login": None}


# ----------------------------------------------------------------- helpers
def _secret():
    s = ctx.config.get("secret") or ""
    if not s:
        s = secrets.token_hex(32)
        ctx.config["secret"] = s
        ctx.save_config()
    return s.encode()


def _sign(msg):
    return hmac.new(_secret(), msg.encode(), hashlib.sha256).hexdigest()


def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def client_ip(handler):
    """Real client IP: trust X-Forwarded-For only when the socket peer is Caddy on localhost."""
    peer = handler.client_address[0]
    if peer in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        xff = handler.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
    return peer


def is_local(handler):
    peer = handler.client_address[0]
    if peer not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return False
    return not handler.headers.get("X-Forwarded-For")      # proxied requests are not the kiosk


def configured():
    c = ctx.config
    return bool(c.get("google_client_id") and c.get("google_client_secret") and c.get("allowed_emails") and c.get("public_host"))


def _cookies(handler):
    out = {}
    for part in (handler.headers.get("Cookie") or "").split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            out[k] = v
    return out


def _valid_session(token):
    """token = <expiry>.<sid>.<hmac>"""
    try:
        exp, sid, mac = token.split(".")
        if not hmac.compare_digest(mac, _sign(f"{exp}.{sid}")):
            return None
        if int(exp) < time.time():
            return None
        with _lock:
            return _sessions.get(sid) or {"sid": sid}      # valid even after a restart (HMAC), just not in the list
    except Exception:
        return None


def _token_hash(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


def _failed(ip):
    now = time.time()
    with _lock:
        lst = [t for t in _failures.get(ip, []) if now - t < FAIL_WINDOW]
        lst.append(now)
        _failures[ip] = lst
        return len(lst)


def _rate_limited(ip):
    now = time.time()
    with _lock:
        return len([t for t in _failures.get(ip, []) if now - t < FAIL_WINDOW]) >= FAIL_LIMIT


def _origin_ok(handler):
    """CSRF guard for state-changing requests from browsers: Origin/Referer must match the public host or be absent (token clients)."""
    host = (ctx.config.get("public_host") or "").lower()
    for h in ("Origin", "Referer"):
        v = handler.headers.get(h)
        if v:
            return urllib.parse.urlparse(v).hostname and urllib.parse.urlparse(v).hostname.lower() in (host, "localhost", "127.0.0.1", handler.headers.get("Host", "").split(":")[0].lower())
    return True


# ----------------------------------------------------------------- the gate
def check(handler):
    """True if this request may proceed. Called by server.py for every non-/auth/ request."""
    if not ctx or not ctx.config.get("enabled"):
        return True
    if is_local(handler):
        return True
    tok = handler.headers.get("X-HomeDeck-Token")
    if tok:
        h = _token_hash(tok)
        if any(hmac.compare_digest(h, t.get("hash", "")) for t in ctx.config.get("tokens", [])):
            return True
    sess = _valid_session(_cookies(handler).get(COOKIE, ""))
    if not sess:
        return False
    if handler.command == "POST" and not _origin_ok(handler):
        return False
    return True


# ----------------------------------------------------------------- routes
def _redirect(handler, url, cookie=None):
    handler.send_response(302)
    handler.send_header("Location", url)
    handler.send_header("Cache-Control", "no-store")
    if cookie:
        handler.send_header("Set-Cookie", cookie)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def _login_page(handler):
    err = handler.query.get("err", "") if hasattr(handler, "query") else ""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "login.html")
    try:
        html = open(p, encoding="utf-8").read()
    except FileNotFoundError:
        html = "<html><body><a href='/auth/start'>Sign in with Google</a></body></html>"
    msgs = {"denied": "That Google account isn't allowed on this device.", "rate": "Too many attempts. Try again in 10 minutes.",
            "oauth": "Google sign-in failed. Try again.", "state": "Sign-in expired. Try again.", "off": "Remote sign-in is not enabled on this device."}
    html = html.replace("{{DEVICE}}", (ctx.global_config.get("general", {}).get("name") or "HomeDeck")).replace("{{ERROR}}", msgs.get(err, ""))
    handler.send(200, "text/html; charset=utf-8", html)


def _start(handler):
    ip = client_ip(handler)
    if not ctx.config.get("enabled") or not configured():
        return _redirect(handler, "/auth/login?err=off")
    if _rate_limited(ip):
        ctx.emit("auth_event", {"kind": "rate_limited", "ip": ip})
        return _redirect(handler, "/auth/login?err=rate")
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    nonce = secrets.token_urlsafe(24)
    state = f"{nonce}.{_sign(nonce)}"
    with _lock:
        now = time.time()
        for k in [k for k, v in _pending.items() if now - v["created"] > 600]:
            _pending.pop(k, None)
        _pending[nonce] = {"verifier": verifier, "created": now}
    params = {
        "client_id": ctx.config["google_client_id"], "redirect_uri": f"https://{ctx.config['public_host']}/auth/callback",
        "response_type": "code", "scope": "openid email", "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "prompt": "select_account", "access_type": "online",
    }
    _redirect(handler, "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params))


def _callback(handler):
    ip = client_ip(handler)
    q = handler.query
    if _rate_limited(ip):
        return _redirect(handler, "/auth/login?err=rate")
    state, code = q.get("state", ""), q.get("code", "")
    try:
        nonce, mac = state.split(".")
        if not hmac.compare_digest(mac, _sign(nonce)):
            raise ValueError("bad state")
        with _lock:
            pend = _pending.pop(nonce, None)
        if not pend or time.time() - pend["created"] > 600:
            raise ValueError("expired state")
    except Exception:
        _failed(ip)
        ctx.emit("auth_event", {"kind": "failure", "ip": ip, "why": "state"})
        return _redirect(handler, "/auth/login?err=state")
    if not code:
        _failed(ip)
        return _redirect(handler, "/auth/login?err=oauth")
    try:
        data = urllib.parse.urlencode({
            "code": code, "client_id": ctx.config["google_client_id"], "client_secret": ctx.config["google_client_secret"],
            "redirect_uri": f"https://{ctx.config['public_host']}/auth/callback", "grant_type": "authorization_code",
            "code_verifier": pend["verifier"],
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        tok = json.load(urllib.request.urlopen(req, timeout=20))
        id_token = tok.get("id_token", "")
        # Google validates the signature server-side; we check the claims it returns
        info = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"id_token": id_token}), timeout=20))
        if info.get("aud") != ctx.config["google_client_id"] or info.get("iss") not in ("https://accounts.google.com", "accounts.google.com"):
            raise ValueError("claims")
        if int(info.get("exp", 0)) < time.time():
            raise ValueError("expired token")
        email = (info.get("email") or "").lower()
        if info.get("email_verified") not in (True, "true"):
            raise ValueError("unverified")
    except Exception as e:
        n = _failed(ip)
        ctx.log(f"login failure from {ip}: {e}")
        ctx.emit("auth_event", {"kind": "failure", "ip": ip, "why": str(e)[:80], "count": n})
        return _redirect(handler, "/auth/login?err=oauth")
    allowed = [a.strip().lower() for a in ctx.config.get("allowed_emails", []) if a.strip()]
    if email not in allowed:
        n = _failed(ip)
        ctx.log(f"login denied for {email} from {ip}")
        ctx.emit("auth_event", {"kind": "denied", "ip": ip, "email": email, "count": n})
        return _redirect(handler, "/auth/login?err=denied")
    days = int(ctx.config.get("session_days", 30) or 30)
    exp = int(time.time() + days * 86400)
    sid = secrets.token_urlsafe(24)
    token = f"{exp}.{sid}.{_sign(f'{exp}.{sid}')}"
    with _lock:
        _sessions[sid] = {"email": email, "ip": ip, "created": time.time(), "expires": exp}
        _state["last_login"] = {"email": email, "ts": time.time(), "ip": ip}
        _failures.pop(ip, None)
    ctx.log(f"login ok: {email} from {ip}")
    ctx.emit("auth_event", {"kind": "login", "ip": ip, "email": email})
    cookie = f"{COOKIE}={token}; Path=/; Max-Age={days * 86400}; HttpOnly; Secure; SameSite=Lax"
    _redirect(handler, "/", cookie=cookie)


def _logout(handler):
    tok = _cookies(handler).get(COOKIE, "")
    try:
        sid = tok.split(".")[1]
        with _lock:
            _sessions.pop(sid, None)
    except Exception:
        pass
    ctx.emit("auth_event", {"kind": "logout", "ip": client_ip(handler)})
    _redirect(handler, "/auth/login", cookie=f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax")


ROUTES = {"/login": _login_page, "/start": _start, "/callback": _callback, "/logout": _logout}


# ----------------------------------------------------------------- module API
def start(c):
    global ctx
    ctx = c
    _secret()
    if ctx.config.get("enabled") and not configured():
        ctx.config["enabled"] = False
        ctx.save_config()
        ctx.log("auth was enabled but not configured; disabled")

    def on_auth_event(d):
        n = ctx.module("notify")
        if n and d.get("kind") in ("denied", "failure", "rate_limited") and d.get("count", 5) >= 3:
            try:
                n.send("HomeDeck sign-in attempts", f"{d.get('kind')} from {d.get('ip')} {d.get('email', '')}", priority="high", tags=["warning"])
            except Exception:
                pass
    ctx.on("auth_event", on_auth_event)


def on_config():
    if ctx.config.get("enabled") and not configured():
        ctx.config["enabled"] = False
        ctx.save_config()
        ctx.log("refusing to enable remote sign-in: client id, secret, allowed emails and host are all required")


def state():
    now = time.time()
    with _lock:
        active = len([s for s in _sessions.values() if s["expires"] > now])
        fails = sum(len([t for t in v if now - t < FAIL_WINDOW]) for v in _failures.values())
        last = _state["last_login"]
    return {"enabled": bool(ctx.config.get("enabled")), "configured": configured(), "public_host": ctx.config.get("public_host"),
            "sessions_active": active, "last_login": last, "failures_10m": fails,
            "tokens": [{"name": t.get("name"), "created": t.get("created")} for t in ctx.config.get("tokens", [])]}


def api(action, params):
    if action == "create_token":
        name = (params.get("name") or "device").strip()[:40]
        tok = "hdt_" + secrets.token_urlsafe(32)
        ctx.config.setdefault("tokens", []).append({"name": name, "hash": _token_hash(tok), "created": time.time()})
        ctx.save_config()
        ctx.log(f"device token created: {name}")
        return {"ok": True, "token": tok, "name": name}      # shown once
    if action == "revoke_token":
        name = params.get("name")
        ctx.config["tokens"] = [t for t in ctx.config.get("tokens", []) if t.get("name") != name]
        ctx.save_config()
        return {"ok": True}
    if action == "logout_all":
        with _lock:
            _sessions.clear()
        ctx.config["secret"] = secrets.token_hex(32)     # invalidates every cookie
        ctx.save_config()
        return {"ok": True}
    return {"ok": False, "error": "unknown action"}
