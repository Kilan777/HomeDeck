"""Generate the project symbol library (HomeDeck.kicad_sym) and footprint library (HomeDeck.pretty)."""
import os

OUT_SYM = os.path.join(os.path.dirname(__file__), "..", "kicad", "HomeDeck.kicad_sym")
OUT_FP = os.path.join(os.path.dirname(__file__), "..", "kicad", "HomeDeck.pretty")

FONT = '(effects (font (size 1.27 1.27)))'


def sym_pin(number, name, etype, x, y, rot, length=2.54):
    return (f'      (pin {etype} line (at {x:g} {y:g} {rot:g}) (length {length:g})\n'
            f'        (name "{name}" {FONT})\n'
            f'        (number "{number}" {FONT})\n      )\n')


def make_symbol(name, units, ref="U", value=None, footprint="", desc="", keywords=""):
    """units: list of dicts {left:[(num,name,type)], right:[...], top:[...], bottom:[...]}
    Pins are laid out at 2.54 spacing on a box sized to fit."""
    value = value or name
    out = [f'  (symbol "{name}" (in_bom yes) (on_board yes)\n']
    out.append(f'    (property "Reference" "{ref}" (at 0 2.54 0) {FONT})\n')
    out.append(f'    (property "Value" "{value}" (at 0 -2.54 0) {FONT})\n')
    out.append(f'    (property "Footprint" "{footprint}" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n')
    out.append(f'    (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n')
    if desc:
        out.append(f'    (property "ki_description" "{desc}" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n')
    if keywords:
        out.append(f'    (property "ki_keywords" "{keywords}" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n')
    for ui, u in enumerate(units, start=1):
        left, right, top, bottom = u.get("left", []), u.get("right", []), u.get("top", []), u.get("bottom", [])
        nl, nr, nt, nb = len(left), len(right), len(top), len(bottom)
        h = max(nl, nr, 1) * 2.54 + 2.54 * 2
        w = max(nt, nb, 1) * 2.54 + 2.54 * 2
        w = max(w, 15.24)
        # widen for long names
        maxname = max([len(p[1]) for p in left + right] + [0])
        w = max(w, maxname * 1.27 * 2 + 5.08)
        w = round(w / 2.54) * 2.54
        h = round(h / 2.54) * 2.54
        hw, hh = w / 2, h / 2
        out.append(f'    (symbol "{name}_{ui}_1"\n')
        out.append(f'      (rectangle (start {-hw:g} {hh:g}) (end {hw:g} {-hh:g}) (stroke (width 0.254) (type default)) (fill (type background)))\n')
        # left pins go down from top
        y0 = hh - 2.54 * 2
        for i, (num, nm, et) in enumerate(left):
            out.append(sym_pin(num, nm, et, -hw - 2.54, y0 - i * 2.54, 0))
        for i, (num, nm, et) in enumerate(right):
            out.append(sym_pin(num, nm, et, hw + 2.54, y0 - i * 2.54, 180))
        x0 = -hw + 2.54 * 2
        for i, (num, nm, et) in enumerate(top):
            out.append(sym_pin(num, nm, et, x0 + i * 2.54, hh + 2.54, 270))
        for i, (num, nm, et) in enumerate(bottom):
            out.append(sym_pin(num, nm, et, x0 + i * 2.54, -hh - 2.54, 90))
        out.append('    )\n')
    out.append('  )\n')
    return "".join(out)


