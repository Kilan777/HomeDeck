# HomeDeck CM4 – Architecture & Design Notes

Smart-display / voice-assistant carrier board for the Raspberry Pi Compute Module 4, built to bolt onto the back of the Raspberry Pi Touch Display 2 (7", 720x1280). Fabricated and assembled by JLCPCB (4-layer, SMT assembly, Basic parts wherever a Basic part exists).

## 1. What the board does

| Block | Choice | Why |
|---|---|---|
| Compute | Raspberry Pi CM4 (any RAM / eMMC / wireless variant) on 2x Hirose DF40C-100DS | Linux, native DSI + CSI, Wi-Fi/BT on module, huge software base (Home Assistant, Wyoming/openWakeWord, Rhasspy). |
| Display | Touch Display 2 via 15-pin 1.0 mm bottom-contact DSI connector (BOOMELE, JLC C66660) (CM4 DSI1, 2 lanes) + 3-pin 5 V header for the display's power lead | Same wiring as a Pi 4, so the stock `vc4-kms-dsi-ili9881-7inch` overlay works. Touch runs over the I2C0 lines inside the DSI cable. |
| Camera | Pi Camera Module (v2/v3/HQ) via 15-pin 1.0 mm bottom-contact CSI connector (same part; CM4 CAM1, 2 lanes) | Stock libcamera support. Camera enable driven by the CM4 `Camera_GPIO` pin, exactly like the CM4IO board. |
| Power in | USB-C #1 with CH224K PD sink (VDD fed from VBUS through 1 k, SMBJ24A TVS, 5 A fuse), configured for 15 V (solder jumpers allow 9/12/20 V) | One cable from any 45 W+ USB-C PD charger. 15 V gives the amplifier headroom and keeps the bucks efficient. |
| Rails | 3x TPS5430 (3 A, Basic part) bucks: `5V_SYS` (CM4 + 3.3 V LDO), `5V_PERIPH` (display + LED bar + fan), `5V_USB` (USB-C #2 + USB-A + internal USB headers). AMS1117-3.3 LDO for `3V3` (22 uF ceramic + 100 uF electrolytic on its output, the LDO needs some ESR). | Three Basic-part bucks are cheaper at JLC than one big Extended buck, and they isolate the CM4 from USB-port load steps. Output caps are 100 uF electrolytic + 22 uF ceramic because the TPS5430 wants some ESR. |
| USB | CM4 USB 2.0 -> TS3USB221 mux -> CH334R 4-port hub. Ports: USB-C #2 (5 V/1.7 A + data, CC pull-ups advertise 1.5 A), USB-A (5 V/1.3 A + data), 2x internal 4-pin headers (for a Zigbee/Thread dongle etc). | CM4 has a single USB 2.0 port so a hub is mandatory. Each external port has a SY6280 current-limit switch and USBLC6 ESD protection. |
| eMMC flashing | `nRPIBOOT` jumper flips both TS3USB221 muxes so the CM4 USB goes straight to USB-C #2 and cuts that port's 5 V output. U6's two switch ports are wired the opposite way round to U7 (so the BOOT pair leaves U6 on the pins facing U7 without crossing the hub pair), and its select pin is therefore driven by an inverted copy of `nRPIBOOT` (Q5 2N7002 + R47 10 k). | Lets you run `rpiboot` from a PC with a USB-A-to-C cable without a separate service port. |
| Storage | microSD (Molex 104031-0811) on the CM4 SD lines with SD_PWR_ON load switch | Boot medium for CM4 *Lite*. On eMMC CM4 variants the SD pins are inactive (Pi limitation). |
| Audio out | PCM5102A I2S DAC -> TPA3118D2 stereo class-D (2x >5 W into 8 ohm from the 15 V rail), LC output filters (10 uH + 1 uF), 2x JST-PH speaker connectors | `dtoverlay=hifiberry-dac` style zero-config DAC. Amp enable/mute/fault on GPIO. |
| Audio in | 2x ICS-43434 I2S MEMS mics (L/R on one I2S data line) at the top corners, bottom-ported through the PCB | Same clocks as the DAC (full-duplex I2S), same arrangement as the Google AIY Voice HAT overlay. |
| Sensors (I2C6, GPIO22/23) | SCD40 (CO2) and BME688 (temp/humidity/pressure/VOC) on a thermally slotted tongue at the left edge; BH1750 ambient light sensor on a 4-pin header (J12) so it can sit behind the bezel and actually see the room. | Keeps the temperature sensor away from the CM4 heat and the light sensor where there is light. |
| Light bar | 10x WS2812B (5050) along the top edge + JST-PH-3 header for an external strip, 74AHCT1G125 level shifter, data on GPIO10 (SPI MOSI, works with `rpi_ws281x` SPI mode) | Classic "listening" glow. |
| Buttons / LEDs | Power button (GPIO3: wake from halt + `gpio-shutdown`), two user buttons (GPIO16, GPIO26), user LED (GPIO12, PWM-capable), PWR / ACT LEDs from the CM4 LED pins, PD-good LED. Each button has an on-board tactile switch *and* a 2-pin header for a panel-mounted button. | All programmable; nothing is hard-wired to the mics or camera. |
| Misc | 5 V fan header (GPIO25 PWM via transistor), UART debug header (GPIO14/15), 2x8 expansion header with the spare GPIOs, `GLOBAL_EN` and `RUN` headers, reset button | Bring-up and future expansion. |

## 2. Power budget (15 V PD input)

| Load | Rail | Typ | Peak |
|---|---|---|---|
| CM4 | 5V_SYS | 1.4 A | 3.0 A |
| 3V3 LDO loads (hub, DAC, mux, sensors, mics) | 5V_SYS | 0.25 A | 0.45 A |
| Touch Display 2 | 5V_PERIPH | 0.6 A | 1.0 A |
| LED bar (10x WS2812B) | 5V_PERIPH | 0.1 A | 0.6 A |
| Fan | 5V_PERIPH | 0.1 A | 0.2 A |
| USB-C #2 + USB-A + internal headers | 5V_USB | 0.5 A | 3.0 A (1.74 A + 1.33 A limits of the SY6280s) |
| Amplifier (2x5 W into 8 ohm, music) | VBUS 15 V | 0.3 A | 1.0 A |

Worst case at 15 V: (3.45 + 1.8 + 2.9) x 5 V / 0.88 + 15 W = ~61 W momentarily; realistic sustained draw is 20–30 W. A 45 W (15 V / 3 A) PD supply is the minimum; 65 W is comfortable. If the charger only offers 9 V or 12 V the CH224K falls back to it and everything still works (the amp just has less headroom). At 5 V only (dumb charger) the bucks cannot regulate and the board is not guaranteed to boot — the PD-good LED tells you.

Buck design (TPS5430, 500 kHz, non-synchronous): 10 uH / 7.8 A shielded inductor, SS34 catch diode, 2x 10 uF/50 V ceramic input, 100 uF electrolytic + 22 uF ceramic output, 10 nF bootstrap, feedback 15 k / 4.7 k -> 5.12 V (CM4 window is 4.75–5.25 V, USB ports need >4.75 V after the switch drop).

## 3. CM4 pin usage

* USB: `USB_P/N` (105/103) -> mux. `USB_OTG_ID` DNP link to GND (host mode is set by `otg_mode=1` in `config.txt`).
* DSI1 lanes 0-1 + clock -> display connector; CAM1 lanes 0-1 + clock -> camera connector; `SCL0/SDA0` (80/82) to both connectors (the CM4 has 1.8 k internal pull-ups, none added); `Camera_GPIO` (97) -> camera pin 11.
* SD: `SD_CLK/CMD/DAT0-3` (57/62/63/67/69/61) -> microSD; `SD_PWR_ON` (75) -> P-FET load switch, 10 k pull-up to `CM4_3.3V` so the card is powered at boot; `SD_VDD_OVERRIDE` NC.
* Power/control: 6x `+5V` pins from 5V_SYS, `GPIO_VREF` (78) -> `CM4_3.3V`, `GLOBAL_EN` (99) header, `RUN_PG` (92) reset switch via 220 R, `nRPIBOOT` (93) jumper, `PI_LED_nPWR` (95, buffered with a P-FET as the datasheet requires) / `Pi_nLED_Activity` (21) LEDs, `EEPROM_nWP`, `WL_nDisable`, `BT_nDisable`, `AnalogIP*`, `VDAC_COMP`, HDMI, PCIe, Ethernet all NC.
* GPIO map:

| GPIO | Function | GPIO | Function |
|---|---|---|---|
| 2 | expansion (SDA1) | 16 | BTN_A |
| 3 | PWR_BTN (SCL1, wake) | 17 | expansion |
| 4 | AMP_SDZ (amp enable, pulled low) | 18 | I2S_BCLK |
| 5 | AMP_MUTE (high = mute, pulled low) | 19 | I2S_LRCLK |
| 6 | AMP_FAULT (input, pulled up) | 20 | I2S_DIN (mics) |
| 7 | expansion (CE1) | 21 | I2S_DOUT (DAC) |
| 8 | expansion (CE0) | 22 | I2C6_SDA sensors |
| 9 | expansion (MISO) | 23 | I2C6_SCL sensors |
| 10 | LED_DATA (MOSI) | 24 | DAC_XSMT (pulled up) |
| 11 | expansion (SCLK) | 25 | FAN_PWM |
| 12 | USER_LED | 26 | BTN_B |
| 13 | expansion (PWM1) | 27 | PD_GOOD (input, pulled up) |
| 14/15 | UART TX/RX debug | 0/1 | ID_SD/ID_SC on expansion |

All pull-ups on CM4 GPIOs go to `CM4_3.3V` (not the always-on 3V3) so no pin sees voltage while the module is off, as the CM4 datasheet requires.

Software notes: `dtoverlay=i2c6,pins_22_23`, `dtoverlay=gpio-shutdown,gpio_pin=3`, `dtoverlay=hifiberry-dac` (or a custom simple-audio-card overlay that adds the ICS-43434 capture side), `dtoverlay=vc4-kms-dsi-ili9881-7inch`, `otg_mode=1`, `dtparam=i2c_vc=on`.

## 4. Mechanical

* Board 130 x 105 mm, 1.6 mm, 4 layers (Sig – GND – PWR – Sig), ENIG recommended for the 0.4 mm DF40 pads. JLCPCB 4-layer rules: 0.2/0.15 mm tracks/clearance generally, 0.1/0.1 mm and 0.45/0.2 mm vias inside the two CM4 fan-out rule areas.
* Four M2.5 holes on the 58 x 49 mm Raspberry Pi pattern (centred on the board), matching the Touch Display 2 standoffs. The display sits against the *bottom* side, so bottom-side parts are limited to 0603-1206 passives, one SOT-23 and the two mics (~1 mm tall); 114 parts live there, so order two-sided assembly.
* CM4 on top, centred over the standoff pattern; use the official CM4 heatsink (the design leaves the CM4 mounting holes free).
* All external connectors on the bottom edge (y = 105): microSD, USB-A, USB-C data, fan, speakers, display power, USB-C power. Display and camera FPC connectors sit above the CM4 with the cables exiting toward the top edge.
* Sensor tongue on the left edge with two 1.6 mm routed slots for thermal isolation; enclosure needs vent slots there and a light pipe for the BH1750.
* Mics at the top corners: 1.0 mm acoustic holes through the PCB (they are bottom-ported and mounted on the bottom side so they listen "up" through the board); enclosure needs matching holes with a gasket.
* LED bar along the top edge shining upward — enclosure needs a diffuser slot, or use the 3-pin header for a strip elsewhere.

## 5. Fan-out and routing notes

Every used CM4 pad gets a 0.1 mm stub to a 0.45/0.2 mm via, in three staggered rows (1.2 / 1.9 / 2.6 mm from the pad row). Inner rows fan out under the module, outer rows fan out away from it; the region below the lower connector (x 52-78, y 73-86) is kept free of components for this, and the lower fan-out rule area extends to y = 79.5 so the SD-card bus can leave the connector at 0.1 mm spacing. The routing was done by a negotiated-congestion grid router written for this project, then post-processed into conventional 0/45/90-degree geometry (staircases replaced by straight and 45-degree runs wherever clear, right-angle corners chamfered), and every differential pair was length-matched with small meander bumps on the shorter leg; the top/bottom GND pours use 0.25 mm minimum width and 0.25 mm clearance so they do not fragment into slivers, every pour island that ended up without a path to the internal GND plane got a stitching via, and a coarse grid of stitching vias ties the pours to the plane in the open areas (a connectivity check on the final board finds zero floating GND copper). In2 carries split power planes: 5V_SYS under the CM4, VBUS (15 V) along the right and bottom-right, 5V_USB bottom-left, 5V_PERIPH along the top, 3V3 under the sensor tongue.

### Differential-pair status (final board)

| Pair | Length P / N (mm) | Skew |
|---|---|---|
| DSI D0 / D1 / CLK | 19.0/18.8, 21.3/21.5, 20.4/20.6 | 0.1 / 0.2 / 0.2 mm |
| CSI D0 / D1 / CLK | 14.3/14.1, 17.1/16.6, 21.0/19.8 | 0.2 / 0.5 / 1.2 mm |
| CM4 USB -> U6 | 43.8/43.9 | 0.1 mm |
| U6 -> U7 (BOOT) | 6.8/7.2 | 0.3 mm |
| U6 -> hub upstream | 4.7/6.0 | 1.3 mm |
| hub -> U7 (DS1) | 3.4/4.2 | 0.8 mm |
| hub -> USB-A (signal path through the ESD diode) | 11.4/12.6 | 1.1 mm |
| hub -> internal headers DS3 / DS4 | 46.7/46.5, 34.2/34.0 | 0.2 / 0.2 mm |
| U7 -> USB-C #2 (signal path) | 22.9/15.2 | **7.7 mm** |

Everything except USB-C #2 is within 1.3 mm (under 10 ps), which is well inside what MIPI D-PHY and USB 2.0 receivers tolerate. The USB-C #2 data pair is the one that could not be matched automatically: the receptacle's A6/B6 and A7/B7 pads interleave, so one leg has to loop behind the connector, and the 0.5 mm-pitch mux pins leave no room for meanders. 7.7 mm is about 50 ps, 2.5 % of a USB high-speed bit, so it will work, but if you want it textbook-clean, re-route that pair with KiCad's interactive differential-pair router (Route -> Differential Pair, then Tune Skew) between U7 and J2. Nothing else on the board is impedance- or length-critical.

## 6. Options not populated (but discussed)

mmWave presence radar (LD2410 on the UART header), hardware mic/camera kill switch (can be added in series with the mic 3V3 and `Camera_GPIO`), Zigbee/Thread (a USB dongle on the internal USB header is the pragmatic route), IR blaster/receiver, PoE, RTC with coin cell, PIR.
