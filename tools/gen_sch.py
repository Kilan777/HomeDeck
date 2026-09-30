"""Generate KiCad 7 hierarchical schematic from the circuit model (label-based connectivity)."""
import os, uuid, math, copy
import sexpdata
from sexpdata import Symbol
import kilib

PROJECT = "HomeDeck"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "kicad")

SHEET_TITLES = {
    "power": "Power: USB-C PD input, 3x TPS5430 bucks, 3.3V LDO",
    "cm4": "Compute Module 4, LEDs, headers",
    "usb": "USB: boot mux, CH334R hub, USB-C data port, USB-A, internal headers",
    "video": "Display (DSI1) and Camera (CAM1) connectors",
    "sd": "microSD with SD_PWR_ON load switch",
    "audio": "Audio: PCM5102A DAC, TPA3118D2 amplifier, MEMS microphones",
    "sensors": "Sensors: SCD40 CO2, BME688, I2C header",
    "ui": "LED bar, user LED, buttons, fan",
    "mech": "Mounting holes",
}
SHEET_ORDER = ["power", "cm4", "usb", "video", "sd", "audio", "sensors", "ui", "mech"]


def uid():
    return str(uuid.uuid4())


def q(s):
    return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"') + '"'


def fmt(v):
    return f"{v:.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


class SymbolPlacer:
    """Compute schematic geometry of a symbol unit: pins and bounding box."""

    def __init__(self, part, unit):
        self.part, self.unit = part, unit
        pins = [p for p in part.pininfo if p.unit in (unit, 0)]
        self.pins = pins
        self.rot = part_rot(part, unit)
        if self.rot == 90:
            xs = [-p.y for p in pins] or [0]
            ys = [-p.x for p in pins] or [0]
        else:
            xs = [p.x for p in pins] or [0]
            ys = [p.y for p in pins] or [0]
        self.minx, self.maxx, self.miny, self.maxy = min(xs), max(xs), min(ys), max(ys)
        self.label_len = 22.0  # room for labels
        vertical_pins = any(int((p.rot + self.rot) % 180) == 90 for p in pins)
        self.w = (self.maxx - self.minx) + 2 * (2.54 + self.label_len) + 5
        self.h = (self.maxy - self.miny) + 2 * (2.54 + (self.label_len if vertical_pins else 4)) + 5


def rot_outward(a):
    """direction vector (screen coords, y down) pointing away from body for an effective pin angle."""
    return {0: (-1, 0), 180: (1, 0), 90: (0, -1), 270: (0, 1)}[int(a)]


def label_angle(a):
    return {0: 180, 180: 0, 90: 270, 270: 90}[int(a)]


def sym_to_sch(x, y, px, py, rot=0):
    if rot == 90:
        return x - py, y - px
    return x + px, y - py


def eff_angle(pin, rot):
    return (pin.rot + rot) % 360


def part_rot(part, unit):
    """Rotate 2-pin vertical passives by 90 deg so they read horizontally."""
    pins = [p for p in part.pininfo if p.unit in (unit, 0)]
    if len(pins) == 2 and all(int(p.rot) % 180 == 90 for p in pins):
        return 90
    return 0


