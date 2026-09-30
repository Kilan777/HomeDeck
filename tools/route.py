"""Export routing problem, run the C++ router, import tracks/vias, fill zones, run DRC."""
import os, sys, json, subprocess, re, time, collections
import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM

sys.path.insert(0, os.path.dirname(__file__))
import gen_pcb

KICAD_DIR = gen_pcb.KICAD_DIR
TOOLS = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(KICAD_DIR, "HomeDeck.kicad_pcb")

PAIRS = [("DSI_D0_P", "DSI_D0_N"), ("DSI_D1_P", "DSI_D1_N"), ("DSI_C_P", "DSI_C_N"), ("CSI_D0_P", "CSI_D0_N"), ("CSI_D1_P", "CSI_D1_N"), ("CSI_C_P", "CSI_C_N"),
         ("USB_CM4_P", "USB_CM4_N"), ("USB_BOOT_P", "USB_BOOT_N"), ("USB_HUB_UP_P", "USB_HUB_UP_N"), ("USB_DS1_P", "USB_DS1_N"), ("USB_C2_P", "USB_C2_N"),
         ("USB_DSA_P", "USB_DSA_N"), ("USB_DS3_P", "USB_DS3_N"), ("USB_DS4_P", "USB_DS4_N")]
PLANES = {"GND": 1, "5V_SYS": 2, "VBUS": 2, "5V_USB": 2, "5V_PERIPH": 2, "3V3": 2}
PLANE_POLYS = gen_pcb.PLANE_POLYS
WIDE = {"CM4_3V3": 0.4, "5V_USBC2": 0.4, "5V_USBA": 0.4, "SD_VDD": 0.4, "HUB_V33": 0.3, "PD_VDD": 0.3, "DAC_AVDD": 0.3, "AMP_AVCC": 0.4, "AMP_GVDD": 0.3,
        "AMP_OUTPL": 0.5, "AMP_OUTNL": 0.5, "AMP_OUTPR": 0.5, "AMP_OUTNR": 0.5, "SPK_LP": 0.5, "SPK_LN": 0.5, "SPK_RP": 0.5, "SPK_RN": 0.5,
        "BK1_PH": 0.8, "BK2_PH": 0.8, "BK3_PH": 0.8, "VBUS_RAW": 0.8, "FAN_N": 0.4, "LED_D0": 0.2}
PLANE_W = {"GND": 0.4, "5V_SYS": 0.5, "VBUS": 0.5, "5V_USB": 0.5, "5V_PERIPH": 0.5, "3V3": 0.4}
CLEAR = 0.16
RES = 0.1


def pad_poly(pad):
    poly = pad.GetEffectivePolygon()
    pts = []
    if poly.OutlineCount() > 0:
        o = poly.Outline(0)
        for i in range(o.PointCount()):
            p = o.CPoint(i)
            pts.append((ToMM(p.x), ToMM(p.y)))
    else:
        bb = pad.GetBoundingBox()
        pts = [(ToMM(bb.GetLeft()), ToMM(bb.GetTop())), (ToMM(bb.GetRight()), ToMM(bb.GetTop())), (ToMM(bb.GetRight()), ToMM(bb.GetBottom())), (ToMM(bb.GetLeft()), ToMM(bb.GetBottom()))]
    # simplify: keep at most 16 points
    if len(pts) > 16:
        step = len(pts) / 16.0
        pts = [pts[int(i * step)] for i in range(16)]
    return pts


