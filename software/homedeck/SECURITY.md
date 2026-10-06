# HomeDeck security model

A personal smart-display with a camera and microphones, reachable from the internet at
`https://jarvis.example.com` through Caddy (HTTPS, Let's Encrypt) in front of the app on `127.0.0.1:8080`.

## What is protected, and how

| Surface | Protection |
|---|---|
| Every page, `/api/*`, camera stream/snapshots/clips, Spotify and cloud routes | `modules/auth.py` gate in `server.py`: Google Sign-In (OAuth 2.0 code flow + PKCE, HMAC-signed state), allow-listed email only, 30-day `hd_session` cookie (`Secure`, `HttpOnly`, `SameSite=Lax`, HMAC over expiry+id). POSTs must carry a matching `Origin`/`Referer`. 5 failed sign-ins per IP per 10 min lock that IP out; repeated failures push an ntfy alert. `X-Forwarded-For` is trusted only from Caddy on localhost. |
| The device's own screen | Requests from localhost without `X-Forwarded-For` (the kiosk browser) skip the login. Guest mode hides personal apps (Settings, Camera, Presence, Calendar, Alarms) and the only way out on the device is the 3-second clock hold or the voice phrase. |
| Secrets in `/var/lib/homedeck/config.json` (API keys, Google client secret, Spotify refresh token, session secret, hashed device tokens) | File written `0600`. `GET /api/config` and the `POST` echo redact every `*key`, `*secret`, `*token(s)`, `psk`, `password` field to `••••` plus a `<field>_set` flag; a client cannot overwrite a secret with the placeholder, and `auth.secret`, `auth.tokens`, `spotify.tokens` are server-owned and ignored on write. |
| Command execution | All subprocess calls are argument lists (no shell). User-controlled strings that reach commands are validated: rclone remote `^[A-Za-z0-9_-]+:[A-Za-z0-9_./ -]*$`, cloud clip path `^YYYY-MM-DD/name.mp4$`, clip dates `YYYY-MM-DD`, local clip paths resolved inside the clips directory, Spotify URIs, presence IPs/MACs, piper voice ids from a fixed catalogue. |
| Input sizes | Request bodies capped at 1 MB; text sent to the voice/LLM path capped at 2 kB; timers 1 s–7 days; LED colours 0–255, brightness 0–100, chain length 1–500; alarms validated (HH:MM, days 0–6, sound = built-in tone, Spotify URI, or a `.wav` inside the sounds folder). |
| Browser hardening | `Content-Security-Policy` (self + inline app code; images only from self, OSM/RainViewer tiles and Spotify art; `frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, HSTS from Caddy, no scrollbars/URL bar on the kiosk. |
| Third parties | Weather (Open-Meteo, RainViewer), bikes (Bay Wheels GBFS), geocoding (Nominatim), calendar (the iCal URLs you paste, http(s) only), Google Drive via rclone (clips only, `drive.file` scope), ntfy.sh for push. |

## What the owner must keep private

- `/var/lib/homedeck/config.json` and `~/.config/rclone/rclone.conf` (+ the root copy): API keys, OAuth secrets, the Drive token, the session secret.
- The ntfy topic name: anyone who knows it can read your alerts and post to them. Regenerate it in Settings if it leaks. Motion snapshots are uploaded to ntfy.sh as attachments; the "Attach a snapshot" switch in Settings turns that off.
- Device tokens created in Settings › Remote access (shown once).
- The DuckDNS token in `/etc/homedeck/duckdns.env`.

## Accepted risks / not covered

- Anyone with physical access to the device screen can use it as the owner (no PIN on the kiosk); guest mode reduces, not removes, that.
- The Pi's local network: with remote sign-in enabled, LAN clients on `http://<ip>:8080` are gated too, but the LAN itself is trusted for the kiosk (localhost) and for Caddy.
- SSRF-ish fetches: calendar URLs and the geocoder are restricted to http(s) but not to specific hosts; pasting an internal URL as a calendar would fetch it (owner-only action).
- ntfy.sh is a public relay secured only by the topic name (see above). Use a self-hosted ntfy server for stronger privacy.
- Google `tokeninfo` is used to validate the ID token server-side over HTTPS instead of local RS256 verification (stdlib has no RSA); the claims `aud`, `iss`, `exp`, `email_verified` are checked.
- The Chromium kiosk profile lives in `/tmp` and is wiped on reboot; the kiosk never holds credentials.
- Rate limiting and sessions are in memory: a service restart clears the failure counters (cookies stay valid because they are HMAC-signed; "Sign out everywhere" rotates the secret).
