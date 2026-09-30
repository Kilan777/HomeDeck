"""Build the HomeDeck PCB with the pcbnew API: outline, placement, nets, zones. Routing is added by route.py."""
import os, sys, math, json
import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import circuit as circ

KICAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "kicad"))
FP_DIR = "/usr/share/kicad/footprints"
BOARD_W, BOARD_H = 130.0, 105.0
CORNER_R = 3.0
# display standoff pattern 58 x 49 centred on the board
HOLES = [(36.0, 28.0), (94.0, 28.0), (36.0, 77.0), (94.0, 77.0)]
CM4_POS = (65.0, 52.5, 90.0)  # module outline x 37.5..92.5, y 32.5..72.5
POWER_NETS = {"GND", "3V3", "VBUS", "VBUS_RAW", "5V_SYS", "5V_PERIPH", "5V_USB", "CM4_3V3", "HUB_V33", "PD_VDD", "DAC_AVDD",
              "AMP_AVCC", "AMP_GVDD", "SD_VDD", "5V_USBC2", "5V_USBA"}

# ---------------------------------------------------------------- manual placement: ref -> (x, y, rot, side)
MANUAL = {
    "M1": (65.0, 52.5, 90, "top"),
    "H1": (36.0, 28.0, 0, "top"), "H2": (94.0, 28.0, 0, "top"), "H3": (36.0, 77.0, 0, "top"), "H4": (94.0, 77.0, 0, "top"),
    # display / camera FPC above the module, cable exits toward the top edge
    "J6": (77.5, 26.0, 180, "top"), "J7": (52.5, 26.0, 180, "top"),
    # top strip: LED bar, mics, buttons, LEDs
    **{f"D{10+i}": (30.0 + i * 7.0, 4.5, 0, "top") for i in range(10)},
    "U19": (21.0, 8.0, 0, "top"), "J17": (104.0, 5.5, 180, "top"),
    "U15": (6.0, 7.0, 0, "bottom"), "U16": (124.0, 7.0, 0, "bottom"),
    "SW1": (32.0, 13.0, 0, "top"), "J18": (39.5, 11.0, 0, "top"), "SW2": (48.0, 13.0, 0, "top"), "J19": (55.5, 11.0, 0, "top"),
    "SW3": (64.0, 13.0, 0, "top"), "J20": (71.5, 11.0, 0, "top"), "SW4": (80.0, 13.0, 0, "top"),
    "D5": (88.0, 12.0, 90, "top"), "D3": (91.5, 12.0, 90, "top"), "D4": (95.0, 12.0, 90, "top"), "D2": (98.5, 12.0, 90, "top"),
    "J16": (4.0, 22.0, 90, "top"),
    # left: sensor tongue
    "U18": (12.0, 38.0, 0, "top"), "U17": (12.0, 52.0, 0, "top"), "J12": (8.0, 62.0, 90, "top"),
    # left strip headers between tongue and CM4
    "J13": (30.5, 34.0, 0, "top"), "J14": (30.5, 41.0, 0, "top"), "J15": (30.5, 50.0, 0, "top"),
    # bottom strip left: internal USB headers, microSD, USB-A
    "J4": (4.5, 76.0, 0, "top"), "J5": (9.5, 76.0, 0, "top"),
    "J9": (17.0, 93.5, 180, "top"), "Q1": (12.0, 84.0, 0, "top"), "Q2": (17.0, 84.0, 0, "top"),
    "J3": (30.0, 87.0, 0, "top"), "U12": (26.0, 78.0, 0, "top"), "U11": (36.0, 81.0, 0, "top"),
    # hub / mux / USB-C data
    "U8": (44.0, 78.0, 0, "top"), "Y1": (44.0, 72.5, 0, "top"), "U6": (52.0, 74.0, 0, "top"), "U7": (52.0, 80.0, 0, "top"),
    "J2": (52.0, 96.6, 0, "top"), "U9": (52.0, 88.0, 0, "top"), "U10": (60.0, 88.0, 0, "top"),
    # audio
    "U13": (66.0, 78.0, 0, "top"), "U14": (79.0, 77.5, 270, "top"),
    "J10": (68.0, 94.5, 0, "top"), "J11": (80.0, 94.5, 0, "top"),
    "L4": (65.0, 89.0, 0, "top"), "L5": (71.0, 89.0, 0, "top"), "L6": (77.0, 89.0, 0, "top"), "L7": (83.0, 89.0, 0, "top"),
    "J21": (94.0, 93.2, 0, "top"), "Q3": (94.0, 77.0, 0, "top"), "D6": (97.0, 82.0, 0, "top"), "J8": (102.0, 89.5, 0, "top"),
    # power (right strip)
    "J1": (120.0, 96.6, 0, "top"), "F1": (108.0, 92.0, 90, "top"), "D1": (112.0, 91.0, 90, "top"), "U1": (112.0, 84.0, 0, "top"),
    "JP1": (127.5, 77.0, 90, "top"), "JP2": (127.5, 81.0, 90, "top"), "JP3": (127.5, 85.0, 90, "top"), "C3": (121.0, 83.0, 0, "top"),
    "U2": (102.0, 68.0, 0, "top"), "U3": (102.0, 52.0, 0, "top"), "U4": (102.0, 36.0, 0, "top"),
    "U5": (110.0, 18.0, 0, "top"),
}
# shift middle/bottom regions for the 105 mm tall board
for _r, (_x, _y, _rot, _side) in list(MANUAL.items()):
    if _r in ("M1", "H1", "H2", "H3", "H4", "J6", "J7"):
        continue
    if _y >= 72:
        MANUAL[_r] = (_x, _y + 5.0, _rot, _side)
    elif _y >= 30:
        MANUAL[_r] = (_x, _y + 2.5, _rot, _side)