def export_problem(b, path, only_terms=None, fixed=False, strips=True):
    pads = []
    nets = {}
    holes = []
    netnames = {}
    for code, ni in b.GetNetsByNetcode().items():
        if code > 0:
            netnames[code] = ni.GetNetname()
    escapes = []
    from shapely.geometry import Polygon, box
    from shapely.strtree import STRtree
    # all pad bboxes (for clipping escape strips against other footprints), expanded by clearance
    padboxes, padrefs = [], []
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            bb = pad.GetBoundingBox()
            padboxes.append(box(ToMM(bb.GetLeft()) - 0.2, ToMM(bb.GetTop()) - 0.2, ToMM(bb.GetRight()) + 0.2, ToMM(bb.GetBottom()) + 0.2))
            padrefs.append(fp.GetReference())
    tree = STRtree(padboxes)
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        fcx, fcy = ToMM(fp.GetPosition().x), ToMM(fp.GetPosition().y)
        if ref == "M1":
            fcx, fcy = 65.0, 52.5
        for pad in fp.Pads():
            net = pad.GetNetCode()
            # escape strip for fine pads: reserve the outward direction for the pad's own net
            szx, szy = ToMM(pad.GetSize().x), ToMM(pad.GetSize().y)
            if strips and net > 0 and pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and min(szx, szy) < 0.5 and ref != "M1":
                px, py = ToMM(pad.GetPosition().x), ToMM(pad.GetPosition().y)
                if ref == "M1":
                    # rows: outward from the connector centre line (row pairs at y=34/37.1 and 67.9/71)
                    dx, dy = 0.0, (-1.0 if py < 36 else (1.0 if py < 52.5 else (-1.0 if py < 69.5 else 1.0)))
                else:
                    dx, dy = px - fcx, py - fcy
                    # snap to the dominant axis so strips stay parallel to the pad row
                    if abs(dx) > abs(dy):
                        dx, dy = (1.0 if dx > 0 else -1.0), 0.0
                    else:
                        dx, dy = 0.0, (1.0 if dy > 0 else -1.0)
                wdt = min(szx, szy)
                E = 0.7
                nx_, ny_ = -dy, dx
                hw = wdt / 2
                x0, y0 = px, py
                # shorten the strip until it does not run into another footprint's pads
                while E >= 0.3:
                    x1, y1 = px + dx * (max(szx, szy) / 2 + E), py + dy * (max(szx, szy) / 2 + E)
                    poly = [[x0 + nx_ * hw, y0 + ny_ * hw], [x1 + nx_ * hw, y1 + ny_ * hw], [x1 - nx_ * hw, y1 - ny_ * hw], [x0 - nx_ * hw, y0 - ny_ * hw]]
                    sp = Polygon(poly)
                    hit = [i for i in tree.query(sp) if padrefs[i] != ref and padboxes[i].intersects(sp)]
                    if not hit:
                        break
                    E -= 0.2
                if E >= 0.3:
                    escapes.append({"net": net, "layer": 0 if pad.IsOnLayer(pcbnew.F_Cu) else 1, "poly": poly})
            on_f = pad.IsOnLayer(pcbnew.F_Cu)
            on_b = pad.IsOnLayer(pcbnew.B_Cu)
            tht = pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
            layer = 2 if tht else (0 if on_f else 1)
            poly = pad_poly(pad)
            pidx = len(pads)
            pads.append({"net": net, "layer": layer, "poly": poly})
            if tht:
                d = ToMM(pad.GetDrillSize().x)
                holes.append([ToMM(pad.GetPosition().x), ToMM(pad.GetPosition().y), d / 2 + 0.1, net if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH else 0])
            if net > 0 and pad.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
                sz = pad.GetSize()
                w = min(ToMM(sz.x), ToMM(sz.y))
                name = netnames[net]
                nodrop = (name == "GND")  # GND SMD pads connect through the top/bottom pours; repair pass adds vias where the pour cannot reach
                nets.setdefault(net, {"id": net, "name": name, "terms": []})["terms"].append(
                    {"pad": pidx, "layer": layer, "cx": ToMM(pad.GetPosition().x), "cy": ToMM(pad.GetPosition().y), "w": round(w, 3), "nodrop": nodrop, "ref": ref, "padnum": pad.GetNumber()})
    tracks, fvias = [], []
    # CM4 fan-out: fixed stubs + vias; the M1 terminals move to the via positions
    fan_path = os.path.join(gen_pcb.KICAD_DIR, "fanout.json")
    if os.path.exists(fan_path):
        fan = json.load(open(fan_path))
        pad_index = {}
        for n in nets.values():
            for t in n["terms"]:
                if t["ref"] == "M1":
                    pad_index[t["padnum"]] = t
        for f in fan:
            t = pad_index.get(f["pad"])
            if t is None:
                continue
            code = [k for k, v in netnames.items() if v == f["net"]][0]
            (x1, y1), (x2, y2) = f["stub"]
            tracks.append([0, x1, y1, x2, y2, gen_pcb.FANOUT_W, code, t["pad"]])
            fvias.append([f["via"][0], f["via"][1], code, gen_pcb.FANOUT_VIA[0] / 2, gen_pcb.FANOUT_VIA[1] / 2, t["pad"]])
            t["cx"], t["cy"] = f["via"]
            t["layer"] = 2
            t["w"] = 0.3
            t["cells"] = [[int(round(f["via"][0] / RES)), int(round(f["via"][1] / RES))]]
    if fixed:
        for t in b.GetTracks():
            if t.GetClass() == "PCB_VIA":
                fvias.append([ToMM(t.GetPosition().x), ToMM(t.GetPosition().y), t.GetNetCode(), ToMM(t.GetWidth()) / 2, ToMM(t.GetDrillValue()) / 2, -1])
            else:
                tracks.append([0 if t.GetLayer() == pcbnew.F_Cu else 1, ToMM(t.GetStart().x), ToMM(t.GetStart().y), ToMM(t.GetEnd().x), ToMM(t.GetEnd().y), ToMM(t.GetWidth()), t.GetNetCode(), -1])
    if only_terms is not None:
        # keep only the listed (ref, pad) terminals; drop nets without terminals
        keep = set(only_terms)
        for code, n in list(nets.items()):
            n["terms"] = [t for t in n["terms"] if (t["ref"], t["padnum"]) in keep]
            if not n["terms"]:
                del nets[code]
        for n in nets.values():
            for t in n["terms"]:
                t["nodrop"] = False
    netlist = []
    name2id = {v["name"]: k for k, v in nets.items()}
    pair_of = {}
    for a, bn in PAIRS:
        if a in name2id and bn in name2id:
            pair_of[name2id[bn]] = name2id[a]
    for code, n in nets.items():
        name = n["name"]
        plane = name in PLANES
        width = PLANE_W.get(name, WIDE.get(name, 0.2))
        pr = 4
        if name in pair_of or code in pair_of.values():
            pr = 0
        elif plane:
            pr = 5 if name == "GND" else 4
        elif name in WIDE:
            pr = 3
        elif name.startswith("I2S") or name.startswith("SD_") or name.startswith("I2C"):
            pr = 1
        else:
            pr = 2
        minpad = min(t["w"] for t in n["terms"])
        width = min(width, max(0.2, round(0.75 * minpad, 2)))
        if any(t["ref"] == "M1" for t in n["terms"]) and not plane and name not in WIDE:
            width = 0.1
        vc = 6.0 if (name in pair_of or code in pair_of.values()) else 3.0
        n.update({"width": width, "clearance": CLEAR, "via_cost": vc, "plane": plane, "plane_layer": PLANES.get(name, 0), "priority": pr, "pair_of": pair_of.get(code, -1)})
        netlist.append(n)
    # keepouts: slots (with clearance)
    keep = []
    slots = [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]] for (x1, y1, x2, y2) in gen_pcb.SLOTS]
    prob = {"width": gen_pcb.BOARD_W, "height": gen_pcb.BOARD_H, "res": RES, "via_dia": 0.6, "clearance": CLEAR, "rmax": 0.7, "edge_clearance": 0.3,
            "keepouts": keep, "slots": slots, "holes": holes, "outline": gen_pcb.board_outline_points(),
            "in2": [{"net": name2id[k], "poly": v} for k, v in PLANE_POLYS.items() if k in name2id],
            "pads": pads, "escapes": escapes, "tracks": tracks, "fixed_vias": fvias, "clr_areas": [[x1, y1, x2, y2, 0.1] for (x1, y1, x2, y2) in gen_pcb.FANOUT_AREAS], "nets": netlist, "via_cost": 1.5, "max_expand": 4000000, "max_iter": 10, "penalty": 4.0}
    with open(path, "w") as f:
        json.dump(prob, f)
    return prob


