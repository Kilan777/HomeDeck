# Jarvis HomeDeck software

Everything runs on the CM4 as one systemd service, `homedeck.service`, from `/opt/homedeck`. Config lives in
`/var/lib/homedeck/config.json` (mode 0600, never in the repo). The device UI is Chromium in kiosk mode on the
touch panel; phones get a separate remote app on `https://jarvis.example.com` behind Google sign-in.

## Layout

```
software/homedeck/
  server.py            core: config, module loader, event bus, HTTP API, auth gate, secret redaction, CSP
  modules/*.py         one file per feature (see below)
  web/index.html       device UI shell + apps
  web/shell.js         app registry, home screen, switcher, now playing, controls, events
  web/keyboard.js      on-screen keyboard (also injected into Spotify's sign-in pages)
  web/style.css        design system, landscape rules, touch targets
  web/themes/          home screen styles (weather-led is the one in use)
  web/apps/*.js        one file per app
  web/remote.*         phone app
  install.sh           full install/update on the Pi
  install/             kiosk script, audio setup, Caddy, DuckDNS/UPnP, Spotify event hook, voice deps
```

## Module contract

A module is a Python file in `modules/` with `NAME`, `DEFAULTS`, `state()`, `api(action, params)`, a blocking
`start(ctx)` loop, an optional `intent(text)` for voice (return a spoken string, `""` for a silently handled
command, or `None` if the text is not yours) and optional `ROUTES` for raw HTTP. `ctx` gives config, logging,
`emit`/`on` events and `module(name)` for cross-module calls. Apps register with `HD.registerApp({...})` and get
`render`, `update(state)`, `idleWidget` for a home tile and `onEvent`.

## Modules

| Module | What it does |
|---|---|
| voice | Wake word (openwakeword "hey jarvis"), recorder with hysteresis end-of-speech and speculative transcription, Groq Whisper STT, local intents (math, time, volume, stop), module intents, Groq chat (qwen, reasoning off) with web search fallback, Orpheus TTS with Piper offline fallback, conversation history and recall, offline mode, mic taps for other modules |
| timers | Persistent countdown timers with labels, pause, add time, ringing until stopped; understands most phrasings and STT mishearings |
| alarms, reminders, lists, calendar, countdowns, memory | The usual assistant basics; calendar from private iCal URLs; countdowns also derived from calendar titles |
| spotify | Spotify Connect speaker (librespot / go-librespot) plus a full Web API client: library, search, playlists, queue, devices, likes, on-device sign-in with the injected keyboard |
| youtube | yt-dlp search, ffmpeg remux stream for an ad-free native player, iframe fallback |
| sensors | SCD40 / BME688 / J12 sensors, comfort zones, nudges, one-minute history log, daily spoken air report |
| weather | Open-Meteo forecast and the animated sky |
| bikes | Bay Wheels GBFS: station health, corrected e-bike counts, nearest free e-bikes, morning warning |
| transit | BART (legacy API) and Muni (511.org key) departures with walking time |
| flights | Live ADS-B aircraft around home with routes and a radar view |
| leds | WS2812B strip: lamp, Jarvis patterns, timer fill, music-reactive VU, sunrise |
| display | Backlight from ambient light, night mode, manual override, screen off, orientation, power button |
| fan | CM4 fan with auto thresholds |
| sleep | Generated sleep sounds with a fading sleep timer |
| presence | Home/away from phones on the LAN; drives notifications |
| guest | Wi-Fi QR card and house notes; "give me the wifi" overlay |
| wifi | Scan, join and forget networks from Settings |
| notify | ntfy push notifications |
| auth | Google OAuth sign-in for the phone app |
| audio | System volume (ALSA softvol shared by everything) |

## Things that are not obvious

- Chromium runs with `--alsa-output-device=default` and a dead `PULSE_SERVER` so browser audio shares the ALSA
  dmix/softvol chain with Jarvis and Spotify instead of PipeWire taking the card exclusively.
- The on-screen keyboard is our own page-level keyboard; squeekboard is installed but never shows in Chromium.
- Landscape is the default orientation (config `general.orientation`), applied live via wlr-randr and at boot by
  `install/kiosk.sh`. Landscape CSS lives in `@media (orientation: landscape) and (max-height: 600px)` blocks.
- Groq's free tier changes its model list; the fast model is configurable (`voice.llm.groq_fast_model`).
- The language model is told it cannot perform actions; every command is matched on the device first, and the
  timers module accepts common STT mishearings of "timer".
- Secrets are redacted in every API response (`*key`, `*secret`, `*token`, `*password`) with a `_set` flag for
  the UI; the phone app never receives them.
- Deploying: `install.sh` for everything, or copy single files and `systemctl restart homedeck.service`. Web
  files hot-reload in the kiosk when their version changes. Timers, conversation history, air history and
  YouTube history persist in `/var/lib/homedeck/` across restarts and power loss.
- Chromium keeps its shared memory in /tmp on this board (Debian's `/etc/chromium.d/dev-shm` rule) and leaks it
  slowly; after about a day /tmp fills and the page shows "Reconnecting" while the service is fine.
  `install/kiosk_watchdog.py`, started by `kiosk.sh`, restarts the browser when /tmp passes 70 %, when the page
  has been offline for a minute while the server answers, or at 4 AM, and never while the screen is being touched.
- Echo cancellation: `/etc/asound.conf` tees the speaker feed into an ALSA loopback card (snd-aloop, clocked from the
  I2S card via `timer_source`, ignored by WirePlumber), and `install/aec/homedeck-aec` (WebRTC AEC3, built by
  `install/aec/build.sh`) reads mics + loopback and feeds cleaned 16 kHz audio to the voice pipeline. The echo
  reaches the mics 20-40 ms before the loopback copy, so the mic path is delayed 60 ms. Live on the device at
  volume 55 it removes ~16 dB of music echo; the pipeline falls back to plain arecord if the helper dies twice in
  a minute. Settings: `voice.aec` (delay_ms, mic_delay_ms, ns, stereo_ref, music_wake_threshold). The Jarvis app has
  a Voice calibration card (api `voice/calibrate`) to re-measure after the enclosure changes the acoustics.
