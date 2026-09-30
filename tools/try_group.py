import sys, shutil, pcbnew, route, gen_pcb, skew
PCB=route.PCB
nets=sys.argv[1].split(","); riter=sys.argv[2] if len(sys.argv)>2 else "6"
pairs=[p for p in skew.PAIRS if p[0] in nets or p[1] in nets]
def tot(rep): return sum(abs(rep[p][0]-rep[p][1]) for p in pairs)
before=skew.report(quiet=True); s0=tot(before)
shutil.copy(PCB, PCB+".bak")
r=route.reroute_nets(nets, riter=riter); print("reroute:", r[:4], r[4][-100:])
b=pcbnew.LoadBoard(PCB); gen_pcb.setup_board(b)
nv,nu,txt=route.run_drc(b,"../out/drc_try.txt"); del b
score=route.drc_score(txt); after=skew.report(quiet=True); s1=tot(after)
for p in pairs: print(p, f"{before[p][0]:.1f}/{before[p][1]:.1f} -> {after[p][0]:.1f}/{after[p][1]:.1f}")
print("bad:",route.drc_bad_pairs(txt)[:6])
print(f"DRC score {score} unconnected {nu}; total skew {s0:.1f} -> {s1:.1f}")
if score>0 or nu>0 or s1>=s0: shutil.copy(PCB+".bak", PCB); print("REVERTED")
else: print("KEPT")
