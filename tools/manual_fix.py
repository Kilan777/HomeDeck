import pcbnew, sys
from pcbnew import ToMM, FromMM, VECTOR2I
import route
PCB="../kicad/HomeDeck.kicad_pcb"
B=pcbnew.B_Cu; F=pcbnew.F_Cu
phase=sys.argv[1]
b=pcbnew.LoadBoard(PCB)
def net(n): return b.FindNet(n)
def trk(x1,y1,x2,y2,n,w,layer):
    t=pcbnew.PCB_TRACK(b); t.SetStart(VECTOR2I(FromMM(x1),FromMM(y1))); t.SetEnd(VECTOR2I(FromMM(x2),FromMM(y2))); t.SetWidth(FromMM(w)); t.SetLayer(layer); t.SetNet(net(n)); b.Add(t)
def via(x,y,n,dia=0.45,drill=0.2):
    v=pcbnew.PCB_VIA(b); v.SetPosition(VECTOR2I(FromMM(x),FromMM(y))); v.SetWidth(FromMM(dia)); v.SetDrill(FromMM(drill)); v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(F,B); v.SetNet(net(n)); b.Add(v)
def remove_segs(n, layer, bbox):
    x0,y0,x1,y1=bbox; kill=[]
    for t in b.GetTracks():
        if t.GetClass()=="PCB_VIA" or t.GetNetname()!=n or t.GetLayer()!=layer: continue
        s,e=t.GetStart(),t.GetEnd()
        if all(x0<=ToMM(p.x)<=x1 and y0<=ToMM(p.y)<=y1 for p in (s,e)): kill.append(t)
    for t in kill: b.Remove(t)
    return len(kill)
if phase=="A":
    trk(34.6,83.4,32.8,86.8,"5V_USBA",0.4,B); via(34.8625,85.5,"GND")      # U11.2
    via(72.5,27.7,"GND")                                                    # J6.13
    via(14.6,103.55,"GND")                                                  # J9.6
    via(82.4,91.5,"GND")                                                    # C61.2
    r18=b.FindFootprintByReference("R18"); r18.SetPosition(VECTOR2I(FromMM(49.65),FromMM(93.2))); r18.SetOrientationDegrees(90)
    pads={p.GetNumber():(ToMM(p.GetPosition().x),ToMM(p.GetPosition().y)) for p in r18.Pads()}
    if pads["1"][1]<pads["2"][1]:
        r18.SetOrientationDegrees(-90); pads={p.GetNumber():(ToMM(p.GetPosition().x),ToMM(p.GetPosition().y)) for p in r18.Pads()}
    print("R18 pads",pads)
    p2=pads["2"]
    trk(p2[0],p2[1],50.4,p2[1],"C2_CC1",0.2,B); trk(50.4,p2[1],50.4,95.3,"C2_CC1",0.2,B); trk(50.4,95.3,50.7,95.6,"C2_CC1",0.2,B)
    via(51.08,93.83,"GND")                                                  # U9.2
    b.Save(PCB); print("A saved")
elif phase=="B":
    print("U11 removed", remove_segs("5V_USBA", B, (32.75,84.55,35.85,86.85)))
    print("C2_CC1 removed", remove_segs("C2_CC1", B, (50.65,93.85,50.75,95.65)))
    b.Save(PCB); print("B saved")
elif phase=="C":
    route.fill_zones(b); b.Save(PCB); print("C saved")
    b=pcbnew.LoadBoard(PCB)
    n,u,txt=route.run_drc(b,"../out/drc.txt"); print(n,u,route.summarize_drc(txt))
