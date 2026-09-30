"""Room sensors: SCD40 (CO2/T/RH) and BME688 (T/P/RH/gas) on I2C6, with air-quality context and nudges.

state()["metrics"] is a list of {key,label,unit,value,lo,hi,zones,status,hint,history} tiles the app renders.
Emits: "co2_high" {value} when CO2 crosses the nudge threshold upward (hysteresis 100 ppm, once per hour max),
       "co2_ok" when it recovers, "humidity_low"/"humidity_high" similarly (once per 6 h).
"""
import json, os, re, threading, time

NAME = "sensors"
DEFAULTS = {
    "i2c_bus": 6,
    "nudges": {"enabled": True, "co2_threshold": 1000, "humidity_low": 30, "humidity_high": 65, "spoken": False},
    "history_every_s": 30, "history_len": 240,
    "temp_source": "scd40",      # scd40 sits further from the CM4 than the bme688 and reads closer to the room
    "temp_offset_c": 0.0,        # calibration against a real thermometer (Settings)
    "log_every_s": 60, "log_keep_days": 30,     # long-term history on disk (air_history.jsonl) for the chart and the report
    "report_enabled": True, "report_time": "21:30",   # pushed "air today" summary (notification + on-screen)
    "report_spoken": False,                           # say it out loud too (off: it interrupts the evening)
}
SCD40, BME688 = 0x62, 0x76

_state = {"scd40": {}, "bme688": {}, "external": {}, "metrics": [], "nudge": None}
_hist = {"co2": [], "temp": [], "hum": [], "voc": [], "press": []}
_lock = threading.Lock()
ctx = None

# ----------------------------------------------------------------- context zones
def _z(key, label, unit, v, lo, hi, zones, hint):
    m = dict(key=key, label=label, unit=unit, value=v, lo=lo, hi=hi, zones=zones, hint=hint,
             status={"level": "unknown", "text": "no data"})
    if v is not None:
        for a, b, level, text in zones:
            if a <= v < b or (v >= b and b == hi) or (v < a and a == lo):
                m["status"] = {"level": level, "text": text}; break
    m["history"] = [round(x, 1) for _, x in _hist[key]]
    return m

def _room_temp(s, b):
    """Room temperature: preferred source plus the user's calibration offset."""
    cfg = ctx.config if ctx else {}
    src = cfg.get("temp_source", "scd40")
    ext = _state.get("external") or {}
    if ext.get("temp_c") is not None and src != "bme688":
        t = ext["temp_c"]                       # an external sensor away from the board always wins
    else:
        t = (s.get("temp_c") if src == "scd40" else b.get("temp_c"))
    if t is None:
        t = b.get("temp_c", s.get("temp_c"))
    return None if t is None else round(t + float(cfg.get("temp_offset_c", 0.0)), 1)


def _metrics():
    s, b = _state["scd40"], _state["bme688"]
    return [
        _z("co2", "CO₂", "ppm", s.get("co2_ppm"), 400, 2500,
           [(400, 800, "good", "Good"), (800, 1000, "warning", "Acceptable"), (1000, 1500, "serious", "Poor, ventilate"), (1500, 2500, "critical", "Bad")],
           "Outdoor air is about 420 ppm. Under 800 feels fresh; above 1000 people get drowsy and lose focus."),
        _z("temp", "Temperature", "°C", _room_temp(s, b), 10, 34,
           [(10, 18, "serious", "Cold"), (18, 20, "warning", "Cool"), (20, 24, "good", "Comfortable"), (24, 26, "warning", "Warm"), (26, 34, "serious", "Hot")],
           "Comfort range 20 to 24 °C. This sensor sits near the CM4 and can read a degree or two high."),
        _z("hum", "Humidity", "%", (_state.get("external") or {}).get("humidity_pct", b.get("humidity_pct", s.get("humidity_pct"))), 0, 100,
           [(0, 30, "serious", "Dry"), (30, 40, "warning", "Slightly dry"), (40, 60, "good", "Ideal"), (60, 70, "warning", "Humid"), (70, 100, "serious", "Very humid")],
           "40 to 60 % is ideal. Below 30 % dries eyes and skin; above 60 % mould and dust mites thrive."),
        _z("voc", "VOC level", "", b.get("voc_index"), 0, 100,
           [(0, 25, "good", "Clean"), (25, 50, "warning", "Some VOCs"), (50, 75, "serious", "Elevated"), (75, 100, "critical", "High")],
           "Relative reading from the BME688 gas sensor: 0 is the cleanest air it has seen since boot. Needs about 20 minutes of warm-up."),
        _z("press", "Pressure", "hPa", b.get("pressure_hpa"), 950, 1060,
           [(950, 980, "warning", "Low, stormy"), (980, 1040, "good", "Normal"), (1040, 1060, "warning", "High")],
           "Sea-level normal is about 1013 hPa. A fast drop usually means weather is on the way."),
    ]

