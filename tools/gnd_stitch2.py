"""Second pass: pad -> short track -> via for GND clusters with no room for a via inside."""
import pcbnew, math
from pcbnew import ToMM, FromMM, VECTOR2I
from shapely.geometry import Polygon, Point, LineString
from shapely.strtree import STRtree
import gnd_islands, route

PCB="../kicad/HomeDeck.kicad_pcb"
b=pcbnew.LoadBoard(PCB)
bad,_=gnd_islands.analyse(b)
print("clusters",len(bad))
L={"F.Cu":pcbnew.F_Cu,"B.Cu":pcbnew.B_Cu}
allobs=[]; layobs={pcbnew.F_Cu:[],pcbnew.B_Cu:[]}
for t in b.GetTracks():
    if t.GetClass()=="PCB_VIA":
        g=Point(ToMM(t.GetPosition().x),ToMM(t.GetPosition().y)).buffer(ToMM(t.GetWidth())/2)
        allobs.append(g.buffer(0.15))
        if t.GetNetname()!="GND":
            for l in layobs: layobs[l].append(g)
    else:
        g=LineString([(ToMM(t.GetStart().x),ToMM(t.GetStart().y)),(ToMM(t.GetEnd().x),ToMM(t.GetEnd().y))]).buffer(ToMM(t.GetWidth())/2)
        if t.GetNetname()!="GND":
            allobs.append(g)
            if t.GetLayer() in layobs: layobs[t.GetLayer()].append(g)
padgeom={}
for f in b.GetFootprints():
    for p in f.Pads():
        s=p.GetSize(); q=p.GetPosition()
        # rotated rectangle approx: use polygon from pad shape
        poly=p.GetEffectivePolygon()
        pts=[(ToMM(poly.CVertex(i).x),ToMM(poly.CVertex(i).y)) for i in range(poly.VertexCount(0))]
        g=Polygon(pts) if len(pts)>=3 else Point(ToMM(q.x),ToMM(q.y)).buffer(0.4)
        padgeom[(f.GetReference(),p.GetNumber())]=(g,f.GetLayer())
        tht=p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH,pcbnew.PAD_ATTRIB_NPTH)
        if tht:
            allobs.append(g.buffer(0.3))
            if p.GetNetname()!="GND":
                for l in layobs: layobs[l].append(g)
        else:
            allobs.append(g)   # no via in any pad
            if p.GetNetname()!="GND" and f.GetLayer() in layobs: layobs[f.GetLayer()].append(g)

# board edge: keep vias/tracks 0.5 mm away
from shapely.geometry import box
bb=b.GetBoardEdgesBoundingBox()
edge=box(ToMM(bb.GetLeft()),ToMM(bb.GetTop()),ToMM(bb.GetRight()),ToMM(bb.GetBottom())).exterior.buffer(0.35)
allobs.append(edge)
for l in layobs: layobs[l].append(edge)
ta=STRtree(allobs); tl={l:STRtree(v) for l,v in layobs.items()}
def clear(g, tree, geoms, margin):
    for j in tree.query(g.buffer(margin)):
        if geoms[int(j)].distance(g)<margin: return False
    return True
gnd=b.FindNet("GND")
for layname,g,pads in bad:
    lay=L[layname]
    ref,num=pads[0].split(":")[1].split(".")
    pg,_=padgeom[(ref,num)]
    c=pg.centroid; cx,cy=c.x,c.y
    best=None
    for R in [x*0.1 for x in range(5,45)]:
        for k in range(36):
            a=2*math.pi*k/36; x=round(cx+R*math.cos(a),1); y=round(cy+R*math.sin(a),1)
            for dia,drill in ((0.6,0.3),(0.45,0.2)):
                v=Point(x,y).buffer(dia/2)
                if not clear(v, ta, allobs, 0.16): continue
                trk=LineString([(cx,cy),(x,y)]).buffer(0.1)
                if not clear(trk, tl[lay], layobs[lay], 0.16): continue
                best=(x,y,dia,drill); break
            if best: break
        if best: break
    if not best: print("STILL NO SPOT",layname,pads); continue
    x,y,dia,drill=best
    t=pcbnew.PCB_TRACK(b); t.SetStart(VECTOR2I(FromMM(cx),FromMM(cy))); t.SetEnd(VECTOR2I(FromMM(x),FromMM(y))); t.SetWidth(FromMM(0.2)); t.SetLayer(lay); t.SetNet(gnd); b.Add(t)
    v=pcbnew.PCB_VIA(b); v.SetPosition(VECTOR2I(FromMM(x),FromMM(y))); v.SetWidth(FromMM(dia)); v.SetDrill(FromMM(drill)); v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu); v.SetNet(gnd); b.Add(v)
    allobs.append(Point(x,y).buffer(dia/2+0.15)); ta=STRtree(allobs)
    print("stitched",layname,pads,"->",x,y,dia)
route.fill_zones(b); b.Save(PCB)
b=pcbnew.LoadBoard(PCB)
n,u,txt=route.run_drc(b,"../out/drc.txt"); print(n,u,route.summarize_drc(txt))
