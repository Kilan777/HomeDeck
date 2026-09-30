#!/bin/bash
# Ask the home router (UPnP / NAT-PMP) to forward 443 and 80 to this Pi's current LAN address.
# Runs every 5 minutes from a systemd timer, so it follows DHCP changes and survives router reboots.
IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')
[ -z "$IP" ] && exit 0
for port in 443 80; do
  upnpc -e "HomeDeck" -a "$IP" "$port" "$port" TCP 604800 >/dev/null 2>&1 || upnpc -e "HomeDeck" -a "$IP" "$port" "$port" TCP >/dev/null 2>&1
done
upnpc -l 2>/dev/null | grep -E "TCP +(443|80)->" | head -2