def write_symbol_instance(part, unit, x, y, root_uuid, sheet_uuid, out):
    su = uid()
    rot = part_rot(part, unit)
    out.append(f'  (symbol (lib_id {q(part.lib + ":" + part.sym)}) (at {fmt(x)} {fmt(y)} {rot}) (unit {unit}) (in_bom yes) (on_board yes) (dnp {"yes" if part.dnp else "no"}) (fields_autoplaced)\n')
    out.append(f'    (uuid "{su}")\n')
    props = [("Reference", part.ref, x, y - 4, False), ("Value", part.value, x, y - 1.5, False), ("Footprint", part.fp or "", x, y, True),
             ("Datasheet", "", x, y, True), ("LCSC", part.lcsc or "", x, y, True), ("MPN", part.mpn or "", x, y, True),
             ("JLC", ("Basic" if part.basic else "Extended") if part.basic is not None else "", x, y, True)]
    if part.desc:
        props.append(("Description", part.desc, x, y, True))
    for name, val, px, py, hide in props:
        h = " hide" if hide else ""
        out.append(f'    (property {q(name)} {q(val)} (at {fmt(px)} {fmt(py)} 0) (effects (font (size 1.27 1.27)){h}))\n')
    for p in part.pininfo:
        if p.unit in (unit, 0):
            out.append(f'    (pin {q(p.number)} (uuid "{uid()}"))\n')
    out.append(f'    (instances (project {q(PROJECT)} (path "/{root_uuid}/{sheet_uuid}" (reference {q(part.ref)}) (unit {unit}))))\n')
    out.append('  )\n')


def write_pin_labels(part, unit, x, y, out):
    rot = part_rot(part, unit)
    for p in part.pininfo:
        if p.unit not in (unit, 0):
            continue
        cx, cy = sym_to_sch(x, y, p.x, p.y, rot)
        if p.number in part.nc:
            out.append(f'  (no_connect (at {fmt(cx)} {fmt(cy)}) (uuid "{uid()}"))\n')
            continue
        net = part.pins.get(p.number)
        if net is None:
            continue
        ea = eff_angle(p, rot)
        dx, dy = rot_outward(ea)
        ex, ey = cx + dx * 2.54, cy + dy * 2.54
        out.append(f'  (wire (pts (xy {fmt(cx)} {fmt(cy)}) (xy {fmt(ex)} {fmt(ey)})) (stroke (width 0) (type default)) (uuid "{uid()}"))\n')
        ang = label_angle(ea)
        shape = "input" if p.etype in ("input", "power_in") else ("output" if p.etype in ("output", "power_out") else "bidirectional")
        just = "right" if ang == 180 else "left"
        out.append(f'  (global_label {q(net)} (shape {shape}) (at {fmt(ex)} {fmt(ey)} {ang}) (fields_autoplaced)\n'
                   f'    (effects (font (size 1.27 1.27)) (justify {just}))\n    (uuid "{uid()}")\n'
                   f'    (property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n  )\n')


def lib_symbols_block(parts_units, extra=()):
    """Return lib_symbols s-expression text for the given parts (+ extra (lib, name))."""
    seen = {}
    for part in parts_units:
        seen[(part.lib, part.sym)] = True
    for e in extra:
        seen[e] = True
    out = ["  (lib_symbols\n"]
    for lib, name in seen:
        node = copy.deepcopy(kilib.get_symbol(lib, name))
        node[1] = f"{lib}:{name}"
        txt = sexpdata.dumps(node, true_as="yes", false_as="no")
        out.append("    " + txt + "\n")
    out.append("  )\n")
    return "".join(out)


def place_sheet(parts):
    """Shelf-pack symbols. Returns list of (part, unit, x, y) and page size."""
    items = []
    for part in parts:
        for unit in kilib.symbol_units(part.lib, part.sym):
            items.append(SymbolPlacer(part, unit))
    # big items first (ICs), then passives; keep grouping: non-passive first
    def key(sp):
        passive = sp.part.lib == "Device" or sp.part.sym.startswith("Conn_") or sp.part.lib in ("Switch", "Jumper", "Mechanical")
        return (1 if passive else 0, -sp.h)
    items.sort(key=key)
    W = 560.0
    x, y, rowh = 20.0, 30.0, 0.0
    placed = []
    for sp in items:
        if x + sp.w > W:
            x = 20.0
            y += rowh + 5
            rowh = 0
        # symbol origin so that its bbox top-left sits at (x, y)
        ox = x + 2.54 + sp.label_len - sp.minx
        oy = y + 2.54 + sp.label_len + sp.maxy
        ox = round(ox / 1.27) * 1.27
        oy = round(oy / 1.27) * 1.27
        placed.append((sp.part, sp.unit, ox, oy))
        x += sp.w
        rowh = max(rowh, sp.h)
    H = y + rowh + 20
    return placed, W, H


