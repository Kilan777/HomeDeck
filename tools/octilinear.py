"""Re-shape track chains into 0/45/90-degree geometry where clear (professional 'octilinear' look)."""
import pcbnew, math, sys
from pcbnew import ToMM, FromMM, VECTOR2I
from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree
import obstacles, route
PCB=route.PCB
CLR=0.16
def key(p): return (round(ToMM(p.x),3),round(ToMM(p.y),3))
def tkey(t): return t.m_Uuid.AsString()
def is_oct(a,c,tol=0.02):
    dx,dy=c[0]-a[0],c[1]-a[1]
    if abs(dx)<tol or abs(dy)<tol: return True
    return abs(abs(dx)-abs(dy))<tol
def candidates(a,c):
    """polylines from a to c using only 0/45/90 segments"""
    dx,dy=c[0]-a[0],c[1]-a[1]
    if is_oct(a,c): return [[a,c]]
    sx=1 if dx>0 else -1; sy=1 if dy>0 else -1; d=min(abs(dx),abs(dy))
    out=[]
    m1=(a[0]+sx*d, a[1]+sy*d); out.append([a,m1,c])          # 45 first
    m2=(c[0]-sx*d, c[1]-sy*d); out.append([a,m2,c])          # ortho first
    # 3-segment: ortho half, 45, ortho half (nicer for long runs)
    if abs(dx)>abs(dy):
        rem=(abs(dx)-d)/2; m3=(a[0]+sx*rem, a[1]); m4=(m3[0]+sx*d, a[1]+sy*d); out.append([a,m3,m4,c])
    else:
        rem=(abs(dy)-d)/2; m3=(a[0], a[1]+sy*rem); m4=(a[0]+sx*d, m3[1]+sy*d); out.append([a,m3,m4,c])
    out.append([a,(c[0],a[1]),c]); out.append([a,(a[0],c[1]),c])   # pure L fallbacks
    # round to 0.01
    return [[(round(x,3),round(y,3)) for x,y in pl] for pl in out]
