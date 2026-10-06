"""Replace 90-degree track corners by 45-degree chamfers where the diagonal is clear."""
import pcbnew, math, sys
from pcbnew import ToMM, FromMM, VECTOR2I
from shapely.geometry import LineString, Point, Polygon
import obstacles, route
PCB=route.PCB
CLR=0.16; DMAX=0.5; DMIN=0.15
def key(p): return (round(ToMM(p.x),3),round(ToMM(p.y),3))
def tkey(t): return (t.GetLayer(),t.GetNetCode(),t.GetStart().x,t.GetStart().y,t.GetEnd().x,t.GetEnd().y)
def run():
    b=pcbnew.LoadBoard(PCB)
    obs,trees=obstacles.build(b)
    tracks=[t for t in b.GetTracks() if t.GetClass()!="PCB_VIA" and t.GetLayer() in obs]
    deg={}
    for t in tracks:
        for p in (t.GetStart(),t.GetEnd()): deg.setdefault((t.GetLayer(),key(p)),[]).append(t)
    blocked=set(key(t.GetPosition()) for t in b.GetTracks() if t.GetClass()=="PCB_VIA")
    padpolys=[]
    for f in b.GetFootprints():
        for p in f.Pads():
            pp=p.GetEffectivePolygon(); padpolys.append(Polygon([(ToMM(pp.CVertex(i).x),ToMM(pp.CVertex(i).y)) for i in range(pp.VertexCount(0))]).buffer(0.05))
    from shapely.strtree import STRtree
    padtree=STRtree(padpolys)
    def on_pad(pt):
        P=Point(pt); return any(padpolys[int(j)].contains(P) for j in padtree.query(P))
    done=0; newtracks=[]
    for (layer,pt),ts in deg.items():
        if len(ts)!=2 or pt in blocked or on_pad(pt): continue
        a,c=ts
        if a.GetNetCode()!=c.GetNetCode() or a.GetWidth()!=c.GetWidth(): continue
        net=a.GetNetname(); w=ToMM(a.GetWidth())
        # far ends
        fa=key(a.GetEnd()) if key(a.GetStart())==pt else key(a.GetStart())
        fc=key(c.GetEnd()) if key(c.GetStart())==pt else key(c.GetStart())
        va=(fa[0]-pt[0],fa[1]-pt[1]); vc=(fc[0]-pt[0],fc[1]-pt[1])
        la=math.hypot(*va); lc=math.hypot(*vc)
        if la<1e-6 or lc<1e-6: continue
        cosang=(va[0]*vc[0]+va[1]*vc[1])/(la*lc)
        if abs(cosang)>0.05: continue     # only ~90 degree corners
        d=min(DMAX, 0.45*la, 0.45*lc)
        if d<DMIN: continue
        pa=(pt[0]+va[0]/la*d, pt[1]+va[1]/la*d); pc=(pt[0]+vc[0]/lc*d, pt[1]+vc[1]/lc*d)
        g=LineString([pa,pc]).buffer(w/2)
        ids={tkey(a),tkey(c)}
        if not obstacles.clear(g, layer, net, obs, trees, CLR, skip_ids=ids): continue
        # same-net copper touching the removed corner must still touch the new geometry
        old=LineString([pa,pt,pc]).buffer(w/2+0.005); ok=True
        for k in trees[layer].query(old):
            n,gg,tid,req=obs[layer][int(k)]
            if n!=net or (tid is not None and tid in ids): continue
            if gg.intersects(old) and not gg.intersects(g): ok=False; break
        if not ok: continue
        # apply: shorten a and c, add diagonal
        if key(a.GetStart())==pt: a.SetStart(VECTOR2I(FromMM(pa[0]),FromMM(pa[1])))
        else: a.SetEnd(VECTOR2I(FromMM(pa[0]),FromMM(pa[1])))
        if key(c.GetStart())==pt: c.SetStart(VECTOR2I(FromMM(pc[0]),FromMM(pc[1])))
        else: c.SetEnd(VECTOR2I(FromMM(pc[0]),FromMM(pc[1])))
        nt=pcbnew.PCB_TRACK(b); nt.SetStart(VECTOR2I(FromMM(pa[0]),FromMM(pa[1]))); nt.SetEnd(VECTOR2I(FromMM(pc[0]),FromMM(pc[1]))); nt.SetWidth(a.GetWidth()); nt.SetLayer(layer); nt.SetNet(a.GetNet()); b.Add(nt)
        obs[layer].append((net,g,None,0.0)); done+=1
        if done%200==0: trees[layer]=STRtree([gg for _,gg,_,_ in obs[layer]])
    b.Save(PCB); print("chamfered corners:",done)
if __name__=="__main__": run()
