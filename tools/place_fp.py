import pcbnew, math
from pcbnew import ToMM, FromMM, VECTOR2I
from shapely.geometry import Point, LineString, Polygon, box
from shapely.strtree import STRtree
import freespot
def place(b, fp, target, layer, ignore_nets=(), rmax=10.0, step=0.25, rots=(0,90,180,270), ymin=None, clr=0.25):
    cu,courts=freespot.build(b, exclude=(fp.GetReference(),))
    cu[layer]=[(n,g) for n,g in cu[layer] if n not in ignore_nets]
    tree=STRtree([g for _,g in cu[layer]]); ctree=STRtree(courts[layer])
    tx,ty=target
    if (fp.GetLayer()==pcbnew.B_Cu)!=(layer==pcbnew.B_Cu): fp.Flip(fp.GetPosition(), False)
    for r in [i*step for i in range(int(rmax/step)+1)]:
        nn=max(8,int(2*math.pi*r/step)) if r>0 else 1
        for k in range(nn):
            a=2*math.pi*k/nn; x=round(tx+r*math.cos(a),2); y=round(ty+r*math.sin(a),2)
            for rot in rots:
                fp.SetPosition(VECTOR2I(FromMM(x),FromMM(y))); fp.SetOrientationDegrees(rot)
                bb=fp.GetBoundingBox(False,False); body=box(ToMM(bb.GetLeft()),ToMM(bb.GetTop()),ToMM(bb.GetRight()),ToMM(bb.GetBottom()))
                if ymin is not None and layer==pcbnew.F_Cu and body.bounds[1]<ymin: continue
                if any(courts[layer][int(j)].intersects(body.buffer(0.3)) for j in ctree.query(body.buffer(0.3))): continue
                ok=True
                for p in fp.Pads():
                    pp=p.GetEffectivePolygon(); g=Polygon([(ToMM(pp.CVertex(i).x),ToMM(pp.CVertex(i).y)) for i in range(pp.VertexCount(0))])
                    for j in tree.query(g.buffer(clr)):
                        n,gg=cu[layer][int(j)]
                        if n!=p.GetNetname() and gg.distance(g)<clr: ok=False; break
                    if not ok: break
                if ok: return (x,y,rot)
    return None