def import_result(b, res_path):
    with open(res_path) as f:
        res = json.load(f)
    layers = {0: pcbnew.F_Cu, 1: pcbnew.B_Cu}
    nseg = nvia = 0
    for n in res["nets"]:
        code = n["id"]
        for (L, x1, y1, x2, y2, w) in n["segs"]:
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
            t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
            t.SetWidth(FromMM(w))
            t.SetLayer(layers[L])
            t.SetNetCode(code)
            b.Add(t)
            nseg += 1
        for (x, y) in n["vias"]:
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
            v.SetDrill(FromMM(0.3))
            v.SetWidth(FromMM(0.6))
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            v.SetNetCode(code)
            b.Add(v)
            nvia += 1
    return nseg, nvia, res["failures"]


def fill_zones(b):
    filler = pcbnew.ZONE_FILLER(b)
    filler.Fill(b.Zones())


def run_drc(b, path):
    pcbnew.WriteDRCReport(b, path, True, True)
    txt = open(path).read()
    m = re.search(r"Found (\d+) DRC violations", txt)
    u = re.search(r"Found (\d+) unconnected pads", txt)
    return int(m.group(1)) if m else -1, int(u.group(1)) if u else -1, txt


def summarize_drc(txt):
    counts = {}
    for m in re.finditer(r"^\[(\w+)\]", txt, re.M):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