# overrides (final coordinates) to keep a fan-out corridor free below the CM4's lower connector (x 52..78, y 73..86)
OVERRIDE = {
    "U8": (43.5, 80.5, 90, "top"), "Y1": (43.5, 75.5, 0, "top"), "U6": (49.5, 77.0, 0, "top"), "U7": (49.5, 83.0, 0, "top"),
    "U12": (26.0, 79.0, 0, "top"), "U11": (36.0, 85.5, 0, "top"), "U9": (52.0, 95.0, 0, "top"), "U10": (57.0, 91.0, 0, "top"),
    "U13": (64.5, 91.5, 0, "top"), "U14": (84.5, 80.5, 270, "top"),
    "L4": (73.0, 93.0, 0, "top"), "L5": (79.0, 93.0, 0, "top"), "L6": (85.0, 93.0, 0, "top"), "L7": (91.0, 93.0, 0, "top"),
    "J10": (77.0, 99.5, 0, "top"), "J11": (89.0, 99.5, 0, "top"), "J21": (62.0, 99.5, 0, "top"),
    "Q3": (68.0, 98.5, 0, "top"), "D6": (71.5, 95.5, 0, "top"), "J8": (104.0, 96.0, 0, "top"), "F1": (108.0, 97.0, 90, "top"),
}
MANUAL.update(OVERRIDE)
CORRIDOR = (52.0, 73.0, 78.0, 86.0)
# per-buck manual layout (relative to the TPS5430): inductor, diode, bulk cap
BUCK_GROUPS = {"U2": ("L1", "D7", "C13"), "U3": ("L2", "D8", "C21"), "U4": ("L3", "D9", "C29")}


def fp_path(fpid):
    lib, name = fpid.split(":")
    if lib == "HomeDeck":
        return os.path.join(KICAD_DIR, "HomeDeck.pretty"), name, lib
    return os.path.join(FP_DIR, lib + ".pretty"), name, lib


def load_fp(fpid):
    path, name, lib = fp_path(fpid)
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise RuntimeError("cannot load " + fpid)
    fpid_obj = pcbnew.LIB_ID(lib, name)
    fp.SetFPID(fpid_obj)
    return fp


def courtyard_bbox_local(fp):
    """(minx, miny, maxx, maxy) in mm of the front courtyard in footprint-local coords at rotation 0 (before placement)."""
    cy = fp.GetCourtyard(pcbnew.F_CrtYd)
    if cy.OutlineCount() > 0:
        bb = cy.BBox()
    else:
        bb = fp.GetBoundingBox(False, False)
    return ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom())


