import pcbnew, sys
from pcbnew import ToMM
b=pcbnew.LoadBoard("../kicad/HomeDeck.kicad_pcb")
def dump(cx,cy,R=2.0):
    seen=set()
    for t in b.GetTracks():
        if t.GetClass()=="PCB_VIA":
            p=t.GetPosition()
            if abs(ToMM(p.x)-cx)<R and abs(ToMM(p.y)-cy)<R: print("  VIA",t.GetNetname(),ToMM(p.x),ToMM(p.y),ToMM(t.GetWidth()))
        else:
            s,e=t.GetStart(),t.GetEnd(); k=(t.GetLayer(),s.x,s.y,e.x,e.y)
            if k in seen: continue
            seen.add(k)
            if (abs(ToMM(s.x)-cx)<R and abs(ToMM(s.y)-cy)<R) or (abs(ToMM(e.x)-cx)<R and abs(ToMM(e.y)-cy)<R):
                print("  TRK",t.GetNetname(),b.GetLayerName(t.GetLayer()),ToMM(s.x),ToMM(s.y),ToMM(e.x),ToMM(e.y),ToMM(t.GetWidth()))
    for f in b.GetFootprints():
        for p in f.Pads():
            q=p.GetPosition()
            if abs(ToMM(q.x)-cx)<R and abs(ToMM(q.y)-cy)<R:
                print("  PAD",f.GetReference(),p.GetNumber(),p.GetNetname(),ToMM(q.x),ToMM(q.y),ToMM(p.GetSize().x),ToMM(p.GetSize().y),f.GetOrientationDegrees(),b.GetLayerName(f.GetLayer()),"THT" if p.GetAttribute()==pcbnew.PAD_ATTRIB_PTH else "SMD")
for ref,num in [a.split(".") for a in sys.argv[1:]]:
    f=b.FindFootprintByReference(ref)
    for p in f.Pads():
        if p.GetNumber()==num:
            q=p.GetPosition(); print("==",ref,num,ToMM(q.x),ToMM(q.y),b.GetLayerName(f.GetLayer()),f.GetFPIDAsString()); dump(ToMM(q.x),ToMM(q.y))
