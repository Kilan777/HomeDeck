"""News headlines from RSS feeds (stdlib only), refreshed every 15 minutes.

api: refresh, set_feeds {urls: [..]}
state(): {sources: [{name, url, items: [{title, link, ts}]}], briefing: str, fetched_at, error}
intent(text): "what's the news", "news briefing", "top headlines" -> spoken briefing (top 5 across feeds)
"""
import html, re, threading, time, urllib.request
import xml.etree.ElementTree as ET

NAME = "news"
DEFAULTS = {
    "feeds": ["https://feeds.npr.org/1001/rss.xml", "http://feeds.bbci.co.uk/news/world/rss.xml", "https://www.theguardian.com/world/rss"],
    "per_feed": 8, "refresh_s": 900,
}

_state = {"sources": [], "briefing": "", "fetched_at": None, "error": None}
_lock = threading.Lock()
_wake = threading.Event()
ctx = None


def _clean(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return html.unescape(s).strip()


def _fetch(url):
    if not re.match(r"^https?://", url):
        raise ValueError("feed must be http(s)")
    req = urllib.request.Request(url, headers={"User-Agent": "HomeDeck/1.0 (RSS reader)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read(2_000_000)
    root = ET.fromstring(raw)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    # RSS 2.0
    chan = root.find("channel")
    items, name = [], None
    if chan is not None:
        name = _clean(chan.findtext("title") or "")
        for it in chan.findall("item"):
            title = _clean(it.findtext("title") or "")
            if title:
                items.append({"title": title, "link": (it.findtext("link") or "").strip(), "ts": (it.findtext("pubDate") or "").strip()})
    else:  # Atom
        name = _clean(root.findtext("atom:title", default="", namespaces=ns))
        for e in root.findall("atom:entry", ns):
            title = _clean(e.findtext("atom:title", default="", namespaces=ns))
            link_el = e.find("atom:link", ns)
            if title:
                items.append({"title": title, "link": (link_el.get("href") if link_el is not None else "") or "", "ts": e.findtext("atom:updated", default="", namespaces=ns)})
    name = re.sub(r"\s*[-|:].*$", "", name)[:40] or url.split("/")[2]
    return name, items


def refresh():
    per = int(ctx.config.get("per_feed", 8))
    sources, errors = [], []
    for url in ctx.config.get("feeds") or []:
        try:
            name, items = _fetch(url)
            sources.append({"name": name, "url": url, "items": items[:per]})
        except Exception as e:
            errors.append(f"{url.split('/')[2]}: {str(e)[:60]}")
    with _lock:
        _state.update({"sources": sources, "briefing": _briefing(sources), "fetched_at": time.time(),
                       "error": "; ".join(errors) if errors else None})


def _briefing(sources, n=5):
    """Round-robin the top headlines across sources into one spoken paragraph."""
    picked, i = [], 0
    while len(picked) < n and any(len(s["items"]) > i for s in sources):
        for s in sources:
            if len(s["items"]) > i and len(picked) < n:
                title = s["items"][i]["title"].rstrip(".")
                picked.append(f"From {s['name']}: {title}.")
        i += 1
    if not picked:
        return "I couldn't fetch any headlines right now."
    return "Here are the top headlines. " + " ".join(picked)


def intent(text):
    low = (text or "").lower().strip()
    if not low:
        return None
    if re.search(r"\b(news|headlines?|briefing)\b", low) and re.search(r"\b(what|whats|what's|read|tell|give|any|latest|top|today|the|my|news)\b", low):
        with _lock:
            b = _state.get("briefing")
            stale = not _state.get("fetched_at") or time.time() - _state["fetched_at"] > 3600
        if stale:
            try: refresh()
            except Exception: pass
            with _lock:
                b = _state.get("briefing")
        return b or "I couldn't fetch any headlines right now."
    return None


def start(c):
    global ctx
    ctx = c
    while True:
        try:
            refresh()
        except Exception as e:
            with _lock:
                _state["error"] = str(e)[:120]
        _wake.wait(int(ctx.config.get("refresh_s", 900)))
        _wake.clear()


def state():
    with _lock:
        return dict(_state)


def api(action, params):
    if action == "refresh":
        _wake.set()
        return {"ok": True}
    if action == "set_feeds":
        urls = params.get("urls") or []
        if not isinstance(urls, list) or len(urls) > 10:
            return {"ok": False, "error": "urls must be a list of up to 10"}
        urls = [str(u).strip()[:300] for u in urls if re.match(r"^https?://", str(u).strip())]
        ctx.config["feeds"] = urls
        ctx.save_config()
        _wake.set()
        return {"ok": True, "feeds": urls}
    if action == "briefing":
        with _lock:
            return {"ok": True, "text": _state.get("briefing", "")}
    return {"ok": False, "error": f"unknown action {action}"}
