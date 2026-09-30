import pcbnew, json, re, os
from pcbnew import ToMM, FromMM, VECTOR2I
from shapely.geometry import LineString, Point
import obstacles, route, gen_pcb
PCB=route.PCB
F=pcbnew.F_Cu; B=pcbnew.B_Cu
P="USB_C2_P"; N="USB_C2_N"
TR=[ # (net, layer, x1,y1,x2,y2,w)
 (P,F,50.175,82.75,51.15,82.75,0.2),(P,F,51.15,82.75,51.15,92.9,0.2),(P,F,51.15,92.0,52.93,92.0,0.2),(P,F,52.93,92.0,52.93,92.9,0.2),
 (P,F,52.93,92.9,53.9,92.9,0.2),(P,F,53.9,92.9,53.9,95.8,0.2),(P,F,53.9,95.8,52.75,96.95,0.2),
 (N,F,50.175,83.25,50.75,83.25,0.2),(N,F,50.75,83.25,50.75,91.0,0.2),(N,F,50.75,91.0,50.35,91.4,0.2),(N,F,50.35,91.4,50.35,91.5,0.2),
 (N,B,50.35,91.5,51.8,92.5,0.2),(N,B,51.8,92.5,51.8,93.9,0.2),
 (N,F,51.8,93.9,51.8,94.78,0.2),(N,F,51.2,94.78,52.4,94.78,0.2),(N,F,51.8,94.78,51.8,96.5,0.2),
 # bridges (already present but re-added after deletion)
 (N,F,51.25,96.5,52.25,96.5,0.2),(N,F,51.375,96.5,51.375,96.95,0.15),(N,F,52.25,96.5,52.25,96.9,0.2),
 (P,F,51.75,98.2,51.75,98.6,0.2),(P,F,51.75,98.6,52.75,98.6,0.2),(P,F,52.75,98.2,52.75,98.6,0.2),
]
VIAS=[(N,50.35,91.5),(N,51.8,93.9)]
def check(b):
    obs,trees=obstacles.build(b, exclude_nets=(P,N))
    bad=[]
    geoms={P:[],N:[]}
    for net,l,x1,y1,x2,y2,w in TR:
        g=LineString([(x1,y1),(x2,y2)]).buffer(w/2); geoms[net].append((l,g))
        if not obstacles.clear(g,l,net,obs,trees,0.15): bad.append(("trk",net,x1,y1,x2,y2))
    for net,x,y in VIAS:
        g=Point(x,y).buffer(0.225); geoms[net].append((F,g)); geoms[net].append((B,g))
        for l in (F,B):
            if not obstacles.clear(g,l,net,obs,trees,0.15): bad.append(("via",net,x,y))
    # P vs N mutual
    for l1,g1 in geoms[P]:
        for l2,g2 in geoms[N]:
            if l1==l2 and g1.distance(g2)<0.15: bad.append(("PN",l1,[round(v,2) for v in g1.bounds],[round(v,2) for v in g2.bounds],round(g1.distance(g2),3)))
    return bad
def detail(b):
    obs,trees=obstacles.build(b, exclude_nets=(P,N))
    for net,l,x1,y1,x2,y2,w in TR:
        g=LineString([(x1,y1),(x2,y2)]).buffer(w/2)
        for j in trees[l].query(g.buffer(0.3)):
            n,gg,tid,req=obs[l][int(j)]
            if n==net: continue
            need=0.15 if req==0 else req
            if gg.distance(g)<need: print("  conflict",net,b.GetLayerName(l),(x1,y1,x2,y2),"vs",n,round(gg.distance(g),3),[round(v,2) for v in gg.bounds])
    for net,x,y in VIAS:
        g=Point(x,y).buffer(0.225)
        for l in (F,B):
            for j in trees[l].query(g.buffer(0.3)):
                n,gg,tid,req=obs[l][int(j)]
                if n==net: continue
                need=0.15 if req==0 else req
                if gg.distance(g)<need: print("  via conflict",net,b.GetLayerName(l),(x,y),"vs",n,round(gg.distance(g),3),[round(v,2) for v in gg.bounds])
def apply():
    b=pcbnew.LoadBoard(PCB); codes={b.GetNetcodeFromNetname(P),b.GetNetcodeFromNetname(N)}; del b
    txt=open(PCB).read().split("\n"); keep=[]; removed=0
    for line in txt:
        m=re.match(r"\((segment|via) .*\(net (\d+)\)", line.strip())
        if m and int(m.group(2)) in codes: removed+=1; continue
        keep.append(line)
    open(PCB,"w").write("\n".join(keep)); print("removed",removed)
    b=pcbnew.LoadBoard(PCB)
    for net,l,x1,y1,x2,y2,w in TR:
        t=pcbnew.PCB_TRACK(b); t.SetStart(VECTOR2I(FromMM(x1),FromMM(y1))); t.SetEnd(VECTOR2I(FromMM(x2),FromMM(y2))); t.SetWidth(FromMM(w)); t.SetLayer(l); t.SetNet(b.FindNet(net)); b.Add(t)
    for net,x,y in VIAS:
        v=pcbnew.PCB_VIA(b); v.SetPosition(VECTOR2I(FromMM(x),FromMM(y))); v.SetWidth(FromMM(0.45)); v.SetDrill(FromMM(0.2)); v.SetViaType(pcbnew.VIATYPE_THROUGH); v.SetLayerPair(F,B); v.SetNet(b.FindNet(net)); b.Add(v)
    gen_pcb.setup_board(b)
    for z in b.Zones(): z.SetIsFilled(False)
    route.fill_zones(b); b.Save(PCB); print("applied")
if __name__=="__main__":
    import sys
    b=pcbnew.LoadBoard(PCB)
    bad=check(b); print("bad:",bad)
    if bad: detail(b)
    if not bad and len(sys.argv)>1 and sys.argv[1]=="apply": apply()
