#!/bin/sh
# librespot --onevent hook (raspotify: LIBRESPOT_ONEVENT). librespot runs this with the playback event in environment
# variables (PLAYER_EVENT, TRACK_ID, POSITION_MS, DURATION_MS, NAME, ARTISTS, ALBUM, COVERS, SHUFFLE, REPEAT, ...).
# It forwards them to the HomeDeck server so now-playing follows what the speaker actually plays instead of the
# Spotify Web API, which can lag or desync. Installed at /usr/local/bin/homedeck-spotify-event. Fire and forget.
exec /usr/bin/python3 - <<'PY'
import json, os, urllib.request
SKIP = ("PATH", "HOME", "LANG", "PWD", "OLDPWD", "SHLVL", "_", "TMPDIR", "USER", "LOGNAME", "SHELL", "TERM", "PYTHONPATH",
        "INVOCATION_ID", "JOURNAL_STREAM", "SYSTEMD_EXEC_PID", "LISTEN_PID", "LISTEN_FDS", "NOTIFY_SOCKET", "RUST_BACKTRACE")
ev = {k: v for k, v in os.environ.items() if k.isupper() and not k.startswith(("LIBRESPOT_", "SYSTEMD_", "XDG_", "DBUS_", "LC_")) and k not in SKIP}
if not ev.get("PLAYER_EVENT"):
    raise SystemExit(0)
try:
    req = urllib.request.Request("http://127.0.0.1:8080/api/spotify/local_event", data=json.dumps(ev).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=2).read()
except Exception:
    pass
PY
