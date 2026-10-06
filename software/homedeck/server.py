#!/usr/bin/env python3
"""HomeDeck core: config, event bus, module loader, HTTP server.

Layout (installed to /opt/homedeck):
  server.py            this file
  modules/<name>.py    one file per feature; see MODULE CONTRACT below
  web/                 static front-end (index.html, shell.js, style.css, apps/<name>.js)
  /var/lib/homedeck/   config.json (user settings), clips/, logs

MODULE CONTRACT (modules/<name>.py):
  NAME = "camera"                      # module id, also the URL prefix /api/<NAME>/...
  DEFAULTS = {...}                     # default config for this module, merged under config[NAME]
  def start(ctx): ...                  # called once at boot in its own thread; may block (run loops)
  def state() -> dict                  # JSON-able snapshot, served under /api/state[NAME] every poll
  def api(action, params) -> dict      # optional; POST /api/<NAME>/<action> with a JSON body
  ROUTES = {"/stream": handler}        # optional raw HTTP routes, served at /<NAME>/stream;
                                       #   handler(req) gets the BaseHTTPRequestHandler and writes the response itself
ctx (shared object passed to start):
  ctx.config            -> live dict for THIS module (already merged with DEFAULTS); ctx.save_config() persists
  ctx.global_config     -> the whole config dict (read other modules' settings, e.g. location)
  ctx.emit(event, data) -> publish an event ("motion", "wake", "alarm", "presence", "co2_high", ...)
  ctx.on(event, fn)     -> subscribe; fn(data) runs on the emitter's thread, keep it quick
  ctx.modules()         -> {name: module} for every loaded module
  def intent(text) -> str|None   # optional: handle a spoken command, return the spoken reply (voice tries every module)
  ctx.module(name)      -> another module's python module object (for direct calls, e.g. ctx.module("leds").pattern("listen"))
  ctx.log(msg)          -> timestamped log line
  ctx.data_dir          -> /var/lib/homedeck
"""
import importlib, json, os, re, sys, threading, time, traceback, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("HOMEDECK_DATA", "/var/lib/homedeck")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
PORT = int(os.environ.get("HOMEDECK_PORT", "8080"))

GLOBAL_DEFAULTS = {
    "general": {
        "name": "HomeDeck",
        "location": {"lat": 37.7509, "lon": -122.4153, "city": "San Francisco", "zip": "94110", "timezone": "America/Los_Angeles"},
        "clock_24h": False,
        "units": "imperial",           # imperial | metric
        "guest_mode": False,
        "guest_exit_phrase": "jarvis welcome home",
    }
}

_config = {}
_config_lock = threading.Lock()
_modules = {}      # name -> python module
_events = {}       # event -> [fn]
_ring = []         # last 100 emitted events, served in /api/state as events.ring
_ring_lock = threading.Lock()
_log_lock = threading.Lock()


def log(msg, src="core"):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{src}] {msg}"
    with _log_lock:
        print(line, flush=True)


def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_config(defaults):
    saved = {}
    for path in (CONFIG_PATH, CONFIG_PATH + ".bak"):
        try:
            with open(path) as f:
                saved = json.load(f)
            if path != CONFIG_PATH:
                log("config.json was unreadable; restored the last good copy")
            break
        except FileNotFoundError:
            continue
        except Exception as e:
            log(f"{os.path.basename(path)} unreadable: {e}")
    return deep_merge(defaults, saved)