def _push(key, v):
    if v is None: return
    h = _hist[key]; now = time.time()
    if not h or now - h[-1][0] >= ctx.config["history_every_s"]:
        h.append((now, v)); del h[:-ctx.config["history_len"]]

# ----------------------------------------------------------------- SCD40
def _crc8(data):
    crc = 0xFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

def _scd(bus, cmd, nread=0):
    from smbus2 import i2c_msg
    bus.i2c_rdwr(i2c_msg.write(SCD40, [cmd >> 8, cmd & 0xFF]))
    if not nread: return None
    time.sleep(0.001)
    r = i2c_msg.read(SCD40, nread); bus.i2c_rdwr(r)
    raw = list(r); out = []
    for i in range(0, len(raw), 3):
        if _crc8(raw[i:i + 2]) != raw[i + 2]: raise ValueError("SCD40 CRC")
        out.append((raw[i] << 8) | raw[i + 1])
    return out

# ----------------------------------------------------------------- BME688
def _s8(v): return v - 256 if v > 127 else v
def _s16(lo, hi):
    v = (hi << 8) | lo
    return v - 65536 if v > 32767 else v

class _BME:
    K1 = [0, 0, 0, 0, 0, -1, 0, -0.8, 0, 0, -0.2, -0.5, 0, -1, 0, 0]
    K2 = [0, 0, 0, 0, 0.1, 0.7, 0, -0.8, -0.1, 0, 0, 0, 0, 0, 0, 0]
    def __init__(self, bus):
        self.bus = bus
        bus.write_byte_data(BME688, 0xE0, 0xB6); time.sleep(0.01)
        c = {}
        for base, n in ((0x8A, 23), (0xE1, 14), (0x00, 5)):
            for i, b in enumerate(bus.read_i2c_block_data(BME688, base, n)): c[base + i] = b
        self.t1 = (c[0xEA] << 8) | c[0xE9]; self.t2 = _s16(c[0x8A], c[0x8B]); self.t3 = _s8(c[0x8C])
        self.p1 = (c[0x8F] << 8) | c[0x8E]; self.p2 = _s16(c[0x90], c[0x91]); self.p3 = _s8(c[0x92])
        self.p4 = _s16(c[0x94], c[0x95]); self.p5 = _s16(c[0x96], c[0x97]); self.p6 = _s8(c[0x99])
        self.p7 = _s8(c[0x98]); self.p8 = _s16(c[0x9C], c[0x9D]); self.p9 = _s16(c[0x9E], c[0x9F]); self.p10 = c[0xA0]
        self.h1 = (c[0xE3] << 4) | (c[0xE2] & 0x0F); self.h2 = (c[0xE1] << 4) | (c[0xE2] >> 4)
        self.h3 = _s8(c[0xE4]); self.h4 = _s8(c[0xE5]); self.h5 = _s8(c[0xE6]); self.h6 = c[0xE7]; self.h7 = _s8(c[0xE8])
        self.g1 = _s8(c[0xED]); self.g2 = _s16(c[0xEB], c[0xEC]); self.g3 = _s8(c[0xEE])
        self.res_heat_range = (c[0x02] & 0x30) >> 4; self.res_heat_val = _s8(c[0x00])
        self.range_sw_err = (c[0x04] & 0xF0) >> 4
        if self.range_sw_err > 7: self.range_sw_err -= 16
        self.chip = bus.read_byte_data(BME688, 0xD0); self.variant = bus.read_byte_data(BME688, 0xF0)
        self.amb = 25.0; self.gas_best = None
    def _heater(self, target=320):
        v1 = self.g1 / 16 + 49; v2 = (self.g2 / 32768) * 0.0005 + 0.00235; v3 = self.g3 / 1024
        v5 = v1 * (1 + v2 * target) + v3 * self.amb
        r = 3.4 * ((v5 * (4 / (4 + self.res_heat_range)) * (1 / (1 + self.res_heat_val * 0.002))) - 25)
        return max(0, min(255, int(r)))
    def read(self):
        b = self.bus
        b.write_byte_data(BME688, 0x64, self._heater()); b.write_byte_data(BME688, 0x6D, 0x65)
        b.write_byte_data(BME688, 0x70, 0x00); b.write_byte_data(BME688, 0x71, 0x20 if self.variant == 1 else 0x10)
        b.write_byte_data(BME688, 0x72, 0x01); b.write_byte_data(BME688, 0x74, (2 << 5) | (5 << 2) | 1)
        time.sleep(0.25)
        for _ in range(30):
            if b.read_byte_data(BME688, 0x1D) & 0x80: break
            time.sleep(0.02)
        d = b.read_i2c_block_data(BME688, 0x1F, 16)
        p_adc = (d[0] << 12) | (d[1] << 4) | (d[2] >> 4); t_adc = (d[3] << 12) | (d[4] << 4) | (d[5] >> 4); h_adc = (d[6] << 8) | d[7]
        v1 = (t_adc / 16384 - self.t1 / 1024) * self.t2; v2 = ((t_adc / 131072 - self.t1 / 8192) ** 2) * self.t3 * 16
        t_fine = v1 + v2; temp = t_fine / 5120; self.amb = temp
        v1 = t_fine / 2 - 64000; v2 = v1 * v1 * self.p6 / 131072; v2 = v2 + v1 * self.p5 * 2; v2 = v2 / 4 + self.p4 * 65536
        v1 = (self.p3 * v1 * v1 / 16384 + self.p2 * v1) / 524288; v1 = (1 + v1 / 32768) * self.p1
        press = 0.0
        if v1:
            press = 1048576 - p_adc; press = (press - v2 / 4096) * 6250 / v1
            v1 = self.p9 * press * press / 2147483648; v2 = press * self.p8 / 32768; v3 = (press / 256) ** 3 * self.p10 / 131072
            press = press + (v1 + v2 + v3 + self.p7 * 128) / 16
        v1 = h_adc - (self.h1 * 16 + self.h3 / 2 * temp)
        v2 = v1 * (self.h2 / 262144 * (1 + self.h4 / 16384 * temp + self.h5 / 1048576 * temp * temp))
        hum = max(0.0, min(100.0, v2 + (self.h6 / 16384 + self.h7 / 2097152 * temp) * v2 * v2))
        msb, lsb = (d[13], d[14]) if self.variant == 1 else (d[11], d[12])
        gas_adc = (msb << 2) | (lsb >> 6); gas_range = lsb & 0x0F; gas_valid = bool(lsb & 0x20)
        gas_res = None
        if gas_valid:
            if self.variant == 1:
                gas_res = (10000 * (262144 >> gas_range)) / (4096 + (gas_adc - 512) * 3) * 100
            else:
                var1 = 1340 + 5 * self.range_sw_err; var2 = var1 * (1 + self.K1[gas_range] / 100); var3 = 1 + self.K2[gas_range] / 100
                gas_res = 1 / (var3 * 0.000000125 * (1 << gas_range) * (((gas_adc - 512) / var2) + 1))
        out = {"temp_c": round(temp, 1), "pressure_hpa": round(press / 100, 1), "humidity_pct": round(hum, 1),
               "chip_id": hex(self.chip), "gas_ohm": None if gas_res is None else int(gas_res), "voc_index": None}
        if gas_res is not None:
            self.gas_best = gas_res if self.gas_best is None else max(self.gas_best, gas_res)
            out["voc_index"] = round(max(0.0, 100 * (1 - gas_res / self.gas_best)), 1)
        return out

