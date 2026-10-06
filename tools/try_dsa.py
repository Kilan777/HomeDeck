import sys, shutil, pcbnew, route, gen_pcb, pathlen
PCB=route.PCB
def m():
    b=pcbnew.LoadBoard(PCB)
    return {d: pathlen.path_length(b,"USB_DSA_P",("U8","6"),d,()) for d in [("J3","3"),("U11","1"),("U11","6")]}, pathlen.path_length(b,"USB_DSA_N",("U8","5"),("J3","2"),pathlen.LINKS)
r0,n0=m(); print("before",r0,n0)
shutil.copy(PCB,PCB+".bak")
print(route.reroute_nets(["USB_DSA_P"], riter=sys.argv[1] if len(sys.argv)>1 else "6")[:4])
b=pcbnew.LoadBoard(PCB); gen_pcb.setup_board(b); nv,nu,txt=route.run_drc(b,"../out/drc_try.txt"); del b
r1,n1=m(); print("after",r1,n1,"DRC",route.drc_score(txt),"unconn",nu)
ok = route.drc_score(txt)==0 and nu==0 and all(v is not None for v in r1.values()) and max(r1[("U11","1")],r1[("U11","6")])<r1[("J3","3")]+1.0
if not ok: shutil.copy(PCB+".bak",PCB); print("REVERTED")
else: print("KEPT")
