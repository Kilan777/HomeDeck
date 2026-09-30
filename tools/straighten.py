"""Replace staircase chains of track segments by straight segments where the straight line is clear."""
import pcbnew, math, sys
from pcbnew import ToMM, FromMM, VECTOR2I
from shapely.geometry import Point, LineString, Polygon, box
from shapely.strtree import STRtree
import route, gen_pcb
PCB=route.PCB
CLR=0.16
def key(p): return (round(ToMM(p.x),3),round(ToMM(p.y),3))
def tkey(t): return t.m_Uuid.AsString()
def run(nets=None, maxchain=8.0):
    b=pcbnew.LoadBoard(PCB)
    import obstacles
    obs,trees=obstacles.build(b)
    # endpoint degree per (layer, point): tracks; blocked points: vias, pad centres/any pad containing the point
    tracks=[t for t in b.GetTracks() if t.GetClass()!="PCB_VIA" and t.GetLayer() in obs and (nets is None or t.GetNetname() in nets)]
    # dedupe exact duplicates
    seen=set(); uniq=[]; dupes=[]
    for t in tracks:
        k=(t.GetLayer(),t.GetNetCode(),t.GetStart().x,t.GetStart().y,t.GetEnd().x,t.GetEnd().y); k2=(t.GetLayer(),t.GetNetCode(),t.GetEnd().x,t.GetEnd().y,t.GetStart().x,t.GetStart().y)
        if k in seen or k2 in seen: dupes.append(t); continue
        seen.add(k); uniq.append(t)
    tracks=uniq
    deg={}
    for t in b.GetTracks():
        if t.GetClass()=="PCB_VIA": continue
        for p in (t.GetStart(),t.GetEnd()): deg.setdefault((t.GetLayer(),key(p)),[]).append(t)
    blocked=set()
    for t in b.GetTracks():
        if t.GetClass()=="PCB_VIA": blocked.add(key(t.GetPosition()))
    padpolys=[]
    for f in b.GetFootprints():
        for p in f.Pads():
            pp=p.GetEffectivePolygon(); padpolys.append(Polygon([(ToMM(pp.CVertex(i).x),ToMM(pp.CVertex(i).y)) for i in range(pp.VertexCount(0))]).buffer(0.05))
    padtree=STRtree(padpolys)
    def on_pad(pt):
        P=Point(pt); return any(padpolys[int(j)].contains(P) for j in padtree.query(P))
    def chain_ok(t, pt):   # interior node: degree 2 on this layer, same net, not a via, not on a pad
        if pt in blocked or on_pad(pt): return False
        ts=deg.get((t.GetLayer(),pt),[])
        return len(ts)==2 and ts[0].GetNetCode()==ts[1].GetNetCode() and ts[0].GetWidth()==ts[1].GetWidth()
    visited=set(); kill=[]; replaced=0; tried=0
    for t in tracks:
        if tkey(t) in visited: continue
        visited.add(tkey(t))
        # extend forward from t.end and backward from t.start
        def extend(track, pt, forward):
            cur=track; p=pt; out=[]
            while chain_ok(cur, p):
                cands=[x for x in deg[(cur.GetLayer(),p)] if tkey(x)!=tkey(cur)]
                if not cands: break
                nxt=cands[0]
                if tkey(nxt) in visited: break
                visited.add(tkey(nxt)); out.append(nxt)
                p=key(nxt.GetEnd()) if key(nxt.GetStart())==p else key(nxt.GetStart()); cur=nxt
            return out
        fwd=extend(t,key(t.GetEnd()),True); bwd=extend(t,key(t.GetStart()),False)
        seq=list(reversed(bwd))+[t]+fwd
        if len(seq)<2: continue
        # ordered points
        pts=[]; prev=None
        # find start point: endpoint of seq[0] not shared with seq[1]
        s0=seq[0]; s1=seq[1]
        shared={key(s0.GetStart()),key(s0.GetEnd())}&{key(s1.GetStart()),key(s1.GetEnd())}
        if len(shared)!=1: continue
        start=[k for k in (key(s0.GetStart()),key(s0.GetEnd())) if k not in shared][0]
        pts=[start]; p=start
        for s in seq:
            p=key(s.GetEnd()) if key(s.GetStart())==p else key(s.GetStart()); pts.append(p)
        layer=t.GetLayer(); net=t.GetNetname(); w=ToMM(t.GetWidth()); ids={tkey(s) for s in seq}
        # try to straighten sub-chains: greedy from i, longest j such that straight i->j is clear
        i=0; newsegs=[]
        while i<len(pts)-1:
            best=i+1
            for j in range(len(pts)-1, i+1, -1):
                if math.hypot(pts[j][0]-pts[i][0],pts[j][1]-pts[i][1])>maxchain: continue
                g=LineString([pts[i],pts[j]]).buffer(w/2)
                ok=obstacles.clear(g, layer, net, obs, trees, CLR, skip_ids=ids)
                if ok:
                    # same-net copper that touched the old sub-chain must still touch the new segment
                    old=LineString(pts[i:j+1]).buffer(w/2+0.005)
                    for k in trees[layer].query(old):
                        n,gg,tid,req=obs[layer][int(k)]
                        if n!=net or (tid is not None and tid in ids): continue
                        if gg.intersects(old) and not gg.intersects(g): ok=False; break
                if ok: best=j; break
            newsegs.append((pts[i],pts[best])); i=best
        if len(newsegs)<len(seq):
            replaced+=len(seq)-len(newsegs)
            # modify: reuse seq[k] for newsegs[k], kill the rest; update obstacles (remove old, add new)
            for k,s in enumerate(seq):
                if k<len(newsegs):
                    (x1,y1),(x2,y2)=newsegs[k]; s.SetStart(VECTOR2I(FromMM(x1),FromMM(y1))); s.SetEnd(VECTOR2I(FromMM(x2),FromMM(y2)))
                else: kill.append(s)
            # update obstacle list: mark old ids as removed by replacing geometry
            for idx,(n,g,tid,req) in enumerate(obs[layer]):
                if tid in ids: obs[layer][idx]=(n,Point(0,0).buffer(0.0001),tid,req)
            for (a,c) in newsegs: obs[layer].append((net,LineString([a,c]).buffer(w/2),-1,0.0))
            trees[layer]=STRtree([g for _,g,_,_ in obs[layer]])
    kill+=dupes
    for s in kill: b.Remove(s)
    b.Save(PCB)
    print("segments removed",len(kill),"(dupes",len(dupes),")")
if __name__=="__main__":
    nets=sys.argv[1].split(",") if len(sys.argv)>1 else None
    run(nets)
