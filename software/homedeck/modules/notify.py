"""Push notifications to the phone via ntfy (https://ntfy.sh): free, no account.

Install the ntfy app on the phone and subscribe to the topic shown in the app page.
Other modules call notify.send(title, body, image_path=..., priority=..., tags=[...]).
"""
import mimetypes, os, secrets, threading, time, urllib.request

NAME = "notify"
DEFAULTS = {"enabled": True, "ntfy_server": "https://ntfy.sh", "ntfy_topic": "",
            "attach_images": True}     # motion snapshots travel to the ntfy server (a third party); turn off to send text only

ctx = None
_lock = threading.Lock()
_ring = []          # last 50 sent notifications


def _topic():
    t = ctx.config.get("ntfy_topic") or ""
    if not t:
        t = "homedeck-" + secrets.token_hex(4)
        ctx.config["ntfy_topic"] = t
        ctx.save_config()
    return t


def _hdr(v):
    """ntfy headers must be latin-1; strip anything else."""
    return str(v).replace("\r", " ").replace("\n", " ")[:500].encode("latin-1", "replace").decode("latin-1")


def send(title, body, image_path=None, priority="default", tags=None, click_url=None):
    """Send a notification. Returns True on success. Never raises."""
    rec = {"t": time.time(), "title": title, "body": body, "image": bool(image_path), "ok": False}
    with _lock:
        _ring.append(rec)
        del _ring[:-50]
    if not ctx or not ctx.config.get("enabled", True):
        return False
    url = f"{ctx.config.get('ntfy_server', 'https://ntfy.sh').rstrip('/')}/{_topic()}"
    headers = {"Title": _hdr(title), "Priority": _hdr(priority)}
    if tags:
        headers["Tags"] = _hdr(",".join(tags))
    if click_url:
        headers["Click"] = _hdr(click_url)
    data = body.encode()
    if image_path and os.path.isfile(image_path) and ctx.config.get("attach_images", True):
        # attachment API: file is the body, text goes in the Message header
        headers["Filename"] = _hdr(os.path.basename(image_path))
        headers["Message"] = _hdr(body)
        headers["Content-Type"] = mimetypes.guess_type(image_path)[0] or "application/octet-stream"
        with open(image_path, "rb") as f:
            data = f.read()
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            rec["ok"] = 200 <= r.status < 300
    except Exception as e:
        rec["error"] = str(e)
        ctx.log(f"ntfy send failed: {e}")
    return rec["ok"]


def state():
    with _lock:
        ring = list(_ring)
    return {"enabled": ctx.config.get("enabled", True) if ctx else True,
            "topic": _topic() if ctx else "", "server": ctx.config.get("ntfy_server") if ctx else "",
            "subscribe_url": f"{ctx.config.get('ntfy_server', 'https://ntfy.sh').rstrip('/')}/{_topic()}" if ctx else "",
            "recent": ring[-20:]}


def api(action, params):
    if action == "test":
        ok = send("HomeDeck", params.get("body", "Test notification from HomeDeck"), tags=["house"])
        return {"ok": ok}
    if action == "send":
        prio = str(params.get("priority", "default"))
        if prio not in ("min", "low", "default", "high", "urgent", "1", "2", "3", "4", "5"):
            prio = "default"
        tags = [str(t)[:32] for t in (params.get("tags") or [])][:8] if isinstance(params.get("tags"), list) else None
        ok = send(str(params.get("title", "HomeDeck"))[:120], str(params.get("body", ""))[:2000], priority=prio, tags=tags)
        return {"ok": ok}
    if action == "new_topic":
        ctx.config["ntfy_topic"] = "homedeck-" + secrets.token_hex(4)
        ctx.save_config()
        return {"ok": True, "topic": ctx.config["ntfy_topic"]}
    return {"ok": False, "error": f"unknown action {action}"}


def start(c):
    global ctx
    ctx = c
    _topic()           # generate + persist on first run
    # nothing to loop over; sends are synchronous from callers
