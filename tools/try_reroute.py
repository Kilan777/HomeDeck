import sys, shutil, os, pcbnew, route, gen_pcb, skew
PCB=route.PCB
nets=sys.argv[1].split(","); riter=sys.argv[2] if len(sys.argv)>2 else "4"
pair=[p for p in skew.PAIRS if nets[0] in p][0]
before=skew.report(quiet=True)[pair]
shutil.copy(PCB, PCB+".bak")
r=route.reroute_nets(nets, riter=riter)
print("reroute:", r[:4], r[4][-120:])
b=pcbnew.LoadBoard(PCB); gen_pcb.setup_board(b)
nv,nu,txt=route.run_drc(b,"../out/drc_try.txt"); del b
score=route.drc_score(txt)
after=skew.report(quiet=True)[pair]
sk0=abs(before[0]-before[1]); sk1=abs(after[0]-after[1])
print(f"DRC score {score} unconnected {nu}; skew {sk0:.1f} -> {sk1:.1f}; lengths {after[0]:.1f}/{after[1]:.1f} (was {before[0]:.1f}/{before[1]:.1f})")
if score>0 or nu>0 or sk1>=sk0:
    shutil.copy(PCB+".bak", PCB); print("REVERTED")
else:
    print("KEPT")
