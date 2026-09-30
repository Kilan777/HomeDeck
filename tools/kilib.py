"""Helpers to read KiCad 7 symbol libraries and footprints."""
import os, re
import sexpdata
from sexpdata import Symbol

SYM_DIR = "/usr/share/kicad/symbols"
FP_DIR = "/usr/share/kicad/footprints"
LOCAL_SYM = os.path.join(os.path.dirname(__file__), "..", "kicad", "HomeDeck.kicad_sym")
LOCAL_FP = os.path.join(os.path.dirname(__file__), "..", "kicad", "HomeDeck.pretty")

_lib_cache = {}


def _load_lib(lib):
    if lib in _lib_cache:
        return _lib_cache[lib]
    path = LOCAL_SYM if lib == "HomeDeck" else os.path.join(SYM_DIR, lib + ".kicad_sym")
    with open(path) as f:
        data = sexpdata.loads(f.read())
    syms = {}
    for item in data[1:]:
        if isinstance(item, list) and item and item[0] == Symbol("symbol"):
            syms[item[1]] = item
    _lib_cache[lib] = syms
    return syms


def _find(node, key):
    for it in node:
        if isinstance(it, list) and it and it[0] == Symbol(key):
            return it
    return None


def _findall(node, key):
    return [it for it in node if isinstance(it, list) and it and it[0] == Symbol(key)]


def get_symbol(lib, name, _depth=0):
    """Return the raw s-expression of a symbol, with 'extends' resolved (inherit pins/graphics)."""
    syms = _load_lib(lib)
    if name not in syms:
        raise KeyError(f"{lib}:{name}")
    node = syms[name]
    ext = _find(node, "extends")
    if ext is not None:
        parent = get_symbol(lib, ext[1], _depth + 1)
        # Build child = parent with properties overridden and name replaced
        import copy
        child = copy.deepcopy(parent)
        child[1] = name
        # replace properties
        props = {p[1]: p for p in _findall(node, "property")}
        newlist = [child[0], child[1]]
        for it in child[2:]:
            if isinstance(it, list) and it and it[0] == Symbol("property"):
                if it[1] in props:
                    newlist.append(props.pop(it[1]))
                    continue
            if isinstance(it, list) and it and it[0] == Symbol("symbol"):
                # rename sub-units parent_0_1 -> name_0_1
                it = copy.deepcopy(it)
                it[1] = it[1].replace(parent[1], name, 1)
            newlist.append(it)
        for p in props.values():
            newlist.insert(2, p)
        child = newlist
        return child
    return node


class Pin:
    def __init__(self, number, name, etype, x, y, rot, length, unit):
        self.number, self.name, self.etype = number, name, etype
        self.x, self.y, self.rot, self.length, self.unit = x, y, rot, length, unit

    def __repr__(self):
        return f"Pin({self.number}:{self.name} {self.etype} @({self.x},{self.y}) r{self.rot} u{self.unit})"


def get_pins(lib, name):
    """List of Pin for a symbol (all units)."""
    node = get_symbol(lib, name)
    pins = []
    for sub in _findall(node, "symbol"):
        m = re.match(r".*_(\d+)_(\d+)$", sub[1])
        unit = int(m.group(1)) if m else 0
        for p in _findall(sub, "pin"):
            etype = str(p[1])
            at = _find(p, "at")
            length = _find(p, "length")[1]
            nm = _find(p, "name")[1]
            num = _find(p, "number")[1]
            pins.append(Pin(str(num), str(nm), etype, float(at[1]), float(at[2]), float(at[3]) if len(at) > 3 else 0.0, float(length), unit))
    return pins


def get_property(lib, name, prop):
    node = get_symbol(lib, name)
    for p in _findall(node, "property"):
        if p[1] == prop:
            return p[2]
    return None


def symbol_units(lib, name):
    node = get_symbol(lib, name)
    units = set()
    for sub in _findall(node, "symbol"):
        m = re.match(r".*_(\d+)_(\d+)$", sub[1])
        if m and int(m.group(1)) > 0:
            units.add(int(m.group(1)))
    return sorted(units) or [1]


def get_footprint_text(fpid):
    lib, name = fpid.split(":")
    if lib == "HomeDeck":
        path = os.path.join(LOCAL_FP, name + ".kicad_mod")
    else:
        path = os.path.join(FP_DIR, lib + ".pretty", name + ".kicad_mod")
    with open(path) as f:
        return f.read()


def get_footprint_pads(fpid):
    """Return list of dicts: number, x, y, w, h, shape, layers, type, drill, roundrect_rratio, primitives-free"""
    data = sexpdata.loads(get_footprint_text(fpid))
    pads = []
    for it in data:
        if isinstance(it, list) and it and it[0] == Symbol("pad"):
            num = str(it[1])
            ptype = str(it[2])
            shape = str(it[3])
            at = _find(it, "at")
            size = _find(it, "size")
            layers = [str(l) for l in _find(it, "layers")[1:]]
            drill = _find(it, "drill")
            d = None
            if drill is not None:
                vals = [v for v in drill[1:] if isinstance(v, (int, float))]
                d = vals[0] if vals else None
            pads.append(dict(number=num, type=ptype, shape=shape, x=float(at[1]), y=float(at[2]),
                             rot=float(at[3]) if len(at) > 3 else 0.0,
                             w=float(size[1]), h=float(size[2]), layers=layers, drill=d))
    return pads


if __name__ == "__main__":
    import sys
    lib, name = sys.argv[1], sys.argv[2]
    for p in get_pins(lib, name):
        print(p)
    print("units", symbol_units(lib, name), "fp", get_property(lib, name, "Footprint"))