def paper_for(W, H):
    if W <= 420 and H <= 297:
        return "A3"
    if W <= 594 and H <= 420:
        return "A2"
    return "A1"


def write_sheet(name, parts, root_uuid, sheet_uuid, pwr_flag_nets=()):
    out = [f'(kicad_sch (version 20230121) (generator gen_sch)\n  (uuid "{sheet_uuid}")\n']
    placed, W, H = place_sheet(parts)
    out.append(f'  (paper "{paper_for(W, H + (30 if pwr_flag_nets else 0))}")\n')
    out.append(f'  (title_block (title {q("HomeDeck CM4 - " + SHEET_TITLES.get(name, name))}) (date "2026-09-06") (rev "A") (company "HomeDeck"))\n')
    extra = [("power", "PWR_FLAG")] if pwr_flag_nets else []
    out.append(lib_symbols_block(parts, extra))
    out.append(f'  (text {q(SHEET_TITLES.get(name, name))} (at 20 15 0) (effects (font (size 3 3) bold) (justify left bottom)) (uuid "{uid()}"))\n')
    for part, unit, x, y in placed:
        write_symbol_instance(part, unit, x, y, root_uuid, sheet_uuid, out)
        write_pin_labels(part, unit, x, y, out)
    # PWR_FLAGs
    fx, fy = 20.0, H + 8
    H = H + 30
    for i, net in enumerate(pwr_flag_nets):
        x = fx + i * 25.4
        ref = f"#FLG{i+1}"
        out.append(f'  (symbol (lib_id "power:PWR_FLAG") (at {fmt(x)} {fmt(fy)} 0) (unit 1) (in_bom yes) (on_board yes) (dnp no)\n    (uuid "{uid()}")\n')
        out.append(f'    (property "Reference" {q(ref)} (at {fmt(x)} {fmt(fy-5)} 0) (effects (font (size 1.27 1.27)) hide))\n')
        out.append(f'    (property "Value" "PWR_FLAG" (at {fmt(x)} {fmt(fy-3)} 0) (effects (font (size 1.27 1.27))))\n')
        out.append(f'    (property "Footprint" "" (at {fmt(x)} {fmt(fy)} 0) (effects (font (size 1.27 1.27)) hide))\n')
        out.append(f'    (property "Datasheet" "" (at {fmt(x)} {fmt(fy)} 0) (effects (font (size 1.27 1.27)) hide))\n')
        out.append(f'    (pin "1" (uuid "{uid()}"))\n')
        out.append(f'    (instances (project {q(PROJECT)} (path "/{root_uuid}/{sheet_uuid}" (reference {q(ref)}) (unit 1))))\n  )\n')
        out.append(f'  (wire (pts (xy {fmt(x)} {fmt(fy)}) (xy {fmt(x)} {fmt(fy+2.54)})) (stroke (width 0) (type default)) (uuid "{uid()}"))\n')
        out.append(f'  (global_label {q(net)} (shape input) (at {fmt(x)} {fmt(fy+2.54)} 270) (fields_autoplaced)\n    (effects (font (size 1.27 1.27)) (justify right))\n    (uuid "{uid()}")\n'
                   f'    (property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n  )\n')
    out.append(')\n')
    return "".join(out)


