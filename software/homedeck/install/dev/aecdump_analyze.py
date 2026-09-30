import numpy as np, os, sys
d = "/tmp/aecdump"
def load(n):
    p = f"{d}/{n}.raw"
    return np.fromfile(p, dtype=np.int16).astype(np.float64) if os.path.exists(p) else None
ref, mic, out, mic2, out2 = (load(n) for n in ("ref", "mic", "out", "mic2", "out2"))
n = min(len(x) for x in (ref, mic, out) if x is not None)
if mic2 is not None: n = min(n, len(mic2), len(out2))
sr = 16000
def db(x): return 20*np.log10(np.sqrt(np.mean(x**2))/32768+1e-12)
print(f"dump {n/sr:.1f}s  ref {db(ref[:n]):.1f} dB")
print("per second: ref | onboard in->out (erle) | usb in->out (erle)")
for i in range(int(n/sr)):
    sl = slice(i*sr, (i+1)*sr)
    r = db(ref[sl]); a, b = db(mic[sl]), db(out[sl])
    line = f"{i:2d}s ref {r:6.1f} | on {a:6.1f} -> {b:6.1f} ({a-b:4.1f} dB)"
    if mic2 is not None:
        c, e = db(mic2[sl]), db(out2[sl]); line += f" | usb {c:6.1f} -> {e:6.1f} ({c-e:4.1f} dB)"
    print(line)
# echo delay: cross-correlate the reference with each raw mic over the loud part
loud = [i for i in range(int(n/sr)) if db(ref[i*sr:(i+1)*sr]) > -55]
if loud:
    s0, s1 = loud[0]*sr, (loud[-1]+1)*sr
    r = ref[s0:s1] - ref[s0:s1].mean()
    for name, m in (("onboard", mic), ("usb", mic2)):
        if m is None: continue
        x = m[s0:s1] - m[s0:s1].mean()
        lags = np.arange(-100, 401, 1)      # ms; positive = mic lags the reference (reference leads: good)
        best = []
        for L in lags:
            k = int(L*sr/1000)
            if k >= 0: c = np.dot(r[:len(r)-k], x[k:]) if k < len(r) else 0
            else: c = np.dot(r[-k:], x[:len(x)+k])
            best.append(c/ (np.linalg.norm(r)*np.linalg.norm(x)+1e-9))
        best = np.array(best); j = int(np.argmax(np.abs(best)))
        print(f"{name}: echo peak at lag {lags[j]:+d} ms (corr {best[j]:.3f}); reference {'leads' if lags[j]>0 else 'LAGS'} the echo")
