#!/usr/bin/env bash
# Waits for the HomeDeck server, rotates the 720x1280 panel to landscape, then runs Chromium in kiosk mode.
# rotate first, from the file the display module keeps (no waiting on the server), so nothing is ever shown portrait
OUT=$(wlr-randr 2>/dev/null | awk '/^[A-Z]/{print $1; exit}')
TR=$(cat /var/lib/homedeck/orientation 2>/dev/null | tr -d '[:space:]'); [ -n "$TR" ] || TR=normal
[ -n "$OUT" ] && wlr-randr --output "$OUT" --transform $TR >/dev/null 2>&1 || true
# watchdog: restarts the browser if its temp space fills (shared-memory leak) or the page loses the server
pgrep -f "kiosk_watchdog[.]py" >/dev/null || (setsid /opt/homedeck/venv/bin/python /opt/homedeck/install/kiosk_watchdog.py >>"$HOME/.cache/homedeck-kiosk-watchdog.log" 2>&1 < /dev/null &)
# the browser starts immediately on a local black "Jarvis" page that hands over to the UI when the server is up
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8   # US date/number formats in the UI
# Browser sound goes through the same ALSA dmix/softvol chain as Jarvis and Spotify (not PipeWire, which would grab the
# card exclusively and make everything else "device busy"): point Chromium at a dead Pulse socket so it falls back to ALSA.
export PULSE_SERVER=unix:/nonexistent
while true; do
  chromium --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble --disable-features=TranslateUI \
    --overscroll-history-navigation=0 --disable-pinch --autoplay-policy=no-user-gesture-required --check-for-update-interval=31536000 \
    --force-device-scale-factor=1.44 --user-data-dir=/tmp/homedeck-kiosk --ozone-platform=wayland --lang=en-US --password-store=basic --touch-events=enabled --enable-wayland-ime --alsa-output-device=homedeck_music --alsa-input-device=null --remote-debugging-port=9222 --remote-allow-origins=http://127.0.0.1:9222 "file:///opt/homedeck/web/boot.html" >/dev/null 2>&1
  sleep 2
done