# ----------------------------------------------------------------- optional external SHT4x / SHT3x on J12 (0x44)
SHT = 0x44
_sht_kind = None   # "sht4x" | "sht3x" | None

def _sht_crc(b):
    crc = 0xFF
    for x in b:
        crc ^= x
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

def _sht_read(bus):
    """Temperature/humidity from a Sensirion SHT40 (or SHT31) breakout on the I2C header. None when absent."""
    global _sht_kind
    from smbus2 import i2c_msg
    try:
        if _sht_kind in (None, "sht4x"):
            bus.i2c_rdwr(i2c_msg.write(SHT, [0xFD])); time.sleep(0.01)      # SHT4x high-precision measure
            r = i2c_msg.read(SHT, 6); bus.i2c_rdwr(r); d = list(r)
            if _sht_crc(d[0:2]) == d[2] and _sht_crc(d[3:5]) == d[5]:
                _sht_kind = "sht4x"
                t = -45 + 175 * ((d[0] << 8) | d[1]) / 65535; rh = -6 + 125 * ((d[3] << 8) | d[4]) / 65535
                return round(t, 2), round(max(0, min(100, rh)), 1)
        if _sht_kind in (None, "sht3x"):
            bus.i2c_rdwr(i2c_msg.write(SHT, [0x2C, 0x06])); time.sleep(0.02)  # SHT3x single shot, high repeatability
            r = i2c_msg.read(SHT, 6); bus.i2c_rdwr(r); d = list(r)
            if _sht_crc(d[0:2]) == d[2] and _sht_crc(d[3:5]) == d[5]:
                _sht_kind = "sht3x"
                t = -45 + 175 * ((d[0] << 8) | d[1]) / 65535; rh = 100 * ((d[3] << 8) | d[4]) / 65535
                return round(t, 2), round(rh, 1)
    except Exception:
        pass
    return None