def remove_dangling_vias(b, txt):
    """Delete vias that DRC reports as dangling (fan-out vias whose net was picked up at the stub instead)."""
    pts = set()
    for m in re.finditer(r"\[via_dangling\].*?\n.*?\n\s*@\(([-\d.]+) mm, ([-\d.]+) mm\): Via", txt):
        pts.add((round(float(m.group(1)), 2), round(float(m.group(2)), 2)))
    n = 0
    for t in list(b.GetTracks()):
        if t.GetClass() == "PCB_VIA":
            k = (round(ToMM(t.GetPosition().x), 2), round(ToMM(t.GetPosition().y), 2))
            if k in pts:
                b.Remove(t)
                n += 1
    return n


def unconnected_terms(txt):
    terms = set()
    block = txt.split("unconnected pads")[1] if "unconnected pads" in txt else ""
    for m in re.finditer(r"Pad (\S+) \[(\S+)\] of (\S+) on", block):
        terms.add((m.group(3), m.group(1), m.group(2)))
    return terms


def run_router(prob_path, res_path, env=None):
    e = dict(os.environ)
    e.update(env or {})
    r = subprocess.run([os.path.join(TOOLS, "router"), prob_path, res_path], capture_output=True, text=True, env=e)
    return r.stderr


if __name__ == "__main__":
    import circuit as circ
    gen_pcb.build(circ.build(), PCB)  # fresh, unrouted board
    b = pcbnew.LoadBoard(PCB)
    gen_pcb.setup_board(b)
    out_dir = os.path.join(gen_pcb.KICAD_DIR, "..", "out")
    prob_path = os.path.join(out_dir, "route_in.json")
    res_path = os.path.join(out_dir, "route_out.json")
    export_problem(b, prob_path)
    t0 = time.time()
    log = run_router(prob_path, res_path, {"RITER": os.environ.get("RITER", "8")})
    print("\n".join(l for l in log.splitlines() if not l.startswith("  FAILED"))[-2500:])
    print("router time %.1fs" % (time.time() - t0))
    nseg, nvia, fails = import_result(b, res_path)
    print("imported", nseg, "segments", nvia, "vias, failures", fails)
    fill_zones(b)
    b.Save(PCB)
    for rep in range(3):
        nv, nu, txt = run_drc(b, os.path.join(out_dir, "drc.txt"))
        print("DRC violations", nv, "unconnected", nu, summarize_drc(txt))
        terms = unconnected_terms(txt)
        gnd_terms = [(r_, p_) for (r_, p_, n_) in terms if n_ == "GND"]
        print("unconnected terminals:", len(terms), "of which GND:", len(gnd_terms))
        if not gnd_terms:
            break
        # repair: route only the unconnected GND pads as plane drops with all existing copper fixed
        b = pcbnew.LoadBoard(PCB)
        gen_pcb.setup_board(b)
        rp = os.path.join(out_dir, "repair_in.json")
        rr = os.path.join(out_dir, "repair_out.json")
        prob = export_problem(b, rp, only_terms=gnd_terms, fixed=True)
        prob["drop_box"] = 10.0
        prob["max_iter"] = 1
        with open(rp, "w") as f:
            json.dump(prob, f)
        log = run_router(rp, rr, {"RITER": "1"})
        print("repair:", log.strip().splitlines()[-1])
        ns, nvv, ff = import_result(b, rr)
        print("repair imported", ns, "segs", nvv, "vias")
        for z in b.Zones():
            z.SetIsFilled(False)
        fill_zones(b)
        b.Save(PCB)
    # final cleanup of dangling fan-out vias
    b = pcbnew.LoadBoard(PCB)
    gen_pcb.setup_board(b)
    nv, nu, txt = run_drc(b, os.path.join(out_dir, "drc.txt"))
    removed = 0  # dangling fan-out vias are harmless junctions; keep them
    if removed:
        for z in b.Zones():
            z.SetIsFilled(False)
        fill_zones(b)
        b.Save(PCB)
        nv, nu, txt = run_drc(b, os.path.join(out_dir, "drc.txt"))
    print("removed dangling vias:", removed)
    print("FINAL DRC violations", nv, "unconnected", nu, summarize_drc(txt))