def save_config():
    """Persist config.json with owner-only permissions (it holds API keys, OAuth secrets and session secrets)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with _config_lock:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(_config, f, indent=2)
            f.flush()
            os.fsync(f.fileno())                     # survive a power cut mid-save
        try:
            if os.path.exists(CONFIG_PATH):
                os.replace(CONFIG_PATH, CONFIG_PATH + ".bak")   # last good copy, used if the main file is ever unreadable
        except OSError:
            pass
        os.replace(tmp, CONFIG_PATH)
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except OSError:
            pass


# Config keys that are secrets: never returned to clients, and a client can never overwrite them with the placeholder.
_SECRET_KEY = re.compile(r"(key|secret|token|tokens|psk|password|passwd)$", re.I)
REDACTED = "••••"
# Fields only the server may write (session secret, hashed device tokens, OAuth refresh tokens).
_SERVER_OWNED = {("auth", "secret"), ("auth", "tokens"), ("spotify", "tokens")}


def redact(obj):
    """Deep copy with secret-like values replaced by REDACTED plus a '<key>_set' boolean for the UI."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _SECRET_KEY.search(str(k)) and not isinstance(v, bool):
                out[k] = REDACTED if v else ""
                out[f"{k}_set"] = bool(v)
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def strip_placeholders(obj, path=()):
    """Drop REDACTED placeholders, '<key>_set' echoes and server-owned fields from a client config write."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if (path[:1] + (k,)) in _SERVER_OWNED or str(k).endswith("_set"):
                continue
            if isinstance(v, str) and v.strip("• ") == "" and v.strip():
                continue                    # the placeholder (any run of bullets) means "keep what you have"
            out[k] = strip_placeholders(v, path + (k,))
        return out
    return obj


class Ctx:
    def __init__(self, name):
        self.name = name
        self.data_dir = DATA_DIR
    @property
    def config(self):
        return _config[self.name]
    @property
    def global_config(self):
        return _config
    def save_config(self):
        save_config()
    def emit(self, event, data=None):
        with _ring_lock:
            _ring.append({"t": time.time(), "name": event, "data": data, "src": self.name})
            del _ring[:-100]
        for fn in list(_events.get(event, [])):
            try:
                fn(data)
            except Exception:
                log(f"handler for '{event}' failed:\n{traceback.format_exc()}", self.name)
    def on(self, event, fn):
        _events.setdefault(event, []).append(fn)
    def module(self, name):
        return _modules.get(name)
    def modules(self):
        """All loaded modules by name (used by voice to offer the transcript to every module's intent())."""
        return dict(_modules)
    def log(self, msg):
        log(msg, self.name)


def load_modules():
    mdir = os.path.join(HERE, "modules")
    sys.path.insert(0, HERE)
    defaults = dict(GLOBAL_DEFAULTS)
    found = []
    for fn in sorted(os.listdir(mdir)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        try:
            m = importlib.import_module(f"modules.{fn[:-3]}")
            name = getattr(m, "NAME", fn[:-3])
            defaults[name] = getattr(m, "DEFAULTS", {})
            found.append((name, m))
        except Exception:
            log(f"module {fn} failed to import:\n{traceback.format_exc()}")
    global _config
    _config = load_config(defaults)
    for name, m in found:
        _modules[name] = m
        m.ctx = Ctx(name)
    for name, m in found:
        def runner(m=m, name=name):
            try:
                m.start(m.ctx)
            except Exception:
                log(f"module {name} crashed:\n{traceback.format_exc()}")
        threading.Thread(target=runner, name=name, daemon=True).start()
        log(f"started module {name}")


_web_ver = {"t": 0, "v": 0}
def web_version():
    """Newest mtime under web/: the page reloads itself when this changes (deploys reach the kiosk without a restart)."""
    now = time.time()
    if now - _web_ver["t"] > 10:
        newest = 0
        for root, _, files in os.walk(os.path.join(HERE, "web")):
            for f in files:
                try: newest = max(newest, os.path.getmtime(os.path.join(root, f)))
                except OSError: pass
        _web_ver.update({"t": now, "v": int(newest)})
    return _web_ver["v"]


def full_state():
    with _ring_lock:
        ring = list(_ring)
    out = {"time": time.time(), "general": _config["general"], "events": {"ring": ring}, "web_version": web_version()}
    for name, m in _modules.items():
        try:
            out[name] = m.state() if hasattr(m, "state") else {}
        except Exception as e:
            out[name] = {"error": str(e)}
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://www.youtube.com https://s.ytimg.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
           "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob: https://upload.wikimedia.org https://thumb.wikimedia.org https://tile.openstreetmap.org "
           "https://tilecache.rainviewer.com https://i.scdn.co https://mosaic.scdn.co https://*.scdn.co https://*.spotifycdn.com https://i.ytimg.com https://*.ytimg.com; media-src 'self' blob:; "
           "connect-src 'self'; frame-src https://www.youtube-nocookie.com https://www.youtube.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://accounts.google.com https://accounts.spotify.com; object-src 'none'")

    def send(self, code, ctype, body, extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "DENY")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", self.CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, code=200):
        self.send(code, "application/json", json.dumps(obj))

    MAX_BODY = 1 << 20      # 1 MB: config writes and api calls are tiny; anything bigger is abuse

    def read_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > self.MAX_BODY:
            self.rfile.read(min(n, self.MAX_BODY)); self.close_connection = True
            return {}
        raw = self.rfile.read(n) if n > 0 else b""
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {"_raw": raw.decode(errors="replace")}

    def gated(self, path):
        """Remote-access gate: the auth module decides (localhost kiosk and disabled auth always pass).
        Returns True when the request was rejected and a response has already been sent."""
        if path.startswith("/auth/") or path in ("/web/login.html", "/web/icon.svg", "/web/style.css"):
            return False
        auth = _modules.get("auth")
        if not auth or not hasattr(auth, "check"):
            return False
        try:
            ok = auth.check(self)
        except Exception:
            log(f"auth check failed open->closed:\n{traceback.format_exc()}")
            ok = False
        if ok:
            return False
        if path.startswith("/api/"):
            self.send_json({"ok": False, "error": "unauthorized"}, 401)
        else:
            self.send_response(302); self.send_header("Location", "/auth/login"); self.send_header("Content-Length", "0"); self.end_headers()
        return True

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path = url.path
        self.query = dict(urllib.parse.parse_qsl(url.query))
        if self.gated(path):
            return
        if path in ("/", "/index.html"):
            # The device's own screen (localhost, ?kiosk=1) gets the kiosk UI; phones and remote clients get the Remote app.
            q = self.query
            peer = self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1") and not self.headers.get("X-Forwarded-For")
            if "kiosk" in q or (peer and "remote" not in q):
                return self.static("index.html")
            return self.static("remote.html")
        if path.startswith("/web/"):
            return self.static(path[5:])
        if path == "/api/health":                     # liveness for the systemd watchdog: no locks, no module calls
            return self.send_json({"ok": True, "t": time.time()})
        if path == "/api/state":
            return self.send_json(full_state())
        if path == "/api/config":
            return self.send_json(redact(_config))
        parts = path.strip("/").split("/", 1)
        m = _modules.get(parts[0])
        if m and len(parts) == 2 and hasattr(m, "ROUTES"):
            h = m.ROUTES.get("/" + parts[1])
            if h:
                try:
                    return h(self)
                except (BrokenPipeError, ConnectionResetError):
                    return
        self.send(404, "text/plain", "not found")

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        path = url.path
        self.query = dict(urllib.parse.parse_qsl(url.query))
        if self.gated(path):
            self.read_body()          # drain the request body before the connection is reused
            return
        body = self.read_body()
        if path == "/api/config":
            # body = partial config, deep-merged and saved
            global _config
            body = strip_placeholders(body if isinstance(body, dict) else {})
            with _config_lock:
                _config = deep_merge(_config, body)
            for name, m in _modules.items():
                m.ctx = m.ctx  # modules read live config through ctx.config
            save_config()
            for name, m in _modules.items():
                if hasattr(m, "on_config"):
                    try: m.on_config()
                    except Exception: log(f"{name}.on_config failed:\n{traceback.format_exc()}")
            return self.send_json({"ok": True, "config": redact(_config)})
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api":
            m = _modules.get(parts[1])
            if m and hasattr(m, "api"):
                try:
                    res = m.api(parts[2], body or {})
                    return self.send_json(res if res is not None else {"ok": True})
                except Exception as e:
                    log(f"api {parts[1]}/{parts[2]} failed:\n{traceback.format_exc()}")
                    return self.send_json({"ok": False, "error": str(e)}, 500)
        m = _modules.get(parts[0]) if parts else None
        if m and len(parts) >= 2 and hasattr(m, "ROUTES"):
            h = m.ROUTES.get("/" + "/".join(parts[1:]))
            if h:
                self.body = body
                return h(self)
        self.send(404, "text/plain", "not found")

    MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".png": "image/png",
            ".jpg": "image/jpeg", ".svg": "image/svg+xml", ".json": "application/json", ".mp3": "audio/mpeg",
            ".wav": "audio/wav", ".woff2": "font/woff2", ".mp4": "video/mp4", ".webmanifest": "application/manifest+json"}

    def static(self, rel):
        rel = os.path.normpath(rel).lstrip("/")
        p = os.path.join(HERE, "web", rel)
        if not p.startswith(os.path.join(HERE, "web") + os.sep) or not os.path.isfile(p):
            return self.send(404, "text/plain", "not found")
        with open(p, "rb") as f:
            data = f.read()
        self.send(200, self.MIME.get(os.path.splitext(p)[1], "application/octet-stream"), data)