# ----------------------------------------------------------------- long-term history (one sample a minute, on disk)
_samples = []            # [{"t": epoch, "co2":…, "temp":…, "hum":…, "voc":…, "press":…, "ext_temp":…, "ext_hum":…}] newest last
_samples_lock = threading.Lock()
_last_logged = 0.0
_last_trim = 0.0
_KEYS = ("co2", "temp", "hum", "voc", "press", "ext_temp", "ext_hum")
_UNITS = {"co2": "ppm", "temp": "°C", "hum": "%", "voc": "", "press": "hPa", "ext_temp": "°C", "ext_hum": "%"}

def _hist_path():
    return os.path.join(ctx.data_dir, "air_history.jsonl")

def _load_history():
    """Read the file into memory (dropping anything older than log_keep_days), rewriting it when it was trimmed."""
    global _last_trim
    keep = time.time() - float(ctx.config.get("log_keep_days", 30)) * 86400
    rows, dropped = [], 0
    try:
        with open(_hist_path()) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("t", 0) >= keep: rows.append(r)
                    else: dropped += 1
                except ValueError:
                    dropped += 1
    except FileNotFoundError:
        pass
    except Exception as e:
        ctx.log(f"history read: {e}")
    with _samples_lock:
        _samples[:] = rows
    if dropped:
        try:
            tmp = _hist_path() + ".tmp"
            with open(tmp, "w") as f:
                for r in rows: f.write(json.dumps(r, separators=(",", ":")) + "\n")
            os.replace(tmp, _hist_path())
        except Exception as e:
            ctx.log(f"history trim: {e}")
    _last_trim = time.time()

