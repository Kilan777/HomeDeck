# HomeDeck journal

Dated notes on what was tried, what broke, and what fixed it. Newest first. The commit messages carry the
"what"; this file keeps the "why" and the dead ends, so nobody repeats them. Software layout is in
SOFTWARE.md, hardware findings in PCB_ISSUES.md.

## 2026-09-29: camera "not focusing", Spotify "disconnected", kiosk stuck after reboot

**Camera autofocus was mechanically blocked by the enclosure.** Symptoms: every frame soft, `af_cycle` fails or
parks at the end stop, FocusFoM barely changes across the whole lens travel (460-550) and nothing can be heard
or felt when the lens is driven between end stops. The electronics were fine: the dw9807 VCM driver bound,
accepted 0..1023 with no I2C errors. Out of the housing the same scan settles mid-travel (3.2 dioptres, FoM 1368).
The lens block on the Camera Module 3 (about 8.5 mm square, 3 mm proud) must have clear air on all sides and in
front; screws snug, board flat on the four holes. The previous "dead" camera was probably the same thing.
Diagnostics live in the camera module: `af_status`, `af_cycle`, `af_manual {position}`. Pulling the ribbon while
the pipeline runs hangs it ("Camera frontend has timed out"): camera off/on to recover.

**Spotify "lost connection".** Playback (go-librespot) was fine; the Web API was answering 429 QUOTA_EXCEEDED
with Retry-After of about an hour because the module polled /me/player every 3 s. `_call` treated one 429 as a
global block, so playlists and recently played came back empty. Now: the Web API is polled every 30 s when the
local player is up (10 s otherwise), devices every 5 min, playlists every 10 min; backoff is per endpoint family
and capped at 10 min (the limit lifts per endpoint: /me/playlists answered while /me/player was still blocked);
the Music app says when it is limited; playlists are cached in config.

**Kiosk stuck on the boot page after a reboot.** `install/kiosk.sh` had lost its executable bit when deployed
with rsync from a non-executable working copy, so labwc's autostart could not run it. Bits are in git now (100755).
Also the Music softvol control only exists once its pcm has been opened since boot; the audio module now opens
the music path with 0.2 s of silence at start, otherwise ducking is silently off until something plays.

**USB mic dead channel.** Re-plugging the SF-558 made the helper open it before the audio interface was ready:
the USB channel read silence and mirrored the built-in mics, so questions were recorded from the fan-noisy
on-board mics and ended as "nothing said" after the 4 s timeout ("Jarvis is slow"). The hotplug watcher now
waits 2.5 s after plug-in, reopens when the helper reports the channel dead, and gives up on the USB mic for
5 min after two failures. Far-field: the wake stream is the USB mic plus on-board mics scaled to the USB noise
floor, lifted so the noise floor sits at ~1200 (up to x10); the same gain goes on the recorded question; wake
threshold 0.40 on the device. Near-misses (0.25..threshold) are logged with the gain and weight in effect.

## 2026-09-28: USB microphone, hearing over music, equaliser and room calibration

**Camera.** The Camera Module 3 that stopped working was replaced; the new one is detected as imx708 with the
existing `dtoverlay=imx708` line and records clips. Nothing changed in software.

**USB microphone (Generalplus SF-558, mono 16-bit, 44.1/48 kHz).** Goal: when it is plugged into the USB-A
port, listen through it *and* the on-board ICS-43434 mics; when it is unplugged, fall back to the on-board mics
without anyone touching a setting.

- `homedeck-aec` (the WebRTC AEC3 helper) got a `--mic2` input. The USB mic runs on its own clock, so it is read
  non-blocking into a small ring and padded/trimmed to the I2S mic's 10 ms frames. It gets its own AEC3 instance
  fed with the same loopback reference, so the speakers are cancelled out of both mics independently. Output
  becomes interleaved stereo (left = on-board, right = USB). If the USB mic vanishes its channel repeats the first.
- `voice.py` picks the mics automatically (`mic_device` "" = automatic, "onboard" = built-in only, or a plughw
  name), watches `/proc/asound/cards` every 2 s and reopens the capture when a USB mic appears or goes away.
  A deliberate reopen no longer counts as a helper crash (it used to trip the "AEC died twice, disable 10 min" rule).
- The Jarvis app's microphone picker existed in code but its markup had never been added; it is in the
  Microphone card now, with a line saying what is being listened through.
- Questions are recorded from the USB mic when present (`mic_prefer_usb`), the on-board mics otherwise.

**Dead end: two wake-word models.** First version ran a second openWakeWord instance on the USB channel. One
instance costs ~55 % of a CM4 core (measured, no thread spinning; tflite not available for Python 3.13). Two in
series could not keep real time: the helper backed up, the I2S capture overran and the USB ring "dropped" ~20
frames/s. Two threads did run in parallel but the box was at 85 % CPU with the kiosk Chromium and the camera,
the fan sat at 100 % and the on-board mics were mostly hearing the fan.

**Fix: one model on the sum of both mics.** Offline test with piper-synthesised "Hey Jarvis"/"Jarvis": summing
the two mics still scores 0.9+ with 3-80 ms of delay between them and one at 30 % level (comb filtering is too
fine-grained for mel bands to notice). Zero drops after the change, wake thread back at half a core.

