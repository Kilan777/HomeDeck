#!/usr/bin/env bash
# HomeDeck remote access: Caddy (HTTPS, Let's Encrypt) in front of the app + DuckDNS updater. Idempotent. No curl|sh.
#   sudo bash remote_access.sh [<duckdns-subdomain> <duckdns-token>]
# The Google sign-in itself is configured in the app: Settings > Remote access.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SUB="${1:-}"; TOKEN="${2:-}"
ok(){ echo "  OK   $*"; }; fail(){ echo "  FAIL $*"; }

echo "==> Caddy"
if ! command -v caddy >/dev/null 2>&1; then
  sudo apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl >/dev/null 2>&1 || true
  sudo curl -fsSL -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    && sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null || true
  sudo curl -fsSL -o /etc/apt/sources.list.d/caddy-stable.list 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt'
  sudo apt-get update -qq >/dev/null 2>&1
  sudo apt-get install -y -qq caddy >/dev/null 2>&1 && ok "caddy installed ($(caddy version | head -1))" || { fail "caddy install failed"; exit 1; }
else
  ok "caddy already installed ($(caddy version | head -1))"
fi
sudo install -m 644 "$HERE/Caddyfile" /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1 && ok "Caddyfile valid" || { fail "Caddyfile invalid"; sudo caddy validate --config /etc/caddy/Caddyfile; exit 1; }
sudo systemctl enable caddy >/dev/null 2>&1
sudo systemctl restart caddy && ok "caddy running (ports 80/443)"

echo "==> DuckDNS updater (keeps the public name pointing at this house when the ISP changes the IP)"
sudo mkdir -p /etc/homedeck
if [[ -n "$SUB" && -n "$TOKEN" ]]; then
  printf 'DUCKDNS_SUB=%s\nDUCKDNS_TOKEN=%s\n' "$SUB" "$TOKEN" | sudo tee /etc/homedeck/duckdns.env >/dev/null
  sudo chmod 600 /etc/homedeck/duckdns.env
  ok "duckdns credentials written to /etc/homedeck/duckdns.env"
fi
sudo tee /usr/local/bin/homedeck-duckdns >/dev/null <<'EOF'
#!/usr/bin/env bash
# Updates the DuckDNS record with this connection's public IP (DuckDNS detects it from the request).
[ -f /etc/homedeck/duckdns.env ] || exit 0
. /etc/homedeck/duckdns.env
[ -n "${DUCKDNS_SUB:-}" ] && [ -n "${DUCKDNS_TOKEN:-}" ] || exit 0
r=$(curl -fsS -m 20 "https://www.duckdns.org/update?domains=${DUCKDNS_SUB}&token=${DUCKDNS_TOKEN}&ip=" || echo "ERR")
echo "$(date '+%F %T') duckdns: $r"
EOF
sudo chmod 755 /usr/local/bin/homedeck-duckdns
sudo tee /etc/systemd/system/homedeck-duckdns.service >/dev/null <<'EOF'
[Unit]
Description=HomeDeck DuckDNS update
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/homedeck-duckdns
EOF
sudo tee /etc/systemd/system/homedeck-duckdns.timer >/dev/null <<'EOF'
[Unit]
Description=HomeDeck DuckDNS update every 5 minutes
[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now homedeck-duckdns.timer >/dev/null 2>&1 && ok "duckdns timer enabled (every 5 min)"
if [[ -f /etc/homedeck/duckdns.env ]]; then
  sudo systemctl start homedeck-duckdns.service && ok "first duckdns update: $(sudo journalctl -u homedeck-duckdns.service -n 1 --no-pager -o cat)"
else
  echo "   (no DuckDNS credentials yet: rerun with  sudo bash remote_access.sh <sub> <token>)"
fi

cat <<'EOF'

==> What the owner still has to do
  1. DuckDNS: sign in at https://www.duckdns.org (Google login), create a subdomain, copy the token, then run
       sudo bash /opt/homedeck/install/remote_access.sh <subdomain> <token>
  2. Domain DNS (Squarespace / Google Domains): add   CNAME  jarvis  ->  <subdomain>.duckdns.org
  3. Home router: make sure UPnP is enabled (Eero app > Settings > Network settings > Advanced > UPnP). The Pi maps 443/80 itself.
     If UPnP is off, forward TCP 443 and 80 to the Pi manually instead.
  4. Google Cloud console > APIs & Services > Credentials > Create OAuth client (Web application):
       Authorized redirect URI:  https://jarvis.example.com/auth/callback
     Paste the client id + secret and your email in HomeDeck  Settings > Remote access, then switch Enable on.
  5. Open https://jarvis.example.com from anywhere and sign in with Google.
EOF