def _log_sample():
    """Append one row a minute. Room temperature is the calibrated value the tiles show."""
    global _last_logged
    now = time.time()
    if now - _last_logged < float(ctx.config.get("log_every_s", 60)): return
    s, b, ext = _state["scd40"], _state["bme688"], _state.get("external") or {}
    row = {"t": int(now), "co2": s.get("co2_ppm"), "temp": _room_temp(s, b), "hum": ext.get("humidity_pct", b.get("humidity_pct", s.get("humidity_pct"))),
           "voc": b.get("voc_index"), "press": b.get("pressure_hpa")}
    if ext.get("temp_c") is not None: row["ext_temp"] = ext["temp_c"]
    if ext.get("humidity_pct") is not None: row["ext_hum"] = ext["humidity_pct"]
    if all(row.get(k) is None for k in ("co2", "temp", "hum", "press")): return    # sensors not up yet
    _last_logged = now
    with _samples_lock:
        _samples.append(row)
    try:
        with open(_hist_path(), "a") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    except Exception as e:
        ctx.log(f"history write: {e}")
    if now - _last_trim > 86400:
        _load_history()

def _window(hours):
    since = time.time() - float(hours) * 3600
    with _samples_lock:
        return [r for r in _samples if r.get("t", 0) >= since]

def _series(rows, metric, max_points=300):
    """Downsample to at most max_points buckets (mean per bucket) and return the series with its stats."""
    pts = [(r["t"], r[metric]) for r in rows if r.get(metric) is not None]
    stats = {"min": None, "max": None, "avg": None, "max_t": None, "min_t": None, "n": len(pts)}
    if pts:
        vals = [v for _, v in pts]
        mx = max(pts, key=lambda p: p[1]); mn = min(pts, key=lambda p: p[1])
        stats.update({"min": round(mn[1], 1), "max": round(mx[1], 1), "avg": round(sum(vals) / len(vals), 1), "max_t": mx[0], "min_t": mn[0]})
    if len(pts) > max_points:
        per = len(pts) / max_points; out = []; i = 0.0
        while int(i) < len(pts):
            chunk = pts[int(i):int(i + per)] or [pts[int(i)]]
            out.append({"t": int(sum(t for t, _ in chunk) / len(chunk)), "v": round(sum(v for _, v in chunk) / len(chunk), 1)})
            i += per
        pts_out = out
    else:
        pts_out = [{"t": t, "v": round(v, 1)} for t, v in pts]
    return pts_out, stats

def _fmt_hour(t):
    lt = time.localtime(t); h = lt.tm_hour % 12 or 12
    return f"{h} {'AM' if lt.tm_hour < 12 else 'PM'}"

def _temp_out(c):
    imperial = (ctx.global_config.get("general", {}) if ctx else {}).get("units", "imperial") != "metric"
    return (round(c * 9 / 5 + 32), "°F") if imperial else (round(c), "°C")

def _summary(rows, label="Today"):
    """Two spoken sentences about a set of samples, or None when there is too little data."""
    if len(rows) < 5: return None
    _, co2 = _series(rows, "co2"); _, hum = _series(rows, "hum"); _, temp = _series(rows, "temp")
    parts = []
    if co2["n"]:
        quality = "stayed fresh" if co2["max"] < 800 else "was fine" if co2["max"] < 1000 else "got stuffy" if co2["max"] < 1500 else "got bad"
        parts.append(f"{label} the air {quality}: CO2 peaked at {int(co2['max']):,} ppm around {_fmt_hour(co2['max_t'])} and averaged {int(co2['avg']):,}.")
    second = []
    if hum["n"]: second.append(f"humidity stayed between {int(hum['min'])} and {int(hum['max'])} percent")
    if temp["n"]:
        lo, u = _temp_out(temp["min"]); hi, _ = _temp_out(temp["max"])
        second.append(f"temperature {lo} to {hi} degrees")
    if second:
        txt = " and ".join(second)
        parts.append(txt[:1].upper() + txt[1:] + ".")                  # str.capitalize() would lowercase the rest
    return " ".join(parts) if parts else None