def run(maxlen=25.0, nets=None):
    b=pcbnew.LoadBoard(PCB)
    obs,trees=obstacles.build(b)
    alltracks=[t for t in b.GetTracks() if t.GetClass()!="PCB_VIA" and t.GetLayer() in obs]
    tracks=[t for t in alltracks if nets is None or t.GetNetname() in nets]
    deg={}
    for t in alltracks:
        for p in (t.GetStart(),t.GetEnd()): deg.setdefault((t.GetLayer(),key(p)),[]).append(t)
    blocked=set(key(t.GetPosition()) for t in b.GetTracks() if t.GetClass()=="PCB_VIA")
    padpolys=[]
    for f in b.GetFootprints():
        for p in f.Pads():
            pp=p.GetEffectivePolygon(); padpolys.append(Polygon([(ToMM(pp.CVertex(i).x),ToMM(pp.CVertex(i).y)) for i in range(pp.VertexCount(0))]).buffer(0.05))
    padtree=STRtree(padpolys)
    def on_pad(pt):
        P=Point(pt); return any(padpolys[int(j)].contains(P) for j in padtree.query(P))
    def chain_ok(t, pt):
        if pt in blocked or on_pad(pt): return False
        ts=deg.get((t.GetLayer(),pt),[])
        return len(ts)==2 and ts[0].GetNetCode()==ts[1].GetNetCode() and ts[0].GetWidth()==ts[1].GetWidth()
    visited=set(); kill=[]; changed=0; added=[]
    for t in tracks:
        if tkey(t) in visited: continue
        visited.add(tkey(t))
        def extend(track, pt):
            cur=track; p=pt; out=[]
            while chain_ok(cur, p):
                cands=[x for x in deg[(cur.GetLayer(),p)] if tkey(x)!=tkey(cur)]
                if not cands: break
                nxt=cands[0]
                if tkey(nxt) in visited: break
                visited.add(tkey(nxt)); out.append(nxt)
                p=key(nxt.GetEnd()) if key(nxt.GetStart())==p else key(nxt.GetStart()); cur=nxt
            return out
        fwd=extend(t,key(t.GetEnd())); bwd=extend(t,key(t.GetStart()))
        seq=list(reversed(bwd))+[t]+fwd
        if len(seq)>=2:
            s0=seq[0]; s1=seq[1]
            shared={key(s0.GetStart()),key(s0.GetEnd())}&{key(s1.GetStart()),key(s1.GetEnd())}
            if len(shared)!=1: continue
            start=[k for k in (key(s0.GetStart()),key(s0.GetEnd())) if k not in shared][0]
        else:
            start=key(t.GetStart())
        pts=[start]; p=start
        for s in seq:
            p=key(s.GetEnd()) if key(s.GetStart())==p else key(s.GetStart()); pts.append(p)
        layer=t.GetLayer(); net=t.GetNetname(); w=ToMM(t.GetWidth()); ids={tkey(s) for s in seq}
        # already octilinear everywhere? skip
        if all(is_oct(pts[i],pts[i+1]) for i in range(len(pts)-1)): continue
        # greedy: from i, longest j whose octilinear candidate is clear and preserves same-net junctions
        i=0; newpts=[pts[0]]; ok_any=False
        while i<len(pts)-1:
            found=None
            for j in range(len(pts)-1, i, -1):
                if math.hypot(pts[j][0]-pts[i][0],pts[j][1]-pts[i][1])>maxlen and j>i+1: continue
                old=LineString(pts[i:j+1]).buffer(w/2+0.005)
                for pl in candidates(pts[i],pts[j]):
                    if len(pl)>2 and any(math.hypot(pl[k+1][0]-pl[k][0],pl[k+1][1]-pl[k][1])<0.15 for k in range(len(pl)-1)): continue
                    g=LineString(pl).buffer(w/2)
                    if not obstacles.clear(g, layer, net, obs, trees, CLR, skip_ids=ids): continue
                    good=True
                    for k in trees[layer].query(old):
                        n,gg,tid,req=obs[layer][int(k)]
                        if n!=net or (tid is not None and tid in ids): continue
                        if gg.intersects(old) and not gg.intersects(g): good=False; break
                    if good: found=(j,pl); break
                if found: break
            if found is None:
                # keep original segment i->i+1 as is
                newpts.append(pts[i+1]); i+=1
            else:
                j,pl=found; newpts.extend(pl[1:]); i=j; ok_any=True
        if not ok_any: continue
        # apply: reuse seq tracks for the first segments, add extra, kill the rest
        segs=[(newpts[k],newpts[k+1]) for k in range(len(newpts)-1)]
        for k,s in enumerate(seq):
            if k<len(segs):
                (x1,y1),(x2,y2)=segs[k]; s.SetStart(VECTOR2I(FromMM(x1),FromMM(y1))); s.SetEnd(VECTOR2I(FromMM(x2),FromMM(y2)))
            else: kill.append(s)
        for k in range(len(seq),len(segs)):
            (x1,y1),(x2,y2)=segs[k]
            nt=pcbnew.PCB_TRACK(b); nt.SetStart(VECTOR2I(FromMM(x1),FromMM(y1))); nt.SetEnd(VECTOR2I(FromMM(x2),FromMM(y2))); nt.SetWidth(t.GetWidth()); nt.SetLayer(layer); nt.SetNet(t.GetNet()); b.Add(nt)
        for idx,(n,g,tid,req) in enumerate(obs[layer]):
            if tid in ids: obs[layer][idx]=(n,Point(0,0).buffer(0.0001),tid,req)
        for a,c in segs: obs[layer].append((net,LineString([a,c]).buffer(w/2),-1,0.0))
        trees[layer]=STRtree([g for _,g,_,_ in obs[layer]])
        changed+=1
    for s in kill: b.Remove(s)
    b.Save(PCB); print("chains reshaped:",changed,"segments removed:",len(kill))
if __name__=="__main__":
    import sys
    run(nets=sys.argv[1].split(",") if len(sys.argv)>1 else None)