def rot_bbox(bb, rot, flip):
    """rotate a local bbox by rot degrees (CCW on screen) and optional flip (mirror y). Returns (hw, hh) extents around origin as min/max."""
    minx, miny, maxx, maxy = bb
    if flip:
        miny, maxy = -maxy, -miny
    pts = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
    a = math.radians(rot)
    rp = [(x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a)) for x, y in pts]
    xs = [p[0] for p in rp]
    ys = [p[1] for p in rp]
    return min(xs), min(ys), max(xs), max(ys)


class Occupancy:
    """coarse occupancy grid for placement, one per side."""

    def __init__(self, res=0.25):
        self.res = res
        self.nx = int(BOARD_W / res) + 1
        self.ny = int(BOARD_H / res) + 1
        self.grid = {"top": np.zeros((self.ny, self.nx), dtype=np.uint8), "bottom": np.zeros((self.ny, self.nx), dtype=np.uint8)}
        # board edge keepout 1.0 mm, corners
        for side in ("top", "bottom"):
            g = self.grid[side]
            e = int(1.0 / res)
            g[:e, :] = 1
            g[-e:, :] = 1
            g[:, :e] = 1
            g[:, -e:] = 1
        # display standoff holes keepout (screw head) r=3.2
        for (x, y) in HOLES:
            self.block_circle(x, y, 3.2, "top")
            self.block_circle(x, y, 3.2, "bottom")
        # CM4 module footprint holes
        X, Y, _ = CM4_POS
        for (lx, ly) in [(16.5, -26.5), (-16.5, -26.5), (16.5, 21.5), (-16.5, 21.5)]:
            self.block_circle(X + ly, Y - lx, 2.5, "top")
            self.block_circle(X + ly, Y - lx, 2.5, "bottom")
        # nothing on top under the CM4 module (x 37.5..92.5, y 30..70)
        self.block_rect(37.5 - 0.5, 32.5 - 0.5, 92.5 + 0.5, 72.5 + 0.5, "top")
        # fan-out corridor below the CM4 lower connector: no parts on either side
        self.block_rect(*CORRIDOR, "top")
        self.block_rect(*CORRIDOR, "bottom")
        # sensor tongue slots (routed 1.6 mm)
        for (x1, y1, x2, y2) in SLOTS:
            self.block_rect(x1 - 1.0, y1 - 1.0, x2 + 1.0, y2 + 1.0, "top")
            self.block_rect(x1 - 1.0, y1 - 1.0, x2 + 1.0, y2 + 1.0, "bottom")

    def idx(self, x, y):
        return int(round(y / self.res)), int(round(x / self.res))

    def block_rect(self, x1, y1, x2, y2, side):
        r1, c1 = self.idx(max(x1, 0), max(y1, 0))
        r2, c2 = self.idx(min(x2, BOARD_W), min(y2, BOARD_H))
        self.grid[side][r1:r2 + 1, c1:c2 + 1] = 1

    def block_circle(self, x, y, r, side):
        self.block_rect(x - r, y - r, x + r, y + r, side)

    def free_rect(self, x1, y1, x2, y2, side):
        if x1 < 0 or y1 < 0 or x2 > BOARD_W or y2 > BOARD_H:
            return False
        r1, c1 = self.idx(x1, y1)
        r2, c2 = self.idx(x2, y2)
        return not self.grid[side][r1:r2 + 1, c1:c2 + 1].any()


# slots around the sensor tongue: (x1,y1,x2,y2) rectangles 1.6 mm wide
SLOTS = [(25.0, 32.5, 26.6, 72.5), (8.0, 32.5, 26.6, 34.1), (8.0, 70.9, 26.6, 72.5)]
SLOT_POLY = [(8.0, 32.5), (26.6, 32.5), (26.6, 72.5), (8.0, 72.5), (8.0, 70.9), (25.0, 70.9), (25.0, 34.1), (8.0, 34.1)]