def reroute_nets(names, riter="1", drop_box=10.0):
    """Delete the tracks of the given nets and reroute them with all other copper fixed."""
    b = pcbnew.LoadBoard(PCB)
    codes = {b.GetNetcodeFromNetname(n) for n in names}
    del b
    # delete the nets' tracks/vias textually (pcbnew.Remove on tracks breaks the SWIG proxies)
    fan = json.load(open(os.path.join(gen_pcb.KICAD_DIR, "fanout.json")))
    stubs, fvias = set(), set()
    for e in fan:
        (x1, y1), (x2, y2) = e["stub"]
        stubs.add((round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3)))
        stubs.add((round(x2, 3), round(y2, 3), round(x1, 3), round(y1, 3)))
        fvias.add((round(e["via"][0], 3), round(e["via"][1], 3)))
    mk = os.path.join(gen_pcb.KICAD_DIR, "manual_keep.json")
    if os.path.exists(mk):
        m = json.load(open(mk))
        for x1, y1, x2, y2 in m.get("segments", []):
            stubs.add((round(x1, 3), round(y1, 3), round(x2, 3), round(y2, 3)))
            stubs.add((round(x2, 3), round(y2, 3), round(x1, 3), round(y1, 3)))
        for x, y in m.get("vias", []):
            fvias.add((round(x, 3), round(y, 3)))
    txt = open(PCB).read().split("\n")
    keep, removed = [], 0
    for line in txt:
        ls = line.strip()
        m = re.match(r"\((segment|via) .*\(net (\d+)\)", ls)
        if m and int(m.group(2)) in codes:
            if m.group(1) == "segment":
                g = re.search(r"\(start ([-\d.]+) ([-\d.]+)\) \(end ([-\d.]+) ([-\d.]+)\)", ls)
                if g and (tuple(round(float(v), 3) for v in g.groups()) in stubs):
                    keep.append(line)
                    continue
            else:
                g = re.search(r"\(at ([-\d.]+) ([-\d.]+)\)", ls)
                if g and (round(float(g.group(1)), 3), round(float(g.group(2)), 3)) in fvias:
                    keep.append(line)
                    continue
            removed += 1
            continue
        keep.append(line)
    with open(PCB, "w") as f:
        f.write("\n".join(keep))
    b = pcbnew.LoadBoard(PCB)
    gen_pcb.setup_board(b)
    out_dir = os.path.join(gen_pcb.KICAD_DIR, "..", "out")
    rp = os.path.join(out_dir, "reroute_in.json")
    rr = os.path.join(out_dir, "reroute_out.json")
    terms = []
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() in codes:
                terms.append((fp.GetReference(), pad.GetNumber()))
    prob = export_problem(b, rp, only_terms=terms, fixed=True, strips=False)
    prob["drop_box"] = drop_box
    prob["penalty"] = 120.0
    with open(rp, "w") as f:
        json.dump(prob, f)
    log = run_router(rp, rr, {"RITER": riter})
    ns, nv, ff = import_result(b, rr)
    for z in b.Zones():
        z.SetIsFilled(False)
    fill_zones(b)
    b.Save(PCB)
    return removed, ns, nv, ff, log.strip().splitlines()[-1]


