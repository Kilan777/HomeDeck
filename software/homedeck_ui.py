#!/usr/bin/env python3
"""HomeDeck bench dashboard: camera stream, air quality with context, mic level, GPIO status.

Runs on the CM4, serves http://<pi-ip>:8080 for any phone/laptop on the LAN.
Standard library + picamera2 + smbus2 + numpy only (all in Raspberry Pi OS).
"""
import io, json, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from smbus2 import SMBus, i2c_msg

PORT = 8080
I2C_BUS = 6           # sensors on I2C6 (GPIO22/23)
SCD40 = 0x62
BME688 = 0x76
MIC_DEV = "hw:CARD=sndrpigooglevoi,DEV=0"   # by name: the card index moves depending on HDMI/DSI state
GPIO_NAMES = {27: "PD_GOOD (low = ok)", 6: "AMP_FAULT (high = ok)", 16: "Button A", 26: "Button B",
              4: "AMP_SDZ (amp enable)", 12: "User LED"}
HIST_EVERY = 30       # seconds between history samples
HIST_LEN = 240        # 2 hours

state = {"camera": {"ok": False, "error": None}, "scd40": {}, "bme688": {}, "mic": {},
         "system": {}, "gpio": {}, "metrics": [], "updated": 0}
history = {"co2": [], "temp": [], "hum": [], "voc": [], "press": []}
lock = threading.Lock()

# ----------------------------------------------------------------- air quality context
# Each metric carries its own zones so the page renders them generically.
# Levels: good / warning / serious / critical (status palette, shown with icon + word, never color alone).
def zones_co2(v):
    z = [(400, 800, "good", "Good"), (800, 1000, "warning", "Acceptable"),
         (1000, 1500, "serious", "Poor, ventilate"), (1500, 2500, "critical", "Bad")]
    return dict(key="co2", label="CO₂", unit="ppm", value=v, lo=400, hi=2500, zones=z,
                hint="Outdoor air is about 420 ppm. Under 800 feels fresh; above 1000 people get drowsy and lose focus.")

def zones_temp(v):
    z = [(10, 18, "serious", "Cold"), (18, 20, "warning", "Cool"), (20, 24, "good", "Comfortable"),
         (24, 26, "warning", "Warm"), (26, 34, "serious", "Hot")]
    return dict(key="temp", label="Temperature", unit="°C", value=v, lo=10, hi=34, zones=z,
                hint="Comfort range 20 to 24 °C. This sensor sits near the CM4 and can read a degree or two high.")

def zones_hum(v):
    z = [(0, 30, "serious", "Dry"), (30, 40, "warning", "Slightly dry"), (40, 60, "good", "Ideal"),
         (60, 70, "warning", "Humid"), (70, 100, "serious", "Very humid")]
    return dict(key="hum", label="Humidity", unit="%", value=v, lo=0, hi=100, zones=z,
                hint="40 to 60 % is ideal. Below 30 % dries eyes and skin; above 60 % mould and dust mites thrive.")

def zones_voc(v):
    z = [(0, 25, "good", "Clean"), (25, 50, "warning", "Some VOCs"), (50, 75, "serious", "Elevated"),
         (75, 100, "critical", "High")]
    return dict(key="voc", label="VOC level", unit="", value=v, lo=0, hi=100, zones=z,
                hint="Relative reading from the BME688 gas sensor: 0 is the cleanest air it has seen since boot. Needs about 20 minutes of warm-up.")

def zones_press(v):
    z = [(950, 980, "warning", "Low, stormy"), (980, 1040, "good", "Normal"), (1040, 1060, "warning", "High")]
    return dict(key="press", label="Pressure", unit="hPa", value=v, lo=950, hi=1060, zones=z,
                hint="Sea-level normal is about 1013 hPa. A fast drop usually means weather is on the way.")

def with_status(m):
    v = m["value"]
    m["status"] = {"level": "unknown", "text": "no data"}
    if v is None:
        return m
    for lo, hi, level, text in m["zones"]:
        if lo <= v < hi or (v >= hi and hi == m["hi"]) or (v < lo and lo == m["lo"]):
            m["status"] = {"level": level, "text": text}
            break
    return m