# ---------------------------------------------------------------- CM4 symbol
def cm4_pins():
    """Return dict pin->(name, type) for the CM4 200-pin connector (from the CM4 datasheet Table 6)."""
    p = {}
    gnd = [1, 2, 7, 8, 13, 14, 22, 23, 32, 33, 42, 43, 52, 53, 59, 60, 65, 66, 71, 74, 98, 107, 108, 113, 114, 119, 120,
           125, 126, 131, 132, 137, 138, 144, 150, 155, 156, 161, 162, 167, 168, 173, 174, 179, 180, 185, 186, 191, 192, 197, 198]
    for g in gnd:
        p[g] = ("GND", "power_in")
    eth = {3: "ETH_PAIR3_P", 4: "ETH_PAIR1_P", 5: "ETH_PAIR3_N", 6: "ETH_PAIR1_N", 9: "ETH_PAIR2_N", 10: "ETH_PAIR0_N",
           11: "ETH_PAIR2_P", 12: "ETH_PAIR0_P", 15: "ETH_nLED3", 16: "ETH_SYNC_IN", 17: "ETH_nLED2", 18: "ETH_SYNC_OUT",
           19: "ETH_nLED1"}
    for k, v in eth.items():
        p[k] = (v, "bidirectional")
    p[20] = ("EEPROM_nWP", "input")
    p[21] = ("Pi_nLED_Activity", "open_collector")
    gpio = {24: 26, 25: 21, 26: 19, 27: 20, 28: 13, 29: 16, 30: 6, 31: 12, 34: 5, 37: 7, 38: 11, 39: 8, 40: 9, 41: 25,
            44: 10, 45: 24, 46: 22, 47: 23, 48: 27, 49: 18, 50: 17, 51: 15, 54: 4, 55: 14, 56: 3, 58: 2}
    for k, v in gpio.items():
        p[k] = (f"GPIO{v}", "bidirectional")
    p[35] = ("ID_SC", "bidirectional")
    p[36] = ("ID_SD", "bidirectional")
    sd = {57: "SD_CLK", 61: "SD_DAT3", 62: "SD_CMD", 63: "SD_DAT0", 64: "SD_DAT5", 67: "SD_DAT1", 68: "SD_DAT4",
          69: "SD_DAT2", 70: "SD_DAT7", 72: "SD_DAT6"}
    for k, v in sd.items():
        p[k] = (v, "bidirectional")
    p[73] = ("SD_VDD_OVERRIDE", "input")
    p[75] = ("SD_PWR_ON", "output")
    p[76] = ("Reserved", "no_connect")
    for k in (77, 79, 81, 83, 85, 87):
        p[k] = ("+5V", "power_in")
    p[78] = ("GPIO_VREF", "power_in")
    p[80] = ("SCL0", "bidirectional")
    p[82] = ("SDA0", "bidirectional")
    p[84] = ("CM4_3.3V", "power_out")
    p[86] = ("CM4_3.3V", "power_out")
    p[88] = ("CM4_1.8V", "power_out")
    p[90] = ("CM4_1.8V", "power_out")
    p[89] = ("WL_nDisable", "input")
    p[91] = ("BT_nDisable", "input")
    p[92] = ("RUN_PG", "bidirectional")
    p[93] = ("nRPIBOOT", "input")
    p[94] = ("AnalogIP1", "input")
    p[95] = ("PI_LED_nPWR", "open_collector")
    p[96] = ("AnalogIP0", "input")
    p[97] = ("Camera_GPIO", "output")
    p[99] = ("GLOBAL_EN", "input")
    p[100] = ("nEXTRST", "output")
    p[101] = ("USB_OTG_ID", "input")
    p[102] = ("PCIe_CLK_nREQ", "input")
    p[103] = ("USB_N", "bidirectional")
    p[104] = ("Reserved", "no_connect")
    p[105] = ("USB_P", "bidirectional")
    p[106] = ("Reserved", "no_connect")
    p[109] = ("PCIe_nRST", "output")
    p[110] = ("PCIe_CLK_P", "output")
    p[111] = ("VDAC_COMP", "passive")
    p[112] = ("PCIe_CLK_N", "output")
    p[116] = ("PCIe_RX_P", "input")
    p[118] = ("PCIe_RX_N", "input")
    p[122] = ("PCIe_TX_P", "output")
    p[124] = ("PCIe_TX_N", "output")
    cam = {115: "CAM1_D0_N", 117: "CAM1_D0_P", 121: "CAM1_D1_N", 123: "CAM1_D1_P", 127: "CAM1_C_N", 129: "CAM1_C_P",
           133: "CAM1_D2_N", 135: "CAM1_D2_P", 139: "CAM1_D3_N", 141: "CAM1_D3_P",
           128: "CAM0_D0_N", 130: "CAM0_D0_P", 134: "CAM0_D1_N", 136: "CAM0_D1_P", 140: "CAM0_C_N", 142: "CAM0_C_P"}
    for k, v in cam.items():
        p[k] = (v, "input")
    hdmi = {143: "HDMI1_HOTPLUG", 145: "HDMI1_SDA", 146: "HDMI1_TX2_P", 147: "HDMI1_SCL", 148: "HDMI1_TX2_N", 149: "HDMI1_CEC",
            151: "HDMI0_CEC", 152: "HDMI1_TX1_P", 153: "HDMI0_HOTPLUG", 154: "HDMI1_TX1_N", 158: "HDMI1_TX0_P", 160: "HDMI1_TX0_N",
            164: "HDMI1_CLK_P", 166: "HDMI1_CLK_N", 170: "HDMI0_TX2_P", 172: "HDMI0_TX2_N", 176: "HDMI0_TX1_P", 178: "HDMI0_TX1_N",
            182: "HDMI0_TX0_P", 184: "HDMI0_TX0_N", 188: "HDMI0_CLK_P", 190: "HDMI0_CLK_N", 199: "HDMI0_SDA", 200: "HDMI0_SCL"}
    for k, v in hdmi.items():
        p[k] = (v, "bidirectional")
    dsi = {157: "DSI0_D0_N", 159: "DSI0_D0_P", 163: "DSI0_D1_N", 165: "DSI0_D1_P", 169: "DSI0_C_N", 171: "DSI0_C_P",
           175: "DSI1_D0_N", 177: "DSI1_D0_P", 181: "DSI1_D1_N", 183: "DSI1_D1_P", 187: "DSI1_C_N", 189: "DSI1_C_P",
           193: "DSI1_D2_N", 194: "DSI1_D3_N", 195: "DSI1_D2_P", 196: "DSI1_D3_P"}
    for k, v in dsi.items():
        p[k] = (v, "output")
    assert len(p) == 200, len(p)
    return p


