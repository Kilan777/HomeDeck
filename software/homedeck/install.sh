#!/usr/bin/env bash
# HomeDeck installer: run ON the Pi as the login user (kilan) with sudo rights, from the unpacked hd/ folder.
#   bash install.sh            # install/update everything and (re)start the service
#   bash install.sh --no-kiosk # skip the kiosk/autologin setup
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
APP=/opt/homedeck
DATA=/var/lib/homedeck
USER_NAME="${SUDO_USER:-$USER}"
KIOSK=1; [[ "${1:-}" == "--no-kiosk" ]] && KIOSK=0

echo "== packages"
sudo apt-get install -y -q python3-smbus2 python3-numpy python3-picamera2 python3-spidev rclone espeak-ng ffmpeg alsa-utils >/dev/null 2>&1 || \
  sudo apt-get install -y -q python3-numpy python3-picamera2 python3-spidev rclone espeak-ng ffmpeg alsa-utils

echo "== files -> $APP"
sudo mkdir -p "$APP" "$DATA/clips" "$DATA/sounds"
sudo rsync -a --delete --exclude 'install' --exclude 'venv' "$SRC/" "$APP/"
sudo cp -r "$SRC/install" "$APP/" 2>/dev/null || true
sudo chown -R root:root "$APP"
sudo chown -R "$USER_NAME":"$USER_NAME" "$DATA"

echo "== power button: short press = screen, long press = shutdown (logind must not poweroff on the key)"
sudo mkdir -p /etc/systemd/logind.conf.d
printf "[Login]\nHandlePowerKey=ignore\nHandlePowerKeyLongPress=ignore\n" | sudo tee /etc/systemd/logind.conf.d/homedeck.conf >/dev/null
sudo systemctl restart systemd-logind 2>/dev/null || true

echo "== activity LED off"
# The CM4 activity LED sits behind the display and shows through it as a faint flickering square; with heavy
# eMMC writes it flickers non-stop. Keep it off.
sudo tee /etc/systemd/system/homedeck-act-led-off.service >/dev/null <<'EOF'
[Unit]
Description=HomeDeck: activity LED off (it shows through the display)
DefaultDependencies=no
After=sysinit.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo none > /sys/class/leds/ACT/trigger; echo 0 > /sys/class/leds/ACT/brightness'
RemainAfterExit=yes

[Install]
WantedBy=sysinit.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now homedeck-act-led-off.service >/dev/null 2>&1 || true

echo "== network tuning for uploads"
# BBR copes far better than cubic with the lossy, bufferbloated home uplink (measured 0.8 -> 3.7 Mbit/s on the same
# link), and Wi-Fi power saving on the CM4 dozes the radio between packets (router ping 118 ms -> 40 ms with it off).
printf "net.core.default_qdisc=fq\nnet.ipv4.tcp_congestion_control=bbr\n" | sudo tee /etc/sysctl.d/90-homedeck-bbr.conf >/dev/null
echo tcp_bbr | sudo tee /etc/modules-load.d/homedeck-bbr.conf >/dev/null
sudo modprobe tcp_bbr 2>/dev/null; echo bbr | sudo tee /proc/sys/net/ipv4/tcp_congestion_control >/dev/null; echo fq | sudo tee /proc/sys/net/core/default_qdisc >/dev/null
printf "[connection]\nwifi.powersave = 2\n" | sudo tee /etc/NetworkManager/conf.d/homedeck-wifi-powersave-off.conf >/dev/null
for c in $(nmcli -t -f NAME,TYPE con show | awk -F: '$2=="802-11-wireless"{print $1}'); do sudo nmcli con modify "$c" 802-11-wireless.powersave 2; done
command -v iw >/dev/null && sudo iw dev wlan0 set power_save off 2>/dev/null || true

echo "== write video to storage within seconds"
# the camera writes continuously; the kernel's default 30 s write-back delay means a power cut loses up to ~30 s
printf "vm.dirty_expire_centisecs=500\nvm.dirty_writeback_centisecs=200\n" | sudo tee /etc/sysctl.d/91-homedeck-writeback.conf >/dev/null
echo 500 | sudo tee /proc/sys/vm/dirty_expire_centisecs >/dev/null; echo 200 | sudo tee /proc/sys/vm/dirty_writeback_centisecs >/dev/null

