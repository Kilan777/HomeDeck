import pcbnew, math, sys
from pcbnew import ToMM
PAIRS=[("DSI_D0_P","DSI_D0_N"),("DSI_D1_P","DSI_D1_N"),("DSI_C_P","DSI_C_N"),("CSI_D0_P","CSI_D0_N"),("CSI_D1_P","CSI_D1_N"),("CSI_C_P","CSI_C_N"),
       ("USB_C2_P","USB_C2_N"),("USB_DSA_P","USB_DSA_N"),("USB_DS3_P","USB_DS3_N"),("USB_DS4_P","USB_DS4_N"),("USB_CM4_P","USB_CM4_N"),
       ("USB_BOOT_P","USB_BOOT_N"),("USB_HUB_UP_P","USB_HUB_UP_N"),("USB_DS1_P","USB_DS1_N")]
def lengths(b):
    L={}; V={}; seen=set()
    for t in b.GetTracks():
        n=t.GetNetname()
        if t.GetClass()=="PCB_VIA": V[n]=V.get(n,0)+1; continue
        s,e=t.GetStart(),t.GetEnd(); k=(n,t.GetLayer(),s.x,s.y,e.x,e.y)
        if k in seen: continue
        seen.add(k); L[n]=L.get(n,0)+math.hypot(ToMM(e.x)-ToMM(s.x),ToMM(e.y)-ToMM(s.y))
    return L,V
def report(path="../kicad/HomeDeck.kicad_pcb", quiet=False):
    b=pcbnew.LoadBoard(path); L,V=lengths(b); out={}
    for p,n in PAIRS:
        out[(p,n)]=(L.get(p,0),L.get(n,0),V.get(p,0),V.get(n,0))
        if not quiet: print(f"{p:13s} {L.get(p,0):6.1f} {n:13s} {L.get(n,0):6.1f}  skew {abs(L.get(p,0)-L.get(n,0)):5.1f}  vias {V.get(p,0)}/{V.get(n,0)}")
    return out
if __name__=="__main__": report(sys.argv[1] if len(sys.argv)>1 else "../kicad/HomeDeck.kicad_pcb")