def cm4_symbol():
    p = cm4_pins()

    def pl(nums):
        return [(str(n), p[n][0], p[n][1]) for n in nums]
    gnd_all = [n for n in range(1, 201) if p[n][0] == "GND"]
    # Unit 1: power & control
    u1 = dict(left=pl([77, 79, 81, 83, 85, 87, 78, 84, 86, 88, 90]),
              right=pl([99, 92, 93, 100, 89, 91, 20, 21, 95, 94, 96, 97, 80, 82, 73, 75, 76, 104, 106, 111]),
              bottom=pl(gnd_all))
    # Unit 2: GPIO
    gp = sorted([n for n in range(24, 59) if p[n][0].startswith("GPIO")], key=lambda n: int(p[n][0][4:]))
    u2 = dict(left=pl(gp[:14]), right=pl(gp[14:]) + pl([36, 35]))
    # Unit 3: SD, USB, PCIe
    u3 = dict(left=pl([57, 62, 63, 67, 69, 61, 68, 64, 72, 70]),
              right=pl([105, 103, 101, 110, 112, 116, 118, 122, 124, 109, 102]))
    # Unit 4: CSI / DSI
    u4 = dict(left=pl([117, 115, 123, 121, 129, 127, 135, 133, 141, 139, 130, 128, 136, 134, 142, 140]),
              right=pl([177, 175, 183, 181, 189, 187, 195, 193, 196, 194, 159, 157, 165, 163, 171, 169]))
    # Unit 5: HDMI, Ethernet
    hd = [n for n in range(143, 201) if p[n][0].startswith("HDMI")]
    u5 = dict(left=pl(hd), right=pl([3, 5, 4, 6, 11, 9, 12, 10, 15, 17, 19, 16, 18]))
    return make_symbol("RPi_CM4", [u1, u2, u3, u4, u5], ref="M", value="RPi_CM4", footprint="HomeDeck:RPi_CM4",
                       desc="Raspberry Pi Compute Module 4 (2x Hirose DF40C-100DS-0.4V)", keywords="raspberry cm4")


