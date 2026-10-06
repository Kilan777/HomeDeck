#!/usr/bin/env bash
# The power button belongs to HomeDeck, not to the desktop.
#
# The gpio-shutdown overlay turns the button on J18 into a KEY_POWER press. Three things listen for it: logind (told
# to ignore it by install.sh), the desktop, and our display module (short press toggles the screen, long press shuts
# down). The Raspberry Pi desktop binds the key to /usr/bin/pwrkey, which opens the shutdown dialog on the first
# press and calls `shutdown -h now` on the next one. That is why a second press used to power the device off instead
# of waking the screen.
#
# Two layers, so it holds whichever way labwc merges its config:
#   1. a no-op `pwrkey` earlier in PATH (/usr/local/bin), leaving the distro's file untouched
#   2. an explicit do-nothing binding for the key in the user's labwc config
# Run on the Pi with sudo. Takes effect immediately for the shim, at the next login for the binding.
set -euo pipefail
U="${SUDO_USER:-kilan}"
HOMEDIR=$(getent passwd "$U" | cut -d: -f6)

# 1. shim: /usr/local/bin comes before /usr/bin in PATH, so the desktop's power-key command does nothing
install -d /usr/local/bin
cat > /usr/local/bin/pwrkey <<'EOF'
#!/bin/sh
# HomeDeck owns the power button (see modules/display.py). The desktop's dialog and its "second press shuts down"
# behaviour are deliberately disabled here. Delete this file to restore the Raspberry Pi behaviour.
exit 0
EOF
chmod 755 /usr/local/bin/pwrkey
pkill -f pishutdown 2>/dev/null || true     # close the dialog if it is open right now

# 2. binding: add a no-op for the key to the user's labwc config, whatever root element it uses
RC="$HOMEDIR/.config/labwc/rc.xml"
mkdir -p "$(dirname "$RC")"
[ -f "$RC" ] || printf '<?xml version="1.0"?>\n<openbox_config xmlns="http://openbox.org/3.4/rc">\n</openbox_config>\n' > "$RC"
cp "$RC" "$RC.bak-powerbutton"
python3 - "$RC" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p).read()
s = re.sub(r'\s*<keybind key="XF86PowerOff".*?</keybind>', '', s, flags=re.S)
bind = ('\n    <!-- HomeDeck owns the power button: modules/display.py reads the key directly -->\n'
        '    <keybind key="XF86PowerOff"><action name="None"/></keybind>\n'
        '    <keybind key="XF86PowerOff" onRelease="yes"><action name="None"/></keybind>')
if re.search(r'<keyboard\s*>', s):
    s = re.sub(r'<keyboard\s*>', lambda m: m.group(0) + bind, s, count=1)
else:
    s = re.sub(r'</(openbox_config|labwc_config)>', lambda m: '  <keyboard>' + bind + '\n  </keyboard>\n' + m.group(0), s, count=1)
open(p, 'w').write(s)
print("power key bound to nothing in", p)
PY
chown "$U":"$U" "$RC" "$RC.bak-powerbutton" 2>/dev/null || true
echo "done: the desktop no longer acts on the power button"
