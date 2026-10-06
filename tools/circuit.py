"""HomeDeck CM4 carrier - complete circuit definition."""
from netlist import Circuit

# LCSC numbers (verified against jlcpcb.com/partdetail during design, Sept 2026)
L = dict(
    R10k="C25804", R1k="C21190", R4k7="C23162", R100="C22775", R22="C23345", R5k1="C23186", R22k="C31850", R0="C21189",
    R15k="C22809", R20k="C4184", R100k="C25803", R470="C23179", R220="C22962", R330="C23138", R2k2="C4190", R10="C22859",
    R3k3="C22978", R56k="C23206", R33="C23140",
    C100n="C14663", C1u="C15849", C10u_0603="C96446", C22u_1206="C12891", C10u50_1206="C13585", C2u2="C23630",
    C10n="C57112", C1n="C1588", C2n2="C1604", C22p="C1653", C220n="C21120", C680n_0805="C28323", CP100u35="C3339",
    C4u7_50_1206="C29823", C100p="C14858",
)


def build():
    c = Circuit()
    c.pwr_flags = ["GND", "VBUS_RAW", "VBUS", "5V_SYS", "5V_PERIPH", "5V_USB", "SD_VDD", "HUB_V33", "AMP_GVDD", "DAC_AVDD", "AMP_AVCC"]

    # ------------------------------------------------------------ mechanical
    for i in range(4):
        c.add("H", "Mechanical", "MountingHole", "M2.5 display standoff", "MountingHole:MountingHole_2.7mm_M2.5", "", "mech", ref=f"H{i+1}")

    # ------------------------------------------------------------ USB-C power input + PD sink
    sh = "power"
    j = c.add("J", "Connector", "USB_C_Receptacle_USB2.0_16P", "USB-C PD IN", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
              "C165948", sh, mpn="TYPE-C-31-M-12", ref="J1", desc="USB-C receptacle 16P (power input)")
    j.cn({"A4": "VBUS_RAW", "A9": "VBUS_RAW", "B4": "VBUS_RAW", "B9": "VBUS_RAW", "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",
          "S1": "GND", "A5": "PD_CC1", "B5": "PD_CC2", "A6": "PD_DP", "B6": "PD_DP", "A7": "PD_DM", "B7": "PD_DM"})
    j.noconnect("SBU1", "SBU2")
    f = c.add("F", "Device", "Fuse", "5A", "Fuse:Fuse_1206_3216Metric", "C48332", sh, mpn="SF-1206F500-2", basic=False, ref="F1", desc="5 A fast-acting 1206 fuse (Bourns)")
    f.cn({1: "VBUS_RAW", 2: "VBUS"})
    d = c.add("D", "Device", "D_TVS", "SMBJ24A", "Diode_SMD:D_SMB", "C87268", sh, mpn="SMBJ24A", basic=False, ref="D1", desc="VBUS TVS, cathode (band) to VBUS")
    d.cn({1: "VBUS", 2: "GND"})  # pad 1 = cathode/band on D_SMB
    c.C("10uF/50V", "VBUS", "GND", L["C10u50_1206"], sh, "1206")
    c.C("10uF/50V", "VBUS", "GND", L["C10u50_1206"], sh, "1206")
    c.CP("100uF/35V", "VBUS", "GND", L["CP100u35"], sh)

    u = c.add("U", "HomeDeck", "CH224K", "CH224K", None, "C970725", sh, mpn="CH224K", basic=False, ref="U1", desc="USB PD sink controller")
    u.c(VDD="PD_VDD", CFG1="PD_CFG1", CFG2="PD_CFG2", CFG3="PD_CFG3", PG="PD_GOOD", VBUS="PD_VBUS_SENSE", CC1="PD_CC1", CC2="PD_CC2",
        DP="PD_DP", DM="PD_DM", GND="GND")
    c.R("5.1k", "VBUS", "PD_VBUS_SENSE", L["R5k1"], sh)
    c.R("1k/0.25W", "VBUS", "PD_VDD", "C4410", sh, size="1206")  # CH224K VDD is an internal shunt regulator fed through 1k from VBUS
    c.C("1uF", "PD_VDD", "GND", L["C1u"], sh)
    # voltage select solder jumpers: default CFG1=0, CFG2=1, CFG3=1 -> 15 V
    for name, net, pin1, pin3 in (("JP1", "PD_CFG1", "GND", "PD_VDD"), ("JP2", "PD_CFG2", "PD_VDD", "GND"), ("JP3", "PD_CFG3", "PD_VDD", "GND")):
        jp = c.add("JP", "Jumper", "SolderJumper_3_Bridged12", "PD volt sel", "Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm", "", sh, ref=name)
        jp.cn({1: pin1, 2: net, 3: pin3})
    c.R("10k", "CM4_3V3", "PD_GOOD", L["R10k"], sh)
    led = c.add("D", "Device", "LED", "PD OK (green)", "LED_SMD:LED_0805_2012Metric", "C2297", sh, mpn="KT-0805G", ref="D2")
    led.cn({1: "PD_GOOD", 2: "PD_LED_A"})  # K=1 to PG (open drain), A via resistor to 3V3
    c.R("470R", "3V3", "PD_LED_A", L["R470"], sh)

    # ------------------------------------------------------------ three TPS5430 bucks
    for idx, rail in enumerate(["5V_SYS", "5V_PERIPH", "5V_USB"]):
        ref = f"U{2+idx}"
        ph, boot, fb = f"BK{idx+1}_PH", f"BK{idx+1}_BOOT", f"BK{idx+1}_FB"
        u = c.add("U", "Regulator_Switching", "TPS5430DDA", "TPS5430", "Package_SO:TI_SO-PowerPAD-8_ThermalVias", "C9864", sh,
                  mpn="TPS5430DDAR", basic=True, ref=ref, desc=f"3A buck -> {rail}")
        u.c(VIN="VBUS", BOOT=boot, PH=ph, VSENSE=fb, GND="GND", GNDPAD="GND")
        u.noconnect("EN", "NC")
        c.C("10uF/50V", "VBUS", "GND", L["C10u50_1206"], sh, "1206")
        c.C("100nF", "VBUS", "GND", L["C100n"], sh)
        c.C("10nF", ph, boot, L["C10n"], sh)
        dd = c.add("D", "Device", "D_Schottky", "SS34", "Diode_SMD:D_SMA", "C8678", sh, mpn="SS34", ref=f"D{7+idx}")
        dd.cn({1: ph, 2: "GND"})  # K=PH, A=GND
        ind = c.add("L", "Device", "L", "10uH 7.8A", "Inductor_SMD:L_Sunlord_MWSA1004S", "C408487", sh, mpn="MWSA1004S-100MT", basic=False)
        ind.cn({1: ph, 2: rail})
        c.CP("100uF/35V", rail, "GND", L["CP100u35"], sh)
        c.C("22uF/25V", rail, "GND", L["C22u_1206"], sh, "1206")
        c.C("100nF", rail, "GND", L["C100n"], sh)
        c.R("15k", rail, fb, L["R15k"], sh)
        c.R("4.7k", fb, "GND", L["R4k7"], sh)

    # ------------------------------------------------------------ 3.3 V LDO
    u = c.add("U", "Regulator_Linear", "AMS1117-3.3", "AMS1117-3.3", None, "C6186", sh, mpn="AMS1117-3.3", basic=True, ref="U5")
    u.c(VI="5V_SYS", VO="3V3", GND="GND")
    c.C("22uF/25V", "5V_SYS", "GND", L["C22u_1206"], sh, "1206")
    c.C("22uF/25V", "3V3", "GND", L["C22u_1206"], sh, "1206")
    c.CP("100uF/35V", "3V3", "GND", L["CP100u35"], sh, ref="C96")   # electrolytic on the LDO output: AMS1117 wants some ESR to stay stable
    c.C("100nF", "3V3", "GND", L["C100n"], sh)

    # ------------------------------------------------------------ CM4
    sh = "cm4"
    m = c.add("M", "HomeDeck", "RPi_CM4", "Raspberry Pi CM4", None, "", sh, mpn="CM4", ref="M1", desc="Compute Module 4 (2x DF40C-100DS-0.4V(51), JLC C597931)")
    gpio_nets = {2: "GPIO2", 3: "PWR_BTN", 4: "AMP_SDZ", 5: "AMP_MUTE", 6: "AMP_FAULT", 7: "GPIO7", 8: "GPIO8", 9: "GPIO9",
                 10: "LED_DATA", 11: "GPIO11", 12: "USER_LED", 13: "GPIO13", 14: "UART_TX", 15: "UART_RX", 16: "BTN_A", 17: "GPIO17",
                 18: "I2S_BCLK", 19: "I2S_LRCLK", 20: "I2S_DIN", 21: "I2S_DOUT", 22: "I2C6_SDA", 23: "I2C6_SCL", 24: "DAC_XSMT",
                 25: "FAN_PWM", 26: "BTN_B", 27: "PD_GOOD"}
    m.c(**{f"GPIO{k}": v for k, v in gpio_nets.items()})
    m.c(ID_SD="ID_SD", ID_SC="ID_SC")
    m.cn({77: "5V_SYS", 79: "5V_SYS", 81: "5V_SYS", 83: "5V_SYS", 85: "5V_SYS", 87: "5V_SYS"})
    m.c(GPIO_VREF="CM4_3V3")
    m.cn({84: "CM4_3V3", 86: "CM4_3V3"})
    m.c(GND="GND", GLOBAL_EN="GLOBAL_EN", RUN_PG="RUN_PG", nRPIBOOT="nRPIBOOT", Pi_nLED_Activity="ACT_LED_K", PI_LED_nPWR="PWR_LED_K",
        Camera_GPIO="CAM_GPIO", SCL0="I2C0_SCL", SDA0="I2C0_SDA", SD_PWR_ON="SD_PWR_ON", USB_P="USB_CM4_P", USB_N="USB_CM4_N", USB_OTG_ID="USB_OTG_ID",
        SD_CLK="SD_CLK", SD_CMD="SD_CMD", SD_DAT0="SD_DAT0", SD_DAT1="SD_DAT1", SD_DAT2="SD_DAT2", SD_DAT3="SD_DAT3",
        DSI1_D0_N="DSI_D0_N", DSI1_D0_P="DSI_D0_P", DSI1_D1_N="DSI_D1_N", DSI1_D1_P="DSI_D1_P", DSI1_C_N="DSI_C_N", DSI1_C_P="DSI_C_P",
        CAM1_D0_N="CSI_D0_N", CAM1_D0_P="CSI_D0_P", CAM1_D1_N="CSI_D1_N", CAM1_D1_P="CSI_D1_P", CAM1_C_N="CSI_C_N", CAM1_C_P="CSI_C_P")
    m.nc_rest()
    # (no I2C0 pull-ups: the CM4 has 1.8k internal pull-ups on SDA0/SCL0)
    c.R("10k", "CM4_3V3", "nRPIBOOT", L["R10k"], sh)
    c.R("0R", "USB_OTG_ID", "GND", L["R0"], sh, dnp=True)
    c.C("100nF", "CM4_3V3", "GND", L["C100n"], sh)
    c.C("10uF", "5V_SYS", "GND", L["C10u_0603"], sh)
    c.C("10uF", "5V_SYS", "GND", L["C10u_0603"], sh)
    c.C("100nF", "5V_SYS", "GND", L["C100n"], sh)
    # LEDs from CM4 open-drain pins
    led = c.add("D", "Device", "LED", "ACT (green)", "LED_SMD:LED_0805_2012Metric", "C2297", sh, mpn="KT-0805G", ref="D3")
    led.cn({1: "ACT_LED_K", 2: "ACT_LED_A"})
    c.R("330R", "CM4_3V3", "ACT_LED_A", L["R330"], sh)
    # PI_LED_nPWR must be buffered (CM4 datasheet): P-FET high-side switch
    qp = c.add("Q", "Transistor_FET", "AO3401A", "AO3401A", None, "C15127", sh, mpn="AO3401A", basic=True, ref="Q4", desc="PWR LED buffer")
    qp.c(S="CM4_3V3", G="PWR_LED_K", D="PWR_LED_D")
    c.R("100k", "CM4_3V3", "PWR_LED_K", L["R100k"], sh)
    led = c.add("D", "Device", "LED", "PWR (red)", "LED_SMD:LED_0603_1608Metric", "C2286", sh, mpn="KT-0603R", ref="D4")
    led.cn({1: "GND", 2: "PWR_LED_A"})
    c.R("1k", "PWR_LED_D", "PWR_LED_A", L["R1k"], sh)
    # headers: GLOBAL_EN, nRPIBOOT jumper, UART, expansion
    jj = c.add("J", "Connector_Generic", "Conn_01x02", "GLOBAL_EN", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", "C124375", sh, mpn="B-2100S02P-A110", ref="J13")
    jj.cn({1: "GLOBAL_EN", 2: "GND"})
    jj = c.add("J", "Connector_Generic", "Conn_01x02", "nRPIBOOT", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", "C124375", sh, mpn="B-2100S02P-A110", ref="J14")
    jj.cn({1: "nRPIBOOT", 2: "GND"})
    jj = c.add("J", "Connector_Generic", "Conn_01x03", "UART debug", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", "C124376", sh, mpn="B-2100S03P-A110", ref="J15")
    jj.cn({1: "GND", 2: "UART_TX", 3: "UART_RX"})
    jj = c.add("J", "Connector_Generic", "Conn_02x08_Odd_Even", "Expansion", "Connector_PinHeader_2.54mm:PinHeader_2x08_P2.54mm_Vertical", "C492425", sh, mpn="PZ254V-12-16P", ref="J16")
    jj.cn({1: "3V3", 2: "5V_SYS", 3: "GPIO2", 4: "5V_SYS", 5: "GPIO7", 6: "GND", 7: "GPIO8", 8: "UART_TX", 9: "GPIO9", 10: "UART_RX",
           11: "GPIO11", 12: "GPIO13", 13: "GPIO17", 14: "ID_SD", 15: "GND", 16: "ID_SC"})
    sw = c.add("SW", "Switch", "SW_Push", "RESET", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", "C318884", sh, mpn="TS-1187A-B-A-B", ref="SW4")
    sw.cn({1: "RUN_SW", 2: "GND"})
    c.R("220R", "RUN_PG", "RUN_SW", L["R220"], sh)

    # ------------------------------------------------------------ USB mux + hub + ports
    sh = "usb"
    # U6 (CM4 side) has its two switch ports swapped relative to U7 so that on the PCB the BOOT pair
    # leaves U6 from the pins facing U7 without crossing the hub pair; its select input is therefore
    # the inverted nRPIBOOT (Q5 + R47). TS3USB221: S low -> 1D, S high -> 2D.
    for ref, common, d1, d2, sel in (("U6", "USB_CM4", "USB_HUB_UP", "USB_BOOT", "MUX_SEL_B"), ("U7", "USB_C2", "USB_BOOT", "USB_DS1", "nRPIBOOT")):
        u = c.add("U", "HomeDeck", "TS3USB221", "TS3USB221", None, "C130085", sh, mpn="TS3USB221RSER", basic=False, ref=ref, desc="USB 2.0 2:1 mux")
        u.c(**{"D+": common + "_P", "D-": common + "_N", "1D+": d1 + "_P", "1D-": d1 + "_N", "2D+": d2 + "_P", "2D-": d2 + "_N",
               "S": sel, "OE": "GND", "VCC": "3V3", "GND": "GND"})
        c.C("100nF", "3V3", "GND", L["C100n"], sh)
    q = c.add("Q", "Transistor_FET", "2N7002", "2N7002", None, "C8545", sh, mpn="2N7002", basic=True, ref="Q5", desc="nRPIBOOT inverter for U6 select")
    q.c(G="nRPIBOOT", D="MUX_SEL_B", S="GND")
    c.R("10k", "3V3", "MUX_SEL_B", L["R10k"], sh, ref="R47")
    u = c.add("U", "Interface_USB", "CH334R", "CH334R", None, "C4154405", sh, mpn="CH334R", basic=False, ref="U8", desc="USB 2.0 4-port hub")
    u.c(**{"DPU+": "USB_HUB_UP_P", "DMU-": "USB_HUB_UP_N", "DP1+": "USB_DS1_P", "DM1-": "USB_DS1_N", "DP2+": "USB_DSA_P", "DM2-": "USB_DSA_N",
           "DP3+": "USB_DS3_P", "DM3-": "USB_DS3_N", "DP4+": "USB_DS4_P", "DM4-": "USB_DS4_N", "V5": "5V_SYS", "VDD33": "HUB_V33", "GND": "GND",
           "XI": "HUB_XI", "XO": "HUB_XO", "~{RESET}/CDP": "HUB_nRST"})
    c.C("1uF", "5V_SYS", "GND", L["C1u"], sh)
    c.C("10uF", "HUB_V33", "GND", L["C10u_0603"], sh)
    c.C("100nF", "HUB_V33", "GND", L["C100n"], sh)
    c.R("10k", "HUB_V33", "HUB_nRST", L["R10k"], sh)
    c.C("100nF", "HUB_nRST", "GND", L["C100n"], sh)
    y = c.add("Y", "Device", "Crystal_GND24", "12MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", "C9002", sh, mpn="X322512MSB4SI", ref="Y1")
    y.cn({1: "HUB_XI", 3: "HUB_XO", 2: "GND", 4: "GND"})
    # CH334R has built-in crystal load capacitors: footprints kept, parts not populated
    c.C("22pF", "HUB_XI", "GND", L["C22p"], sh, dnp=True)
    c.C("22pF", "HUB_XO", "GND", L["C22p"], sh, dnp=True)
    # USB-C #2 (data + 5 V out)
    j = c.add("J", "Connector", "USB_C_Receptacle_USB2.0_16P", "USB-C DATA/5V", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
              "C165948", sh, mpn="TYPE-C-31-M-12", ref="J2")
    j.cn({"A4": "5V_USBC2", "A9": "5V_USBC2", "B4": "5V_USBC2", "B9": "5V_USBC2", "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",
          "S1": "GND", "A5": "C2_CC1", "B5": "C2_CC2", "A6": "USB_C2_P", "B6": "USB_C2_P", "A7": "USB_C2_N", "B7": "USB_C2_N"})
    j.noconnect("SBU1", "SBU2")
    c.R("22k", "5V_USBC2", "C2_CC1", L["R22k"], sh)
    c.R("22k", "5V_USBC2", "C2_CC2", L["R22k"], sh)
    e = c.add("U", "Power_Protection", "USBLC6-2SC6", "USBLC6-2SC6", None, "C7519", sh, mpn="USBLC6-2SC6", basic=False, ref="U9")
    e.cn({1: "USB_C2_P", 6: "USB_C2_P", 3: "USB_C2_N", 4: "USB_C2_N", 5: "5V_USBC2", 2: "GND"})
    ps = c.add("U", "HomeDeck", "SY6280AAC", "SY6280AAC", None, "C55136", sh, mpn="SY6280AAC", basic=False, ref="U10", desc="USB-C #2 power switch 1.3A")
    ps.c(IN="5V_USB", EN="nRPIBOOT", ISET="C2_ISET", OUT="5V_USBC2", GND="GND")
    c.R("3.9k", "C2_ISET", "GND", "C23018", sh)  # 1.74 A limit, matches the 1.5 A Rp advertisement
    c.C("10uF", "5V_USB", "GND", L["C10u_0603"], sh)
    c.C("10uF", "5V_USBC2", "GND", L["C10u_0603"], sh)
    # USB-A
    j = c.add("J", "HomeDeck", "USB_A_R", "USB-A", None, "C2346", sh, mpn="901-211A1021D10100", ref="J3")
    j.c(VBUS="5V_USBA", **{"D-": "USB_DSA_N", "D+": "USB_DSA_P"}, GND="GND", SHIELD="GND")
    e = c.add("U", "Power_Protection", "USBLC6-2SC6", "USBLC6-2SC6", None, "C7519", sh, mpn="USBLC6-2SC6", basic=False, ref="U11")
    e.cn({1: "USB_DSA_P", 6: "USB_DSA_P", 3: "USB_DSA_N", 4: "USB_DSA_N", 5: "5V_USBA", 2: "GND"})
    ps = c.add("U", "HomeDeck", "SY6280AAC", "SY6280AAC", None, "C55136", sh, mpn="SY6280AAC", basic=False, ref="U12", desc="USB-A power switch 1.3A")
    ps.c(IN="5V_USB", EN="3V3", ISET="A_ISET", OUT="5V_USBA", GND="GND")
    c.R("5.1k", "A_ISET", "GND", L["R5k1"], sh)
    c.C("10uF", "5V_USB", "GND", L["C10u_0603"], sh)
    c.C("10uF", "5V_USBA", "GND", L["C10u_0603"], sh)
    # internal USB headers
    for ref, ds in (("J4", "USB_DS3"), ("J5", "USB_DS4")):
        jj = c.add("J", "Connector_Generic", "Conn_01x04", "USB int", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", "C124378", sh, mpn="B-2100S04P-A110", ref=ref)
        jj.cn({1: "5V_USB", 2: ds + "_N", 3: ds + "_P", 4: "GND"})

    # ------------------------------------------------------------ display + camera
    sh = "video"
    j = c.add("J", "HomeDeck", "FPC_15P_1.0mm", "DISPLAY (DSI1)", None, "C66660", sh, mpn="1.0-15PContact,Bottom", basic=False, ref="J6", desc="15-pin 1.0mm FPC, bottom contact, right angle (BOOMELE)")
    j.cn({1: "GND", 2: "DSI_D1_N", 3: "DSI_D1_P", 4: "GND", 5: "DSI_C_N", 6: "DSI_C_P", 7: "GND", 8: "DSI_D0_N", 9: "DSI_D0_P", 10: "GND",
          11: "I2C0_SCL", 12: "I2C0_SDA", 13: "GND", 14: "CM4_3V3", 15: "CM4_3V3", "MP": "GND"})
    j = c.add("J", "HomeDeck", "FPC_15P_1.0mm", "CAMERA (CAM1)", None, "C66660", sh, mpn="1.0-15PContact,Bottom", basic=False, ref="J7", desc="15-pin 1.0mm FPC, bottom contact, right angle (BOOMELE)")
    j.cn({1: "GND", 2: "CSI_D0_N", 3: "CSI_D0_P", 4: "GND", 5: "CSI_D1_N", 6: "CSI_D1_P", 7: "GND", 8: "CSI_C_N", 9: "CSI_C_P", 10: "GND",
          11: "CAM_GPIO", 13: "I2C0_SCL", 14: "I2C0_SDA", 15: "CM4_3V3", "MP": "GND"})
    j.nc.add("12")
    jj = c.add("J", "Connector_Generic", "Conn_01x03", "DISPLAY 5V", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", "C124376", sh, mpn="B-2100S03P-A110", ref="J8")
    jj.cn({1: "5V_PERIPH", 2: "5V_PERIPH", 3: "GND"})
    c.C("10uF", "5V_PERIPH", "GND", L["C10u_0603"], sh)
    c.C("100nF", "CM4_3V3", "GND", L["C100n"], sh)

    # ------------------------------------------------------------ microSD
    sh = "sd"
    j = c.add("J", "HomeDeck", "microSD_104031", "microSD", None, "C585350", sh, mpn="104031-0811", basic=False, ref="J9")
    j.c(DAT2="SD_DAT2", CMD="SD_CMD", VDD="SD_VDD", CLK="SD_CLK", VSS="GND", DAT0="SD_DAT0", DAT1="SD_DAT1", DET="GND", DET_COM="GND", SHIELD="GND")
    j.c(**{"DAT3/CD": "SD_DAT3"})
    q = c.add("Q", "Transistor_FET", "AO3401A", "AO3401A", None, "C15127", sh, mpn="AO3401A", basic=True, ref="Q1")
    q.c(S="3V3", D="SD_VDD", G="SD_PWR_G")
    c.R("10k", "3V3", "SD_PWR_G", L["R10k"], sh)
    q = c.add("Q", "Transistor_FET", "2N7002", "2N7002", None, "C8545", sh, mpn="2N7002", basic=True, ref="Q2")
    q.c(G="SD_PWR_ON", D="SD_PWR_G", S="GND")
    c.R("10k", "CM4_3V3", "SD_PWR_ON", L["R10k"], sh)   # pull-up referenced to the CM4 rail like every other CM4 pin
    c.C("10uF", "SD_VDD", "GND", L["C10u_0603"], sh)
    c.C("100nF", "SD_VDD", "GND", L["C100n"], sh)

    # ------------------------------------------------------------ audio
    sh = "audio"
    u = c.add("U", "Audio", "PCM5102A", "PCM5102A", None, "C107671", sh, mpn="PCM5102APWR", basic=False, ref="U13", desc="I2S stereo DAC")
    u.c(DVDD="3V3", AVDD="DAC_AVDD", CPVDD="3V3", DGND="GND", AGND="GND", CPGND="GND", CAPP="DAC_CAPP", CAPM="DAC_CAPM", VNEG="DAC_VNEG",
        LDOO="DAC_LDOO", SCK="GND", BCK="I2S_BCLK", DIN="I2S_DOUT", LRCK="I2S_LRCLK", FMT="GND", DEMP="GND", FLT="GND", XSMT="DAC_XSMT",
        OUTL="DAC_OUTL", OUTR="DAC_OUTR")
    c.R("10R", "3V3", "DAC_AVDD", L["R10"], sh)
    c.C("10uF", "DAC_AVDD", "GND", L["C10u_0603"], sh)
    c.C("100nF", "DAC_AVDD", "GND", L["C100n"], sh)
    c.C("100nF", "3V3", "GND", L["C100n"], sh)
    c.C("10uF", "3V3", "GND", L["C10u_0603"], sh)
    c.C("2.2uF", "DAC_CAPP", "DAC_CAPM", L["C2u2"], sh)
    c.C("2.2uF", "DAC_VNEG", "GND", L["C2u2"], sh)
    c.C("2.2uF", "DAC_LDOO", "GND", L["C2u2"], sh)
    c.R("10k", "CM4_3V3", "DAC_XSMT", L["R10k"], sh)
    for ch in ("L", "R"):
        c.R("470R", f"DAC_OUT{ch}", f"AO{ch}", L["R470"], sh)
        c.C("2.2nF", f"AO{ch}", "GND", L["C2n2"], sh)
        c.R("22k", f"AO{ch}", f"AO{ch}2", L["R22k"], sh)
        c.R("6.8k", f"AO{ch}2", "GND", "C23212", sh)  # ~0.42 Vrms full scale into the 26 dB amp -> no clipping at 15 V
        c.C("1uF", f"AO{ch}2", f"AMP_IN{ch}P", L["C1u"], sh)
        c.C("1uF", f"AMP_IN{ch}N", "GND", L["C1u"], sh)
    a = c.add("U", "HomeDeck", "TPA3118D2", "TPA3118D2", None, "C46497", sh, mpn="TPA3118D2DAPR", basic=False, ref="U14", desc="Stereo class-D amplifier")
    a.c(LINP="AMP_INLP", LINN="AMP_INLN", RINP="AMP_INRP", RINN="AMP_INRN", SDZ="AMP_SDZ", MUTE="AMP_MUTE", FAULTZ="AMP_FAULT", MODSEL="GND",
        PLIMIT="AMP_GVDD", AM2="GND", AM1="GND", AM0="GND", GVDD="AMP_GVDD", AVCC="AMP_AVCC", PVCC="VBUS", GND="GND",
        OUTPL="AMP_OUTPL", OUTNL="AMP_OUTNL", BSPL="AMP_BSPL", BSNL="AMP_BSNL", OUTPR="AMP_OUTPR", OUTNR="AMP_OUTNR", BSPR="AMP_BSPR", BSNR="AMP_BSNR")
    a.c(**{"GAIN/SLV": "AMP_GAIN"})
    a.noconnect("SYNC")
    c.R("20k", "AMP_GAIN", "GND", L["R20k"], sh)
    c.R("100k", "AMP_GVDD", "AMP_GAIN", L["R100k"], sh)
    c.C("1uF", "AMP_GVDD", "GND", L["C1u"], sh)
    c.R("10R", "VBUS", "AMP_AVCC", L["R10"], sh)
    c.C("1uF", "AMP_AVCC", "GND", L["C1u"], sh)
    c.C("100nF", "AMP_AVCC", "GND", L["C100n"], sh)
    c.R("10k", "AMP_SDZ", "GND", L["R10k"], sh)
    c.R("10k", "AMP_MUTE", "GND", L["R10k"], sh)
    c.R("10k", "CM4_3V3", "AMP_FAULT", L["R10k"], sh)
    for bs, out in (("AMP_BSPL", "AMP_OUTPL"), ("AMP_BSNL", "AMP_OUTNL"), ("AMP_BSPR", "AMP_OUTPR"), ("AMP_BSNR", "AMP_OUTNR")):
        c.C("220nF", bs, out, L["C220n"], sh)
    for i in range(2):
        c.C("1nF", "VBUS", "GND", L["C1n"], sh)
        c.C("10uF/50V", "VBUS", "GND", L["C10u50_1206"], sh, "1206")
    c.CP("100uF/35V", "VBUS", "GND", L["CP100u35"], sh)
    for out, spk in (("AMP_OUTPL", "SPK_LP"), ("AMP_OUTNL", "SPK_LN"), ("AMP_OUTPR", "SPK_RP"), ("AMP_OUTNR", "SPK_RN")):
        ind = c.add("L", "Device", "L", "10uH 2.1A", "Inductor_SMD:L_Sunlord_SWPA5040S", "C84608", sh, mpn="SWPA5040S100MT", basic=False)
        ind.cn({1: out, 2: spk})
        c.C("1uF/50V", spk, "GND", L["C680n_0805"], sh, "0805")   # class-D LC filter cap (TI: 0.68-1 uF for 8 ohm); 1 uF is a JLC Basic part
    jj = c.add("J", "Connector_Generic", "Conn_01x02", "SPK L", "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal", "C173752", sh, mpn="S2B-PH-K-S", ref="J10")
    jj.cn({1: "SPK_LP", 2: "SPK_LN"})
    jj = c.add("J", "Connector_Generic", "Conn_01x02", "SPK R", "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal", "C173752", sh, mpn="S2B-PH-K-S", ref="J11")
    jj.cn({1: "SPK_RP", 2: "SPK_RN"})
    # microphones
    for ref, lr in (("U15", "GND"), ("U16", "3V3")):
        mic = c.add("U", "Sensor_Audio", "ICS-43434", "ICS-43434", None, "C5656610", sh, mpn="ICS-43434", basic=False, ref=ref, desc="I2S MEMS mic" + (" LEFT" if lr == "GND" else " RIGHT"))
        mic.c(WS="I2S_LRCLK", SCK="I2S_BCLK", SD="I2S_DIN", LR=lr, VDD="3V3", GND="GND")
        c.C("100nF", "3V3", "GND", L["C100n"], sh)

    # ------------------------------------------------------------ sensors (I2C6)
    sh = "sensors"
    s = c.add("U", "Sensor_Gas", "SCD40-D-R2", "SCD40", None, "C3659421", sh, mpn="SCD40-D-R2", basic=False, ref="U17", desc="CO2 sensor")
    s.c(VDD="3V3", GND="GND", SDA="I2C6_SDA", SCL="I2C6_SCL")
    c.C("10uF", "3V3", "GND", L["C10u_0603"], sh)
    c.C("100nF", "3V3", "GND", L["C100n"], sh)
    b = c.add("U", "HomeDeck", "BME688", "BME688", None, "C3664478", sh, mpn="BME688", basic=False, ref="U18", desc="Temp/humidity/pressure/VOC")
    b.c(VDD="3V3", VDDIO="3V3", GND="GND", SDI="I2C6_SDA", SCK="I2C6_SCL", CSB="3V3", SDO="GND")
    c.C("100nF", "3V3", "GND", L["C100n"], sh)
    c.C("100nF", "3V3", "GND", L["C100n"], sh)
    c.R("4.7k", "CM4_3V3", "I2C6_SDA", L["R4k7"], sh)
    c.R("4.7k", "CM4_3V3", "I2C6_SCL", L["R4k7"], sh)
    jj = c.add("J", "Connector_Generic", "Conn_01x04", "I2C ext (light sensor)", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", "C124378", sh, mpn="B-2100S04P-A110", ref="J12")
    jj.cn({1: "3V3", 2: "GND", 3: "I2C6_SDA", 4: "I2C6_SCL"})

    # ------------------------------------------------------------ LED bar, user LED, buttons, fan
    sh = "ui"
    ls = c.add("U", "74xGxx", "74AHCT1G125", "74AHCT1G125", "Package_TO_SOT_SMD:SOT-23-5", "C7484", sh, mpn="SN74AHCT1G125DBVR", basic=False, ref="U19", desc="3.3->5V level shifter")
    ls.cn({1: "GND", 2: "LED_DATA", 3: "GND", 4: "LED_DATA_5V", 5: "5V_PERIPH"})
    c.C("100nF", "5V_PERIPH", "GND", L["C100n"], sh)
    c.R("330R", "LED_DATA_5V", "LED_D0", L["R330"], sh)
    n_led = 10
    for i in range(n_led):
        dd = c.add("D", "LED", "WS2812B", "WS2812B", "LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm", "C2761795", sh, mpn="WS2812B-B/T", basic=False, ref=f"D{10+i}")
        dd.c(VDD="5V_PERIPH", VSS="GND", DIN=f"LED_D{i}", DOUT=f"LED_D{i+1}")
        c.C("100nF", "5V_PERIPH", "GND", L["C100n"], sh)
    jj = c.add("J", "Connector_Generic", "Conn_01x03", "LED strip ext", "Connector_JST:JST_PH_S3B-PH-K_1x03_P2.00mm_Horizontal", "C157929", sh, mpn="S3B-PH-K-S", ref="J17")
    jj.cn({1: "5V_PERIPH", 2: f"LED_D{n_led}", 3: "GND"})
    c.C("10uF", "5V_PERIPH", "GND", L["C10u_0603"], sh)
    led = c.add("D", "Device", "LED", "USER (green)", "LED_SMD:LED_0805_2012Metric", "C2297", sh, mpn="KT-0805G", ref="D5")
    led.cn({1: "GND", 2: "USER_LED_A"})
    c.R("470R", "USER_LED", "USER_LED_A", L["R470"], sh)
    for ref, hdr, net in (("SW1", "J18", "PWR_BTN"), ("SW2", "J19", "BTN_A"), ("SW3", "J20", "BTN_B")):
        sw = c.add("SW", "Switch", "SW_Push", ref.replace("SW1", "POWER").replace("SW2", "BTN A").replace("SW3", "BTN B"),
                   "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", "C318884", sh, mpn="TS-1187A-B-A-B", ref=ref)
        sw.cn({1: net, 2: "GND"})
        jj = c.add("J", "Connector_Generic", "Conn_01x02", "ext button", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", "C124375", sh, mpn="B-2100S02P-A110", ref=hdr)
        jj.cn({1: net, 2: "GND"})
        c.R("10k", "CM4_3V3", net, L["R10k"], sh)
        c.C("100nF", net, "GND", L["C100n"], sh)
    # fan
    q = c.add("Q", "Transistor_FET", "AO3400A", "AO3400A", None, "C20917", sh, mpn="AO3400A", basic=True, ref="Q3")
    q.c(G="FAN_G", D="FAN_N", S="GND")
    c.R("100R", "FAN_PWM", "FAN_G", L["R100"], sh)
    c.R("100k", "FAN_G", "GND", L["R100k"], sh)
    dd = c.add("D", "Device", "D_Schottky", "SS34", "Diode_SMD:D_SMA", "C8678", sh, mpn="SS34", ref="D6")
    dd.cn({1: "5V_PERIPH", 2: "FAN_N"})
    jj = c.add("J", "Connector_Generic", "Conn_01x02", "FAN 5V", "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal", "C173752", sh, mpn="S2B-PH-K-S", ref="J21")
    jj.cn({1: "5V_PERIPH", 2: "FAN_N"})

    return c


if __name__ == "__main__":
    c = build()
    errs = c.check()
    print(len(c.parts), "parts,", len(c.nets()), "nets")
    for e in errs:
        print("ERR", e)
