#!/usr/bin/env bash
# HomeDeck audio: a software volume control (ALSA softvol) in front of the PCM5102A/TPA3118 card, which has no
# hardware mixer. Everything that plays through pcm "default" or "homedeck" obeys the "HomeDeck" control.
# Idempotent. Run with sudo on the Pi.
set -euo pipefail
CARD="${1:-sndrpigooglevoi}"
ok(){ echo "  OK   $*"; }; fail(){ echo "  FAIL $*"; }

echo "==> ALSA loopback for the echo-cancellation reference (snd-aloop, clocked from the I2S card)"
echo "snd-aloop" | sudo tee /etc/modules-load.d/homedeck-aloop.conf >/dev/null
echo "options snd-aloop index=5 id=Loopback pcm_substreams=1 timer_source=${CARD}" | sudo tee /etc/modprobe.d/homedeck-aloop.conf >/dev/null
sudo mkdir -p /etc/wireplumber/wireplumber.conf.d
sudo tee /etc/wireplumber/wireplumber.conf.d/60-homedeck-ignore-loopback.conf >/dev/null <<'EOW'
# HomeDeck: the ALSA loopback card carries the echo-cancellation reference; PipeWire must never open it
monitor.alsa.rules = [
  {
    matches = [ { device.name = "~alsa_card.platform-snd_aloop.*" } ]
    actions = { update-props = { device.disabled = true } }
  }
]
EOW
lsmod | grep -q snd_aloop || sudo modprobe snd-aloop index=5 id=Loopback pcm_substreams=1 timer_source="${CARD}"
ok "snd-aloop loaded and persisted"

echo "==> /etc/asound.conf"
sudo tee /etc/asound.conf >/dev/null <<EOF
# HomeDeck: software volume for the speaker amp (no hardware mixer on this DAC)
pcm.homedeck_raw { type hw; card ${CARD}; device 0 }
# dmix lets several players (speech, chirp, alarm, Spotify, browser) share the card instead of "device busy"
pcm.homedeck_mix { type dmix; ipc_key 5978293; ipc_perm 0666; slave { pcm "homedeck_raw"; rate 48000; format S32_LE; channels 2; period_size 1024; buffer_size 8192 } }
# echo-cancellation reference: an identical copy of the speaker feed goes to the ALSA loopback card (snd-aloop,
# clocked from the I2S card); homedeck-aec reads it back from hw:Loopback,1,0
pcm.homedeck_loopmix { type dmix; ipc_key 5978294; ipc_perm 0666; slave { pcm "hw:Loopback,0,0"; rate 48000; format S32_LE; channels 2; period_size 1024; buffer_size 8192 } }
pcm.homedeck_both {
  type multi
  slaves.a { pcm "homedeck_mix"; channels 2 }
  slaves.b { pcm "homedeck_loopmix"; channels 2 }
  bindings.0 { slave a; channel 0 }
  bindings.1 { slave a; channel 1 }
  bindings.2 { slave b; channel 0 }
  bindings.3 { slave b; channel 1 }
  master 0
}
pcm.homedeck_tee { type route; slave.pcm "homedeck_both"; slave.channels 4; ttable.0.0 1; ttable.1.1 1; ttable.0.2 1; ttable.1.3 1 }
# 10-band equaliser (alsaequal + caps Eq10) in front of the volume control (default -> plug -> equal -> plug ->
# softvol -> tee), so the echo-cancellation reference still hears exactly what the speakers get. Bands are set by
# the audio module (bass/treble, room calibration) through the "equal" mixer. The plugin only takes S16 and the
# chain only negotiates in this order (softvol in front of it fails hw_params), hence the plugs.
pcm.homedeck_eq { type equal; slave.pcm "plug:homedeck"; controls "/var/lib/homedeck/alsaequal.bin"; channels 2 }
ctl.equal { type equal; controls "/var/lib/homedeck/alsaequal.bin" }
pcm.homedeck { type softvol; slave.pcm "homedeck_tee"; control { name "HomeDeck"; card ${CARD} }; max_dB 0.0; min_dB -40.0; resolution 101 }
# music path: the same equaliser, then its own volume ("Music" control: the music volume, also ducked while Jarvis
# listens and answers), straight to the tee. Spotify and the browser play through homedeck_music; speech, timers
# and alarms go through "default" and the "HomeDeck" control (the Jarvis volume). The two are independent.
pcm.homedeck_musicvol { type softvol; slave.pcm "homedeck_tee"; control { name "Music"; card ${CARD} }; max_dB 0.0; min_dB -40.0; resolution 101 }
pcm.homedeck_eq_music { type equal; slave.pcm "plug:homedeck_musicvol"; controls "/var/lib/homedeck/alsaequal.bin"; channels 2 }
pcm.homedeck_music { type plug; slave.pcm "homedeck_eq_music" }
pcm.!default { type plug; slave.pcm "homedeck_eq" }
ctl.!default { type hw; card ${CARD} }
EOF
ok "asound.conf written (card ${CARD})"
echo "==> equaliser plugin (alsaequal + caps)"
sudo apt-get install -y -q libasound2-plugin-equal >/dev/null && ok "libasound2-plugin-equal installed" || fail "libasound2-plugin-equal (bass/treble and room calibration unavailable)"
# the plugin mmaps its state file and crashes (bus error) on an empty one: never touch it, let the plugin create it
[[ -s /var/lib/homedeck/alsaequal.bin ]] || rm -f /var/lib/homedeck/alsaequal.bin
amixer -D equal scontrols >/dev/null 2>&1 && sudo chmod 666 /var/lib/homedeck/alsaequal.bin && ok "equaliser state at /var/lib/homedeck/alsaequal.bin" || fail "equaliser mixer"

echo "==> initialising the softvol control (appears on first playback)"
head -c 38400 /dev/zero | aplay -q -D homedeck -f S16_LE -r 48000 -c 2 -t raw 2>/dev/null || true
if amixer -c "${CARD}" sget HomeDeck >/dev/null 2>&1; then
  amixer -c "${CARD}" sset HomeDeck 55% >/dev/null && ok "HomeDeck control ready, set to 55%"
else
  fail "HomeDeck control did not appear; is the card '${CARD}' present? (aplay -l)"
fi
command -v sox >/dev/null 2>&1 || { sudo apt-get install -y -qq sox >/dev/null 2>&1 && ok "sox installed (speech high-pass)" || fail "sox not installed (optional)"; }
echo "==> raspotify: point it at the softvol device if installed"
if [[ -f /etc/raspotify/conf ]]; then
  sudo sed -i -E 's|^LIBRESPOT_DEVICE=.*|LIBRESPOT_DEVICE="default"|' /etc/raspotify/conf && sudo systemctl restart raspotify 2>/dev/null && ok "raspotify -> default (plug over softvol)" || fail "raspotify restart"
fi
echo "==> echo canceller (homedeck-aec, WebRTC AEC3)"
HERE="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$HERE/aec/build.sh" ]]; then sudo bash "$HERE/aec/build.sh" && ok "homedeck-aec built" || fail "homedeck-aec build (voice falls back to the plain mic)"; fi
echo "done: restart homedeck.service to pick up the control"
