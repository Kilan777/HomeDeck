import pcbnew, math, heapq, sys
from pcbnew import ToMM
from shapely.geometry import LineString, Point, Polygon
def path_length(b, net, src, dst, links=(), want_path=False):
    segs=[]; seen=set()
    for t in b.GetTracks():
        if t.GetNetname()!=net: continue
        if t.GetClass()=="PCB_VIA":
            x,y=ToMM(t.GetPosition().x),ToMM(t.GetPosition().y); segs.append(["via",None,(x,y),(x,y),Point(x,y).buffer(ToMM(t.GetWidth())/2),[]])
        else:
            s,e=t.GetStart(),t.GetEnd(); k=(t.GetLayer(),s.x,s.y,e.x,e.y)
            if k in seen: continue
            seen.add(k); a=(ToMM(s.x),ToMM(s.y)); c=(ToMM(e.x),ToMM(e.y))
            segs.append(["trk",t.GetLayer(),a,c,LineString([a,c]).buffer(ToMM(t.GetWidth())/2),[]])
    pads={}
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetname()!=net: continue
            poly=p.GetEffectivePolygon(); pts=[(ToMM(poly.CVertex(i).x),ToMM(poly.CVertex(i).y)) for i in range(poly.VertexCount(0))]
            tht=p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH,pcbnew.PAD_ATTRIB_NPTH)
            pads[(f.GetReference(),p.GetNumber())]=(None if tht else f.GetLayer(),Polygon(pts))
    nodes=[]  # (x,y)
    def newnode(x,y): nodes.append((x,y)); return len(nodes)-1
    edges=[]
    def param(i,pt):
        a,c=segs[i][2],segs[i][3]; L=math.hypot(c[0]-a[0],c[1]-a[1])
        if L==0: return 0.0
        return ((pt[0]-a[0])*(c[0]-a[0])+(pt[1]-a[1])*(c[1]-a[1]))/(L*L)
    def attach(i,pt):
        """node on segment i nearest to pt"""
        a,c=segs[i][2],segs[i][3]; u=min(1,max(0,param(i,pt))); q=(a[0]+u*(c[0]-a[0]),a[1]+u*(c[1]-a[1]))
        n=newnode(*q); segs[i][5].append((u,n)); return n
    for i,s in enumerate(segs):
        segs[i][5].append((0.0,newnode(*s[2]))); segs[i][5].append((1.0,newnode(*s[3])))
    for i in range(len(segs)):
        for j in range(i+1,len(segs)):
            li,lj=segs[i][1],segs[j][1]
            if li is not None and lj is not None and li!=lj: continue
            if segs[i][4].intersects(segs[j][4]):
                c=segs[i][4].intersection(segs[j][4]).centroid; pt=(c.x,c.y)
                edges.append((attach(i,pt),attach(j,pt),0.0))
    padnode={}
    for key,(lay,poly) in pads.items():
        pn=newnode(poly.centroid.x,poly.centroid.y); padnode[key]=pn
        for i,s in enumerate(segs):
            if lay is not None and s[1] is not None and s[1]!=lay: continue
            if poly.intersects(s[4]):
                c=poly.intersection(s[4]).centroid; edges.append((pn,attach(i,(c.x,c.y)),0.0))
    for s in segs:
        pts=sorted(s[5]); a,c=s[2],s[3]; L=math.hypot(c[0]-a[0],c[1]-a[1])
        for (u1,n1),(u2,n2) in zip(pts,pts[1:]): edges.append((n1,n2,(u2-u1)*L))
    for ref,a,c in links:
        if (ref,a) in padnode and (ref,c) in padnode: edges.append((padnode[(ref,a)],padnode[(ref,c)],0.0))
    adj=[[] for _ in nodes]
    for a,c,w in edges: adj[a].append((c,w)); adj[c].append((a,w))
    s=padnode[src]; d=padnode[dst]; dist={s:0.0}; pq=[(0.0,s)]; prev={}
    while pq:
        dd,u=heapq.heappop(pq)
        if u==d:
            if not want_path: return dd
            path=[]; x=d
            while x!=s: path.append((nodes[prev[x]],nodes[x])); x=prev[x]
            return dd, path
        if dd>dist.get(u,1e9): continue
        for v,w in adj[u]:
            if dd+w<dist.get(v,1e9): dist[v]=dd+w; prev[v]=u; heapq.heappush(pq,(dd+w,v))
    return (None,[]) if want_path else None
LINKS=(("U9","1","6"),("U9","3","4"),("U11","1","6"),("U11","3","4"),("J2","A6","B6"),("J2","A7","B7"))
PATHS=[("USB_C2_P",("U7","8"),("J2","A6")),("USB_C2_N",("U7","7"),("J2","A7")),("USB_DSA_P",("U8","6"),("J3","3")),("USB_DSA_N",("U8","5"),("J3","2"))]
if __name__=="__main__":
    b=pcbnew.LoadBoard(sys.argv[1] if len(sys.argv)>1 else "../kicad/HomeDeck.kicad_pcb")
    for net,s,d in PATHS: print(net,s,d,round(path_length(b,net,s,d,LINKS),2))
