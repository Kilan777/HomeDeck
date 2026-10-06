import pcbnew, math
from pcbnew import ToMM
from shapely.geometry import Point, LineString, Polygon, box
from shapely.strtree import STRtree
def build(b, exclude=()):
    cu={pcbnew.F_Cu:[], pcbnew.B_Cu:[]}; courts={pcbnew.F_Cu:[], pcbnew.B_Cu:[]}; tht=[]
    for t in b.GetTracks():
        if t.GetClass()=="PCB_VIA":
            g=Point(ToMM(t.GetPosition().x),ToMM(t.GetPosition().y)).buffer(ToMM(t.GetWidth())/2)
            for l in cu: cu[l].append((t.GetNetname(),g))
        elif t.GetLayer() in cu:
            cu[t.GetLayer()].append((t.GetNetname(),LineString([(ToMM(t.GetStart().x),ToMM(t.GetStart().y)),(ToMM(t.GetEnd().x),ToMM(t.GetEnd().y))]).buffer(ToMM(t.GetWidth())/2)))
    for f in b.GetFootprints():
        if f.GetReference() in exclude: continue
        bb=f.GetBoundingBox(False,False)
        poly=box(ToMM(bb.GetLeft()),ToMM(bb.GetTop()),ToMM(bb.GetRight()),ToMM(bb.GetBottom()))
        if f.GetLayer() in courts: courts[f.GetLayer()].append(poly)
        for p in f.Pads():
            pp=p.GetEffectivePolygon(); g=Polygon([(ToMM(pp.CVertex(i).x),ToMM(pp.CVertex(i).y)) for i in range(pp.VertexCount(0))])
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH,pcbnew.PAD_ATTRIB_NPTH):
                for l in cu: cu[l].append((p.GetNetname(),g)); 
                for l in courts: courts[l].append(g.buffer(0.5))
            elif f.GetLayer() in cu: cu[f.GetLayer()].append((p.GetNetname(),g))
    return cu, courts
def find(b, layer, body_w, body_h, pads, target, cu, courts, rmax=8.0, step=0.25, rots=(0,90,180,270), ymin=None, clr=0.25):
    """pads: list of (dx,dy,w,h,net) in footprint coords (rot 0). Returns (x,y,rot) nearest target."""
    tree=STRtree([g for _,g in cu[layer]]); ctree=STRtree(courts[layer])
    best=None
    tx,ty=target
    for r in [i*step for i in range(int(rmax/step)+1)]:
        nn=max(8,int(2*math.pi*r/step)) if r>0 else 1
        for k in range(nn):
            a=2*math.pi*k/nn; x=round(tx+r*math.cos(a),2); y=round(ty+r*math.sin(a),2)
            if ymin is not None and layer==pcbnew.F_Cu and y-body_h/2<ymin: continue
            for rot in rots:
                c,s=math.cos(math.radians(rot)),math.sin(math.radians(rot))
                def tr(dx,dy): return (x+dx*c-dy*s, y+dx*s+dy*c)
                bw,bh=(body_w,body_h) if rot%180==0 else (body_h,body_w)
                body=box(x-bw/2,y-bh/2,x+bw/2,y+bh/2)
                if any(courts[layer][int(j)].intersects(body.buffer(0.3)) for j in ctree.query(body.buffer(0.3))): continue
                ok=True
                for dx,dy,w,h,net in pads:
                    px,py=tr(dx,dy); pw,ph=(w,h) if rot%180==0 else (h,w)
                    pg=box(px-pw/2,py-ph/2,px+pw/2,py+ph/2)
                    for j in tree.query(pg.buffer(clr)):
                        n,g=cu[layer][int(j)]
                        if n!=net and g.distance(pg)<clr: ok=False; break
                    if not ok: break
                if not ok: continue
                # body area free of copper (any net) so the part sits flat / no shorts on bottom
                if ok: return (x,y,rot)
    return None