def other_symbols():
    s = []
    s.append(make_symbol("CH224K", [dict(left=[("1", "VDD", "power_out"), ("2", "CFG1", "input"), ("3", "CFG2", "input"), ("9", "CFG3", "input"), ("10", "PG", "open_collector")],
                                         right=[("8", "VBUS", "input"), ("6", "CC1", "bidirectional"), ("7", "CC2", "bidirectional"), ("4", "DP", "bidirectional"), ("5", "DM", "bidirectional")],
                                         bottom=[("11", "GND", "power_in")])],
                         footprint="HomeDeck:ESSOP-10-1EP_3.9x4.9mm_P1.0mm", desc="USB PD sink controller", keywords="usb pd"))
    s.append(make_symbol("TPA3118D2", [dict(left=[("10", "LINP", "input"), ("11", "LINN", "input"), ("4", "RINP", "input"), ("5", "RINN", "input"),
                                                 ("2", "SDZ", "input"), ("12", "MUTE", "input"), ("3", "FAULTZ", "open_collector"), ("1", "MODSEL", "input"),
                                                 ("8", "GAIN/SLV", "input"), ("6", "PLIMIT", "input"), ("13", "AM2", "input"), ("14", "AM1", "input"), ("15", "AM0", "input"), ("16", "SYNC", "bidirectional")],
                                           right=[("23", "OUTPL", "output"), ("21", "OUTNL", "output"), ("24", "BSPL", "passive"), ("20", "BSNL", "passive"),
                                                  ("29", "OUTPR", "output"), ("27", "OUTNR", "output"), ("30", "BSPR", "passive"), ("26", "BSNR", "passive"),
                                                  ("7", "GVDD", "power_out")],
                                           top=[("17", "AVCC", "power_in"), ("18", "PVCC", "power_in"), ("19", "PVCC", "power_in"), ("31", "PVCC", "power_in"), ("32", "PVCC", "power_in")],
                                           bottom=[("9", "GND", "power_in"), ("22", "GND", "power_in"), ("25", "GND", "power_in"), ("28", "GND", "power_in"), ("33", "GND", "power_in")])],
                         footprint="Package_SO:HTSSOP-32-1EP_6.1x11mm_P0.65mm_EP5.2x11mm_Mask4.11x4.36mm_ThermalVias", desc="Stereo class-D amplifier 2x30W", keywords="amplifier class-d"))
    s.append(make_symbol("TS3USB221", [dict(left=[("8", "D+", "bidirectional"), ("7", "D-", "bidirectional"), ("9", "S", "input"), ("6", "OE", "input")],
                                           right=[("1", "1D+", "bidirectional"), ("2", "1D-", "bidirectional"), ("3", "2D+", "bidirectional"), ("4", "2D-", "bidirectional")],
                                           top=[("10", "VCC", "power_in")], bottom=[("5", "GND", "power_in")])],
                         footprint="Package_DFN_QFN:Texas_UQFN-10_1.5x2mm_P0.5mm", desc="USB 2.0 high-speed 2:1 switch", keywords="usb mux"))
    s.append(make_symbol("SY6280AAC", [dict(left=[("5", "IN", "power_in"), ("4", "EN", "input"), ("3", "ISET", "passive")],
                                           right=[("1", "OUT", "power_out")], bottom=[("2", "GND", "power_in")])],
                         footprint="Package_TO_SOT_SMD:SOT-23-5", desc="Current limited power switch", keywords="usb power switch"))
    s.append(make_symbol("BME688", [dict(left=[("8", "VDD", "power_in"), ("6", "VDDIO", "power_in"), ("2", "CSB", "input"), ("5", "SDO", "bidirectional")],
                                       right=[("3", "SDI", "bidirectional"), ("4", "SCK", "input")],
                                       bottom=[("1", "GND", "power_in"), ("7", "GND", "power_in")])],
                         footprint="Package_LGA:Bosch_LGA-8_3x3mm_P0.8mm_ClockwisePinNumbering", desc="Gas/humidity/pressure/temperature sensor", keywords="bosch sensor"))
    s.append(make_symbol("FPC_15P_1.0mm", [dict(left=[(str(i), str(i), "passive") for i in range(1, 16)], bottom=[("MP", "MP", "passive")])],
                         ref="J", footprint="HomeDeck:FPC_15P_1.0mm_BottomContact_RA", desc="15-pin 1.0mm FPC connector, bottom contact, right angle (Raspberry Pi DSI/CSI)", keywords="fpc"))
    s.append(make_symbol("microSD_104031", [dict(left=[("1", "DAT2", "bidirectional"), ("2", "DAT3/CD", "bidirectional"), ("3", "CMD", "bidirectional"), ("4", "VDD", "power_in"),
                                                       ("5", "CLK", "input"), ("6", "VSS", "power_in"), ("7", "DAT0", "bidirectional"), ("8", "DAT1", "bidirectional")],
                                                 right=[("9", "DET", "passive"), ("10", "DET_COM", "passive"), ("11", "SHIELD", "passive")])],
                         ref="J", footprint="Connector_Card:microSD_HC_Molex_104031-0811", desc="microSD socket Molex 104031-0811", keywords="microsd"))
    s.append(make_symbol("USB_A_R", [dict(left=[("1", "VBUS", "power_in"), ("2", "D-", "bidirectional"), ("3", "D+", "bidirectional"), ("4", "GND", "power_in"), ("5", "SHIELD", "passive")])],
                         ref="J", footprint="Connector_USB:USB_A_Molex_67643_Horizontal", desc="USB-A receptacle right angle THT", keywords="usb"))
    return "".join(s)