PLANE_POLYS = {"5V_SYS": [(28, 30), (96, 30), (96, 75), (28, 75)], "VBUS": [(97, 27), (130, 27), (130, 105), (66, 105), (66, 76), (97, 76)],
               "5V_USB": [(0, 76), (65, 76), (65, 105), (0, 105)], "5V_PERIPH": [(0, 0), (130, 0), (130, 26), (0, 26)], "3V3": [(0, 27), (27, 27), (27, 75), (0, 75)]}


def board_outline_points():
    pts = []
    n = 6
    for cx, cy, a0 in [(BOARD_W - CORNER_R, CORNER_R, -90), (BOARD_W - CORNER_R, BOARD_H - CORNER_R, 0), (CORNER_R, BOARD_H - CORNER_R, 90), (CORNER_R, CORNER_R, 180)]:
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + CORNER_R * math.cos(a), cy + CORNER_R * math.sin(a)))
    return pts


def add_outline(b):
    pts = board_outline_points()
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s = pcbnew.PCB_SHAPE(b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
        s.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(FromMM(0.1))
        b.Add(s)
    # U-shaped slot around the sensor tongue as one closed polyline
    sp = SLOT_POLY
    for i in range(len(sp)):
        x1, y1 = sp[i]
        x2, y2 = sp[(i + 1) % len(sp)]
        s = pcbnew.PCB_SHAPE(b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
        s.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(FromMM(0.1))
        b.Add(s)


def setup_board(b):
    ds = b.GetDesignSettings()
    ds.SetCopperLayerCount(4)
    ds.m_MinClearance = FromMM(0.1)
    ds.m_TrackMinWidth = FromMM(0.1)
    ds.m_ViasMinSize = FromMM(0.45)
    ds.m_MinThroughDrill = FromMM(0.2)
    ds.m_CopperEdgeClearance = FromMM(0.3)
    ds.m_HoleClearance = FromMM(0.25)
    ds.m_HoleToHoleMin = FromMM(0.5)
    ds.m_SolderMaskMinWidth = FromMM(0.1)
    ds.m_SolderMaskExpansion = FromMM(0.0)
    dc = ds.m_NetSettings.m_DefaultNetClass
    dc.SetClearance(FromMM(0.15))
    dc.SetTrackWidth(FromMM(0.2))
    dc.SetViaDiameter(FromMM(0.6))
    dc.SetViaDrill(FromMM(0.3))
    b.SetLayerName(pcbnew.In1_Cu, "GND")
    b.SetLayerName(pcbnew.In2_Cu, "PWR")


def add_nets(b, circuit):
    nets = {}
    for net in circuit.nets():
        item = pcbnew.NETINFO_ITEM(b, net)
        b.Add(item)
        nets[net] = item
    return nets


def place_footprint(b, part, x, y, rot, side, nets):
    fp = load_fp(part.fp)
    fp.SetReference(part.ref)
    fp.SetValue(part.value)
    fp.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    b.Add(fp)
    if side == "bottom":
        fp.Flip(fp.GetPosition(), False)
    fp.SetOrientationDegrees(rot if side == "top" else -rot)
    # properties
    fp.SetProperty("LCSC", part.lcsc or "")
    fp.SetProperty("MPN", part.mpn or "")
    fp.SetProperty("JLC", ("Basic" if part.basic else "Extended") if part.basic is not None else "")
    fp.SetProperty("Sheet", part.sheet)
    if part.dnp:
        fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
    if part.lib == "Mechanical":
        fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
    fp.SetPath(pcbnew.KIID_PATH("/" + part.ref))
    for pad in fp.Pads():
        num = pad.GetNumber()
        net = part.pins.get(num)
        if net is not None:
            pad.SetNet(nets[net])
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
            pad.SetZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
    # reference text smaller
    fp.Reference().SetTextSize(VECTOR2I(FromMM(0.8), FromMM(0.8)))
    fp.Reference().SetTextThickness(FromMM(0.12))
    fp.Value().SetVisible(False)
    return fp


def anchors_for(circuit):
    """anchor for each passive = last non-passive part added before it on the same sheet."""
    anchors = {}
    last = {}
    for p in circuit.parts.values():
        is_passive = p.lib == "Device" or p.sym.startswith("Conn_") or p.lib in ("Switch", "Jumper")
        if p.ref in MANUAL:
            last[p.sheet] = p if not is_passive else last.get(p.sheet)
            if not is_passive:
                last[p.sheet] = p
            continue
        if not is_passive:
            last[p.sheet] = p
        else:
            anchors[p.ref] = last.get(p.sheet)
    return anchors


FIXED = {"M1", "H1", "H2", "H3", "H4", "J1", "J2", "J3", "J9", "J10", "J11", "J21", "J8", "J6", "J7", "J17"}


def legalize(circuit):
    """Push overlapping manually placed parts apart (courtyard bboxes + margin)."""
    boxes = {}
    for ref, (x, y, rot, side) in MANUAL.items():
        part = circuit.parts[ref]
        bb = rot_bbox(courtyard_bbox_local(load_fp(part.fp)), rot, side == "bottom")
        boxes[ref] = bb
    m = 0.35
    for it in range(200):
        moved = False
        refs = list(MANUAL.keys())
        for i in range(len(refs)):
            for j in range(i + 1, len(refs)):
                a, bref = refs[i], refs[j]
                if a in FIXED and bref in FIXED:
                    continue
                xa, ya, ra, sa = MANUAL[a]
                xb, yb, rb, sb = MANUAL[bref]
                if sa != sb and not (a == "M1" or bref == "M1"):
                    continue
                A = boxes[a]; B = boxes[bref]
                ax1, ay1, ax2, ay2 = xa + A[0] - m, ya + A[1] - m, xa + A[2] + m, ya + A[3] + m
                bx1, by1, bx2, by2 = xb + B[0] - m, yb + B[1] - m, xb + B[2] + m, yb + B[3] + m
                ox = min(ax2, bx2) - max(ax1, bx1)
                oy = min(ay2, by2) - max(ay1, by1)
                if ox <= 0 or oy <= 0:
                    continue
                # move the non-fixed one (or both) along the smaller overlap axis
                movers = [r for r in (a, bref) if r not in FIXED]
                if ox < oy:
                    d = ox / len(movers) + 0.05
                    for r in movers:
                        x, y, rot, side = MANUAL[r]
                        sign = 1 if (x >= (xa if r == bref else xb)) else -1
                        MANUAL[r] = (round(x + sign * d, 2), y, rot, side)
                else:
                    d = oy / len(movers) + 0.05
                    for r in movers:
                        x, y, rot, side = MANUAL[r]
                        sign = 1 if (y >= (ya if r == bref else yb)) else -1
                        MANUAL[r] = (x, round(y + sign * d, 2), rot, side)
                moved = True
        if not moved:
            return it
    return -1


def build(circuit, out_path):
    b = pcbnew.BOARD()
    n_it = legalize(circuit)
    print("legalizer iterations:", n_it)
    setup_board(b)
    nets = add_nets(b, circuit)
    add_outline(b)
    occ = Occupancy()
    placed = {}
    fps = {}
    # --- manual placements
    for ref, (x, y, rot, side) in MANUAL.items():
        part = circuit.parts[ref]
        fp = place_footprint(b, part, x, y, rot, side, nets)
        fps[ref] = fp
        placed[ref] = (x, y, rot, side)
        bb = courtyard_bbox_local(load_fp(part.fp))
        rb = rot_bbox(bb, rot, side == "bottom")
        m = 0.3
        # fine-pitch ICs: keep a fan-out band free around them
        fine = any(min(ToMM(pd.GetSize().x), ToMM(pd.GetSize().y)) < 0.5 and pd.GetAttribute() == pcbnew.PAD_ATTRIB_SMD for pd in fp.Pads()) and ref != "M1"
        if fine:
            m = 1.6
        occ.block_rect(x + rb[0] - m, y + rb[1] - m, x + rb[2] + m, y + rb[3] + m, side)
        if any(pd.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH) for pd in fp.Pads()):
            # anything with holes blocks both sides
            occ.block_rect(x + rb[0] - m, y + rb[1] - m, x + rb[2] + m, y + rb[3] + m, "bottom")
    # --- buck groups: inductor, diode, bulk cap next to each TPS5430
    for uref in BUCK_GROUPS:
        u = circuit.parts[uref]
        ph = u.pins[[p.number for p in u.pininfo if p.name == "PH"][0]]
        rail = [pp for pp in circuit.parts.values() if pp.sym == "L" and ph in pp.pins.values()][0]
        lref = rail.ref
        rail_net = [n for n in rail.pins.values() if n != ph][0]
        dref = [pp.ref for pp in circuit.parts.values() if pp.sym == "D_Schottky" and ph in pp.pins.values()][0]
        cref = [pp.ref for pp in circuit.parts.values() if pp.sym == "C_Polarized" and rail_net in pp.pins.values() and pp.sheet == "power"][0]
        ux, uy, _, _ = placed[uref]
        for ref, (dx, dy, rot) in ((lref, (12.0, 3.0, 0)), (dref, (0.0, 6.0, 0)), (cref, (23.3, 3.0, 90))):
            part = circuit.parts[ref]
            x, y = ux + dx, uy + dy
            fp = place_footprint(b, part, x, y, rot, "top", nets)
            fps[ref] = fp
            placed[ref] = (x, y, rot, "top")
            rb = rot_bbox(courtyard_bbox_local(load_fp(part.fp)), rot, False)
            occ.block_rect(x + rb[0] - 0.3, y + rb[1] - 0.3, x + rb[2] + 0.3, y + rb[3] + 0.3, "top")
    # amp bootstrap capacitors right below the output pins (pin pairs 20/21, 23/24, 26/27, 29/30)
    ux, uy, urot, _ = placed["U14"]
    u14 = circuit.parts["U14"]
    pin_of = {n: num for num, n in u14.pins.items()}
    for bs, out, rot in (("AMP_BSNL", "AMP_OUTNL", 270), ("AMP_BSPL", "AMP_OUTPL", 270), ("AMP_BSNR", "AMP_OUTNR", 270), ("AMP_BSPR", "AMP_OUTPR", 270)):
        cap = [pp for pp in circuit.parts.values() if pp.sym == "C" and set(pp.pins.values()) == {bs, out}][0]
        def pinx(num):
            return ux - 4.875 + (int(num) - 17) * 0.65
        x = (pinx(pin_of[bs]) + pinx(pin_of[out])) / 2
        y = uy + 5.83 + 2.2
        fp = place_footprint(b, cap, x, y, rot, "top", nets)
        fps[cap.ref] = fp
        placed[cap.ref] = (x, y, rot, "top")
        rb = rot_bbox(courtyard_bbox_local(load_fp(cap.fp)), rot, False)
        occ.block_rect(x + rb[0] - 0.2, y + rb[1] - 0.2, x + rb[2] + 0.2, y + rb[3] + 0.2, "top")
    # amp bulk capacitor
    for pp in circuit.parts.values():
        if pp.sym == "C_Polarized" and pp.sheet == "audio":
            x, y = 100.5, 89.5
            fp = place_footprint(b, pp, x, y, 0, "top", nets)
            fps[pp.ref] = fp
            placed[pp.ref] = (x, y, 0, "top")
            rb = rot_bbox(courtyard_bbox_local(load_fp(pp.fp)), 0, False)
            occ.block_rect(x + rb[0] - 0.3, y + rb[1] - 0.3, x + rb[2] + 0.3, y + rb[3] + 0.3, "top")
    # --- automatic placement of the rest near their anchor
    anchors = anchors_for(circuit)
    pad_pos_cache = {}

    def pad_positions(ref):
        if ref not in pad_pos_cache:
            fp = fps[ref]
            pad_pos_cache[ref] = {p.GetNumber(): (ToMM(p.GetPosition().x), ToMM(p.GetPosition().y)) for p in fp.Pads()}
        return pad_pos_cache[ref]

    for part in circuit.parts.values():
        if part.ref in placed:
            continue
        anchor = anchors.get(part.ref)
        if anchor is None or anchor.ref not in placed:
            anchor_xy, side = (65.0, 85.0), "top"
        else:
            ax, ay, _, aside = placed[anchor.ref]
            anchor_xy, side = (ax, ay), aside
            # prefer the anchor pad that shares a signal net with this part
            shared = [n for n in part.pins.values() if n not in POWER_NETS and n in anchor.pins.values()]
            if not shared:
                shared = [n for n in part.pins.values() if n in anchor.pins.values() and n != "GND"]
            if shared:
                pp = pad_positions(anchor.ref)
                for num, n in anchor.pins.items():
                    if n == shared[0] and num in pp:
                        anchor_xy = pp[num]
                        break
        bb = courtyard_bbox_local(load_fp(part.fp))
        best = None
        sides = [side, "bottom" if side == "top" else "top"]
        if anchor is not None and anchor.ref == "M1":
            sides = ["bottom", "top"]
        low_profile = any(k in (part.fp or "") for k in ("0603", "0805", "1206", "SOT-23"))
        if not low_profile:
            sides = ["top"]
        for rad in np.arange(1.0, 70.0, 0.5):
            for s in sides:
                for k in range(int(8 * rad)):
                    a = 2 * math.pi * k / int(8 * rad)
                    x = round((anchor_xy[0] + rad * math.cos(a)) * 2) / 2
                    y = round((anchor_xy[1] + rad * math.sin(a)) * 2) / 2
                    for rot in (0, 90):
                        rb = rot_bbox(bb, rot, s == "bottom")
                        m = 0.25
                        if occ.free_rect(x + rb[0] - m, y + rb[1] - m, x + rb[2] + m, y + rb[3] + m, s):
                            best = (x, y, rot, s)
                            break
                    if best:
                        break
                if best:
                    break
            if best:
                break
        if best is None:
            raise RuntimeError(f"no room for {part.ref}")
        x, y, rot, s = best
        if math.hypot(x - anchor_xy[0], y - anchor_xy[1]) > 12:
            print(f"  note: {part.ref} placed {math.hypot(x - anchor_xy[0], y - anchor_xy[1]):.0f} mm from its anchor")
        fp = place_footprint(b, part, x, y, rot, s, nets)
        fps[part.ref] = fp
        placed[part.ref] = best
        rb = rot_bbox(bb, rot, s == "bottom")
        occ.block_rect(x + rb[0] - 0.25, y + rb[1] - 0.25, x + rb[2] + 0.25, y + rb[3] + 0.25, s)
    add_zones(b, nets)
    add_rule_areas(b)
    write_dru()
    fan = cm4_fanout(b, circuit, fps)
    add_fanout_to_board(b, fan, nets)
    b.Save(out_path)
    with open(os.path.join(os.path.dirname(out_path), "placement.json"), "w") as f:
        json.dump(placed, f, indent=1)
    with open(os.path.join(os.path.dirname(out_path), "fanout.json"), "w") as f:
        json.dump(fan, f)
    return b, placed


_KEEP = []


FANOUT_AREAS = [(53.0, 30.0, 77.0, 41.0), (53.0, 64.0, 77.0, 75.5)]
FANOUT_W = 0.1
FANOUT_VIA = (0.45, 0.2)


def cm4_fanout(b, circuit, fps):
    """Deterministic fan-out for every used CM4 pad: 0.1 mm stub + 0.45/0.2 via, three staggered via rows.
    Returns list of dicts {pad, net, via:(x,y), stub:[(x1,y1),(x2,y2)]}."""
    m1 = fps["M1"]
    part = circuit.parts["M1"]
    rows = {}
    for pad in m1.Pads():
        num = pad.GetNumber()
        if not num:
            continue
        x, y = ToMM(pad.GetPosition().x), ToMM(pad.GetPosition().y)
        key = round(y, 1)
        rows.setdefault(key, []).append((x, num, pad))
    out = []
    X, Y, _ = CM4_POS
    for ykey, plist in rows.items():
        plist.sort()
        # direction: outer rows escape away from the module centre, inner rows toward it
        outer = abs(ykey - Y) > 16.0
        direction = (1.0 if ykey > Y else -1.0) if outer else (-1.0 if ykey > Y else 1.0)
        for i, (x, num, pad) in enumerate(plist):
            net = part.pins.get(num)
            if net is None:
                continue
            k = i % 3
            depth = 1.2 + 0.7 * k
            vy = ykey + direction * depth
            out.append({"pad": num, "net": net, "via": (round(x, 3), round(vy, 3)), "stub": [(round(x, 3), round(ykey, 3)), (round(x, 3), round(vy, 3))]})
    return out


def add_fanout_to_board(b, fan, nets):
    for f in fan:
        code = nets[f["net"]].GetNetCode()
        (x1, y1), (x2, y2) = f["stub"]
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
        t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
        t.SetWidth(FromMM(FANOUT_W))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNetCode(code)
        b.Add(t)
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(VECTOR2I(FromMM(f["via"][0]), FromMM(f["via"][1])))
        v.SetDrill(FromMM(FANOUT_VIA[1]))
        v.SetWidth(FromMM(FANOUT_VIA[0]))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNetCode(code)
        b.Add(v)


def add_rule_areas(b):
    for (x1, y1, x2, y2) in FANOUT_AREAS:
        z = pcbnew.ZONE(b)
        _KEEP.append(z)
        z.SetIsRuleArea(True)
        z.SetZoneName("CM4_FANOUT")
        z.SetDoNotAllowCopperPour(False)
        z.SetDoNotAllowTracks(False)
        z.SetDoNotAllowVias(False)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        ls = pcbnew.LSET()
        ls.addLayer(pcbnew.F_Cu)
        ls.addLayer(pcbnew.B_Cu)
        z.SetLayerSet(ls)
        z.SetOutline(poly(b, [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]))
        b.Add(z)


def write_dru():
    txt = """(version 1)
(rule "CM4 fanout clearance"
  (condition "A.insideArea('CM4_FANOUT') && B.insideArea('CM4_FANOUT')")
  (constraint clearance (min 0.1mm)))
(rule "CM4 fanout track width"
  (condition "A.insideArea('CM4_FANOUT')")
  (constraint track_width (min 0.1mm)))
(rule "CM4 fanout vias"
  (condition "A.insideArea('CM4_FANOUT')")
  (constraint via_diameter (min 0.45mm))
  (constraint hole_size (min 0.2mm)))
"""
    with open(os.path.join(KICAD_DIR, "HomeDeck.kicad_dru"), "w") as f:
        f.write(txt)


def poly(b, pts):
    sh = pcbnew.SHAPE_POLY_SET()
    _KEEP.append(sh)
    sh.NewOutline()
    for x, y in pts:
        sh.Append(FromMM(x), FromMM(y))
    return sh


def add_zone(b, net, layer, pts, priority=0, clearance=0.2, minw=0.25, thermal=True):
    z = pcbnew.ZONE(b)
    _KEEP.append(z)
    z.SetLayer(layer)
    z.SetNetCode(b.GetNetcodeFromNetname(net))
    z.SetOutline(poly(b, pts))
    z.SetAssignedPriority(priority)
    z.SetLocalClearance(FromMM(clearance))
    z.SetMinThickness(FromMM(minw))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL if thermal else pcbnew.ZONE_CONNECTION_FULL)
    z.SetThermalReliefGap(FromMM(0.3))
    z.SetThermalReliefSpokeWidth(FromMM(0.4))
    z.SetIsFilled(False)
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    b.Add(z)
    return z


def add_zones(b, nets):
    full = board_outline_points()
    # GND: inner layer 1 full plane, plus top and bottom pours
    add_zone(b, "GND", pcbnew.In1_Cu, full, priority=0, thermal=False)
    add_zone(b, "GND", pcbnew.F_Cu, full, priority=0)
    add_zone(b, "GND", pcbnew.B_Cu, full, priority=0)
    # PWR layer (In2): split planes. VBUS on the right strip + bottom-right, 5V_SYS under the CM4, 5V_USB bottom-left, 5V_PERIPH top strip, 3V3 left/tongue
    for name, pts in PLANE_POLYS.items():
        add_zone(b, name, pcbnew.In2_Cu, pts, priority=1)
    add_zone(b, "GND", pcbnew.In2_Cu, full, priority=0)


if __name__ == "__main__":
    c = circ.build()
    out = os.path.join(KICAD_DIR, "HomeDeck.kicad_pcb")
    b, placed = build(c, out)
    print("placed", len(placed), "footprints ->", out)
