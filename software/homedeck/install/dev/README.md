# Dev helpers (run on the Pi)

- `cdp_eval.py "<js>"` runs JavaScript in the kiosk Chromium through DevTools on 127.0.0.1:9222, e.g.
  `HD.openApp("sensors")` then `grim /tmp/shot.png` (with `WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000`)
  for a screenshot of a page, and `HD.showIdle()` to go back.
- `threadcpu.py <pid> [seconds]` per-thread CPU of the service (`systemctl show -p MainPID --value homedeck`).
- `aecdump_analyze.py` per-second echo reduction and echo delay for both mics from a helper dump
  (`kill -USR1` the homedeck-aec process after setting dump_s in /var/lib/homedeck/aec_runtime.conf).
- `wake_mix.py` offline check that summing two mics keeps the wake word detectable (needs the piper voices).
