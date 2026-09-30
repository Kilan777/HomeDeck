# Rev A findings and the rev B change list

What actually happened when the first two rev A boards were assembled and brought up (September 2026), the
workarounds that are in place on board #1, and what the next revision should change. Board references use the
designators in `kicad/HomeDeck.kicad_pcb`.

## What works on rev A board #1

USB-C PD input, all three bucks, 3.3 V LDO, CM4 (wireless, 4 GB / 16 GB eMMC), Wi-Fi and Bluetooth, DSI display and
Goodix touch, Camera Module 3, SCD40 and BME688 on I2C6, J12 I2C header (SHT4x and BH1750 auto-detected), I2S
microphones, TPA3118 amplifier and speakers, RGB LED bar and the J17 strip (70 LEDs in one chain), fan on J21,
buttons A / B / power, user LED, USB hub and ports. Board #2 is assembled but has not been powered.

## Problems found, in order of importance

### 1. 15 V PD chargers trip on plug-in (power)

Laptop-class PD chargers negotiate 15 V and then trip their protection during the 5 to 15 V step. Only 9 V
sources worked (a 20 W phone charger). The likely cause is inrush into the roughly 280 uF of VBUS bulk capacitance
(C3 100 uF electrolytic plus the buck input caps) at the moment of the voltage step.

Workaround on board #1: request 9 V instead. CH224K configuration jumpers JP2 and JP3 were cut between the
bottom and centre pads and bridged centre to top (CFG2 and CFG3 to GND). The board runs fine at 9 V; the
amplifier has less headroom but the small speakers do not need it.

Rev B: add inrush limiting on VBUS (a P-channel soft-start or a hot-swap controller such as TPS2595, or at least
an NTC in series with C3), reduce C3, and make 9 V the default jumper setting with 15 V as the option. Consider
whether 15 V is needed at all: the only 15 V consumer is the amplifier, and 12 V or 9 V is enough for
Dayton ND65-class speakers.

### 2. 5V_PERIPH rail intermittent (power)

The 5V_PERIPH buck (U3) output was dead on first power-up: no LED bar, no display power on J8. It came alive on
handling the board at the office and stayed up, which points at a poor joint on L2 or at the rail side of the
output stage rather than at U3 itself. U2 and U3 both ran cold, so it was not a load fault.

Workaround: the display was temporarily powered from 5V_SYS on the J16 expansion header (pins 4 and 6). After
the joint reflowed itself the normal path works. Reflow L2 on both boards before trusting them.

Rev B: use a smaller, easier-to-solder inductor footprint for L1 to L3 (the current one is wide and sits over
a plane cutout), add test points on every rail output (5V_SYS, 5V_PERIPH, 5V_USB, 3V3, VBUS), and route the
rails so a meter probe reaches them without a wire.

### 3. microSD slot does not work with an eMMC CM4 (design)

The eMMC variants of the CM4 disable the SD interface, so the slot is dead by design with the module installed.
It only works with a CM4 Lite.

Rev B: either drop the slot and the SD switching, or document it as Lite-only. Storage for camera clips went to
the cloud instead (Google Drive via rclone).

### 4. Button A shares GPIO16 with the voice HAT overlay (firmware)

The stock `googlevoicehat-soundcard` overlay claims GPIO16, which is button A. A custom overlay
(`homedeck-audio.dtbo`, same sound card with the amplifier shutdown line moved) fixed it.

Rev B: keep GPIO16 free of buttons, or pick GPIOs that no common audio overlay uses.

### 5. Amplifier pops on shutdown toggling (audio)

Toggling AMP_SDZ (GPIO4) per playback produced pops. The line is now held high permanently and the amplifier is
muted by silence only; the overlay's shutdown control was moved to an unused pin (GPIO13).

Rev B: add a proper mute (TPA3118 has MUTE separate from SDZ) with an RC ramp, and keep the DAC running between
plays. A hardware volume control is not needed because the DAC has none anyway; software volume via ALSA
softvol is fine.

### 6. Temperature sensors read high (thermal)

The SCD40 and BME688 sit close to the CM4 and its heat sink; in portrait mounting they were above the module in
the rising warm air and read 8 to 10 F high. Landscape mounting (sensors beside the module) and a configurable
offset fixed it in software.

Rev B: move the environmental sensors to the board edge farthest from the CM4, ideally on a slot-isolated
tongue with its own vent opening in the enclosure, and put the fan header where the fan pulls air across the
CM4 and away from the sensors.

### 7. Display panel sometimes fails to probe at boot (mechanical)

Occasionally the touch controller returns I2C errors at boot and the panel stays dark; a power cycle with the J6
ribbon reseated fixes it. Swapping the display and camera ribbons (they are different lengths) also broke the
display once.

Rev B: use a locking FPC connector for J6 and label the two FPC connectors clearly with their ribbon lengths.

### 8. Fan is on/off only (features)

J21 drives the fan through a low-side switch on GPIO25. Speed control needs PWM, which the software driver
supports but the hardware does not do smoothly (fans stall below about 35 percent and the switch is not meant
for 25 kHz).

Rev B: a proper PWM fan stage (logic-level MOSFET with a flyback diode, or a 4-wire fan header with a PWM line).

### 9. Chargers report under-voltage at 5 V (power)

With a plain 5 V USB source the CM4 reports under-voltage. Expected, since the design needs PD, but the board
should refuse to boot cleanly rather than brown out.

Rev B: a VBUS good comparator that holds the CM4 in reset below 8.5 V, and a status LED for "PD contract OK".

### 10. Minor

- The onboard LED bar (first 10 LEDs of the chain) is not used in the final enclosure; the external J17 strip is.
  Rev B could drop the bar or put it on a separate data line so the strip index does not start at 10.
- J19 and J20 button headers were clipped off to make room; only J18 (power button) is used.
- `config.txt` on Trixie does not accept trailing comments on a line; the bring-up doc now says so.
- Keep `enable_uart=1` and a serial adapter handy for bring-up; it saved time twice.
- Add the CM4 stack height (1.5 mm DF40C) and the display standoff pattern to the enclosure notes; the enclosure
  reference SVG lives outside the repo.

## Rev B change list, short form

1. Inrush limiter on VBUS, smaller C3, 9 V default jumpers.
2. Rail test points and friendlier inductor footprints.
3. Drop or clearly mark the microSD slot.
4. Move buttons off GPIO16; move the sensors away from the CM4; fan header positioned for airflow.
5. Amplifier mute with a ramp; keep SDZ high.
6. PWM fan stage.
7. Locking FPC connector for the display; label ribbon lengths.
8. VBUS-good reset gate and a PD status LED.
9. Optional: remove the onboard LED bar.
