#!/usr/bin/env bash
# HomeDeck speaker: go-librespot replaces raspotify/librespot.
#   - Spotify Connect speaker "HomeDeck" on the shared ALSA chain (dmix + softvol "default")
#   - local HTTP API + event websocket on 127.0.0.1:3678 that modules/spotify.py uses for transport and now-playing,
#     so playback never depends on the Web API "activation" that librespot needed after every restart
# Run ON the Pi as the login user (sudo rights). Idempotent. Re-run to upgrade the binary.
set -euo pipefail
VER="${GO_LIBRESPOT_VERSION:-v0.10.0}"
USER_NAME="${SUDO_USER:-$USER}"
HOME_DIR=$(getent passwd "$USER_NAME" | cut -d: -f6)
CFG="$HOME_DIR/.config/go-librespot"
ARCH=$(uname -m); case "$ARCH" in aarch64) A=arm64;; armv7l|armv6l) A=armv6_rpi;; x86_64) A=x86_64;; *) echo "unsupported arch $ARCH"; exit 1;; esac

echo "== binary $VER ($A)"
tmp=$(mktemp -d); curl -sL -o "$tmp/gl.tgz" "https://github.com/devgianlu/go-librespot/releases/download/$VER/go-librespot_linux_$A.tar.gz"
tar xzf "$tmp/gl.tgz" -C "$tmp"; sudo install -m 755 "$tmp/go-librespot" /usr/local/bin/go-librespot; rm -rf "$tmp"

echo "== config -> $CFG/config.yml"
mkdir -p "$CFG"
[ -f "$CFG/config.yml" ] || cat > "$CFG/config.yml" <<'YAML'
log_level: info
device_name: HomeDeck
device_type: speaker
audio_backend: alsa
audio_device: homedeck_music   # HomeDeck's music path: equaliser + Music (ducking) + master volume (install/audio_setup.sh)
bitrate: 320
external_volume: true          # HomeDeck's softvol is the volume; Spotify's level is mirrored, not multiplied in
volume_steps: 100
initial_volume: 100
zeroconf_enabled: true         # stays discoverable for the phone's Spotify app
zeroconf_backend: builtin
credentials:
  type: zeroconf
  zeroconf:
    persist_credentials: true  # the first pick from the phone is remembered in state.json
server:
  enabled: true
  address: 127.0.0.1
  port: 3678
  image_size: large
cache:
  enabled: true
  size_limit: 512MB
YAML

# Reuse librespot/raspotify's stored credentials if this machine had them: no phone pairing needed at all.
if [ ! -s "$CFG/state.json" ] && sudo test -f /var/cache/raspotify/credentials.json; then
  echo "== reusing raspotify credentials"
  sudo python3 - "$CFG/state.json" <<'PY'
import json, sys
c = json.load(open("/var/cache/raspotify/credentials.json"))
json.dump({"device_id": "", "credentials": {"username": c["username"], "data": c["auth_data"]}}, open(sys.argv[1], "w"))
PY
  sudo chown "$USER_NAME":"$USER_NAME" "$CFG/state.json"; chmod 600 "$CFG/state.json"
fi

echo "== service"
sudo tee /etc/systemd/system/go-librespot.service >/dev/null <<EOT
[Unit]
Description=go-librespot Spotify Connect speaker (HomeDeck)
After=network-online.target sound.target
Wants=network-online.target

[Service]
User=$USER_NAME
Group=audio
ExecStart=/usr/local/bin/go-librespot --config_dir $CFG
Restart=always
RestartSec=3
Environment=HOME=$HOME_DIR

[Install]
WantedBy=multi-user.target
EOT
sudo systemctl disable --now raspotify >/dev/null 2>&1 || true
sudo systemctl daemon-reload; sudo systemctl enable --now go-librespot >/dev/null; sudo systemctl restart go-librespot
sleep 5
if curl -sf 127.0.0.1:3678/status >/dev/null; then
  echo "== go-librespot up: $(curl -s 127.0.0.1:3678/status | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["device_name"], "as", d["username"] or "(not logged in: pick HomeDeck once in the Spotify app on your phone)")')"
else
  echo "== go-librespot did not answer; see: journalctl -u go-librespot -n 30"; exit 1
fi