def rebuild_metrics():
    s, b = state["scd40"], state["bme688"]
    ms = [with_status(zones_co2(s.get("co2_ppm"))),
          with_status(zones_temp(b.get("temp_c", s.get("temp_c")))),
          with_status(zones_hum(b.get("humidity_pct", s.get("humidity_pct")))),
          with_status(zones_voc(b.get("voc_index"))),
          with_status(zones_press(b.get("pressure_hpa")))]
    for m in ms:
        m["history"] = [round(x, 1) for _, x in history[m["key"]]]
    state["metrics"] = ms

def push_history(key, v):
    if v is None:
        return
    h = history[key]
    now = time.time()
    if not h or now - h[-1][0] >= HIST_EVERY:
        h.append((now, v))
        del h[:-HIST_LEN]

# ----------------------------------------------------------------- camera
class StreamOut(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.cond = threading.Condition()
    def write(self, buf):
        with self.cond:
            self.frame = buf
            self.cond.notify_all()

stream = StreamOut()

def camera_thread():
    try:
        from picamera2 import Picamera2
        from picamera2.encoders import MJPEGEncoder
        from picamera2.outputs import FileOutput
        cam = Picamera2()
        cam.configure(cam.create_video_configuration(main={"size": (640, 480)}))
        cam.start_recording(MJPEGEncoder(bitrate=4_000_000), FileOutput(stream))
        with lock:
            state["camera"] = {"ok": True, "error": None, "model": cam.camera_properties.get("Model")}
        while True:  # expose exposure/lux so a black image can be told apart from a covered lens
            try:
                md = cam.capture_metadata()
                with lock:
                    state["camera"].update({"lux": round(md.get("Lux", 0), 1), "exposure_us": md.get("ExposureTime"),
                                            "gain": round(md.get("AnalogueGain", 0), 2)})
            except Exception:
                pass
            time.sleep(1)
    except Exception as e:  # camera absent, busy, etc.
        with lock:
            state["camera"] = {"ok": False, "error": str(e)}

# ----------------------------------------------------------------- sensors
def crc8(data):
    crc = 0xFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc

def scd40_cmd(bus, cmd, nread=0, delay=0.001):
    bus.i2c_rdwr(i2c_msg.write(SCD40, [cmd >> 8, cmd & 0xFF]))
    if not nread:
        return None
    time.sleep(delay)
    r = i2c_msg.read(SCD40, nread)
    bus.i2c_rdwr(r)
    return list(r)

def scd40_words(raw):
    out = []
    for i in range(0, len(raw), 3):
        if crc8(raw[i:i + 2]) != raw[i + 2]:
            raise ValueError("SCD40 CRC")
        out.append((raw[i] << 8) | raw[i + 1])
    return out

def s8(v): return v - 256 if v > 127 else v
def s16(lo, hi):
    v = (hi << 8) | lo
    return v - 65536 if v > 32767 else v

class BME:
    """BME680/BME688 T/P/RH + gas resistance in forced mode, float compensation from Bosch bme68x."""
    K1 = [0, 0, 0, 0, 0, -1, 0, -0.8, 0, 0, -0.2, -0.5, 0, -1, 0, 0]
    K2 = [0, 0, 0, 0, 0.1, 0.7, 0, -0.8, -0.1, 0, 0, 0, 0, 0, 0, 0]

    def __init__(self, bus):
        self.bus = bus
        bus.write_byte_data(BME688, 0xE0, 0xB6); time.sleep(0.01)   # soft reset
        c = {}
        for base, n in ((0x8A, 23), (0xE1, 14), (0x00, 5)):
            for i, b in enumerate(bus.read_i2c_block_data(BME688, base, n)):
                c[base + i] = b
        self.t1 = (c[0xEA] << 8) | c[0xE9]; self.t2 = s16(c[0x8A], c[0x8B]); self.t3 = s8(c[0x8C])
        self.p1 = (c[0x8F] << 8) | c[0x8E]; self.p2 = s16(c[0x90], c[0x91]); self.p3 = s8(c[0x92])
        self.p4 = s16(c[0x94], c[0x95]); self.p5 = s16(c[0x96], c[0x97]); self.p6 = s8(c[0x99])
        self.p7 = s8(c[0x98]); self.p8 = s16(c[0x9C], c[0x9D]); self.p9 = s16(c[0x9E], c[0x9F]); self.p10 = c[0xA0]
        self.h1 = (c[0xE3] << 4) | (c[0xE2] & 0x0F); self.h2 = (c[0xE1] << 4) | (c[0xE2] >> 4)
        self.h3 = s8(c[0xE4]); self.h4 = s8(c[0xE5]); self.h5 = s8(c[0xE6]); self.h6 = c[0xE7]; self.h7 = s8(c[0xE8])
        self.g1 = s8(c[0xED]); self.g2 = s16(c[0xEB], c[0xEC]); self.g3 = s8(c[0xEE])
        self.res_heat_range = (c[0x02] & 0x30) >> 4
        self.res_heat_val = s8(c[0x00])
        self.range_sw_err = (c[0x04] & 0xF0) >> 4
        if self.range_sw_err > 7: self.range_sw_err -= 16
        self.chip = bus.read_byte_data(BME688, 0xD0)
        self.variant = bus.read_byte_data(BME688, 0xF0)    # 0x01 = BME688 (gas "high" variant)
        self.amb = 25.0
        self.gas_best = None                                # cleanest-air baseline (highest resistance seen)

    def heater_reg(self, target=320):
        v1 = self.g1 / 16 + 49
        v2 = (self.g2 / 32768) * 0.0005 + 0.00235
        v3 = self.g3 / 1024
        v4 = v1 * (1 + v2 * target)
        v5 = v4 + v3 * self.amb
        r = 3.4 * ((v5 * (4 / (4 + self.res_heat_range)) * (1 / (1 + self.res_heat_val * 0.002))) - 25)
        return max(0, min(255, int(r)))

    def read(self):
        b = self.bus
        b.write_byte_data(BME688, 0x64, self.heater_reg())     # res_heat_0
        b.write_byte_data(BME688, 0x6D, 0x65)                   # gas_wait_0 = 37 x 4 ms = 148 ms
        b.write_byte_data(BME688, 0x70, 0x00)                   # heater on
        b.write_byte_data(BME688, 0x71, 0x20 if self.variant == 1 else 0x10)  # run_gas, profile 0
        b.write_byte_data(BME688, 0x72, 0x01)                   # humidity x1
        b.write_byte_data(BME688, 0x74, (2 << 5) | (5 << 2) | 1)  # T x2, P x16, forced
        time.sleep(0.25)
        for _ in range(30):
            if b.read_byte_data(BME688, 0x1D) & 0x80:            # new_data
                break
            time.sleep(0.02)
        d = b.read_i2c_block_data(BME688, 0x1F, 16)             # 0x1F..0x2E
        p_adc = (d[0] << 12) | (d[1] << 4) | (d[2] >> 4)
        t_adc = (d[3] << 12) | (d[4] << 4) | (d[5] >> 4)
        h_adc = (d[6] << 8) | d[7]
        v1 = (t_adc / 16384 - self.t1 / 1024) * self.t2
        v2 = ((t_adc / 131072 - self.t1 / 8192) ** 2) * self.t3 * 16
        t_fine = v1 + v2
        temp = t_fine / 5120
        self.amb = temp
        v1 = t_fine / 2 - 64000
        v2 = v1 * v1 * self.p6 / 131072
        v2 = v2 + v1 * self.p5 * 2
        v2 = v2 / 4 + self.p4 * 65536
        v1 = (self.p3 * v1 * v1 / 16384 + self.p2 * v1) / 524288
        v1 = (1 + v1 / 32768) * self.p1
        press = 0.0
        if v1:
            press = 1048576 - p_adc
            press = (press - v2 / 4096) * 6250 / v1
            v1 = self.p9 * press * press / 2147483648
            v2 = press * self.p8 / 32768
            v3 = (press / 256) ** 3 * self.p10 / 131072
            press = press + (v1 + v2 + v3 + self.p7 * 128) / 16
        v1 = h_adc - (self.h1 * 16 + self.h3 / 2 * temp)
        v2 = v1 * (self.h2 / 262144 * (1 + self.h4 / 16384 * temp + self.h5 / 1048576 * temp * temp))
        v3 = self.h6 / 16384; v4 = self.h7 / 2097152
        hum = max(0.0, min(100.0, v2 + (v3 + v4 * temp) * v2 * v2))
        # gas
        if self.variant == 1:
            msb, lsb = d[13], d[14]          # 0x2C, 0x2D
        else:
            msb, lsb = d[11], d[12]          # 0x2A, 0x2B
        gas_adc = (msb << 2) | (lsb >> 6)
        gas_range = lsb & 0x0F
        gas_valid = bool(lsb & 0x20); heat_stab = bool(lsb & 0x10)
        gas_res = None
        if gas_valid:
            if self.variant == 1:
                var1 = 262144 >> gas_range
                var2 = 4096 + (gas_adc - 512) * 3
                gas_res = (10000 * var1) / var2 * 100
            else:
                var1 = 1340 + 5 * self.range_sw_err
                var2 = var1 * (1 + self.K1[gas_range] / 100)
                var3 = 1 + self.K2[gas_range] / 100
                gas_res = 1 / (var3 * 0.000000125 * (1 << gas_range) * (((gas_adc - 512) / var2) + 1))
        out = {"temp_c": round(temp, 1), "pressure_hpa": round(press / 100, 1), "humidity_pct": round(hum, 1),
               "chip_id": hex(self.chip), "gas_ohm": None if gas_res is None else int(gas_res),
               "heater_stable": heat_stab, "voc_index": None}
        if gas_res is not None:   # heat_stab flag is advisory; gas_valid is what matters
            self.gas_best = gas_res if self.gas_best is None else max(self.gas_best, gas_res)
            out["voc_index"] = round(max(0.0, 100 * (1 - gas_res / self.gas_best)), 1)
        return out

def sensor_thread():
    try:
        bus = SMBus(I2C_BUS)
    except Exception as e:
        with lock:
            state["scd40"] = state["bme688"] = {"error": f"I2C bus {I2C_BUS}: {e}"}
        return
    bme = None
    try:
        scd40_cmd(bus, 0x3F86); time.sleep(0.5)          # stop periodic if running
        scd40_cmd(bus, 0x21B1)                            # start periodic (5 s interval)
    except Exception as e:
        with lock: state["scd40"] = {"error": str(e)}
    try:
        bme = BME(bus)
    except Exception as e:
        with lock: state["bme688"] = {"error": str(e)}
    while True:
        try:
            rdy = scd40_words(scd40_cmd(bus, 0xE4B8, 3))[0] & 0x7FF
            if rdy:
                co2, t, rh = scd40_words(scd40_cmd(bus, 0xEC05, 9))
                with lock:
                    state["scd40"] = {"co2_ppm": co2, "temp_c": round(-45 + 175 * t / 65535, 1),
                                      "humidity_pct": round(100 * rh / 65535, 1), "t": time.time()}
                push_history("co2", co2)
        except Exception as e:
            with lock: state["scd40"] = {"error": str(e)}
        if bme:
            try:
                r = bme.read(); r["t"] = time.time()
                with lock: state["bme688"] = r
                push_history("temp", r["temp_c"]); push_history("hum", r["humidity_pct"])
                push_history("press", r["pressure_hpa"]); push_history("voc", r["voc_index"])
            except Exception as e:
                with lock: state["bme688"] = {"error": str(e)}
        with lock:
            rebuild_metrics()
        time.sleep(3)

# ----------------------------------------------------------------- mic
def mic_thread():
    hist_l, hist_r = [], []
    while True:
        try:
            p = subprocess.Popen(["arecord", "-q", "-D", MIC_DEV, "-f", "S32_LE", "-r", "48000", "-c", "2", "-t", "raw"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            n = 4800 * 2 * 4  # 0.1 s of stereo S32
            while True:
                buf = p.stdout.read(n)
                if len(buf) < n:
                    break
                a = np.frombuffer(buf, dtype=np.int32).astype(np.float64) / 2**31
                l, r = a[0::2], a[1::2]
                rms_l = float(np.sqrt(np.mean(l * l))); rms_r = float(np.sqrt(np.mean(r * r)))
                db = lambda x: round(20 * np.log10(max(x, 1e-7)), 1)
                hist_l.append(db(rms_l)); hist_r.append(db(rms_r))
                hist_l, hist_r = hist_l[-100:], hist_r[-100:]
                with lock:
                    state["mic"] = {"db_l": db(rms_l), "db_r": db(rms_r),
                                    "peak_l": round(float(np.max(np.abs(l))), 4), "peak_r": round(float(np.max(np.abs(r))), 4),
                                    "hist_l": hist_l, "hist_r": hist_r}
            p.kill()
            with lock: state["mic"] = {"error": "arecord stopped"}
        except Exception as e:
            with lock: state["mic"] = {"error": str(e)}
        time.sleep(3)

# ----------------------------------------------------------------- system / gpio
def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception as e:
        return f"err: {e}"

def system_thread():
    while True:
        s = {}
        s["CM4 temperature"] = sh(["vcgencmd", "measure_temp"]).replace("temp=", "").replace("'C", " °C")
        thr = sh(["vcgencmd", "get_throttled"]).replace("throttled=", "")
        try:
            v = int(thr, 16)
            flags = []
            if v & 0x1: flags.append("under-voltage NOW")
            if v & 0x4: flags.append("throttled now")
            if v & 0x10000: flags.append("under-voltage occurred")
            if v & 0x40000: flags.append("throttling occurred")
            s["Power flags"] = ", ".join(flags) if flags else "ok"
        except ValueError:
            s["Power flags"] = thr
        s["Uptime"] = sh(["uptime", "-p"]).replace("up ", "")
        try:
            with open("/proc/net/wireless") as f:
                for line in f:
                    if "wlan0" in line:
                        s["Wi-Fi signal"] = line.split()[3].rstrip(".") + " dBm"
        except Exception:
            pass
        ip = sh(["hostname", "-I"])
        s["IP address"] = ip.split()[0] if ip else "?"
        g = {}
        for pin, name in GPIO_NAMES.items():
            out = sh(["pinctrl", "get", str(pin)])
            g[name] = "low" if "| lo" in out else ("high" if "| hi" in out else out)
        try:
            with open("/sys/class/backlight/panel_backlight@1/actual_brightness") as f:
                s["Backlight"] = f.read().strip() + " / 31"
        except Exception:
            s["Backlight"] = "no panel detected"
        with lock:
            state["system"] = s; state["gpio"] = g; state["updated"] = time.time()
        time.sleep(2)

# ----------------------------------------------------------------- page
PAGE = r"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>HomeDeck Bench</title>
<style>
:root{--bg:#f3f4f6;--card:#ffffff;--fg:#17191d;--fg2:#4b5563;--muted:#8a919c;--line:rgba(120,120,130,.18);
 --good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b;--unknown:#9aa0aa;--accent:#2f6fed;--mic2:#e2a326}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121316;--card:#1b1d22;--fg:#ececf0;--fg2:#b7bcc6;--muted:#858c98;--line:rgba(160,160,170,.16);--accent:#6f9bff}}
:root[data-theme="dark"]{--bg:#121316;--card:#1b1d22;--fg:#ececf0;--fg2:#b7bcc6;--muted:#858c98;--line:rgba(160,160,170,.16);--accent:#6f9bff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;padding:14px 16px 32px}
header{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:12px}
h1{font-size:19px;margin:0;font-weight:650}.stamp{color:var(--muted);font-size:12.5px}
h2{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 8px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(290px,1fr))}
.card{background:var(--card);border-radius:12px;padding:14px 16px;box-shadow:0 1px 2px rgba(0,0,0,.08),0 0 0 1px var(--line)}
.hero{grid-column:1/-1}
.val{font-weight:600;line-height:1;letter-spacing:-.01em}
.hero .val{font-size:56px}.tile .val{font-size:30px}
.unit{font-size:.45em;font-weight:500;color:var(--fg2);margin-left:4px}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:var(--fg);padding:3px 10px 3px 8px;border-radius:999px;background:var(--bg)}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block}
.dot.good{background:var(--good)}.dot.warning{background:var(--warning)}.dot.serious{background:var(--serious)}.dot.critical{background:var(--critical)}.dot.unknown{background:var(--unknown)}
.top{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}
.meter{position:relative;height:38px;margin:14px 0 4px}
.track{position:absolute;left:0;right:0;top:12px;height:10px;display:flex;gap:2px}
.seg{height:100%;border-radius:3px;opacity:.85}
.seg.good{background:var(--good)}.seg.warning{background:var(--warning)}.seg.serious{background:var(--serious)}.seg.critical{background:var(--critical)}
.mark{position:absolute;top:6px;width:3px;height:22px;background:var(--fg);border-radius:2px;transform:translateX(-50%);box-shadow:0 0 0 2px var(--card)}
.ticks{position:relative;height:16px;font-size:11px;color:var(--muted)}
.ticks span{position:absolute;transform:translateX(-50%);white-space:nowrap}
.hint{font-size:12.5px;color:var(--fg2);margin-top:8px}
.spark{width:100%;height:44px;display:block;margin-top:6px}
.rows .row{display:flex;justify-content:space-between;gap:12px;padding:5px 0;border-bottom:1px solid var(--line);font-size:14px}
.rows .row:last-child{border:0}.rows .k{color:var(--fg2)}.rows .v{font-variant-numeric:tabular-nums;text-align:right}
.bad{color:var(--critical);font-weight:600}.okt{color:var(--good);font-weight:600}
img.cam{width:100%;border-radius:8px;background:#000;display:block;aspect-ratio:4/3;object-fit:cover}
button{font:inherit;font-size:14px;padding:8px 14px;border-radius:9px;border:1px solid var(--line);background:var(--bg);color:var(--fg);margin:6px 6px 0 0}
canvas{width:100%;height:70px;display:block}
.legend{font-size:12px;color:var(--muted);display:flex;gap:14px;margin-top:4px;flex-wrap:wrap}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
</style></head><body>
<header><h1>HomeDeck bench</h1><span class=stamp id=upd></span></header>
<div class=grid>
 <div class="card hero" id=hero></div>
 <div id=tiles style="grid-column:1/-1"></div>
 <div class=card><h2>Camera</h2><img class=cam id=cam src="/stream" alt="camera stream"><div class=hint id=camstat></div></div>
 <div class=card><h2>Room noise, both mics</h2><canvas id=micc width=640 height=140></canvas>
  <div class=legend><span><i style="background:var(--accent)"></i>Left mic</span><span><i style="background:var(--mic2)"></i>Right mic</span><span>−60 dB quiet · −20 dB loud</span></div><div class=hint id=mic></div></div>
 <div class=card><h2>System</h2><div class=rows id=sys></div></div>
 <div class=card><h2>Board I/O</h2><div class=rows id=gpio></div>
  <div><button onclick="act('led_on')">User LED on</button><button onclick="act('led_off')">User LED off</button><button onclick="act('bl_up')">Backlight +</button><button onclick="act('bl_down')">Backlight −</button></div></div>
</div>
<script>
const $=id=>document.getElementById(id);
const fmt=(v,d)=>v==null?'–':Number(v).toFixed(d);
function meter(m){
 const span=m.hi-m.lo, pct=v=>Math.max(0,Math.min(100,(v-m.lo)/span*100));
 const segs=m.zones.map(([a,b,l,t])=>`<div class="seg ${l}" style="flex:${b-a} ${b-a} 0" title="${t}: ${a}–${b}"></div>`).join('');
 const mark=m.value==null?'':`<div class=mark style="left:${pct(m.value)}%"></div>`;
 const edges=[...new Set(m.zones.flatMap(([a,b])=>[a,b]))].filter(e=>e>m.lo&&e<m.hi);
 const ticks=edges.map(e=>`<span style="left:${pct(e)}%">${e}</span>`).join('');
 return `<div class=meter><div class=track>${segs}</div>${mark}</div><div class=ticks>${ticks}</div>`;
}
function spark(h,color){
 if(!h||h.length<2)return '';
 const w=300,ht=44,min=Math.min(...h),max=Math.max(...h),r=(max-min)||1;
 const pts=h.map((v,i)=>`${(i/(h.length-1)*w).toFixed(1)},${(ht-4-(v-min)/r*(ht-8)).toFixed(1)}`).join(' ');
 return `<svg class=spark viewBox="0 0 ${w} ${ht}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg><div class=hint style="margin-top:0">Last ${Math.max(1,Math.round(h.length*30/60))} min · low ${fmt(min,1)} · high ${fmt(max,1)}</div>`;
}
function chip(s){return `<span class=chip><span class="dot ${s.level}"></span>${s.text}</span>`}
function tile(m){
 const d=m.key=='co2'?0:1;
 return `<div class="top"><div><h2>${m.label}</h2><div class=val>${fmt(m.value,d)}<span class=unit>${m.unit}</span></div></div>${chip(m.status)}</div>${meter(m)}${spark(m.history,'var(--accent)')}<div class=hint>${m.hint}</div>`;
}
function rows(o,fmtv){if(!o||!Object.keys(o).length)return '<div class=hint>no data</div>';if(o.error)return `<div class=bad>${o.error}</div>`;
 return Object.entries(o).map(([k,v])=>`<div class=row><span class=k>${k}</span><span class=v>${fmtv?fmtv(k,v):v}</span></div>`).join('')}
function drawMic(h1,h2){const c=$('micc'),x=c.getContext('2d');x.clearRect(0,0,c.width,c.height);if(!h1||!h1.length)return;
 const n=100,w=c.width/n,lo=-70,hi=-10,y=v=>c.height-(Math.max(lo,Math.min(hi,v))-lo)/(hi-lo)*c.height;
 x.strokeStyle='rgba(128,128,140,.25)';x.lineWidth=1;[-60,-40,-20].forEach(g=>{x.beginPath();x.moveTo(0,y(g));x.lineTo(c.width,y(g));x.stroke()});
 const css=getComputedStyle(document.documentElement);
 const bars=(h,col,off)=>{x.fillStyle=col;h.forEach((v,i)=>{const yy=y(v);x.fillRect((n-h.length+i)*w+off,yy,w*0.42,c.height-yy)})};
 bars(h1,css.getPropertyValue('--accent').trim(),0);bars(h2,css.getPropertyValue('--mic2').trim(),w*0.5)}
async function tick(){try{const s=await (await fetch('/api/state')).json();
 $('upd').textContent='updated '+new Date(s.updated*1000).toLocaleTimeString();
 const ms=s.metrics||[];const hero=ms.find(m=>m.key=='co2');
 $('hero').innerHTML=hero?tile(hero):'<h2>CO₂</h2><div class=hint>waiting for the SCD40…</div>';
 $('tiles').innerHTML='<div class=grid style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr))">'+ms.filter(m=>m.key!='co2').map(m=>`<div class="card tile">${tile(m)}</div>`).join('')+'</div>';
 const c=s.camera;$('camstat').innerHTML=c.ok?`<span class=okt>live</span> · ${c.model||''} · ${c.lux!=null?c.lux+' lux':''}${c.lux!=null&&c.lux<10?' · <b>dark: lens covered or facing down?</b>':''}`:`<span class=bad>no camera:</span> ${c.error}`;
 const m=s.mic;$('mic').innerHTML=m.error?`<span class=bad>${m.error}</span>`:`Now: left ${m.db_l} dB, right ${m.db_r} dB`;drawMic(m.hist_l,m.hist_r);
 $('sys').innerHTML=rows(s.system,(k,v)=>k=='Power flags'&&v!='ok'?`<span class=bad>${v}</span>`:v);
 $('gpio').innerHTML=rows(s.gpio);}catch(e){$('upd').textContent='offline'}}
async function act(a){await fetch('/api/action/'+a,{method:'POST'});tick()}
tick();setInterval(tick,2000);
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, ctype, body):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store"); self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", PAGE.encode())
        elif self.path == "/api/state":
            with lock: body = json.dumps(state).encode()
            self._send(200, "application/json", body)
        elif self.path == "/snapshot.jpg":
            with stream.cond:
                stream.cond.wait(2); f = stream.frame
            self._send(200, "image/jpeg", f) if f else self._send(503, "text/plain", b"no camera")
        elif self.path == "/stream":
            self.send_response(200); self.send_header("Age", "0"); self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME"); self.end_headers()
            try:
                while True:
                    with stream.cond:
                        stream.cond.wait(2); f = stream.frame
                    if f is None: continue
                    self.wfile.write(b"--FRAME\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(f))
                    self.wfile.write(f); self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self._send(404, "text/plain", b"not found")
    def do_POST(self):
        a = self.path.rsplit("/", 1)[-1]
        if a == "led_on": sh(["pinctrl", "set", "12", "op", "dh"])
        elif a == "led_off": sh(["pinctrl", "set", "12", "op", "dl"])
        elif a in ("bl_up", "bl_down"):
            p = "/sys/class/backlight/panel_backlight@1/brightness"
            try:
                v = int(open(p).read()); v = min(31, v + 5) if a == "bl_up" else max(1, v - 5)
                open(p, "w").write(str(v))
            except Exception: pass
        self._send(200, "text/plain", b"ok")

if __name__ == "__main__":
    for t in (camera_thread, sensor_thread, mic_thread, system_thread):
        threading.Thread(target=t, daemon=True).start()
    print(f"HomeDeck UI on port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
