# Jarvis HomeDeck

> **Public mirror.** This is a snapshot of the private working repo (commit `c46c29b`). Some private parts of the software are not included.


A self-built voice assistant with a screen: a Raspberry Pi Compute Module 4 carrier PCB that bolts to the 7-inch
Raspberry Pi Touch Display 2, plus the software that turns it into "Jarvis". Personal project by Kilan.

The board carries the CM4, USB-C PD power, three 5 V bucks, a stereo class-D amplifier, two MEMS microphones,
a Camera Module 3 connector, CO2 / temperature / humidity / pressure / VOC sensors, an RGB LED bar and an external
WS2812B strip header, a fan header, buttons, a Qwiic-style I2C header, microSD, USB-A and a second USB-C.

The software is a single Python service with a module per feature and a touch UI in Chromium, plus a phone app
served on a personal domain behind Google sign-in. Voice runs on a local wake word and hosted speech models;
everything that is a command (timers, lights, music, volume, math) is handled on the device without a model.

| Folder | Contents |
|---|---|
| `kicad/` | KiCad project: hierarchical schematic (9 sheets), 4-layer routed PCB, project symbols and footprints, DRC rules |
| `tools/circuit.py` | The single source the schematic, netlist and BOM are generated from. Edit this, not the KiCad files |
| `out/` | Gerbers, JLCPCB BOM and pick-and-place, schematic PDF, board renders, DRC report (rev A as ordered) |
| `docs/` | Hardware docs: `README.md` (board overview), `ARCHITECTURE.md`, `BRINGUP.md`, `ORIENTATION.md`, and `PCB_ISSUES.md` (what went wrong on rev A and what rev B should change) |
| `software/homedeck/` | The assistant: `server.py`, `modules/`, `web/`, `install/`. See `docs/SOFTWARE.md` |
| `software/homedeck_ui.py` | The original bench dashboard used for bring-up (retired) |

## Status

- Rev A board #1 is fully working and in daily use, running at 9 V PD after two solder-jumper changes.
  Rev A board #2 is assembled and untested. Findings and the rev B list are in `docs/PCB_ISSUES.md`.
- Software is feature complete for daily use: home screen, Jarvis voice, Spotify (full client), YouTube (ad-free
  native player), air quality with history, timers, alarms, reminders, lists, calendar, countdowns, bikes, transit,
  flights radar, lights, fan, sleep sounds, guest card with Wi-Fi QR,
  presence, Wi-Fi setup, on-screen keyboard. See `docs/SOFTWARE.md`.

## Quick start

Hardware: order from `out/` (JLCPCB 4-layer, two-sided assembly), read `docs/BRINGUP.md`, then apply the rev A
fixes in `docs/PCB_ISSUES.md` before first power-on (the 9 V jumper setting matters).

Software, on the Pi:

```
rsync -a software/homedeck/ kilan@homedeck.local:~/hd/
ssh kilan@homedeck.local 'cd ~/hd && bash install.sh'
```

Then open Settings on the device for location, Wi-Fi, Spotify, calendar feeds and the API keys the optional
features need (Groq for voice, 511.org for Muni). Secrets live only on the device in `/var/lib/homedeck/config.json`
and are never in this repository.

## Privacy

This repository is private. It contains no credentials, tokens or Wi-Fi passwords. The device redacts secrets
from every API response, the phone app requires Google sign-in, and there is no VPN or third-party relay involved.