def write_symbols():
    txt = '(kicad_symbol_lib (version 20220914) (generator gen_lib)\n' + cm4_symbol() + other_symbols() + ')\n'
    os.makedirs(os.path.dirname(OUT_SYM), exist_ok=True)
    with open(OUT_SYM, "w") as f:
        f.write(txt)


# ---------------------------------------------------------------- footprints
FP_HDR = '(footprint "{name}" (version 20221018) (generator gen_lib) (layer "F.Cu")\n  (attr smd)\n' \
         '  (fp_text reference "REF**" (at 0 {ry}) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))\n' \
         '  (fp_text value "{name}" (at 0 {vy}) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))\n'


def fp_line(x1, y1, x2, y2, layer, w=0.12):
    return f'  (fp_line (start {x1:g} {y1:g}) (end {x2:g} {y2:g}) (stroke (width {w}) (type solid)) (layer "{layer}"))\n'


def fp_rect_lines(x1, y1, x2, y2, layer, w=0.12):
    return fp_line(x1, y1, x2, y1, layer, w) + fp_line(x2, y1, x2, y2, layer, w) + fp_line(x2, y2, x1, y2, layer, w) + fp_line(x1, y2, x1, y1, layer, w)


def pad_smd(num, x, y, w, h, rot=0, shape="roundrect", rr=0.25, layers='"F.Cu" "F.Paste" "F.Mask"'):
    extra = f' (roundrect_rratio {rr})' if shape == "roundrect" else ""
    return f'  (pad "{num}" smd {shape} (at {x:g} {y:g} {rot:g}) (size {w:g} {h:g}) (layers {layers}){extra})\n'


def pad_npth(x, y, d):
    return f'  (pad "" np_thru_hole circle (at {x:g} {y:g}) (size {d:g} {d:g}) (drill {d:g}) (layers "*.Cu" "*.Mask"))\n'


def fp_cm4():
    """CM4 footprint: geometry taken from the official CM4IO reference (origin at connector centre).
    Pads 0.2x0.7 at 0.4mm pitch; connector A columns x=-18.5 (odd) / -15.42 (even); connector B x=15.42 (odd) / 18.5 (even)."""
    name = "RPi_CM4"
    out = [FP_HDR.format(name=name, ry=-32, vy=27)]
    out.append('  (fp_text user "${REFERENCE}" (at 0 -5) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))\n')
    for i in range(50):
        y = -9.8 + i * 0.4
        # connector A
        out.append(pad_smd(2 * i + 1, -18.5, y, 0.7, 0.2, 0, shape="rect"))
        out.append(pad_smd(2 * i + 2, -15.42, y, 0.7, 0.2, 0, shape="rect"))
        # connector B
        out.append(pad_smd(101 + 2 * i, 15.42, y, 0.7, 0.2, 0, shape="rect"))
        out.append(pad_smd(102 + 2 * i, 18.5, y, 0.7, 0.2, 0, shape="rect"))
    # mounting holes (module holes, 48 x 33 pattern, inset 3.5 mm) - keep free
    for (x, y) in [(16.5, -26.5), (-16.5, -26.5), (16.5, 21.5), (-16.5, 21.5)]:
        out.append(pad_npth(x, y, 2.7))
    # module outline (40 x 55, corner radius 3.5) on F.Fab, courtyards for connectors
    out.append(fp_rect_lines(-20, -30, 20, 25, "F.Fab", 0.1))
    out.append(fp_rect_lines(-20, -30, 20, 25, "F.SilkS", 0.12))
    for xc in (-16.96, 16.96):
        out.append(fp_rect_lines(xc - 1.95, -11.55, xc + 1.95, 11.55, "F.CrtYd", 0.05))
    # pin 1 marker
    out.append('  (fp_circle (center -19.6 -10.6) (end -19.4 -10.6) (stroke (width 0.2) (type solid)) (fill none) (layer "F.SilkS"))\n')
    out.append('  (fp_circle (center 14.3 -10.6) (end 14.5 -10.6) (stroke (width 0.2) (type solid)) (fill none) (layer "F.SilkS"))\n')
    out.append(')\n')
    return name, "".join(out)


