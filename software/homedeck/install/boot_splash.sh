#!/usr/bin/env bash
# HomeDeck boot look: a black "Jarvis" Plymouth splash instead of the Raspberry Pi one, no rainbow square, and a black,
# panel-free desktop in the seconds between the splash and the kiosk browser. Run on the Pi with sudo, from install/.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T=/usr/share/plymouth/themes/homedeck
mkdir -p "$T"
cp "$HERE/splash/homedeck.script" "$T/homedeck.script"
cp "$HERE/splash/splash.png" "$HERE/splash/track.png" "$HERE/splash/fill.png" "$HERE/splash/glow.png" "$T/"
cat > "$T/homedeck.plymouth" <<EOP
[Plymouth Theme]
Name=homedeck
Description=Jarvis HomeDeck boot splash
ModuleName=script

[script]
ImageDir=$T
ScriptFile=$T/homedeck.script
EOP
plymouth-set-default-theme -R homedeck
grep -q '^disable_splash=1' /boot/firmware/config.txt || printf '\n# no rainbow square at power-on\ndisable_splash=1\n' >> /boot/firmware/config.txt
# desktop under the kiosk: the same "Jarvis / Booting" artwork as the splash, no icons, panel hidden; the browser then
# shows an identical page until the server is up, so the whole boot reads as one screen
U="${SUDO_USER:-kilan}"; HOMEDIR=$(getent passwd "$U" | cut -d: -f6)
mkdir -p "$HOMEDIR/.config/pcmanfm/default"
for n in 0 DSI-1; do cat > "$HOMEDIR/.config/pcmanfm/default/desktop-items-$n.conf" <<EOP
[*]
wallpaper_mode=fit
wallpaper=/opt/homedeck/install/splash/splash_landscape.png
desktop_bg=#000000
desktop_fg=#000000
desktop_shadow=#000000
show_documents=0
show_trash=0
show_mounts=0
EOP
done
mkdir -p "$HOMEDIR/.config/wf-panel-pi"
PI="$HOMEDIR/.config/wf-panel-pi/wf-panel-pi.ini"           # the panel reads this path, not ~/.config/wf-panel-pi.ini
# hidden panel with no widgets: nothing to show and no "connected to network" bubbles at boot
printf '[panel]\nautohide=true\nautohide_duration=1\nwidgets_left=\nwidgets_right=\n' > "$PI"
rm -f "$HOMEDIR/.config/wf-panel-pi.ini"
chown -R "$U":"$U" "$HOMEDIR/.config/pcmanfm" "$HOMEDIR/.config/wf-panel-pi"
echo "boot splash installed: theme homedeck, rainbow splash off, desktop black; takes effect at next boot"