**"Jarvis" alone.** The stock hey_jarvis model already fires at 0.99 on a bare "Jarvis." followed by a short
pause (synthetic voices). "Jarvis turn on the lights" said in one breath scores 0.07: that needs a custom model
(openWakeWord training on a GPU, later). No code change; the hint in the app says so.

**Gain clipping.** The on-board mics need x16; applied before the canceller, loud music clipped the int16 signal
and the linear filter could not match it. The helper now applies min(gain, 4) before AEC3 and the rest after.

**Equaliser.** `libasound2-plugin-equal` (alsaequal + caps Eq10, 10 bands). Working chain order is
`default -> plug -> equal -> plug -> softvol -> tee`; with softvol in front of the equaliser `aplay -D default`
fails hw_params negotiation. The tee for the echo-cancellation reference stays after both, so cancellation still
sees what the speakers get. Gotcha: the plugin mmaps its state file; an *empty* file (from `touch`) makes every
ALSA client bus-error. Let the plugin create it, then chmod 666. Band value 66/67 % = 0 dB (ports run
-48..+24 dB). The audio module keeps bass/treble (±8 dB) on top of a measured room correction and shifts the
whole curve down so no band boosts above 0 dB in the 16-bit stage.

**Room calibration with the USB mic (Music app > Sound > Calibrate).** Borrows the mics from the voice module,
records 3 s of room, plays 6.5 s of pink noise at -14 dBFS with volume at least 60 %, records it, octave-band
levels vs. the noise floor, correction where the band was clearly audible (limited to -6/+4 dB, smoothed).
First attempt at 45 % volume was buried in the mic's own noise floor (about 5 dB under the room); at -10 dBFS
the mic clipped (rms 12650). The SF-558 rolls off hard above 8 kHz (-30 dB at 16 kHz), which is the mic, not
the speakers; the text says so instead of "correcting" it.

**Music ducking (Jarvis over music).** Jarvis' voice was inaudible over Spotify: both went through the same master
volume, and the old code only dropped the master to 12 % while *listening*, restoring it before the answer. Now
Spotify (go-librespot `audio_device: homedeck_music`) and the kiosk browser play through a second softvol
("Music") that sits in front of the master; the voice module pulls it down 14 dB for the whole turn (listening,
thinking, answer, follow-up window) and restores it. Speech, timers and alarms stay on `default` at full level.
Verified through the echo reference: -33.8 dB -> -47.8 dB ducked -> -33.8 dB restored. Gotcha: amixer prints this
softvol as "Front Left: 100 [100%]" without the word "Playback"; the regex has to allow both. go-librespot
reconnected by itself after the restart (persisted zeroconf credentials), no re-pick on the phone needed.

**Two volumes.** The volume button now opens Music and Jarvis sliders. The music path (`homedeck_music`) goes
straight to the tee, so the Music softvol and the HomeDeck (Jarvis/system) softvol are independent; the phone's
Spotify volume, the now-playing slider, the Music and YouTube apps and the remote's music slider all drive the
Music control; Settings' "volume now" and the remote's home slider drive Jarvis. Voice: "turn the music down" /
"turn your voice up"; without a target, music if it is playing, otherwise Jarvis. Ducking subtracts from the
music base level, and setting the music level while ducked keeps the duck. Gotcha: `set_volume` clamps to the
night cap, so the calibration writes its 60 % test level straight to the mixer.

**Model fallback.** `groq/compound` vanished from the Groq account (404 model_not_found), which is what "Sorry,
I couldn't get an answer" was. The search model is now `openai/gpt-oss-120b` with Groq's built-in
`browser_search` tool (about 1 s, cites with 【…】 marks that are stripped). `_chat` walks a chain: the model
the question wants, then `groq_fallback_models`, each with more time; a "not found" model is skipped for the
rest of the session; an empty answer moves on too. Gotcha: editing `/var/lib/homedeck/config.json` by hand
while the service runs gets overwritten by the next `save_config` (the volume change persists); use `/api/config`.

**Answer card (Echo Show style).** After every answer the screen shows the gist full screen for 10 s: maths
"17 × 23 / 391", dice tumbling then the roll, a coin flip, or a fact: the fast model picks a 1-5 word headline
("Burj Khalifa"), Wikipedia's summary gives description, extract and picture; tap opens the article (plain-text
extract via `prop=extracts`), scrollable, close button; tap the backdrop or say the wake word to dismiss.
Three things blocked the picture in turn: the page's Content-Security-Policy (img-src had no Wikipedia host),
the thumbnails come from `thumb.wikimedia.org` not `upload.wikimedia.org`, and Wikimedia only serves a few
standard thumbnail widths now (330/960/1280 work, 640/800 return HTTP 400). The math card's source tag is
"math", not "intent". `hows the air been today` used to hit the live-readings intent; day/history words now
route to the sensors module's summary, and the day summary is also in the model's context.

**Air app.** The History card had no gap above the tiles: it follows the tiles' wrapper element, so the
`.card + .card` spacing rule never matched. `#aq .aq-hist { margin-top }` in both layouts.