def fp_essop10():
    """ESSOP-10 3.9x4.9 body, 1.0 mm pitch, exposed pad (WCH CH224K)."""
    name = "ESSOP-10-1EP_3.9x4.9mm_P1.0mm"
    out = [FP_HDR.format(name=name, ry=-3.8, vy=3.8)]
    for i in range(5):
        y = -2.0 + i * 1.0
        out.append(pad_smd(i + 1, -2.75, y, 1.5, 0.6))
        out.append(pad_smd(10 - i, 2.75, y, 1.5, 0.6))
    out.append(pad_smd(11, 0, 0, 2.2, 3.2, shape="rect", rr=0))
    out.append(fp_rect_lines(-1.95, -2.45, 1.95, 2.45, "F.Fab", 0.1))
    out.append(fp_rect_lines(-3.75, -2.75, 3.75, 2.75, "F.CrtYd", 0.05))
    out.append(fp_line(-1.95, -2.65, -3.5, -2.65, "F.SilkS", 0.15))
    out.append(fp_line(-1.95, 2.65, 1.95, 2.65, "F.SilkS", 0.12))
    out.append(fp_line(-1.95, -2.65, 1.95, -2.65, "F.SilkS", 0.12))
    out.append(')\n')
    return name, "".join(out)


def fp_fpc15():
    """15-pin 1.0 mm bottom-contact right-angle FPC connector, land pattern from the BOOMELE 1.0-15PContact,Bottom
    drawing (JLC C66660): 0.6 x 2.2 pads on 1.0 pitch, 2.6 x 2.6 anchor pads 1.0 mm outside the end pads, anchor top edge
    1.8 mm below the signal-pad top edge. Same pad-1 side and pad row position as KiCad's TE_1-84952-5 footprint."""
    name = "FPC_15P_1.0mm_BottomContact_RA"
    out = [FP_HDR.format(name=name, ry=-4.2, vy=8.0)]
    out.append('  (fp_text user "${REFERENCE}" (at 0 3.5) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))\n')
    for i in range(15):
        out.append(pad_smd(i + 1, -7.0 + i, -1.8, 0.6, 2.2, shape="rect", rr=0))
    out.append(pad_smd("MP", -9.3, 0.2, 2.6, 2.6, shape="rect", rr=0))
    out.append(pad_smd("MP", 9.3, 0.2, 2.6, 2.6, shape="rect", rr=0))
    out.append(fp_rect_lines(-10.6, -1.0, 10.6, 6.5, "F.Fab", 0.1))
    out.append(fp_line(-7.5, -1.0, -7.0, 0.0, "F.Fab", 0.1))
    out.append(fp_line(-7.0, 0.0, -6.5, -1.0, "F.Fab", 0.1))
    out.append(fp_rect_lines(-11.2, -3.3, 11.2, 7.0, "F.CrtYd", 0.05))
    out.append(fp_line(-10.8, 6.7, 10.8, 6.7, "F.SilkS", 0.12))
    out.append(fp_line(-10.8, 1.8, -10.8, 6.7, "F.SilkS", 0.12))
    out.append(fp_line(10.8, 1.8, 10.8, 6.7, "F.SilkS", 0.12))
    out.append(fp_line(-7.9, -3.1, -7.0, -3.1, "F.SilkS", 0.15))
    out.append(')\n')
    return name, "".join(out)


def fp_mic_hole():
    """ICS-43434 with a 1.0 mm acoustic hole: reuse KiCad footprint but this variant is placed on the bottom side in layout."""
    return None


def write_footprints():
    os.makedirs(OUT_FP, exist_ok=True)
    for fn in (fp_cm4, fp_essop10, fp_fpc15):
        name, txt = fn()
        with open(os.path.join(OUT_FP, name + ".kicad_mod"), "w") as f:
            f.write(txt)


if __name__ == "__main__":
    write_symbols()
    write_footprints()
    print("wrote", OUT_SYM, OUT_FP)