def _fd_guard():
    """Safety net for file-handle leaks: one leak (a camera retry) used every handle overnight, after which the server
    could not answer and the screen sat on "reconnecting". Above 85 % of the limit, log what is open and exit so
    systemd (Restart=always) brings up a clean process in a few seconds."""
    import resource, collections
    soft = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    warned = False
    last_report = 0.0
    while True:
        time.sleep(60)
        try:
            # threads and memory too: same idea, a slow leak of either ends the same way
            rss_mb = 0
            for line in open("/proc/self/status"):
                if line.startswith("VmRSS:"):
                    rss_mb = int(line.split()[1]) // 1024
            threads = threading.active_count()
            if time.time() - last_report > 3600:          # hourly health line: a slow leak shows up days early
                log(f"health: {len(os.listdir('/proc/self/fd'))} files, {threads} threads, {rss_mb} MB")
                last_report = time.time()
            if rss_mb > 1500 or threads > 400:
                log(f"{rss_mb} MB / {threads} threads in use, restarting the service")
                os._exit(1)
            fds = os.listdir("/proc/self/fd")
            n = len(fds)
            if n > 0.6 * soft and not warned:
                log(f"{n} of {soft} file handles in use; watching for a leak")
                warned = True
            if n > 0.6 * soft:
                import gc
                gc.collect()                                # libraries that leave handles in reference cycles
                n = len(os.listdir("/proc/self/fd"))
            if n > 0.85 * soft:
                kinds = collections.Counter()
                for fd in fds:
                    try:
                        kinds[re.sub(r"\d+", "N", os.readlink(f"/proc/self/fd/{fd}"))] += 1
                    except OSError:
                        pass
                log(f"{n} of {soft} file handles in use, restarting the service. Top: {kinds.most_common(4)}")
                os._exit(1)
        except Exception as e:
            log(f"fd guard: {e}")


