import sys, shutil, pcbnew, route, gen_pcb, pathlen
PCB=route.PCB
nets=sys.argv[1].split(","); riter=sys.argv[2] if len(sys.argv)>2 else "6"
def measure():
    b=pcbnew.LoadBoard(PCB); r={}
    for net,s,d in pathlen.PATHS: r[net]=pathlen.path_length(b,net,s,d,pathlen.LINKS)
    return r
def sk(r,base):
    if r[base+"_P"] is None or r[base+"_N"] is None: return 999
    return abs(r[base+"_P"]-r[base+"_N"])
base=nets[0].rsplit("_",1)[0]
r0=measure(); s0=sk(r0,base)
shutil.copy(PCB, PCB+".bak")
rr=route.reroute_nets(nets, riter=riter); print("reroute:", rr[:4], rr[4][-100:])
b=pcbnew.LoadBoard(PCB); gen_pcb.setup_board(b); nv,nu,txt=route.run_drc(b,"../out/drc_try.txt"); del b
score=route.drc_score(txt); r1=measure(); s1=sk(r1,base)
print(base, r0, r1, 'skew', s0, s1, 'DRC', score, 'unconn', nu)
if score>0 or nu>0 or s1>=s0: shutil.copy(PCB+".bak", PCB); print("REVERTED")
else: print("KEPT")