def drc_bad_pairs(txt):
    cnt = collections.Counter()
    for m in re.finditer(r"^\[(clearance|hole_clearance|hole_near_hole|holes_co_located|diff_pair_gap_out_of_range)\].*?\n.*?\n\s*@\([^)]*\): \w+ \[([^\]]+)\].*?\n\s*@\([^)]*\): \w+ \[([^\]]+)\]", txt, re.M):
        cnt[tuple(sorted((m.group(2), m.group(3))))] += 1
    return [p for p, _ in cnt.most_common()]


def drc_bad_nets(txt):
    """Net names involved in clearance / hole violations, most frequent first."""
    cnt = collections.Counter()
    block = txt.split("** Found")[1] if "** Found" in txt else txt
    for m in re.finditer(r"^\[(clearance|hole_clearance|hole_near_hole|holes_co_located|diff_pair_gap_out_of_range)\].*?\n.*?\n\s*@\([^)]*\): \w+ \[([^\]]+)\].*?\n\s*@\([^)]*\): \w+ \[([^\]]+)\]", txt, re.M):
        cnt[m.group(2)] += 1
        cnt[m.group(3)] += 1
    return [n for n, _ in cnt.most_common()]


def drc_score(txt):
    c = summarize_drc(txt)
    return sum(c.get(k, 0) for k in ("clearance", "hole_clearance", "hole_near_hole", "holes_co_located", "unconnected_items", "diff_pair_gap_out_of_range"))


def cleanup(max_nets=20):
    import shutil
    out_dir = os.path.join(gen_pcb.KICAD_DIR, "..", "out")
    b = pcbnew.LoadBoard(PCB)
    gen_pcb.setup_board(b)
    nv, nu, txt = run_drc(b, os.path.join(out_dir, "drc.txt"))
    del b
    score = drc_score(txt)
    print("cleanup start score", score)
    tried = set()
    for k in range(max_nets):
        cands = [p for p in drc_bad_pairs(txt) if p not in tried and "GND" not in p]
        if not cands:
            break
        net = cands[0]
        tried.add(net)
        shutil.copy(PCB, PCB + ".bak")
        try:
            reroute_nets(list(net), riter="6")
        except Exception as e:
            print("  reroute error", net, e)
            shutil.copy(PCB + ".bak", PCB)
            continue
        b = pcbnew.LoadBoard(PCB)
        gen_pcb.setup_board(b)
        nv, nu, txt2 = run_drc(b, os.path.join(out_dir, "drc.txt"))
        del b
        s2 = drc_score(txt2)
        if s2 < score:
            print(f"  {net}: {score} -> {s2} (kept)")
            score, txt = s2, txt2
        else:
            print(f"  {net}: {score} -> {s2} (reverted)")
            shutil.copy(PCB + ".bak", PCB)
    return score


def gnd_repair(rounds=2):
    out_dir = os.path.join(gen_pcb.KICAD_DIR, "..", "out")
    for rep in range(rounds):
        b = pcbnew.LoadBoard(PCB)
        gen_pcb.setup_board(b)
        nv, nu, txt = run_drc(b, os.path.join(out_dir, "drc.txt"))
        terms = unconnected_terms(txt)
        gnd_terms = [(r_, p_) for (r_, p_, n_) in terms if n_ == "GND"]
        print("unconnected:", len(terms), "GND:", len(gnd_terms))
        if not gnd_terms:
            return
        rp = os.path.join(out_dir, "repair_in.json")
        rr = os.path.join(out_dir, "repair_out.json")
        prob = export_problem(b, rp, only_terms=gnd_terms, fixed=True, strips=False)
        prob["drop_box"] = 15.0
        with open(rp, "w") as f:
            json.dump(prob, f)
        log = run_router(rp, rr, {"RITER": "1"})
        ns, nvv, ff = import_result(b, rr)
        print("repair:", log.strip().splitlines()[-1], "imported", ns, nvv)
        for z in b.Zones():
            z.SetIsFilled(False)
        fill_zones(b)
        b.Save(PCB)


