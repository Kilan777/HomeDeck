"""Add a GND via inside every disconnected GND copper cluster."""
import pcbnew, sys
from pcbnew import ToMM, FromMM, VECTOR2I
from shapely.geometry import Polygon, Point, LineString
from shapely.strtree import STRtree
import gnd_islands, route

PCB="../kicad/HomeDeck.kicad_pcb"
b=pcbnew.LoadBoard(PCB)
bad,_=gnd_islands.analyse(b)
# obstacles for a through via: everything not GND on any layer, plus all holes (vias/THT) regardless of net
obs=[]
for t in b.GetTracks():
    if t.GetClass()=="PCB_VIA":
        obs.append(Point(ToMM(t.GetPosition().x),ToMM(t.GetPosition().y)).buffer(max(ToMM(t.GetWidth())/2, 0.45)))  # hole-hole spacing
    elif t.GetNetname()!="GND":
        obs.append(LineString([(ToMM(t.GetStart().x),ToMM(t.GetStart().y)),(ToMM(t.GetEnd().x),ToMM(t.GetEnd().y))]).buffer(ToMM(t.GetWidth())/2))
for f in b.GetFootprints():
    for p in f.Pads():
        s=p.GetSize(); q=p.GetPosition(); r=max(ToMM(s.x),ToMM(s.y))/2
        g=Point(ToMM(q.x),ToMM(q.y)).buffer(r)
        if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH,pcbnew.PAD_ATTRIB_NPTH): obs.append(g.buffer(0.3))
        elif p.GetNetname()!="GND": obs.append(g)
        else: obs.append(g)  # keep vias out of pads too (JLC does not like via-in-pad)
    # bottom-side/top-side bodies: avoid putting vias under small parts? not needed electrically
tree=STRtree(obs)
gnd_net=b.FindNet("GND")
added=[]
for lay,g,pads in bad:
    best=None
    for dia,drill in ((0.6,0.3),(0.45,0.2)):
        r=dia/2
        region=g.buffer(-(r+0.02))
        if region.is_empty: continue
        minx,miny,maxx,maxy=region.bounds
        x=minx
        while x<=maxx:
            y=miny
            while y<=maxy:
                pt=Point(x,y)
                if region.contains(pt):
                    d=min([obs[int(j)].distance(pt) for j in tree.query(pt.buffer(1.5))] or [9])
                    if d>=r+0.16 and (best is None or d>best[0]): best=(d,x,y,dia,drill)
                y+=0.1
            x+=0.1
        if best: break
    if best is None:
        print("NO SPOT", lay, g.bounds, pads); continue
    d,x,y,dia,drill=best
    v=pcbnew.PCB_VIA(b); v.SetPosition(VECTOR2I(FromMM(round(x,2)),FromMM(round(y,2)))); v.SetWidth(FromMM(dia)); v.SetDrill(FromMM(drill))
    v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu); v.SetNet(gnd_net); b.Add(v)
    obs.append(Point(x,y).buffer(0.45)); tree=STRtree(obs)
    added.append((lay,round(x,2),round(y,2),dia,round(d,2),pads))
    print("via",lay,round(x,2),round(y,2),dia,"clr",round(d-dia/2,2),pads)
route.fill_zones(b)
b.Save(PCB)
print("added",len(added))
