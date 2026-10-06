"""Shared copper/edge/hole obstacle model for the post-processing scripts."""
import pcbnew
from pcbnew import ToMM
from shapely.geometry import Point, LineString, Polygon, box
from shapely.strtree import STRtree
EDGE_CLR=0.3; HOLE_CLR=0.25
def edge_geoms(b):
    out=[]
    for d in b.GetDrawings():
        if d.GetLayer()!=pcbnew.Edge_Cuts: continue
        try:
            sh=d.GetShape()
        except Exception: continue
        if sh==pcbnew.SHAPE_T_SEGMENT:
            out.append(LineString([(ToMM(d.GetStart().x),ToMM(d.GetStart().y)),(ToMM(d.GetEnd().x),ToMM(d.GetEnd().y))]))
        elif sh==pcbnew.SHAPE_T_ARC:
            pts=[]
            n=16
            for i in range(n+1):
                p=d.GetArcMid() if i==n//2 else None
            # approximate arc by start-mid-end polyline via KiCad's own polygonisation
            ps=d.GetEffectiveShape()
            bb=d.GetBoundingBox()
            out.append(box(ToMM(bb.GetLeft()),ToMM(bb.GetTop()),ToMM(bb.GetRight()),ToMM(bb.GetBottom())).exterior)
        elif sh==pcbnew.SHAPE_T_CIRCLE:
            out.append(Point(ToMM(d.GetCenter().x),ToMM(d.GetCenter().y)).buffer(ToMM(d.GetRadius())).exterior)
        elif sh==pcbnew.SHAPE_T_RECT:
            bb=d.GetBoundingBox(); out.append(box(ToMM(bb.GetLeft()),ToMM(bb.GetTop()),ToMM(bb.GetRight()),ToMM(bb.GetBottom())).exterior)
        elif sh==pcbnew.SHAPE_T_POLY:
            ps=d.GetPolyShape().COutline(0); out.append(Polygon([(ToMM(ps.CPoint(i).x),ToMM(ps.CPoint(i).y)) for i in range(ps.PointCount())]).exterior)
    return out
def build(b, exclude_nets=(), with_id=True):
    """returns obs[layer] = list of (net, geom, id); id is a track key or None. Edge/hole entries carry net '__edge__'/'__hole__'
    with their required clearance already added to the geometry (so a plain 'distance < 0' test... no: we return raw geoms and
    a per-entry required clearance)."""
    obs={pcbnew.F_Cu:[],pcbnew.B_Cu:[]}
    def tkey(t): return t.m_Uuid.AsString()
    for t in b.GetTracks():
        n=t.GetNetname()
        if n in exclude_nets: continue
        if t.GetClass()=="PCB_VIA":
            x,y=ToMM(t.GetPosition().x),ToMM(t.GetPosition().y)
            g=Point(x,y).buffer(ToMM(t.GetWidth())/2); h=Point(x,y).buffer(ToMM(t.GetDrillValue())/2)
            for l in obs: obs[l].append((n,g,None,0.0)); obs[l].append(("__hole__",h,None,HOLE_CLR))
        elif t.GetLayer() in obs:
            obs[t.GetLayer()].append((n,LineString([(ToMM(t.GetStart().x),ToMM(t.GetStart().y)),(ToMM(t.GetEnd().x),ToMM(t.GetEnd().y))]).buffer(ToMM(t.GetWidth())/2),tkey(t),0.0))
    for f in b.GetFootprints():
        for p in f.Pads():
            n=p.GetNetname()
            pp=p.GetEffectivePolygon(); g=Polygon([(ToMM(pp.CVertex(i).x),ToMM(pp.CVertex(i).y)) for i in range(pp.VertexCount(0))])
            tht=p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH,pcbnew.PAD_ATTRIB_NPTH)
            if tht:
                ds=p.GetDrillSize(); q=p.GetPosition()
                h=Point(ToMM(q.x),ToMM(q.y)).buffer(max(ToMM(ds.x),ToMM(ds.y))/2)
                if ToMM(ds.x)!=ToMM(ds.y):   # slot: approximate by the pad polygon shrunk
                    h=g
                for l in obs:
                    obs[l].append((n if p.GetAttribute()==pcbnew.PAD_ATTRIB_PTH else "__hole__",g,None,0.0)); obs[l].append(("__hole__",h,None,HOLE_CLR))
            else:
                for l in obs:
                    if p.IsOnLayer(l) and n not in exclude_nets: obs[l].append((n,g,None,0.0))
    for e in edge_geoms(b):
        for l in obs: obs[l].append(("__edge__",e,None,EDGE_CLR))
    trees={l:STRtree([g for _,g,_,_ in v]) for l,v in obs.items()}
    return obs,trees
def clear(geom, layer, net, obs, trees, clr, skip_ids=(), extra_gnd=0.0):
    """True if geom keeps >= clr from all other-net copper on layer (plus edge/hole clearances)."""
    m=max(clr,EDGE_CLR,HOLE_CLR)+extra_gnd
    for j in trees[layer].query(geom.buffer(m)):
        n,g,tid,req=obs[layer][int(j)]
        if tid is not None and tid in skip_ids: continue
        if n==net: continue
        need=clr if req==0.0 else req
        if n=="GND" and extra_gnd: need=max(need,clr+extra_gnd)
        if g.distance(geom)<need: return False
    return True