def write_root(sheet_uuids, root_uuid, circuit):
    out = [f'(kicad_sch (version 20230121) (generator gen_sch)\n  (uuid "{root_uuid}")\n  (paper "A3")\n']
    out.append('  (title_block (title "HomeDeck CM4 carrier - smart display / voice assistant") (date "2026-09-06") (rev "A") (company "HomeDeck"))\n')
    out.append('  (lib_symbols)\n')
    out.append('  (text "HomeDeck CM4 carrier board\\nRaspberry Pi CM4 + Touch Display 2 + camera + audio + sensors\\nAll connectivity is by global labels; each sub-sheet is one functional block." (at 20 20 0) (effects (font (size 3 3)) (justify left bottom)) (uuid "' + uid() + '"))\n')
    x, y = 25.0, 40.0
    for i, name in enumerate(SHEET_ORDER):
        su = sheet_uuids[name]
        out.append(f'  (sheet (at {fmt(x)} {fmt(y)}) (size 60 20) (fields_autoplaced)\n    (stroke (width 0.1524) (type solid))\n    (fill (color 0 0 0 0.0000))\n    (uuid "{su}")\n')
        out.append(f'    (property "Sheetname" {q(name)} (at {fmt(x)} {fmt(y-1)} 0) (effects (font (size 1.27 1.27)) (justify left bottom)))\n')
        out.append(f'    (property "Sheetfile" {q(name + ".kicad_sch")} (at {fmt(x)} {fmt(y+21)} 0) (effects (font (size 1.27 1.27)) (justify left top)))\n')
        out.append(f'    (instances (project {q(PROJECT)} (path "/{root_uuid}" (page "{i+2}"))))\n  )\n')
        x += 70
        if x > 300:
            x = 25.0
            y += 35
    out.append('  (sheet_instances (path "/" (page "1")))\n)\n')
    return "".join(out)


def write_project_files(circuit):
    pro = {
        "board": {"design_settings": {"defaults": {}, "rules": {}}, "layer_presets": [], "viewports": []},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": f"{PROJECT}.kicad_pro", "version": 1},
        "net_settings": {"classes": [{"name": "Default", "clearance": 0.15, "track_width": 0.2, "via_diameter": 0.6, "via_drill": 0.3,
                                      "diff_pair_width": 0.2, "diff_pair_gap": 0.15, "bus_width": 12, "wire_width": 6, "line_style": 0, "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)"}],
                         "meta": {"version": 3}},
        "pcbnew": {"page_layout_descr_file": ""},
        "schematic": {"drawing": {}, "legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [],
        "text_variables": {},
    }
    import json
    with open(os.path.join(OUT_DIR, f"{PROJECT}.kicad_pro"), "w") as f:
        json.dump(pro, f, indent=2)
    with open(os.path.join(OUT_DIR, "sym-lib-table"), "w") as f:
        f.write('(sym_lib_table\n  (version 7)\n  (lib (name "HomeDeck")(type "KiCad")(uri "${KIPRJMOD}/HomeDeck.kicad_sym")(options "")(descr "HomeDeck project symbols"))\n)\n')
    with open(os.path.join(OUT_DIR, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table\n  (version 7)\n  (lib (name "HomeDeck")(type "KiCad")(uri "${KIPRJMOD}/HomeDeck.pretty")(options "")(descr "HomeDeck project footprints"))\n)\n')


def generate(circuit):
    os.makedirs(OUT_DIR, exist_ok=True)
    root_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "homedeck-root"))
    sheet_uuids = {n: str(uuid.uuid5(uuid.NAMESPACE_DNS, "homedeck-" + n)) for n in SHEET_ORDER}
    for name in SHEET_ORDER:
        parts = circuit.sheets.get(name, [])
        flags = circuit.pwr_flags if name == "power" else ()
        txt = write_sheet(name, parts, root_uuid, sheet_uuids[name], flags)
        with open(os.path.join(OUT_DIR, f"{name}.kicad_sch"), "w") as f:
            f.write(txt)
    with open(os.path.join(OUT_DIR, f"{PROJECT}.kicad_sch"), "w") as f:
        f.write(write_root(sheet_uuids, root_uuid, circuit))
    write_project_files(circuit)
    return root_uuid, sheet_uuids


if __name__ == "__main__":
    import circuit as circ
    c = circ.build()
    generate(c)
    print("schematic written")
