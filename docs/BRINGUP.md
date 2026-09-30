# HomeDeck CM4 – ordering, assembly and bring-up

## 0. Shopping list and how it fits together

What you buy besides the assembled board:

| Item | Notes |
|---|---|
| Raspberry Pi Compute Module 4, **wireless**, eMMC (e.g. CM4104016: 4 GB RAM / 16 GB eMMC / Wi-Fi) | Wireless is mandatory (no Ethernet on the board). Lite (no eMMC) works too but then you need a microSD card. Not a CM5. |
| Raspberry Pi Touch Display 2 (7") | Comes with the 15-way DSI ribbon, a 2-wire power lead with female Dupont ends, and four M2.5 screws. |
| Raspberry Pi Camera Module 3 (or v2) | Comes with a 15-way ribbon. Any length is fine; 200 mm gives room to position it in the bezel. |
| 2x speakers, 8 ohm, 3-5 W, ideally with a JST-PH 2.0 mm 2-pin lead | Search "8 ohm 5W speaker JST PH". Otherwise crimp JST-PH housings onto plain speakers. |
| USB-C PD charger, 45-65 W, plus a USB-C cable rated for it | Must offer 15 V (any laptop-class PD charger does). A phone charger will not boot the board. |
| USB-A to USB-C cable | To flash the eMMC from a PC (rpiboot) and for the USB-C data port. |
| M2.5 standoffs 3-4 mm tall (4x) and M2.5 nuts/screws | Board-to-display spacing; the display's own standoffs are on the Pi hole pattern. |
| 2.54 mm jumper cap (2x) | One for the nRPIBOOT jumper J14 during flashing, one spare. |
| Optional: 30 mm 5 V fan with JST-PH 2-pin lead | Plugs into J21. Only needed if the enclosure is sealed. |
| Optional: BH1750 (GY-302) light-sensor breakout + 4 female-female Dupont wires | Plugs into J12; mount it behind the bezel where it sees the room. |
| Optional: microSD card | Only for a CM4 Lite. |
| Optional: WS2812B LED strip with 3-pin JST-PH lead | J17, if you want light outside the board's own 10-LED bar. |
| Optional: panel-mount buttons (3x) with 2-wire leads | J18/J19/J20, if the on-board tactile switches are not reachable through the enclosure. |
| Optional: Zigbee/Thread USB dongle | Plugs into an internal USB header J4/J5 (5V, D-, D+, GND) with a 4-wire lead, or into the USB-A port. |

How it goes together (all connectors are on the top side unless noted):

1. **Board on display.** The board's bottom side faces the back of the display. Line up the four M2.5 holes (H1-H4, the 58 x 49 mm Pi pattern) with the display's standoffs, put 3-4 mm standoffs in between and screw down. The bottom side only has flat 0603-1206 parts and the two mics, which is why it fits.
2. **CM4 on the board.** Press the module onto the two 100-pin sockets (M1A/M1B) until it clicks, then M2.5 screws through its four corner holes into standoffs. Fit the official CM4 heatsink if you have one; the enclosure needs airflow there.
3. **Display ribbon.** 15-way ribbon from the display's DSI connector to **J6** (the right-hand FPC connector above the CM4). Both ends are bottom-contact: pull the black latch out, insert the cable with the **bare contacts facing the PCB** (blue stiffener up), push the latch back. The ribbon exits toward the top edge of the board.
4. **Display power.** The display's power lead with the two Dupont sockets goes on **J8** ("DISPLAY 5V", 3 pins next to the USB-C power input): red/5 V on pin 1 or 2 (both are 5V_PERIPH), black/GND on pin 3.
5. **Camera ribbon.** From the camera to **J7** (the left-hand FPC connector), same orientation rule. The camera enable is handled by the CM4 pin, nothing to set.
6. **Speakers.** JST-PH plugs into **J10** (left) and **J11** (right), pin 1 = +. If the speakers have no polarity marking it does not matter, just be consistent.
7. **Power.** PD charger into **J1**, the USB-C at the right end of the bottom edge (the other USB-C, **J2**, is the data port). D2 lights green when the charger agreed to 15 V.
8. **Optional bits.** Fan on J21 (pin 1 = 5 V). Light sensor on J12: 3V3, GND, SDA, SCL in that order. External LED strip on J17: 5 V, DATA, GND. Panel buttons on J18 (power), J19 (button A), J20 (button B), each to GND. UART debug on J15: GND, TX, RX (3.3 V logic, use a USB-UART adapter).
9. **First flash.** With an eMMC CM4: jumper on J14, USB-A-to-C from the PC into J2, power up, run rpiboot, then Raspberry Pi Imager onto the disk that appears, then remove the jumper and reboot. With a Lite: write the OS to the microSD and put it in J9 (bottom edge, left). Then follow sections 2-4 below.

## 1. Ordering from JLCPCB

1. Upload `out/HomeDeck_gerbers.zip`. Choose: 4 layers, 1.6 mm, 1 oz outer copper, ENIG surface finish (the CM4 connector pads are 0.2 mm wide – HASL is not flat enough), any colour, "Specify stackup" is not needed (JLC7628 default is fine, there are no controlled-impedance traces).
2. Tick SMT assembly, **both sides** ("Standard" assembly, not "Economic"). 116 of the 218 assembled parts sit on the bottom: all the decoupling and filter passives (0603/0805/1206 only), the two ICS-43434 microphones and two SOT-23 FETs. Everything tall (connectors, bucks, hub, amp, CM4 sockets) is on top. Hand-soldering the bottom side is possible but it is over 100 passives, so pay for two-sided assembly.
3. Upload `out/HomeDeck_BOM_JLCPCB.csv` and `out/HomeDeck_CPL_JLCPCB.csv`.
4. In the part-matching step, check every line. Part numbers were verified against the JLC catalogue while designing, but stock changes weekly. Known things to expect:
   * The DF40C-100DS-0.4V(51) sockets are LCSC/JLC part C597931 (genuine Hirose, Extended; only ~25 in stock on 2026-09-06 with an 11-day pre-order lead time, minimum order 9 pieces). 2 per board, BOM/CPL designators `M1A` and `M1B`; the KiCad footprint is a single `M1` CM4 footprint that contains both. If JLC cannot supply them, order from Digi-Key/Mouser and hand-reflow them (ENIG + stencil). Pin 1 of each socket is the left-hand pad of its lower row (M1A pin 1 at x=55.2, y=71.0; M1B pin 1 at x=55.2, y=37.08 in board coordinates) – check the orientation in JLC's placement preview.
   * The two 15-pin FPC connectors are BOOMELE "1.0-15PContact,Bottom" (C66660, 1.0 mm pitch, bottom contact, right angle, ~3,000 in stock). The footprint follows that part's drawing (0.6 x 2.2 mm pads, 2.6 x 2.6 mm anchors). The TE 1-84952-5 originally chosen is out of stock at JLC.
   * The fuse is Bourns SF-1206F500-2 (C48332, 5 A fast, ~10,000 in stock); the original 1206FT 5A is out of stock.
   * Every LCSC number was checked on jlcpcb.com on 2026-09-06 (library type and stock are in the last two BOM columns). Lowest stocks: BME688 (~1,300), SCD40 (~3,000), CH224K (~3,100), the FPC connector (~3,100) and the CM4 sockets (25). Everything else is in the tens of thousands or millions. 38 lines are Basic and 28 unique parts are Extended (each Extended part adds JLC's ~$3 feed-loading fee once per order). Every Extended part was checked for a Basic equivalent on 2026-09-06: JLC's Basic library contains no connectors, no hub/mux/PD/audio/sensor ICs, no fuses, no TVS, no power inductors and no ESD arrays, so those 28 cannot be reduced further without changing the design (e.g. dropping the microSD slot or the expansion headers).
   * WS2812B, BME688, SCD40 and the ICS-43434 mics are "Standard assembly only" parts, which is another reason to choose Standard, two-sided assembly.
   * Placement file: positions are the centre of each part's pads (what JLC expects, so connectors and pin headers land where they should) and rotations already include the usual KiCad-to-JLC package corrections (SOT-23 -90, SOIC/TSSOP/QSOP/QFN 270, SOT-223/electrolytics/USB-C/JST 180, etc.), the same table the popular kicad-jlcpcb-tools plugin uses. JLC's own library orientation still varies part by part, so in the placement preview check every polarized part: electrolytic caps (C3, C8, C14, C20, C70), SS34 diodes (D6-D9), SMBJ24A (D1), all LEDs, the WS2812Bs, every IC, and pin 1 of the CM4 sockets, FPC connectors and USB connectors. Rotate in their UI if needed; it does not change your files. `docs/ORIENTATION.md` lists, for every assembled part, whether its orientation matters and which corner/side its pin-1 dot, cathode band or + mark has to be on, so you can check the preview part by part. Square-looking parts still matter: the tactile switches (SW1-SW4) have internally connected pin pairs along the long 6 mm axis, so a 90-degree error shorts the button permanently; the terminals of the inductors and switches must sit on the pads, which the preview shows clearly.
5. Buy separately: Raspberry Pi CM4 (any variant; buy CM4 *Lite* if you want to use the microSD slot), Touch Display 2 (7"), a Pi camera module with 15-pin cable, two 8 ohm 3-5 W speakers with JST-PH leads, a 45-65 W USB-C PD charger, optionally a 5 V 30 mm fan and a BH1750 (GY-302) light-sensor breakout.

## 2. Before applying power

* Visually check the two CM4 connectors under magnification for solder bridges (0.4 mm pitch).
* With no CM4 fitted: measure resistance from VBUS to GND (should be > 1 kΩ), 5V_SYS/5V_PERIPH/5V_USB to GND (> 100 Ω), 3V3 to GND (> 100 Ω).
* D1 (SMBJ24A) band/cathode must face VBUS (the fuse side). Check the nRPIBOOT inverter Q5 (bottom side, under the CM4) is fitted, then check the three PD solder jumpers JP1-3: JP1 bridged 1-2 (CFG1 = GND), JP2 and JP3 bridged 1-2 (CFG2/CFG3 = VDD) → 15 V request.

## 3. First power-on (no CM4)

1. Plug a PD charger into J1 (the right-hand USB-C). D2 (PD OK) should light and VBUS should read 15 V (9 or 12 V if the charger cannot do 15).
2. Check 5.0-5.2 V on the three 5 V rails (test at the big electrolytic caps C14/C20/C29 area) and 3.3 V at U5.
3. Check that the USB-C data port (J2) and USB-A (J3) VBUS pins read 5 V.

## 4. Fit the CM4

1. Press the CM4 onto the two connectors, screw it down with M2.5 screws through the four CM4 holes (use 1.5 mm standoffs if you prefer; the DF40C is a 1.5 mm stack).
2. For an eMMC CM4: fit the nRPIBOOT jumper (J14), connect a PC to J2 with a USB-**A**-to-C cable (a C-to-C cable will not enumerate in this mode because the port's CC pull-ups are switched off with its 5 V), run `rpiboot`, flash Raspberry Pi OS with `rpi-imager`, remove the jumper. For a CM4 Lite: write the OS to a microSD.
3. `config.txt` additions (put at the end):

```
dtoverlay=vc4-kms-v3d
dtoverlay=vc4-kms-dsi-ili9881-7inch      # Touch Display 2
camera_auto_detect=1
otg_mode=1                                # CM4 USB port as host
dtparam=i2c_vc=on
dtoverlay=i2c6,pins_22_23                 # sensors + light sensor header (I2C6, /dev/i2c-6)
dtoverlay=gpio-shutdown,gpio_pin=3        # power button: shutdown while running, wake from halt
dtoverlay=hifiberry-dac                   # PCM5102A on I2S (playback)
dtoverlay=googlevoicehat-soundcard        # alternative: playback + ICS-43434 mic capture in one card
```
Use one of the two audio overlays, not both. `googlevoicehat-soundcard` gives you a full-duplex card (DAC + the two mics as a stereo capture device), which is the easiest way to get both directions working; `hifiberry-dac` is playback-only.

4. GPIO housekeeping the software must do: drive GPIO4 (AMP_SDZ) high to enable the amplifier and keep GPIO5 (AMP_MUTE) low; GPIO24 is the DAC soft-mute (pulled up = unmuted, drive low to mute); GPIO25 is the fan (PWM); GPIO27 reads low when the PD negotiation succeeded; GPIO6 reads low when the amplifier reports a fault.
5. Buttons: GPIO3 = power (handled by the overlay), GPIO16 = button A, GPIO26 = button B, all active-low with pull-ups on the board. User LED on GPIO12 (active high). Light bar: 10x WS2812B on GPIO10 (SPI0 MOSI) – use `rpi_ws281x` / `adafruit-circuitpython-neopixel-spi` in SPI mode, plus whatever you plug into J17.
6. Sensors on I2C6: SCD40 at 0x62, BME688 at 0x76, BH1750 breakout (J12) at 0x23.

## 5. Things to know / possible revision-B items

* The ambient light sensor is not on the board on purpose: it must see the room. Mount the BH1750 breakout behind the bezel and wire it to J12 (3V3, GND, SDA, SCL).
* The BME688 will read a few degrees high if the enclosure traps CM4 heat – the sensor tongue slots help but give the enclosure vents there.
* A 5 V-only USB charger will not boot the board reliably (the bucks need > 6 V). Use a PD charger.
* The USB-C data port is limited to 1.7 A and the USB-A port to 1.3 A by the SY6280 switches; both share the 3 A 5V_USB buck.
* Bottom-side parts are limited to 0603-1206 passives so the board can sit on the display's standoffs; keep at least 2.5 mm standoff height.
* The router is a home-grown grid router; the traces were straightened and the differential pairs length-matched afterwards (see ARCHITECTURE.md section 5 for the numbers). The one pair still out of tolerance by textbook standards is USB-C #2 data (7.7 mm skew); it will work, but it is the first thing to tidy in KiCad if you want to.
* C36 and C37 (22 pF next to the hub crystal Y1) are intentionally not populated: the CH334R has built-in crystal load capacitors. Leave them empty.
* If you ever move the PD jumpers to 20 V, replace R2 (1 k, 0.25 W) with a 0.5 W part; at 15 V it dissipates 0.14 W and is fine.
* Five ground pads have their via inside the pad (U9 pin 2, U11 pin 2, J6 pin 13, J9 pin 6, C61 pin 2) because there was no room next to them. They are 0.45/0.2 mm vias, tented by default, and JLC assembles boards like this every day; if you want to be picky, ask for "via filling / epoxy plugged" on the order (not needed).
* The DRC report (`out/drc.txt`) ends with 0 errors and 0 unconnected items. The 292 remaining entries are all warnings: silkscreen clipped by the board edge (connector outlines that deliberately overhang the edge), reference designators printed over copper, "footprint not in library" (only because the report is generated from the command line without KiCad's global footprint table) and 22 "via connected on one layer" notes, which are fan-out junction vias that are harmless.