def _today_rows():
    lt = time.localtime(); start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    with _samples_lock:
        return [r for r in _samples if r.get("t", 0) >= start]

_report_last_day = None
def _report_thread():
    """Speak and push the daily summary at report_time (local), once per day."""
    global _report_last_day
    while True:
        try:
            cfg = ctx.config
            if cfg.get("report_enabled", True):
                lt = time.localtime(); hhmm = f"{lt.tm_hour:02d}:{lt.tm_min:02d}"; day = (lt.tm_year, lt.tm_yday)
                if hhmm == str(cfg.get("report_time", "21:30")) and _report_last_day != day:
                    _report_last_day = day
                    text = _summary(_today_rows())
                    if text:
                        ctx.log(f"air report: {text}")
                        v = ctx.module("voice")
                        if cfg.get("report_spoken", False) and v and hasattr(v, "say"):
                            try: v.say(text, blocking=False)
                            except Exception as e: ctx.log(f"air report say: {e}")
                        n = ctx.module("notify")
                        if n and hasattr(n, "send"):
                            try: n.send("Air today", text, tags=["leaf"])
                            except Exception as e: ctx.log(f"air report push: {e}")
                        ctx.emit("air_report", {"text": text})
        except Exception as e:
            ctx.log(f"air report: {e}")
        time.sleep(20)

_REPORT_RE = re.compile(r"(?!.*\b(outside|outdoors?|weather|forecast|rain|wind)\b)"     # outdoor questions go to the weather/LLM
                        r"(?=.*\b(air|co2|co 2|carbon dioxide|humidity|humid|temperature|temp|voc|vocs|pressure|air quality|room)\b)"
                        r"(?=.*\b(today|been|day|so far|lately|this morning|this afternoon|this evening|overnight|last night|tonight|"
                        r"report|summary|earlier|history|trend|trending|while i was|since)\b)", re.I)

def intent(text):
    """Spoken: "air report", "how was the air today" -> the day's summary. Live readings stay with the voice module."""
    t = (text or "").lower()
    if not _REPORT_RE.search(t): return None
    rows = _today_rows()
    if len(rows) < 5:
        rows = _window(24)
        s = _summary(rows, "Over the last day")
        return s or "I've only just started keeping track; ask me again in a little while."
    return _summary(rows) or "Not enough readings yet today."

# ----------------------------------------------------------------- nudges
_nudge_last = {}
def _nudges():
    n = ctx.config["nudges"]
    if not n["enabled"]: return
    co2 = _state["scd40"].get("co2_ppm"); hum = _state["bme688"].get("humidity_pct")
    now = time.time()
    def fire(key, text, level, every_s):
        if now - _nudge_last.get(key, 0) < every_s: return
        _nudge_last[key] = now
        with _lock: _state["nudge"] = {"key": key, "text": text, "level": level, "t": now}
        ctx.emit(key, {"text": text, "level": level, "co2": co2, "humidity": hum})
        v = ctx.module("voice")
        if n.get("spoken") and v and hasattr(v, "say"):
            try: v.say(text)
            except Exception: pass
    if co2 is not None:
        if co2 >= n["co2_threshold"]:
            fire("co2_high", f"CO₂ is {co2} ppm. Crack a window for a few minutes.", "serious" if co2 < 1500 else "critical", 3600)
        elif co2 < n["co2_threshold"] - 100 and _nudge_last.get("co2_high", 0) > _nudge_last.get("co2_ok", 0):
            fire("co2_ok", f"CO₂ is back to {co2} ppm.", "good", 0)
    if hum is not None:
        if hum < n["humidity_low"]: fire("humidity_low", f"Air is dry, {hum:.0f} % humidity.", "warning", 6 * 3600)
        elif hum > n["humidity_high"]: fire("humidity_high", f"Humidity is {hum:.0f} %, consider airing the room.", "warning", 6 * 3600)

