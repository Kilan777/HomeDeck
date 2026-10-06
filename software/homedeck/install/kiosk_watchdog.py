#!/usr/bin/env python3
"""Kiosk watchdog: keeps the on-screen browser healthy without anyone touching it.

Chromium on this board keeps its shared memory in /tmp (Debian's dev-shm rule adds --disable-dev-shm-usage) and
leaks segments over a day or so of running the home screen. When /tmp fills, the browser's networking fails and the
screen sits on "Reconnecting" even though the HomeDeck service is fine. This restarts Chromium (kiosk.sh relaunches
it within a couple of seconds, straight into the black Jarvis page and then the UI) when:
  - /tmp is more than 70 % full,
  - the page has reported "offline" for 60 s while the server answers,
  - the browser's debugging endpoint stops answering for 60 s,
  - it is 04:00 and the browser has been up for more than 12 hours (quiet nightly refresh).
It never restarts while the screen is in use: a restart waits until there has been no touch for 2 minutes, except
when the page is already broken. Runs as the kiosk user, started by kiosk.sh.
"""
import json, os, shutil, subprocess, time, urllib.request

CDP = "http://127.0.0.1:9222/json"
SERVER = "http://127.0.0.1:8080/api/state"
CHECK_S = 15


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "[kiosk-watchdog]", msg, flush=True)


def tmp_used_pct():
    u = shutil.disk_usage("/tmp")
    return 100.0 * u.used / u.total


def server_ok():
    try:
        with urllib.request.urlopen(SERVER, timeout=4) as r:
            return r.status == 200
    except Exception:
        return False


def idle_seconds():
    try:
        with urllib.request.urlopen(SERVER, timeout=4) as r:
            return float((json.load(r).get("display") or {}).get("idle_s", 0))
    except Exception:
        return 0.0


def page_state():
    """Returns 'ok', 'offline', or None when the debugging endpoint does not answer."""
    try:
        with urllib.request.urlopen(CDP, timeout=4) as r:
            pages = [t for t in json.load(r) if t.get("type") == "page"]
    except Exception:
        return None
    if not pages:
        return None
    url = pages[0].get("url", "")
    if url.startswith("file://"):
        return "ok"                                   # the boot page: it hands over by itself
    try:
        from websocket import create_connection
        ws = create_connection(pages[0]["webSocketDebuggerUrl"], origin="http://127.0.0.1:9222", timeout=5)
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": "document.body && document.body.classList.contains('offline')", "returnByValue": True}}))
        res = json.loads(ws.recv()); ws.close()
        return "offline" if res.get("result", {}).get("result", {}).get("value") else "ok"
    except Exception:
        return None


def browser_age_s():
    try:
        out = subprocess.run(["pgrep", "-o", "-f", "/usr/lib/chromium/chromium"], capture_output=True, text=True).stdout.strip()
        if not out:
            return 0
        with open(f"/proc/{out}/stat") as f:
            start_ticks = int(f.read().split(")")[1].split()[19])
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        return up - start_ticks / os.sysconf("SC_CLK_TCK")
    except Exception:
        return 0


def restart(reason):
    log(f"restarting the browser: {reason}")
    subprocess.run(["pkill", "-f", "/usr/lib/chromium/chromium"], capture_output=True)


def main():
    bad_since = None
    last_nightly = None
    while True:
        time.sleep(CHECK_S)
        try:
            now = time.time()
            st = page_state()
            broken = (st is None) or (st == "offline" and server_ok())
            if broken:
                bad_since = bad_since or now
                if now - bad_since >= 60:
                    restart("page could not reach the server for a minute" if st == "offline" else "browser not responding")
                    bad_since = None
                    time.sleep(30)
                continue
            bad_since = None
            pct = tmp_used_pct()
            if pct > 70 and idle_seconds() > 120:
                restart(f"/tmp is {pct:.0f} % full (browser shared-memory leak)")
                time.sleep(30)
                continue
            lt = time.localtime(now)
            if lt.tm_hour == 4 and last_nightly != lt.tm_yday and browser_age_s() > 12 * 3600 and idle_seconds() > 120:
                last_nightly = lt.tm_yday
                restart("nightly refresh")
                time.sleep(30)
        except Exception as e:
            log(f"check failed: {e}")


if __name__ == "__main__":
    main()
