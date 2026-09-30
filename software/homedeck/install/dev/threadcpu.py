import os, sys, time
pid = sys.argv[1]; secs = float(sys.argv[2]) if len(sys.argv) > 2 else 5
def snap():
    d = {}
    for t in os.listdir(f"/proc/{pid}/task"):
        try:
            with open(f"/proc/{pid}/task/{t}/stat") as f: s = f.read()
            with open(f"/proc/{pid}/task/{t}/comm") as f: c = f.read().strip()
            f2 = s.rsplit(")", 1)[1].split(); d[t] = (int(f2[11]) + int(f2[12]), c)
        except Exception: pass
    return d
a = snap(); time.sleep(secs); b = snap()
hz = os.sysconf("SC_CLK_TCK")
rows = sorted(((b[t][0]-a[t][0])/hz/secs*100, t, b[t][1]) for t in b if t in a)
tot = sum(r[0] for r in rows)
print(f"process total {tot:.0f}%")
for pct, t, c in rows[::-1][:6]: print(f"  tid {t} {c:16s} {pct:5.1f}%")