# ----------------------------------------------------------------- module API
def start(c):
    global ctx
    ctx = c
    try:
        from smbus2 import SMBus
        bus = SMBus(ctx.config["i2c_bus"])
    except Exception as e:
        with _lock: _state["scd40"] = _state["bme688"] = {"error": f"I2C: {e}"}
        return
    try:
        _scd(bus, 0x3F86); time.sleep(0.5); _scd(bus, 0x21B1)
    except Exception as e:
        with _lock: _state["scd40"] = {"error": str(e)}
    bme = None
    try: bme = _BME(bus)
    except Exception as e:
        with _lock: _state["bme688"] = {"error": str(e)}
    try: _load_history()
    except Exception as e: ctx.log(f"history load: {e}")
    threading.Thread(target=_report_thread, daemon=True, name="air-report").start()
    while True:
        try:
            if _scd(bus, 0xE4B8, 3)[0] & 0x7FF:
                co2, t, rh = _scd(bus, 0xEC05, 9)
                with _lock:
                    _state["scd40"] = {"co2_ppm": co2, "temp_c": round(-45 + 175 * t / 65535, 1), "humidity_pct": round(100 * rh / 65535, 1), "t": time.time()}
                _push("co2", co2)
        except Exception as e:
            with _lock: _state["scd40"] = {"error": str(e)}
        if bme:
            try:
                r = bme.read(); r["t"] = time.time()
                with _lock: _state["bme688"] = r
                _push("temp", r["temp_c"]); _push("hum", r["humidity_pct"]); _push("press", r["pressure_hpa"]); _push("voc", r["voc_index"])
            except Exception as e:
                with _lock: _state["bme688"] = {"error": str(e)}
        ext = _sht_read(bus)
        with _lock:
            _state["external"] = {"temp_c": ext[0], "humidity_pct": ext[1], "kind": _sht_kind} if ext else {}
        with _lock: _state["metrics"] = _metrics()
        try: _nudges()
        except Exception as e: ctx.log(f"nudge error: {e}")
        try: _log_sample()
        except Exception as e: ctx.log(f"history log: {e}")
        time.sleep(3)

def state():
    with _lock: return dict(_state)

def api(action, params):
    if action == "clear_nudge":
        with _lock: _state["nudge"] = None
        return {"ok": True}
    if action == "history":
        try: hours = max(0.25, min(24 * 31, float(params.get("hours", 24))))
        except (TypeError, ValueError): hours = 24.0
        metric = str(params.get("metric", "co2"))
        if metric not in _KEYS: return {"ok": False, "error": "unknown metric"}
        rows = _window(hours)
        pts, stats = _series(rows, metric, int(params.get("max_points", 300) or 300))
        zones = next((m for m in _state.get("metrics", []) if m["key"] == metric), None)
        return {"ok": True, "metric": metric, "hours": hours, "unit": _UNITS.get(metric, ""), "points": pts, "samples": len(rows),
                "since": int(time.time() - hours * 3600), "until": int(time.time()), **stats,
                "zones": zones["zones"] if zones else [], "lo": zones["lo"] if zones else None, "hi": zones["hi"] if zones else None}
    if action == "report":
        text = _summary(_today_rows()) or _summary(_window(24), "Over the last day")
        if text and params.get("speak"):
            v = ctx.module("voice")
            if v and hasattr(v, "say"):
                try: v.say(text, blocking=False)
                except Exception: pass
        return {"ok": bool(text), "text": text or "Not enough readings yet."}
    return {"ok": False, "error": "unknown action"}
