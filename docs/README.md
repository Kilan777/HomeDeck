# HomeDeck CM4 – smart display / voice assistant carrier board

A Raspberry Pi Compute Module 4 carrier that bolts onto the back of the Raspberry Pi Touch Display 2 (7") and turns it into a self-built "Echo Show" style device: touchscreen, camera, two MEMS microphones, stereo class-D speaker amplifier, CO2 / temperature / humidity / pressure / VOC sensors, ambient light sensor header, RGB light bar, three programmable buttons, microSD, USB-C PD power, a second USB-C (data + 5 V) and a USB-A port.

Everything in this package was generated from a single circuit description (`tools/circuit.py`), so the schematic, the PCB netlist and the BOM cannot disagree with each other.

## What is in the box

| File | What it is |
|---|---|
| `kicad/HomeDeck.kicad_pro` + `*.kicad_sch` | KiCad 7 project, hierarchical schematic (9 sheets). Opens in KiCad 7, 8 or 9. |
| `kicad/HomeDeck.kicad_pcb` | 4-layer board, placed and routed, ground/power planes filled. |
| `kicad/HomeDeck.kicad_sym`, `kicad/HomeDeck.pretty/` | Project symbols and footprints (CM4, CH224K, TPA3118D2, TS3USB221, SY6280, BME688, FPC, USB-A, microSD). |
| `kicad/HomeDeck.kicad_dru` | Custom DRC rules (0.1 mm rules inside the CM4 fan-out areas). |
| `out/HomeDeck_gerbers.zip` | Gerbers + Excellon drill files for JLCPCB. |
| `out/HomeDeck_BOM_JLCPCB.csv` | BOM in JLCPCB format with LCSC part numbers, library type and stock as checked on 2026-09-06. |
| `out/HomeDeck_CPL_JLCPCB.csv` | Pick-and-place file in JLCPCB format (pad-centre positions, JLC rotation corrections applied). |
| `out/HomeDeck_BOM_other.csv` | Parts you buy elsewhere (the CM4 itself) and DNP parts. |
| `out/HomeDeck_schematic.pdf` | Printable schematic. |
| `out/board_top.png`, `out/board_bottom.png` | Renders. |
| `out/drc.txt` | KiCad DRC report of the delivered board. |
| `docs/ARCHITECTURE.md` | Design rationale, power budget, pin map. |
| `docs/BRINGUP.md` | Ordering, assembly, first power-on and software setup. |

## Key numbers

* Board: 130 x 105 mm, 1.6 mm, 4 layers (signal / GND / power planes / signal), ENIG recommended because of the 0.4 mm-pitch CM4 connector pads.
* Mounting: four M2.5 holes on the 58 x 49 mm Raspberry Pi pattern (Touch Display 2 standoffs), centred on the board.
* Power in: USB-C PD, 15 V requested (solder jumpers for 9/12/20 V). Needs a 45 W or better PD charger.
* Rails: 3x TPS5430 bucks (5V_SYS for the CM4, 5V_PERIPH for display/LEDs/fan, 5V_USB for the ports), AMS1117 3.3 V, amplifier directly from the 15 V rail.
* Design rules: 0.2 mm tracks / 0.15 mm clearance generally, 0.1 mm / 0.1 mm only inside the two CM4 fan-out rule areas, vias 0.6/0.3 mm (0.45/0.2 mm in the fan-out). All within JLCPCB's 4-layer capabilities.

## Status of the delivered board

* Placed, fully routed (160 nets), planes filled. KiCad DRC: **0 errors, 0 unconnected items, 0 dangling tracks or vias**; 272 warnings, all cosmetic (silkscreen clipped by the edge on overhanging connectors, designators over copper, and "footprint not in library" because the report was generated headless). Details in `docs/BRINGUP.md` section 5.
* Schematic-to-board netlist verified identical (both come from `tools/circuit.py`); a separate GND connectivity check finds no floating ground copper.
* Design-reviewed twice by independent passes over the datasheets; all findings are fixed in this revision (CH224K VDD feed, TVS orientation, buffered PWR LED, pull-ups referenced to the CM4 3.3 V, USB-C port current limit, I2C0 pull-ups, hub crystal caps removed, LDO output electrolytic, SD_PWR_ON pull-up rail). Manufacturing checks: minimum hole-to-hole gap 0.35 mm, vias 0.6/0.3 and 0.45/0.2, no top-side parts under the CM4, no bottom-side parts near the display standoffs.
* 218 assembled parts (plus the two CM4 sockets as M1A/M1B), 66 BOM lines (38 Basic, 28 Extended), all checked for JLC stock and library type on 2026-09-06 (three out-of-stock parts were swapped: fuse, FPC connectors, CM4 sockets). 116 parts on the bottom side, so order two-sided Standard assembly.
* Routing is 0/45/90-degree geometry with chamfered corners; differential pairs length-matched to within 1.3 mm (most under 0.3 mm), except USB-C #2 data (7.7 mm, still within what USB 2.0 tolerates; see ARCHITECTURE.md section 5).
* Buy separately: CM4 module, Touch Display 2, camera, speakers, PD charger, optional fan and BH1750 breakout (see `out/HomeDeck_BOM_other.csv`).

## How the schematic is drawn

The schematic is "label style": every pin carries a global label with its net name and the sub-sheets group the circuit by function (power, cm4, usb, video, sd, audio, sensors, ui, mech). Every net name is unique across the project, so you can click any label in KiCad and see every place the net goes. It is not a pretty hand-drawn schematic, but it is complete and it is exactly what the PCB was built from.

## Regenerating

```
python3 tools/gen_lib.py        # symbols + footprints
python3 tools/gen_sch.py        # schematic
python3 tools/route.py          # placement + routing + zone fill + DRC (takes 20-40 min)
python3 tools/export.py         # gerbers, BOM, CPL, PDF
```
`tools/router.cpp` is the negotiated-congestion grid router (build with `g++ -O2 -std=c++17 -o tools/router tools/router.cpp`, needs nlohmann-json).
