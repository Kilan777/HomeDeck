"""Add a grid of GND stitching vias in free pour areas (outside the In2 power polygons)."""
import pcbnew, math
from pcbnew import ToMM, FromMM, VECTOR2I
from shapely.geometry import Point, Polygon, box
from shapely.strtree import STRtree
import obstacles, route
PCB=route.PCB
PITCH=5.0; DIA=0.6; DRILL=0.3; CLR=0.35
def run():
    b=pcbnew.LoadBoard(PCB)
    obs,trees=obstacles.build(b)
    # power polygons on In2 (avoid), GND fills (must be inside on F or B)
    power=[]; gndfill={}
    for z in b.Zones():
        if z.GetNetname()!="GND" and z.GetFirstLayer()==pcbnew.In2_Cu:
            o=z.Outline().COutline(0); power.append(Polygon([(ToMM(o.CPoint(i).x),ToMM(o.CPoint(i).y)) for i in range(o.PointCount())]))
        if z.GetNetname()=="GND" and z.GetFirstLayer() in (pcbnew.F_Cu,pcbnew.B_Cu):
            gndfill[z.GetFirstLayer()]=z.GetFilledPolysList(z.GetFirstLayer())
    ptree=STRtree(power)
    # footprint bodies (courtyard bbox) on each side: avoid vias under bottom-side parts? vias under parts are fine; avoid THT bodies only via obstacles
    bb=b.GetBoardEdgesBoundingBox(); x0,y0,x1,y1=ToMM(bb.GetLeft()),ToMM(bb.GetTop()),ToMM(bb.GetRight()),ToMM(bb.GetBottom())
    gnd=b.FindNet("GND"); added=0
    xs=[x0+2.5+i*PITCH for i in range(int((x1-x0)/PITCH))]; ys=[y0+2.5+j*PITCH for j in range(int((y1-y0)/PITCH))]
    for x in xs:
        for y in ys:
            P=Point(x,y)
            if any(power[int(j)].contains(P) for j in ptree.query(P)): continue
            v=VECTOR2I(FromMM(x),FromMM(y))
            infill=any(fp.Contains(v) for fp in gndfill.values())
            if not infill: continue
            g=P.buffer(DIA/2)
            if not (obstacles.clear(g,pcbnew.F_Cu,"GND",obs,trees,CLR) and obstacles.clear(g,pcbnew.B_Cu,"GND",obs,trees,CLR)): continue
            via=pcbnew.PCB_VIA(b); via.SetPosition(v); via.SetWidth(FromMM(DIA)); via.SetDrill(FromMM(DRILL)); via.SetViaType(pcbnew.VIATYPE_THROUGH); via.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu); via.SetNet(gnd); b.Add(via)
            for l in obs: obs[l].append(("GND",g,None,0.0))
            added+=1
    for l in obs: trees[l]=STRtree([gg for _,gg,_,_ in obs[l]])
    b.Save(PCB); print("stitching vias added:",added)
if __name__=="__main__": run()
