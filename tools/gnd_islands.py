"""Find GND copper clusters on F.Cu/B.Cu that have no via / THT connection to the GND plane."""
import pcbnew, sys
from pcbnew import ToMM
from shapely.geometry import Polygon, Point, LineString, box
from shapely.strtree import STRtree
from shapely.ops import unary_union

def analyse(b, net="GND"):
    layers={pcbnew.F_Cu:"F.Cu", pcbnew.B_Cu:"B.Cu"}
    items=[]  # (layer or None(all), geom, kind)
    for t in b.GetTracks():
        if t.GetNetname()!=net: continue
        if t.GetClass()=="PCB_VIA":
            items.append((None, Point(ToMM(t.GetPosition().x),ToMM(t.GetPosition().y)).buffer(ToMM(t.GetWidth())/2), "via"))
        elif t.GetLayer() in layers:
            items.append((t.GetLayer(), LineString([(ToMM(t.GetStart().x),ToMM(t.GetStart().y)),(ToMM(t.GetEnd().x),ToMM(t.GetEnd().y))]).buffer(ToMM(t.GetWidth())/2), "trk"))
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetname()!=net: continue
            pp=p.GetEffectivePolygon(); g=Polygon([(ToMM(pp.CVertex(i).x),ToMM(pp.CVertex(i).y)) for i in range(pp.VertexCount(0))])
            if p.GetAttribute()==pcbnew.PAD_ATTRIB_PTH: items.append((None,g,"tht"))
            else:
                for lay in layers:
                    if p.IsOnLayer(lay): items.append((lay,g,"pad:"+f.GetReference()+"."+p.GetNumber()))
    for z in b.Zones():
        if z.GetNetname()!=net or z.GetFirstLayer() not in layers: continue
        lay=z.GetFirstLayer()
        fp=pcbnew.SHAPE_POLY_SET(z.GetFilledPolysList(lay)); fp.Unfracture(pcbnew.SHAPE_POLY_SET.PM_FAST)
        for i in range(fp.OutlineCount()):
            o=fp.Outline(i); shell=[(ToMM(o.CPoint(k).x),ToMM(o.CPoint(k).y)) for k in range(o.PointCount())]
            holes=[]
            for h in range(fp.HoleCount(i)):
                ho=fp.Hole(i,h); holes.append([(ToMM(ho.CPoint(k).x),ToMM(ho.CPoint(k).y)) for k in range(ho.PointCount())])
            poly=Polygon(shell,holes)
            if not poly.is_valid: poly=poly.buffer(0)
            items.append((lay,poly,"zone"))
    n=len(items); parent=list(range(n))
    def find(a):
        while parent[a]!=a: parent[a]=parent[parent[a]]; a=parent[a]
        return a
    def union(a,c): parent[find(a)]=find(c)
    geoms=[it[1] for it in items]; tree=STRtree(geoms)
    for i,(lay,g,k) in enumerate(items):
        for j in tree.query(g):
            j=int(j)
            if j<=i: continue
            lay2=items[j][0]
            if lay is not None and lay2 is not None and lay!=lay2: continue
            if g.intersects(items[j][1]): union(i,j)
    comps={}
    for i in range(n): comps.setdefault(find(i),[]).append(i)
    bad=[]
    for root,members in comps.items():
        if any(items[m][0] is None for m in members): continue
        zones=[items[m] for m in members if items[m][2]=="zone"]
        pads=[items[m][2] for m in members if items[m][2].startswith("pad")]
        lay=items[members[0]][0]
        g=unary_union([items[m][1] for m in members])
        bad.append((layers[lay], g, pads))
    return bad, items

if __name__=="__main__":
    b=pcbnew.LoadBoard(sys.argv[1] if len(sys.argv)>1 else "../kicad/HomeDeck.kicad_pcb")
    bad,_=analyse(b)
    print(len(bad))
    for lay,g,pads in bad: print(lay,[round(v,2) for v in g.bounds],round(g.area,2),pads)