echo "== network watchdog"
sudo install -m 755 "$HERE/install/net_watchdog.sh" /usr/local/bin/homedeck-netwatch
sudo tee /etc/systemd/system/homedeck-netwatch.service >/dev/null <<'EOF'
[Unit]
Description=HomeDeck network watchdog (reconnect Wi-Fi when the router stops answering)
After=NetworkManager.service

[Service]
ExecStart=/usr/local/bin/homedeck-netwatch
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload; sudo systemctl enable --now homedeck-netwatch.service >/dev/null 2>&1 || true

echo "== close unused ports"
# rpcbind (port 111, "sunrpc") is only for NFS shares, which the HomeDeck does not use
sudo systemctl disable --now rpcbind.service rpcbind.socket >/dev/null 2>&1 || true
sudo systemctl mask rpcbind.service rpcbind.socket >/dev/null 2>&1 || true

echo "== service"
sudo tee /etc/systemd/system/homedeck.service >/dev/null <<EOF
[Unit]
Description=HomeDeck assistant (server, sensors, camera, voice, alarms)
After=network-online.target sound.target
Wants=network-online.target
# if it cannot stay up (crash loop, or a thread stuck in the kernel that survives a restart), reboot the Pi
StartLimitIntervalSec=600
StartLimitBurst=10
StartLimitAction=reboot

[Service]
ExecStart=/bin/sh -c "exec \$([ -x $APP/venv/bin/python ] && echo $APP/venv/bin/python || echo /usr/bin/python3) $APP/server.py"
WorkingDirectory=$APP
Environment=HOMEDECK_DATA=$DATA
Restart=always
RestartSec=3
# server.py pings the watchdog only while /api/health answers: a wedged server (handle leak, deadlock) is restarted
WatchdogSec=180
NotifyAccess=main
TimeoutStopSec=20
User=root

[Install]
WantedBy=multi-user.target
EOF
# the old bench dashboard used the same port and the camera; retire it
sudo systemctl disable --now homedeck-ui.service 2>/dev/null || true
sudo systemctl daemon-reload
sudo systemctl enable homedeck.service >/dev/null
sudo systemctl restart homedeck.service

if [[ $KIOSK == 1 ]]; then
  echo "== kiosk (Chromium full screen on the touch panel, autologin, no blanking)"
  sudo raspi-config nonint do_boot_behaviour B4 >/dev/null 2>&1 || true   # desktop autologin
  sudo raspi-config nonint do_blanking 1 >/dev/null 2>&1 || true          # 1 = disable screen blanking
  HOME_DIR=$(getent passwd "$USER_NAME" | cut -d: -f6)
  mkdir -p "$HOME_DIR/.config/labwc"
  AUTOSTART="$HOME_DIR/.config/labwc/autostart"
  touch "$AUTOSTART"
  grep -q homedeck-kiosk "$AUTOSTART" || cat >> "$AUTOSTART" <<'EOF'
# homedeck-kiosk: full-screen HomeDeck UI on the built-in display
/opt/homedeck/install/kiosk.sh &
EOF
  sudo tee "$APP/install/kiosk.sh" >/dev/null <<'EOF'
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
    --force-device-scale-factor=1.44 --user-data-dir=/tmp/homedeck-kiosk --ozone-platform=wayland --lang=en-US --password-store=basic --touch-events=enabled --enable-wayland-ime --alsa-output-device=default --alsa-input-device=null --remote-debugging-port=9222 --remote-allow-origins=http://127.0.0.1:9222 "file:///opt/homedeck/web/boot.html" >/dev/null 2>&1
  sleep 2
done
EOF
  sudo chmod +x "$APP/install/kiosk.sh"
  sudo bash "$APP/install/power_button.sh" >/dev/null 2>&1 || true   # the power key belongs to HomeDeck, not the desktop
  echo "   kiosk autostart written to $AUTOSTART (takes effect at next login/boot)"
fi

sleep 3
if systemctl is-active --quiet homedeck.service; then
  IP=$(hostname -I | awk '{print $1}')
  echo "== HomeDeck is running: http://$IP:8080  (phone)   http://localhost:8080/?kiosk=1 (device)"
else
  echo "== service failed to start; last log lines:"; sudo journalctl -u homedeck.service --no-pager -n 30
  exit 1
fi
