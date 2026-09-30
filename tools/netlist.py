"""Tiny netlist model: parts with pins connected to named nets."""
import re
from collections import OrderedDict
import kilib


class Part:
    def __init__(self, ref, lib, sym, value, fp, lcsc, sheet, dnp=False, mpn="", basic=None, desc="", pcb=None):
        self.ref, self.lib, self.sym, self.value, self.fp = ref, lib, sym, value, fp
        self.lcsc, self.sheet, self.dnp, self.mpn, self.basic, self.desc = lcsc, sheet, dnp, mpn, basic, desc
        self.pins = OrderedDict()  # pin number -> net
        self.nc = set()  # explicitly unconnected pins
        self.pcb = pcb or {}  # placement hints: x, y, rot, side
        self._pininfo = None

    @property
    def pininfo(self):
        if self._pininfo is None:
            self._pininfo = kilib.get_pins(self.lib, self.sym)
        return self._pininfo

    def pin_numbers(self):
        return [p.number for p in self.pininfo]

    def pin_by_name(self, name):
        hits = [p.number for p in self.pininfo if p.name == name]
        if not hits:
            raise KeyError(f"{self.ref}: no pin named {name}")
        return hits

    def c(self, **kw):
        """connect pins: c(VIN='VBUS', GND='GND') by pin name, or p1='NET' by number via key 'p<num>'."""
        for k, v in kw.items():
            if k.startswith("p") and k[1:].isdigit():
                nums = [k[1:]]
            else:
                nums = self.pin_by_name(k)
            for n in nums:
                if n not in [p.number for p in self.pininfo]:
                    raise KeyError(f"{self.ref}: no pin {n}")
                self.pins[n] = v
        return self

    def cn(self, mapping):
        """connect by explicit pin numbers: {1:'GND', 2:'X'}"""
        valid = set(p.number for p in self.pininfo)
        for n, v in mapping.items():
            n = str(n)
            if n not in valid:
                raise KeyError(f"{self.ref}: no pin {n}")
            self.pins[n] = v
        return self

    def noconnect(self, *names):
        for nm in names:
            for n in self.pin_by_name(nm):
                self.nc.add(n)
        return self

    def nc_rest(self):
        for p in self.pininfo:
            if p.number not in self.pins:
                self.nc.add(p.number)
        return self


class Circuit:
    def __init__(self):
        self.parts = OrderedDict()
        self.counters = {}
        self.pwr_flags = []  # nets that get a PWR_FLAG
        self.sheets = OrderedDict()

    def ref(self, prefix):
        while True:
            self.counters[prefix] = self.counters.get(prefix, 0) + 1
            r = f"{prefix}{self.counters[prefix]}"
            if r not in self.parts:
                return r

    def add(self, prefix, lib, sym, value, fp=None, lcsc="", sheet="misc", dnp=False, mpn="", basic=None, desc="", ref=None, pcb=None):
        ref = ref or self.ref(prefix)
        assert ref not in self.parts, f"duplicate ref {ref}"
        fp = fp or kilib.get_property(lib, sym, "Footprint")
        p = Part(ref, lib, sym, value, fp, lcsc, sheet, dnp, mpn, basic, desc, pcb)
        self.parts[ref] = p
        self.sheets.setdefault(sheet, []).append(p)
        return p

    # ---- passives
    FP_R = {"0603": "Resistor_SMD:R_0603_1608Metric", "0805": "Resistor_SMD:R_0805_2012Metric", "1206": "Resistor_SMD:R_1206_3216Metric"}
    FP_C = {"0603": "Capacitor_SMD:C_0603_1608Metric", "0805": "Capacitor_SMD:C_0805_2012Metric", "1206": "Capacitor_SMD:C_1206_3216Metric"}

    def R(self, value, a, b, lcsc, sheet, size="0603", dnp=False, basic=True, pcb=None, ref=None):
        p = self.add("R", "Device", "R", value, self.FP_R[size], lcsc, sheet, dnp=dnp, basic=basic, pcb=pcb, ref=ref)
        p.cn({1: a, 2: b})
        return p

    def C(self, value, a, b, lcsc, sheet, size="0603", basic=True, pcb=None, ref=None, dnp=False):
        p = self.add("C", "Device", "C", value, self.FP_C[size], lcsc, sheet, basic=basic, pcb=pcb, ref=ref, dnp=dnp)
        p.cn({1: a, 2: b})
        return p

    def CP(self, value, pos, neg, lcsc, sheet, basic=True, pcb=None, ref=None):
        p = self.add("C", "Device", "C_Polarized", value, "Capacitor_SMD:CP_Elec_6.3x7.7", lcsc, sheet, basic=basic, pcb=pcb, ref=ref)
        p.cn({1: pos, 2: neg})
        return p

    def nets(self):
        nets = OrderedDict()
        for p in self.parts.values():
            for n, net in p.pins.items():
                nets.setdefault(net, []).append((p.ref, n))
        return nets

    def check(self):
        errs = []
        nets = self.nets()
        for net, conns in nets.items():
            if len(conns) < 2:
                errs.append(f"net {net} has a single connection: {conns}")
        for p in self.parts.values():
            for pin in p.pininfo:
                if pin.number not in p.pins and pin.number not in p.nc:
                    errs.append(f"{p.ref} ({p.sym}) pin {pin.number} {pin.name} unconnected and not marked NC")
                if pin.number in p.pins and pin.number in p.nc:
                    errs.append(f"{p.ref} pin {pin.number} both connected and NC")
        # power pins driven?
        drivers = {}
        for p in self.parts.values():
            for pin in p.pininfo:
                if pin.number in p.pins and pin.etype in ("power_out", "output"):
                    drivers.setdefault(p.pins[pin.number], []).append(p.ref)
        for p in self.parts.values():
            for pin in p.pininfo:
                if pin.number in p.pins and pin.etype == "power_in":
                    net = p.pins[pin.number]
                    if net not in drivers and net not in self.pwr_flags:
                        errs.append(f"power_in pin {p.ref}.{pin.number} on net {net} has no driver / PWR_FLAG")
        return errs