def _systemd_watchdog():
    """Tell systemd we are alive, but only when the web server really answers. If a request to /api/health fails
    (handles exhausted, server thread wedged, deadlock), the pings stop and systemd restarts the service after
    WatchdogSec. Does nothing when not started by systemd with a watchdog."""
    import socket, urllib.request
    addr = os.environ.get("NOTIFY_SOCKET")
    usec = int(os.environ.get("WATCHDOG_USEC", "0") or 0)
    if not addr or not usec:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    interval = max(5.0, usec / 1e6 / 3)
    sk = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    def notify(msg):
        try:
            sk.sendto(msg.encode(), addr)
        except OSError as e:
            log(f"watchdog notify failed: {e}")
    for _ in range(60):                                   # wait for the HTTP server to start listening
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2).close(); break
        except Exception:
            time.sleep(1)
    notify("READY=1")
    failing = 0
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=10) as r:
                ok = r.status == 200
        except Exception as e:
            ok = False
            failing += 1
            log(f"watchdog: self-check failed ({e}); {'restart pending' if failing > 1 else 'retrying'}")
        if ok:
            failing = 0
            notify("WATCHDOG=1")
        time.sleep(interval)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    load_modules()
    threading.Thread(target=_fd_guard, name="fd-guard", daemon=True).start()
    import signal as _signal
    def _on_term(signum, frame):
        """systemd stop / reboot: give modules a moment to finish files (open files), then exit."""
        log("stopping: closing files")
        for name, m in list(_modules.items()):
            if hasattr(m, "shutdown"):
                try:
                    m.shutdown()
                except Exception as e:
                    log(f"{name} shutdown: {e}")
        log("stopped cleanly")
        try:
            sys.stdout.flush(); sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)
    _signal.signal(_signal.SIGTERM, _on_term)
    threading.Thread(target=_systemd_watchdog, name="watchdog", daemon=True).start()
    log(f"HomeDeck serving on port {PORT}")
    srv = None
    for attempt in range(20):
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
            break
        except OSError as e:
            if e.errno != 98:
                raise
            log(f"port {PORT} still in use ({attempt + 1}/20): an earlier process has not exited yet")
            time.sleep(3)
    if srv is None:
        # An earlier instance stuck in the kernel (a hung camera driver) keeps the port and cannot be killed; only a
        # reboot clears it. Once per boot at most (/run is cleared by a reboot), and never right after boot.
        marker = "/run/homedeck-port-reboot"
        up = float(open("/proc/uptime").read().split()[0])
        if not os.path.exists(marker) and up > 300:
            open(marker, "w").close()
            log(f"port {PORT} held by a process that cannot exit; rebooting")
            os.system("sync; systemctl reboot")
            time.sleep(120)
        raise SystemExit(f"port {PORT} in use")
    srv.daemon_threads = True
    srv.serve_forever()


if __name__ == "__main__":
    main()
