#!/usr/bin/env bash
# HomeDeck: make the CM4 a Spotify Connect speaker named "HomeDeck" using raspotify (librespot).
# Idempotent: safe to re-run. Needs Spotify Premium on the account that will play to it.
# Audio goes out through the board's I2S DAC (voicehat card); the amp enable is handled by the audio overlay.
set -euo pipefail

DEVICE_NAME="${DEVICE_NAME:-HomeDeck}"
ALSA_DEVICE="${ALSA_DEVICE:-default}"   # ALSA softvol device from install/audio_setup.sh (system volume)
CONF=/etc/raspotify/conf

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root: sudo $0" >&2
  exit 1
fi

if ! command -v librespot >/dev/null 2>&1 && ! dpkg -s raspotify >/dev/null 2>&1; then
  echo "== installing raspotify"
  curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
else
  echo "== raspotify already installed"
fi

echo "== writing $CONF"
mkdir -p "$(dirname "$CONF")"
[ -f "$CONF" ] && cp -n "$CONF" "$CONF.orig" || true
# strip any earlier values we manage, keep everything else the user may have added
if [ -f "$CONF" ]; then
  sed -i -E '/^(LIBRESPOT_NAME|LIBRESPOT_DEVICE|LIBRESPOT_BITRATE|LIBRESPOT_INITIAL_VOLUME|LIBRESPOT_BACKEND|LIBRESPOT_DEVICE_TYPE)=/d' "$CONF"
fi
cat >>"$CONF" <<EOF
# --- managed by HomeDeck install/spotify_deps.sh ---
LIBRESPOT_NAME="${DEVICE_NAME}"
LIBRESPOT_DEVICE="${ALSA_DEVICE}"
LIBRESPOT_BACKEND="alsa"
LIBRESPOT_BITRATE="320"
LIBRESPOT_INITIAL_VOLUME="100"
LIBRESPOT_DEVICE_TYPE="speaker"
LIBRESPOT_VOLUME_CTRL="fixed"
EOF

echo "== enabling service"
systemctl daemon-reload
systemctl enable raspotify >/dev/null 2>&1 || true
systemctl restart raspotify
sleep 2
if systemctl is-active --quiet raspotify; then
  echo "raspotify running. '${DEVICE_NAME}' should now appear as a device in the Spotify app (Premium required)."
else
  echo "raspotify failed to start; last log lines:" >&2
  journalctl -u raspotify --no-pager -n 20 >&2
  exit 1
fi

# NOTE (2026-09-20): the speaker is now go-librespot, see install/go_librespot.sh. raspotify is disabled on the device.
