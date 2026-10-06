"""Length-match differential pairs by adding rectangular meander bumps to the shorter net."""
import pcbnew, math, sys
from pcbnew import ToMM, FromMM, VECTOR2I
from shapely.geometry import Point, LineString, Polygon, box
from shapely.strtree import STRtree
import skew, route

PCB="../kicad/HomeDeck.kicad_pcb"
TARGET=0.25
SKIP=set()
PATHPAIRS=[('USB_C2',('U7','8'),('U7','7'),('J2','A6'),('J2','A7')),('USB_DSA',('U8','6'),('U8','5'),('J3','3'),('J3','2'))]
CLR=0.17

import obstacles
def load_obstacles(b):
    return obstacles.build(b)

from shapely.geometry import box as _box
import gen_pcb as _g
FAN=[_box(*a) for a in _g.FANOUT_AREAS]
def clear(geom, layer, net, obs, trees):
    clr=CLR
    if any(f.contains(geom) for f in FAN): clr=0.11   # 0.1 mm rules apply inside the CM4 fan-out areas
    return obstacles.clear(geom, layer, net, obs, trees, clr, extra_gnd=0.0)

def path_segments(b, net, src, dst):
    import pathlen
    from shapely.geometry import LineString as LS, Point as Pt
    d,path=pathlen.path_length(b, net, src, dst, pathlen.LINKS, want_path=True)
    lines=[LS([a,c]) for a,c in path if a!=c]
    out=[]
    for t in net_segments(b, net):
        s,e=t.GetStart(),t.GetEnd(); a=(ToMM(s.x),ToMM(s.y)); c=(ToMM(e.x),ToMM(e.y))
        m=Pt((a[0]+c[0])/2,(a[1]+c[1])/2); pa=Pt(a); pc=Pt(c)
        if any(l.distance(m)<0.02 and l.distance(pa)<0.02 and l.distance(pc)<0.02 for l in lines): out.append(t)
    return out

def net_segments(b, net):
    segs=[]; seen=set()
    for t in b.GetTracks():
        if t.GetClass()=="PCB_VIA" or t.GetNetname()!=net: continue
        s,e=t.GetStart(),t.GetEnd(); k=(t.GetLayer(),s.x,s.y,e.x,e.y)
        if k in seen: continue
        seen.add(k); segs.append(t)
    return segs

def try_bump(b, t, delta, obs, trees):
    """Try to replace track t by a bump adding ~delta length. Returns list of (x1,y1,x2,y2) or None."""
    net=t.GetNetname(); layer=t.GetLayer(); w=ToMM(t.GetWidth())
    x1,y1,x2,y2=ToMM(t.GetStart().x),ToMM(t.GetStart().y),ToMM(t.GetEnd().x),ToMM(t.GetEnd().y)
    L=math.hypot(x2-x1,y2-y1)
    if L<0.9: return None
    ux,uy=(x2-x1)/L,(y2-y1)/L; nx,ny=-uy,ux
    bw=None
    best=None
    for A in [a/20 for a in range(int(min(1.6,(delta+0.5)/2)*20),5,-1)]:   # amplitude (extra length = 2*(sqrt2-1)*A per bump... plus flat)
        bw=4*0.15+max(0.3, w*2+CLR+0.1)
        for frac in (0.5,0.35,0.65,0.2,0.8):
            s0=frac*L-bw/2; s1=s0+bw
            if s0<0.2 or s1>L-0.2: continue
            for side in (1,-1):
                ax,ay=x1+ux*s0,y1+uy*s0; bx,by=x1+ux*s1,y1+uy*s1
                # rectangular bump with 45-degree chamfered corners (c): extra length = 2A - 4c(2-sqrt2)
                c=0.15; sA=A*side
                def P(t_along, h): return (ax+ux*t_along+nx*h*sA, ay+uy*t_along+ny*h*sA)
                pts=[(x1,y1),(ax,ay),P(c,c),P(c,A-c),P(2*c,A),P(bw-2*c,A),P(bw-c,A-c),P(bw-c,c),(bx,by),(x2,y2)]
                geom=LineString(pts[1:-1]).buffer(w/2)
                if clear(geom, layer, net, obs, trees):
                    # same-net self clearance: the bump must not touch other same-net copper except this track
                    ok=True
                    for j in trees[layer].query(geom.buffer(CLR)):
                        n,g=obs[layer][int(j)][0],obs[layer][int(j)][1]
                        if n!=net: continue
                        if g.distance(LineString(pts[2:-2]).buffer(w/2))<CLR and not g.intersects(LineString([(x1,y1),(x2,y2)]).buffer(w/2+0.01)):
                            ok=False; break
                    if ok:
                        return pts, 2*A-4*0.15*(2-math.sqrt(2))
    return None

def tune():
    b=pcbnew.LoadBoard(PCB)
    obs,trees=load_obstacles(b)
    rep=skew.report(quiet=True)
    import pathlen
    for base,sp,sn,dp,dn in PATHPAIRS:
        lp=pathlen.path_length(b,base+"_P",sp,dp,pathlen.LINKS); ln=pathlen.path_length(b,base+"_N",sn,dn,pathlen.LINKS)
        rep[(base+"_P",base+"_N")]=(lp,ln,0,0)
    changes=0
    for (p,n),(lp,ln,vp,vn) in rep.items():
        if p in SKIP: continue
        delta=lp-ln
        if abs(delta)<=TARGET: continue
        short=n if delta>0 else p
        need=abs(delta)
        tries=0
        while need>TARGET and tries<12:
            tries+=1
            pp=[x for x in PATHPAIRS if x[0]+"_P"==p]
            if pp:
                base,sp,sn,dp,dn=pp[0]
                cand=path_segments(b, short, sp if short.endswith("_P") else sn, dp if short.endswith("_P") else dn)
            else:
                cand=net_segments(b, short)
            segs=sorted(cand, key=lambda t:-math.hypot(ToMM(t.GetEnd().x-t.GetStart().x),ToMM(t.GetEnd().y-t.GetStart().y)))
            done=False
            for t in segs[:15]:
                r=try_bump(b, t, need, obs, trees)
                if not r: continue
                pts,added=r
                layer=t.GetLayer(); w=t.GetWidth(); netobj=t.GetNet()
                # replace t by the bump polyline (modify t to first piece, add the rest)
                t.SetEnd(VECTOR2I(FromMM(pts[1][0]),FromMM(pts[1][1])))
                for (xa,ya),(xb,yb) in zip(pts[1:-1],pts[2:]):
                    nt=pcbnew.PCB_TRACK(b); nt.SetStart(VECTOR2I(FromMM(xa),FromMM(ya))); nt.SetEnd(VECTOR2I(FromMM(xb),FromMM(yb))); nt.SetWidth(w); nt.SetLayer(layer); nt.SetNet(netobj); b.Add(nt)
                    g=LineString([(xa,ya),(xb,yb)]).buffer(ToMM(w)/2); obs[layer].append((short,g,None,0.0))
                trees[layer]=STRtree([g for _,g,_,_ in obs[layer]])
                need-=added; changes+=1; done=True
                print(f"  {short}: bump +{added:.2f} mm on {b.GetLayerName(layer)} at ({pts[2][0]:.1f},{pts[2][1]:.1f}); remaining {need:.2f}")
                break
            if not done:
                print(f"  {short}: no room for more bumps (remaining {need:.2f})"); break
    if changes:
        route.fill_zones(b); b.Save(PCB)
    print("bumps added:",changes)

if __name__=="__main__":
    tune()
    skew.report()
