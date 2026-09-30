"""Export fabrication outputs: gerbers+drill zip, JLCPCB BOM and CPL, schematic PDF, board renders."""
import os, sys, csv, subprocess, zipfile, json, collections
import pcbnew
from pcbnew import ToMM

sys.path.insert(0, os.path.dirname(__file__))
import gen_pcb, circuit as circ

KICAD_DIR = gen_pcb.KICAD_DIR
OUT = os.path.abspath(os.path.join(KICAD_DIR, "..", "out"))
PCB = os.path.join(KICAD_DIR, "HomeDeck.kicad_pcb")


def gerbers():
    gd = os.path.join(OUT, "gerbers")
    os.makedirs(gd, exist_ok=True)
    for f in os.listdir(gd):
        os.remove(os.path.join(gd, f))
    layers = "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"
    subprocess.run(["kicad-cli", "pcb", "export", "gerbers", "--layers", layers, "--subtract-soldermask", "--no-x2", "--use-drill-file-origin", "-o", gd + "/", PCB], check=True, capture_output=True)
    subprocess.run(["kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2", "-o", gd + "/", PCB], check=True, capture_output=True)
    zpath = os.path.join(OUT, "HomeDeck_gerbers.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(gd)):
            z.write(os.path.join(gd, f), f)
    return zpath


# JLC placement conventions (same approach as the kicad-jlcpcb-tools plugin): position = centre of the pad bounding box,
# Y negated, bottom-side rotation mirrored, then a per-package correction because JLC's library orientation differs from KiCad's.
ROT_CORR = [(r"^SOT-223", 180), (r"^SOT-23", -90), (r"^TSSOP-", 270), (r"^HTSSOP-", 270), (r"^QSOP-", 270), (r"^TI_SO-PowerPAD", 270),
            (r"^Texas_UQFN-10", 270), (r"^ESSOP-10", 270), (r"^CP_Elec_6.3x7.7", 180), (r"^USB_C_Receptacle_HRO_TYPE-C-31-M-12", 180),
            (r"^JST_PH_S", 180), (r"^Bosch_LGA-8", 90), (r"^LED_WS2812B", 90), (r"^microSD_HC_Molex", 180)]
JLC = json.load(open(os.path.join(os.path.dirname(__file__), "jlc_parts.json")))


def jlc_rotation(fp):
    import re, math
    rot = fp.GetOrientationDegrees()
    if fp.GetLayer() != pcbnew.F_Cu:
        rot = (180 - rot) % 360
    name = fp.GetFPIDAsString().split(":")[-1]
    for pat, corr in ROT_CORR:
        if re.search(pat, name):
            rot = (rot + corr) % 360
            break
    return rot % 360


def jlc_position(fp):
    pads = list(fp.Pads())
    bb = pads[0].GetBoundingBox()
    for p in pads[1:]:
        bb.Merge(p.GetBoundingBox())
    return bb.GetCenter()


def bom_cpl():
    c = circ.build()
    b = pcbnew.LoadBoard(PCB)
    groups = collections.OrderedDict()
    for p in c.parts.values():
        if p.lib == "Mechanical" or p.dnp or not p.lcsc:
            continue
        key = (p.lcsc, p.fp) if p.lcsc else (p.value, p.fp, p.lcsc)
        groups.setdefault(key, []).append(p.ref)
    bom_path = os.path.join(OUT, "HomeDeck_BOM_JLCPCB.csv")
    with open(bom_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "MPN", "JLC type", "Description", "JLC stock (2026-09-06)"])
        for keyt, refs in groups.items():
            lcsc = keyt[0] if len(keyt) == 2 else keyt[2]; fp = keyt[1]; val = c.parts[refs[0]].value
            p = c.parts[refs[0]]
            jt = JLC.get(lcsc)
            typ = jt[0] if jt else (("Basic" if p.basic else "Extended") if p.basic is not None else "")
            stock = jt[1] if jt else ""
            w.writerow([val if len({c.parts[r].value for r in refs}) == 1 else p.mpn, ",".join(refs), fp.split(":")[-1], lcsc, p.mpn, typ, p.desc, stock])
        # the two CM4 sockets are part of the M1 (CM4) footprint; JLC needs them as their own lines
        w.writerow(["DF40C-100DS-0.4V(51)", "M1A,M1B", "Hirose_DF40C-100DS-0.4V", "C597931", "DF40C-100DS-0.4V(51)", "Extended", "CM4 socket, 100-pin 0.4 mm, 1.5 mm stack (genuine Hirose; low stock, may be pre-order)", JLC["C597931"][1]])
    # not-on-JLC parts (CM4 module, DNP, no LCSC)
    extra_path = os.path.join(OUT, "HomeDeck_BOM_other.csv")
    with open(extra_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Value", "Footprint", "Note"])
        for p in c.parts.values():
            if p.lib == "Mechanical" or p.fp.startswith("Jumper:"):
                continue
            if p.dnp:
                w.writerow([p.ref, p.value, p.fp, "DNP (do not populate)"])
            elif not p.lcsc:
                w.writerow([p.ref, p.value, p.fp, "not in JLC library: " + p.desc])
    cpl_path = os.path.join(OUT, "HomeDeck_CPL_JLCPCB.csv")
    with open(cpl_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for fp in b.GetFootprints():
            ref = fp.GetReference()
            p = c.parts.get(ref)
            if p is None or p.lib == "Mechanical" or p.dnp or not p.lcsc:
                continue
            pos = jlc_position(fp)
            layer = "Top" if fp.GetLayer() == pcbnew.F_Cu else "Bottom"
            rot = jlc_rotation(fp)
            w.writerow([ref, f"{ToMM(pos.x):.3f}mm", f"{-ToMM(pos.y):.3f}mm", layer, f"{rot:.1f}"])
        # CM4 sockets (centres of the two 2x50 pad fields of M1; pin 1 is the left pad of the lower row of each)
        m1 = b.FindFootprintByReference("M1")
        pads = {p.GetNumber(): p.GetPosition() for p in m1.Pads()}
        for ref, lo, hi in (("M1A", 1, 100), ("M1B", 101, 200)):
            xs = [ToMM(pads[str(i)].x) for i in range(lo, hi + 1)]
            ys = [ToMM(pads[str(i)].y) for i in range(lo, hi + 1)]
            w.writerow([ref, f"{sum(xs)/len(xs):.3f}mm", f"{-sum(ys)/len(ys):.3f}mm", "Top", "0.0"])
    return bom_path, cpl_path, extra_path, len(groups)


def schematic_pdf():
    out = os.path.join(OUT, "HomeDeck_schematic.pdf")
    subprocess.run(["kicad-cli", "sch", "export", "pdf", "-o", out, os.path.join(KICAD_DIR, "HomeDeck.kicad_sch")], check=True, capture_output=True)
    return out


def project_zip():
    zpath = os.path.join(OUT, "HomeDeck_KiCad_project.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for top in (KICAD_DIR, os.path.join(os.path.dirname(KICAD_DIR), "docs"), os.path.join(os.path.dirname(KICAD_DIR), "tools")):
            for root, dirs, files in os.walk(top):
                for f in files:
                    if f.endswith((".json", "-bak", ".lck", ".bak")) or f in ("router", "router_dbg") or "__pycache__" in root:
                        continue
                    full = os.path.join(root, f)
                    z.write(full, os.path.relpath(full, os.path.dirname(KICAD_DIR)))
        for f in ("drc.txt", "board_top.png", "board_bottom.png", "HomeDeck_schematic.pdf", "HomeDeck_BOM_JLCPCB.csv", "HomeDeck_CPL_JLCPCB.csv", "HomeDeck_BOM_other.csv", "HomeDeck_gerbers.zip"):
            p = os.path.join(OUT, f)
            if os.path.exists(p):
                z.write(p, "out/" + f)
    return zpath


if __name__ == "__main__":
    print(gerbers())
    print(bom_cpl())
    print(schematic_pdf())
    print(project_zip())
