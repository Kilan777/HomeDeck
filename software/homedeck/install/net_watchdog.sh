#!/bin/bash
# HomeDeck network watchdog (homedeck-netwatch.service).
# 2026-10-06: the Wi-Fi link went dead without any disconnect event (Eero roam at 08:31, traffic stopped ~10:50, DHCP
# renewal failed at 14:31) and nothing noticed for 7 hours; the camera kept recording but could not upload.
# Every 30 s: is the router (or the internet) reachable? If neither for 3 min, reconnect Wi-Fi; at 6 min reload the
# Wi-Fi driver; after that retry every 12 min. Never reboots (a warm reboot can hang the display controller).
log() { echo "netwatch: $*"; }
fail=0
while true; do
  gw=$(ip route 2>/dev/null | awk '/^default/{print $3; exit}')
  ok=0
  if [ -n "$gw" ] && ping -c2 -W3 -q "$gw" >/dev/null 2>&1; then ok=1
  elif ping -c2 -W3 -q 1.1.1.1 >/dev/null 2>&1; then ok=1; fi
  if [ "$ok" = 1 ]; then
    [ "$fail" -ge 6 ] && log "network back after about $((fail * 30 / 60)) min"
    fail=0
  else
    fail=$((fail + 1))
    if [ "$fail" -eq 6 ]; then
      log "router unreachable for 3 min (gateway '${gw:-none}'): reconnecting Wi-Fi"
      nmcli dev disconnect wlan0 >/dev/null 2>&1; sleep 3; nmcli dev connect wlan0 >/dev/null 2>&1
    elif [ "$fail" -eq 12 ]; then
      log "still unreachable after 6 min: reloading the Wi-Fi driver"
      modprobe -r brcmfmac_wcc brcmfmac 2>/dev/null; sleep 3; modprobe brcmfmac; sleep 15
      nmcli dev connect wlan0 >/dev/null 2>&1
    elif [ "$fail" -gt 12 ] && [ $(( (fail - 12) % 24 )) -eq 0 ]; then
      log "still unreachable after $((fail * 30 / 60)) min: Wi-Fi radio off and on"
      nmcli radio wifi off; sleep 5; nmcli radio wifi on; sleep 15; nmcli dev connect wlan0 >/dev/null 2>&1
    fi
  fi
  sleep 30
done
