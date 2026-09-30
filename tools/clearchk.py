import pcbnew
from pcbnew import ToMM
from shapely.geometry import Point, LineString, Polygon
from shapely.geometry import box
b=pcbnew.LoadBoard("../kicad/HomeDeck.kicad_pcb")
def items(layer):
    out=[]
    for t in b.GetTracks():
        if t.GetClass()=="PCB_VIA":
            out.append((t.GetNetname(),Point(ToMM(t.GetPosition().x),ToMM(t.GetPosition().y)).buffer(ToMM(t.GetWidth())/2),"via"))
        elif t.GetLayer()==layer:
            out.append((t.GetNetname(),LineString([(ToMM(t.GetStart().x),ToMM(t.GetStart().y)),(ToMM(t.GetEnd().x),ToMM(t.GetEnd().y))]).buffer(ToMM(t.GetWidth())/2),"trk"))
    for f in b.GetFootprints():
        for p in f.Pads():
            tht=p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH,pcbnew.PAD_ATTRIB_NPTH)
            if not tht and f.GetLayer()!=layer: continue
            poly=p.GetEffectivePolygon()
            pts=[(ToMM(poly.CVertex(i).x),ToMM(poly.CVertex(i).y)) for i in range(poly.VertexCount(0))]
            out.append((p.GetNetname(),Polygon(pts),"pad "+f.GetReference()+"."+p.GetNumber()))
    return out
def check(geom, layer, net, clr=0.15):
    bad=[]
    for n,g,k in items(layer):
        if n==net: continue
        d=g.distance(geom)
        if d<clr: bad.append((n,k,round(d,3)))
    return bad
def check_via(x,y,dia,net,clr=0.15):
    g=Point(x,y).buffer(dia/2)
    return check(g,pcbnew.F_Cu,net,clr)+check(g,pcbnew.B_Cu,net,clr)
if __name__=="__main__":
    print("seg",check(LineString([(34.6,83.4),(32.8,86.8)]).buffer(0.2),pcbnew.B_Cu,"5V_USBA"))
    print("via U11",check_via(35.75,85.55,0.45,"GND"))
    print("via J6",check_via(72.5,28.55,0.45,"GND"))
    print("via J9",check_via(14.6,103.55,0.45,"GND"))
    print("via C61",check_via(82.4,91.5,0.45,"GND"))
    print("via U9",check_via(51.08,93.83,0.45,"GND"))
