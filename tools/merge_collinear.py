"""Merge chains of collinear track segments (same net/layer/width, shared endpoint of degree 2) for the given nets."""
import pcbnew, math, sys
from pcbnew import ToMM
import skew
PCB="../kicad/HomeDeck.kicad_pcb"
def key(p): return (round(ToMM(p.x),3),round(ToMM(p.y),3))
def run(nets):
    b=pcbnew.LoadBoard(PCB)
    # degree map: endpoints of all tracks/vias/pads of the net
    tracks={n:[] for n in nets}; seen=set(); dupes=[]
    for t in b.GetTracks():
        n=t.GetNetname()
        if n not in tracks: continue
        if t.GetClass()=="PCB_VIA": tracks[n].append(("via",t)); continue
        k=(t.GetLayer(),t.GetStart().x,t.GetStart().y,t.GetEnd().x,t.GetEnd().y)
        if k in seen or (t.GetLayer(),t.GetEnd().x,t.GetEnd().y,t.GetStart().x,t.GetStart().y) in seen: dupes.append(t); continue
        seen.add(k); tracks[n].append(("trk",t))
    kill=list(dupes); merged=0
    for n,items in tracks.items():
        segs=[t for k,t in items if k=="trk"]
        deg={}
        for t in segs:
            for p in (t.GetStart(),t.GetEnd()): deg.setdefault((t.GetLayer(),key(p)),[]).append(t)
        blocked=set()
        for k,t in items:
            if k=="via": blocked.add(key(t.GetPosition()))
        for f in b.GetFootprints():
            for p in f.Pads():
                if p.GetNetname()==n: blocked.add(key(p.GetPosition()))
        removed=set()
        changed=True
        while changed:
            changed=False
            for t in segs:
                if id(t) in removed: continue
                for end in ("end","start"):
                    p=t.GetEnd() if end=="end" else t.GetStart()
                    kk=(t.GetLayer(),key(p))
                    if key(p) in blocked: continue
                    others=[o for o in deg.get(kk,[]) if o is not t and id(o) not in removed]
                    if len(others)!=1: continue
                    o=others[0]
                    if o.GetWidth()!=t.GetWidth(): continue
                    # o's far end
                    far=o.GetEnd() if key(o.GetStart())==key(p) else o.GetStart()
                    near=t.GetStart() if end=="end" else t.GetEnd()
                    v1=(p.x-near.x,p.y-near.y); v2=(far.x-p.x,far.y-p.y)
                    cross=v1[0]*v2[1]-v1[1]*v2[0]; dot=v1[0]*v2[0]+v1[1]*v2[1]
                    if dot<=0 or abs(cross)>1e-6*abs(dot)+1: continue
                    # merge: extend t to far, remove o
                    if end=="end": t.SetEnd(far)
                    else: t.SetStart(far)
                    removed.add(id(o)); kill.append(o)
                    deg[kk]=[x for x in deg[kk] if x is not o and x is not t]
                    deg.setdefault((t.GetLayer(),key(far)),[]).append(t)
                    deg[(t.GetLayer(),key(far))]=[x for x in deg[(t.GetLayer(),key(far))] if x is not o]
                    merged+=1; changed=True
    for t in kill: b.Remove(t)
    b.Save(PCB)
    print("merged",merged,"removed",len(kill))
if __name__=="__main__":
    nets=sys.argv[1].split(",") if len(sys.argv)>1 else [x for p in skew.PAIRS for x in p]
    run(nets)
