"""Named lists (shopping, to-do, ...) persisted in config.

api: add {list, text}, toggle {list, id}, remove {list, id}, clear_done {list}, new_list {name}, remove_list {name}
state(): {lists: {name: [{id, text, done, ts}]}, open_counts: {name: n}}
intent(text): spoken commands ("add milk to my shopping list", "what's on my to-do list", ...)
"""
import re, threading, time

NAME = "lists"
DEFAULTS = {"lists": {"Shopping": [], "To-do": []}, "next_id": 1}

_lock = threading.Lock()
ctx = None


def _lists():
    ls = ctx.config.get("lists")
    if not isinstance(ls, dict):
        ls = {"Shopping": [], "To-do": []}
        ctx.config["lists"] = ls
    return ls


def _find_list(name):
    """Case-insensitive, forgiving match: 'shopping', 'grocery', 'todo', 'to do'... -> canonical list name."""
    if not name:
        return None
    key = re.sub(r"[^a-z]", "", name.lower())
    aliases = {"grocery": "shopping", "groceries": "shopping", "todo": "todo", "tasks": "todo", "task": "todo"}
    key = aliases.get(key, key)
    for n in _lists():
        if re.sub(r"[^a-z]", "", n.lower()) == key:
            return n
    return None


def _add(list_name, text):
    text = str(text or "").strip()[:120]
    if not text:
        return {"ok": False, "error": "empty item"}
    with _lock:
        ls = _lists()
        name = _find_list(list_name) or list_name
        if name not in ls:
            return {"ok": False, "error": f"no list named {list_name}"}
        iid = int(ctx.config.get("next_id", 1))
        ctx.config["next_id"] = iid + 1
        ls[name].append({"id": iid, "text": text, "done": False, "ts": time.time()})
        ctx.save_config()
    return {"ok": True, "id": iid, "list": name}


def _remove_by_text(list_name, text):
    key = str(text or "").strip().lower()
    with _lock:
        ls = _lists()
        name = _find_list(list_name)
        if not name:
            return None
        for it in ls[name]:
            if it["text"].lower() == key or key in it["text"].lower():
                ls[name].remove(it)
                ctx.save_config()
                return it["text"]
    return ""


# ------------------------------------------------------------------ voice intents
_ADD = re.compile(r"^(?:please\s+)?(?:add|put)\s+(.+?)\s+(?:to|on|onto)\s+(?:my\s+|the\s+)?(.+?)\s*list$", re.I)
_ADD2 = re.compile(r"^(?:please\s+)?(?:add|put)\s+(.+?)\s+(?:to|on|onto)\s+(?:my\s+|the\s+)?list$", re.I)
_REMOVE = re.compile(r"^(?:please\s+)?(?:remove|delete|take)\s+(.+?)\s+(?:from|off)\s+(?:my\s+|the\s+)?(.+?)\s*list$", re.I)
_READ = re.compile(r"^(?:what(?:'s| is| are)|read|show|tell me)\s+(?:on\s+)?(?:my\s+|the\s+)?(.+?)\s*list\??$", re.I)
_CLEAR = re.compile(r"^(?:please\s+)?(?:clear|empty|wipe)\s+(?:my\s+|the\s+)?(.+?)\s*list$", re.I)


def intent(text):
    t = re.sub(r"[.!?]+$", "", (text or "").strip())
    if not t or "list" not in t.lower() or re.search(r"\b(playlist|play list|liked songs|queue)\b", t.lower()):   # Spotify's business
        return None
    m = _ADD2.match(t)                      # "put eggs on the list" -> default list
    if m:
        _add("Shopping", m.group(1))
        return f"Added {m.group(1)} to your shopping list."
    m = _ADD.match(t)
    if m:
        item, lst = m.group(1), m.group(2)
        name = _find_list(lst) or ("Shopping" if lst.lower() in ("the", "my", "a") else None)
        if not name:
            return f"I don't have a list called {lst}."
        _add(name, item)
        return f"Added {item} to your {name} list."
    m = _REMOVE.match(t)
    if m:
        item, lst = m.group(1), m.group(2)
        name = _find_list(lst)
        if not name:
            return f"I don't have a list called {lst}."
        got = _remove_by_text(name, item)
        return f"Removed {got} from your {name} list." if got else f"I couldn't find {item} on your {name} list."
    m = _CLEAR.match(t)
    if m:
        name = _find_list(m.group(1))
        if not name:
            return None
        with _lock:
            _lists()[name] = []
            ctx.save_config()
        return f"Cleared your {name} list."
    m = _READ.match(t)
    if m:
        name = _find_list(m.group(1))
        if not name:
            return None
        items = [i["text"] for i in _lists()[name] if not i.get("done")]
        if not items:
            return f"Your {name} list is empty."
        if len(items) == 1:
            return f"Your {name} list has one item: {items[0]}."
        return f"Your {name} list has {len(items)} items: " + ", ".join(items[:-1]) + f", and {items[-1]}."
    return None


# ------------------------------------------------------------------ module API
def start(c):
    global ctx
    ctx = c
    _lists()


def state():
    with _lock:
        ls = {n: list(items) for n, items in _lists().items()}
    return {"lists": ls, "open_counts": {n: sum(1 for i in items if not i.get("done")) for n, items in ls.items()}}


def api(action, params):
    lst = str(params.get("list") or "Shopping")
    if action == "add":
        return _add(lst, params.get("text"))
    if action in ("toggle", "remove"):
        try:
            iid = int(params.get("id"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "id must be a number"}
        with _lock:
            ls = _lists()
            name = _find_list(lst)
            if not name:
                return {"ok": False, "error": "no such list"}
            for it in ls[name]:
                if it["id"] == iid:
                    if action == "toggle":
                        it["done"] = not it.get("done")
                    else:
                        ls[name].remove(it)
                    ctx.save_config()
                    return {"ok": True}
        return {"ok": False, "error": "item not found"}
    if action == "clear_done":
        with _lock:
            ls = _lists()
            name = _find_list(lst)
            if not name:
                return {"ok": False, "error": "no such list"}
            ls[name] = [i for i in ls[name] if not i.get("done")]
            ctx.save_config()
        return {"ok": True}
    if action == "new_list":
        name = re.sub(r"[^\w \-]", "", str(params.get("name") or "")).strip()[:30]
        if not name:
            return {"ok": False, "error": "name required"}
        with _lock:
            ls = _lists()
            if _find_list(name):
                return {"ok": False, "error": "list exists"}
            ls[name] = []
            ctx.save_config()
        return {"ok": True, "name": name}
    if action == "remove_list":
        with _lock:
            ls = _lists()
            name = _find_list(params.get("name"))
            if not name or len(ls) <= 1:
                return {"ok": False, "error": "cannot remove"}
            del ls[name]
            ctx.save_config()
        return {"ok": True}
    return {"ok": False, "error": f"unknown action {action}"}