def group_reroute(names, riter="4"):
    import shutil
    out_dir = os.path.join(gen_pcb.KICAD_DIR, "..", "out")
    b = pcbnew.LoadBoard(PCB); gen_pcb.setup_board(b)
    nv, nu, txt = run_drc(b, os.path.join(out_dir, "drc.txt")); del b
    s0 = drc_score(txt)
    shutil.copy(PCB, PCB + ".bak")
    print("group reroute", names, reroute_nets(names, riter=riter))
    b = pcbnew.LoadBoard(PCB); gen_pcb.setup_board(b)
    nv, nu, txt = run_drc(b, os.path.join(out_dir, "drc.txt")); del b
    s1 = drc_score(txt)
    if s1 < s0:
        print(f"  kept {s0} -> {s1}")
    else:
        print(f"  reverted {s0} -> {s1}")
        shutil.copy(PCB + ".bak", PCB)
    return min(s0, s1)


def local_ripup(max_spots=8, radius=3.0):
    """For each remaining clearance violation, rip up every net with copper within `radius` of the spot and renegotiate them."""
    import shutil
    out_dir = os.path.join(gen_pcb.KICAD_DIR, "..", "out")
    b = pcbnew.LoadBoard(PCB); gen_pcb.setup_board(b)
    nv, nu, txt = run_drc(b, os.path.join(out_dir, "drc.txt")); del b
    score = drc_score(txt)
    done = 0
    tried = set()
    while done < max_spots:
        spots = []
        for m in re.finditer(r"^\[(clearance|hole_clearance|hole_near_hole|holes_co_located)\].*?\n.*?\n\s*@\(([-\d.]+) mm, ([-\d.]+) mm\): \w+ \[([^\]]+)\]", txt, re.M):
            spots.append((float(m.group(2)), float(m.group(3)), m.group(4)))
        spots = [s for s in spots if (round(s[0]), round(s[1])) not in tried]
        if not spots:
            break
        x, y, _ = spots[0]
        tried.add((round(x), round(y)))
        b = pcbnew.LoadBoard(PCB)
        nets = set()
        for t in b.GetTracks():
            if t.GetClass() == "PCB_VIA":
                px, py = ToMM(t.GetPosition().x), ToMM(t.GetPosition().y)
                if (px - x) ** 2 + (py - y) ** 2 < radius ** 2:
                    nets.add(t.GetNetname())
            else:
                for pt in (t.GetStart(), t.GetEnd()):
                    px, py = ToMM(pt.x), ToMM(pt.y)
                    if (px - x) ** 2 + (py - y) ** 2 < radius ** 2:
                        nets.add(t.GetNetname())
        nets -= {"GND", ""}
        nets = [n for n in nets if not n.startswith("5V_") and n not in ("VBUS", "3V3")]
        del b
        shutil.copy(PCB, PCB + ".bak")
        try:
            reroute_nets(nets, riter="8")
        except Exception as e:
            print("  error", e)
            shutil.copy(PCB + ".bak", PCB)
            continue
        b = pcbnew.LoadBoard(PCB); gen_pcb.setup_board(b)
        nv, nu, txt2 = run_drc(b, os.path.join(out_dir, "drc.txt")); del b
        s2 = drc_score(txt2)
        if s2 < score:
            print(f"  spot ({x:.1f},{y:.1f}) nets {len(nets)}: {score} -> {s2} kept")
            score, txt = s2, txt2
        else:
            print(f"  spot ({x:.1f},{y:.1f}) nets {len(nets)}: {score} -> {s2} reverted")
            shutil.copy(PCB + ".bak", PCB)
        done += 1
    return score
