// Grid A* PCB router with net-aware clearance, via drops to planes, and diff-pair attraction.
// Input: route_in.json  Output: route_out.json
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <vector>
#include <string>
#include <queue>
#include <map>
#include <set>
#include <algorithm>
#include <functional>
#include <nlohmann/json.hpp>
using json = nlohmann::json;
using namespace std;

struct Poly { vector<pair<double,double>> pts; int net; int layer; };  // layer: 0=F,1=B,2=both(THT)
struct Seg { int layer; double x1,y1,x2,y2,w; };
struct Via { double x,y; };
struct Terminal { int pad; int layer; vector<pair<int,int>> cells; double cx, cy; double w; bool nodrop; };
struct Net {
    int id; string name; double width; double clearance; bool plane; int planeLayer; // planeLayer 1=In1(GND),2=In2
    vector<Terminal> terms; int priority; int pair_of; double viaCost; // net id of partner or -1
    vector<Seg> segs; vector<Via> vias;
};

static int NX, NY; static double RES, W, H;
static const int NL = 2; // routing layers F=0, B=1
// two-nearest obstacle info per routing layer
static vector<float> d1[NL], d2[NL]; static vector<int> o1[NL], o2[NL];
static vector<float> vd1, vd2; static vector<int> vo1, vo2; // via blocking (any layer copper incl. holes) -> use for via placement
static vector<int> in2owner; // net id owning In2 at cell, 0 none
static vector<unsigned char> hardblock; // 1 = never route (edge/slot/hole)
static vector<float> vhd; // distance to nearest hole edge (vias + THT) for hole-to-hole rule
static vector<int> netocc[NL]; // net copper occupancy per layer (pads+tracks): net id or 0
static vector<int> padowner[NL]; // pad index (global) for goal detection
static double VIA_R = 0.3, VIA_DRILL_R = 0.15;

inline int idx(int x,int y){ return y*NX+x; }
inline double cx(int x){ return x*RES; }
inline double cy(int y){ return y*RES; }

double pointPolyDist(double px,double py,const vector<pair<double,double>>&P, bool &inside){
    // distance from point to polygon boundary; inside flag
    int n=P.size(); double best=1e9; inside=false;
    for(int i=0,j=n-1;i<n;j=i++){
        double xi=P[i].first, yi=P[i].second, xj=P[j].first, yj=P[j].second;
        if( ((yi>py)!=(yj>py)) && (px < (xj-xi)*(py-yi)/(yj-yi)+xi) ) inside=!inside;
        double dx=xj-xi, dy=yj-yi; double l2=dx*dx+dy*dy; double t = l2>0? max(0.0,min(1.0,((px-xi)*dx+(py-yi)*dy)/l2)):0;
        double qx=xi+t*dx, qy=yi+t*dy; double d=hypot(px-qx,py-qy); if(d<best) best=d;
    }
    return best;
}

void updateNearest(vector<float>&D1,vector<int>&O1,vector<float>&D2,vector<int>&O2,int c,float d,int net){
    if(O1[c]==net){ if(d<D1[c]) D1[c]=d; return; }
    if(O2[c]==net){ if(d<D2[c]) D2[c]=d; if(D2[c]<D1[c]){ swap(D1[c],D2[c]); swap(O1[c],O2[c]); } return; }
    if(d<D1[c]){ D2[c]=D1[c]; O2[c]=O1[c]; D1[c]=d; O1[c]=net; }
    else if(d<D2[c]){ D2[c]=d; O2[c]=net; }
}

void addPolyObstacle(const Poly&P, double rmax, bool markOcc, int padIndex){
    double minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9;
    for(auto&p:P.pts){minx=min(minx,p.first);maxx=max(maxx,p.first);miny=min(miny,p.second);maxy=max(maxy,p.second);}
    int x0=max(0,(int)floor((minx-rmax)/RES)), x1=min(NX-1,(int)ceil((maxx+rmax)/RES));
    int y0=max(0,(int)floor((miny-rmax)/RES)), y1=min(NY-1,(int)ceil((maxy+rmax)/RES));
    for(int y=y0;y<=y1;y++) for(int x=x0;x<=x1;x++){
        bool inside; double d=pointPolyDist(cx(x),cy(y),P.pts,inside); if(inside) d=0;
        if(d>rmax) continue;
        int c=idx(x,y);
        for(int L=0;L<NL;L++){
            if(P.layer==L||P.layer==2){
                updateNearest(d1[L],o1[L],d2[L],o2[L],c,(float)d,P.net);
                if(inside && markOcc && P.net>0){ netocc[L][c]=P.net; padowner[L][c]=padIndex; }
            }
        }
        // via blocking: any pad on any layer blocks vias (THT and SMD both; conservative)
        updateNearest(vd1,vo1,vd2,vo2,c,(float)d,P.net);
    }
}

void addSegObstacle(const Seg&s, int net, double rmax){
    double minx=min(s.x1,s.x2)-s.w, maxx=max(s.x1,s.x2)+s.w, miny=min(s.y1,s.y2)-s.w, maxy=max(s.y1,s.y2)+s.w;
    int x0=max(0,(int)floor((minx-rmax)/RES)), x1=min(NX-1,(int)ceil((maxx+rmax)/RES));
    int y0=max(0,(int)floor((miny-rmax)/RES)), y1=min(NY-1,(int)ceil((maxy+rmax)/RES));
    double dx=s.x2-s.x1, dy=s.y2-s.y1, l2=dx*dx+dy*dy;
    for(int y=y0;y<=y1;y++) for(int x=x0;x<=x1;x++){
        double px=cx(x),py=cy(y); double t=l2>0?max(0.0,min(1.0,((px-s.x1)*dx+(py-s.y1)*dy)/l2)):0;
        double d=hypot(px-(s.x1+t*dx),py-(s.y1+t*dy))-s.w/2; if(d<0)d=0;
        if(d>rmax) continue; int c=idx(x,y);
        updateNearest(d1[s.layer],o1[s.layer],d2[s.layer],o2[s.layer],c,(float)d,net);
        if(d<=0.0001) netocc[s.layer][c]=net;
        updateNearest(vd1,vo1,vd2,vo2,c,(float)d,net);
    }
}
void addViaObstacle(const Via&v,int net,double rmax){
    int x0=max(0,(int)floor((v.x-VIA_R-rmax-0.6)/RES)), x1=min(NX-1,(int)ceil((v.x+VIA_R+rmax+0.6)/RES));
    int y0=max(0,(int)floor((v.y-VIA_R-rmax-0.6)/RES)), y1=min(NY-1,(int)ceil((v.y+VIA_R+rmax+0.6)/RES));
    for(int y=y0;y<=y1;y++) for(int x=x0;x<=x1;x++){
        double dh=hypot(cx(x)-v.x,cy(y)-v.y)-VIA_DRILL_R; int c=idx(x,y); if(dh<vhd[c]) vhd[c]=(float)dh;
        double d=dh+VIA_DRILL_R-VIA_R; if(d<0)d=0; if(d>rmax) continue;
        for(int L=0;L<NL;L++){ updateNearest(d1[L],o1[L],d2[L],o2[L],c,(float)d,net); if(d<=0.0001) netocc[L][c]=net; }
        updateNearest(vd1,vo1,vd2,vo2,c,(float)d,net);
    }
}

inline bool cellFree(int L,int c,int net,double r){
    if(hardblock[c]) return false;
    if(o1[L][c]!=net && o1[L][c]!=0 && d1[L][c]<r) return false;
    if(o2[L][c]!=net && o2[L][c]!=0 && d2[L][c]<r) return false;
    if(o1[L][c]==0 && d1[L][c]<r) return false; // net 0 = keepout/unconnected copper
    if(o2[L][c]==0 && d2[L][c]<r) return false;
    return true;
}
inline bool viaFree(int c,int net,double clr){
    if(hardblock[c]) return false;
    if(vhd[c]<VIA_DRILL_R+0.5) return false; // hole-to-hole >= 0.5
    double r=VIA_R+clr;
    if(vo1[c]!=net && vd1[c]<r) return false;
    if(vo2[c]!=net && vd2[c]<r) return false;
    return true;
}

struct Node { double f; double g; int L; int x; int y; bool operator<(const Node&o)const{ return f>o.f; } };

// A* from source cells to goal predicate. Returns path as list of (L,x,y) or empty.
vector<array<int,3>> astar(int net, double r, double clr, const vector<array<int,3>>&sources, function<bool(int,int,int)> isGoal,
                           function<double(int,int,int)> heur, int bx0,int by0,int bx1,int by1, double viaCost, bool allowVia,
                           function<bool(int,int)> viaAllowedHere, function<double(int,int,int)> extraCost, int planeGoalLayer,
                           function<bool(int,int)> planeGoalHere, long long maxExpand){
    size_t N=(size_t)NX*NY; static vector<float> g[NL]; static vector<int> par[NL]; static vector<unsigned char> closed[NL];
    for(int L=0;L<NL;L++){ if(g[L].size()!=N){ g[L].assign(N,1e30f); par[L].assign(N,-1); closed[L].assign(N,0);} }
    vector<int> touched[NL];
    priority_queue<Node> pq;
    vector<array<int,3>> srcs; for(auto&s:sources){ if(cellFree(s[0],idx(s[1],s[2]),net,r)) srcs.push_back(s); } if(srcs.empty()) srcs=sources;
    for(auto&s:srcs){ int c=idx(s[1],s[2]); if(g[s[0]][c]>0){ g[s[0]][c]=0; par[s[0]][c]=-2; touched[s[0]].push_back(c); pq.push({heur(s[0],s[1],s[2]),0,s[0],s[1],s[2]}); } }
    const int dx8[8]={1,-1,0,0,1,1,-1,-1}, dy8[8]={0,0,1,-1,1,-1,1,-1};
    long long expanded=0; array<int,3> found={-1,-1,-1}; bool planeHit=false; int planeCell=-1;
    while(!pq.empty()){
        Node n=pq.top(); pq.pop(); int c=idx(n.x,n.y);
        if(closed[n.L][c]) continue; closed[n.L][c]=1; expanded++;
        if(expanded>maxExpand) break;
        if(isGoal(n.L,n.x,n.y)){ found={n.L,n.x,n.y}; break; }
        // plane drop goal: at this cell, placing a via into the plane finishes
        if(planeGoalLayer>0 && allowVia && viaAllowedHere(n.x,n.y) && planeGoalHere(n.x,n.y) && viaFree(c,net,clr)){ found={n.L,n.x,n.y}; planeHit=true; break; }
        for(int k=0;k<8;k++){
            int nx=n.x+dx8[k], ny=n.y+dy8[k]; if(nx<bx0||ny<by0||nx>bx1||ny>by1) continue; int nc=idx(nx,ny);
            if(closed[n.L][nc]) continue; if(!cellFree(n.L,nc,net,r)) continue;
            // no diagonal squeezing: both orthogonal neighbours must be free too
            if(k>=4){ if(!cellFree(n.L,idx(n.x+dx8[k],n.y),net,r)||!cellFree(n.L,idx(n.x,n.y+dy8[k]),net,r)) continue; }
            double step=(k<4?1.0:1.41421356)*RES + extraCost(n.L,nx,ny);
            double ng=n.g+step; if(ng<g[n.L][nc]){ if(g[n.L][nc]>=1e29f) touched[n.L].push_back(nc); g[n.L][nc]=ng; par[n.L][nc]=c*NL+n.L; pq.push({ng+heur(n.L,nx,ny),ng,n.L,nx,ny}); }
        }
        if(allowVia && viaAllowedHere(n.x,n.y) && viaFree(c,net,clr)){
            int oL=1-n.L; if(!closed[oL][c] && cellFree(oL,c,net,r)){ double ng=n.g+viaCost; if(ng<g[oL][c]){ if(g[oL][c]>=1e29f) touched[oL].push_back(c); g[oL][c]=ng; par[oL][c]=c*NL+n.L; pq.push({ng+heur(oL,n.x,n.y),ng,oL,n.x,n.y}); } }
        }
    }
    if(getenv("RDEBUG") && (expanded<20 || getenv("RDEBUGALL")) && found[0]<0){ for(auto&s0:srcs){ for(int dy=-3;dy<=18;dy++){ int x=s0[1],y=s0[2]+dy; if(x<0||y<0||x>=NX||y>=NY) continue; int c=idx(x,y); fprintf(stderr,"      cell(%.1f,%.1f) L%d hard=%d o1=%d d1=%.3f o2=%d d2=%.3f free=%d\n",cx(x),cy(y),s0[0],hardblock[c],o1[s0[0]][c],d1[s0[0]][c],o2[s0[0]][c],d2[s0[0]][c],cellFree(s0[0],c,net,r)); } break; } }
    if(getenv("RDEBUG")) fprintf(stderr,"    astar net %d: sources %zu (free %zu) expanded %lld found=%d box=(%d,%d)-(%d,%d)\n",net,sources.size(),srcs.size(),expanded,found[0],bx0,by0,bx1,by1);
    vector<array<int,3>> path;
    if(found[0]>=0){
        int L=found[0], c=idx(found[1],found[2]);
        while(true){ path.push_back({L,c%NX,c/NX}); int p=par[L][c]; if(p<0) break; L=p%NL; c=p/NL; }
        reverse(path.begin(),path.end());
        if(planeHit) path.push_back({-1,found[1],found[2]}); // marker: plane via at end
    }
    for(int L=0;L<NL;L++){ for(int c:touched[L]){ g[L][c]=1e30f; par[L][c]=-1; closed[L][c]=0; } }
    return path;
}

// convert cell path to segments+vias (merge collinear runs)
void pathToGeom(const vector<array<int,3>>&path, double w, vector<Seg>&segs, vector<Via>&vias, bool &endsInPlane){
    endsInPlane=false; if(path.empty()) return;
    vector<array<int,3>> p=path; if(p.back()[0]==-1){ endsInPlane=true; vias.push_back({cx(p.back()[1]),cy(p.back()[2])}); p.pop_back(); }
    size_t i=0;
    while(i+1<p.size()){
        if(p[i][0]!=p[i+1][0]){ vias.push_back({cx(p[i][1]),cy(p[i][2])}); i++; continue; }
        size_t j=i+1; int ddx=p[j][1]-p[i][1], ddy=p[j][2]-p[i][2];
        while(j+1<p.size() && p[j+1][0]==p[j][0] && p[j+1][1]-p[j][1]==ddx && p[j+1][2]-p[j][2]==ddy) j++;
        segs.push_back({p[i][0],cx(p[i][1]),cy(p[i][2]),cx(p[j][1]),cy(p[j][2]),w});
        i=j;
    }
}

int main(int argc,char**argv){
    if(argc<3){ fprintf(stderr,"usage: router in.json out.json\n"); return 1; }
    json J; { FILE*f=fopen(argv[1],"r"); if(!f){perror("in");return 1;} string s; char buf[65536]; size_t n; while((n=fread(buf,1,sizeof buf,f))>0) s.append(buf,n); fclose(f); J=json::parse(s); }
    W=J["width"]; H=J["height"]; RES=J["res"]; NX=(int)ceil(W/RES)+1; NY=(int)ceil(H/RES)+1;
    VIA_R=J["via_dia"].get<double>()/2; double via_clr=J["clearance"];
    size_t N=(size_t)NX*NY;
    for(int L=0;L<NL;L++){ d1[L].assign(N,1e9f); d2[L].assign(N,1e9f); o1[L].assign(N,-1); o2[L].assign(N,-1); netocc[L].assign(N,0); padowner[L].assign(N,-1);}
    vd1.assign(N,1e9f); vd2.assign(N,1e9f); vo1.assign(N,-1); vo2.assign(N,-1); in2owner.assign(N,0); hardblock.assign(N,0); vhd.assign(N,1e9f);
    double RMAX=J["rmax"];
    // hard blocks: outside outline margin, slots, holes
    double edge=J["edge_clearance"];
    for(auto&r:J["keepouts"]){ double x0=r[0],y0=r[1],x1=r[2],y1=r[3]; int a=max(0,(int)floor(x0/RES)),b=max(0,(int)floor(y0/RES)),c2=min(NX-1,(int)ceil(x1/RES)),d=min(NY-1,(int)ceil(y1/RES)); for(int y=b;y<=d;y++)for(int x=a;x<=c2;x++) hardblock[idx(x,y)]=1; }
    for(auto&h:J["holes"]){ double hx=h[0],hy=h[1],hr=h[2]; if(h.size()>3 && h[3].get<int>()>0) continue; int x0=max(0,(int)floor((hx-hr-RMAX)/RES)),x1=min(NX-1,(int)ceil((hx+hr+RMAX)/RES)),y0=max(0,(int)floor((hy-hr-RMAX)/RES)),y1=min(NY-1,(int)ceil((hy+hr+RMAX)/RES));
        for(int y=y0;y<=y1;y++)for(int x=x0;x<=x1;x++){ double d=hypot(cx(x)-hx,cy(y)-hy)-hr; if(d<0)d=0; if(d>RMAX)continue; int c=idx(x,y); for(int L=0;L<NL;L++) updateNearest(d1[L],o1[L],d2[L],o2[L],c,(float)d,0); updateNearest(vd1,vo1,vd2,vo2,c,(float)d,0);} }
    // THT holes for hole-to-hole rule (hr includes +0.1 margin)
    for(auto&h:J["holes"]){ double hx=h[0],hy=h[1],hr=h[2].get<double>()-0.1; int x0=max(0,(int)floor((hx-hr-1.0)/RES)),x1=min(NX-1,(int)ceil((hx+hr+1.0)/RES)),y0=max(0,(int)floor((hy-hr-1.0)/RES)),y1=min(NY-1,(int)ceil((hy+hr+1.0)/RES));
        for(int y=y0;y<=y1;y++)for(int x=x0;x<=x1;x++){ double d=hypot(cx(x)-hx,cy(y)-hy)-hr; int c=idx(x,y); if(d<vhd[c]) vhd[c]=(float)d; } }
    // slots: edge-clearance obstacles
    for(auto&sl:J["slots"]){ vector<pair<double,double>> P; for(auto&p:sl) P.push_back({p[0],p[1]}); double minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9; for(auto&p:P){minx=min(minx,p.first);maxx=max(maxx,p.first);miny=min(miny,p.second);maxy=max(maxy,p.second);}
        for(int y=max(0,(int)((miny-2)/RES));y<=min(NY-1,(int)((maxy+2)/RES));y++)for(int x=max(0,(int)((minx-2)/RES));x<=min(NX-1,(int)((maxx+2)/RES));x++){ bool inside; double d=pointPolyDist(cx(x),cy(y),P,inside); int c=idx(x,y); if(inside||d<edge) hardblock[c]=1; else if(d<edge+RMAX){ for(int L=0;L<NL;L++) updateNearest(d1[L],o1[L],d2[L],o2[L],c,(float)(d-edge),0); updateNearest(vd1,vo1,vd2,vo2,c,(float)(d-edge),0);} } }
    // edge: cells outside the board polygon or within edge clearance
    { auto& op=J["outline"]; vector<pair<double,double>> P; for(auto&p:op) P.push_back({p[0],p[1]});
      for(int y=0;y<NY;y++)for(int x=0;x<NX;x++){ bool inside; double d=pointPolyDist(cx(x),cy(y),P,inside); int c=idx(x,y); if(!inside||d<edge) hardblock[c]=1; else if(d<edge+RMAX){ for(int L=0;L<NL;L++) updateNearest(d1[L],o1[L],d2[L],o2[L],c,(float)(d-edge),0); updateNearest(vd1,vo1,vd2,vo2,c,(float)(d-edge),0);} } }
    // In2 plane ownership polygons
    for(auto&z:J["in2"]){ int net=z["net"]; vector<pair<double,double>> P; for(auto&p:z["poly"]) P.push_back({p[0],p[1]});
        double minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9; for(auto&p:P){minx=min(minx,p.first);maxx=max(maxx,p.first);miny=min(miny,p.second);maxy=max(maxy,p.second);}
        for(int y=max(0,(int)(miny/RES));y<=min(NY-1,(int)(maxy/RES));y++)for(int x=max(0,(int)(minx/RES));x<=min(NX-1,(int)(maxx/RES));x++){ bool inside; double d=pointPolyDist(cx(x),cy(y),P,inside); if(inside && d>0.8) in2owner[idx(x,y)]=net; } }
    // pads
    vector<Poly> pads; vector<int> padNet;
    int pi=0;
    for(auto&p:J["pads"]){ Poly P; P.net=p["net"]; P.layer=p["layer"]; for(auto&q:p["poly"]) P.pts.push_back({q[0],q[1]}); pads.push_back(P); addPolyObstacle(P,RMAX,true,pi); pi++; }
    for(auto&e:J["escapes"]){ Poly P; P.net=e["net"]; P.layer=e["layer"]; for(auto&q:e["poly"]) P.pts.push_back({q[0],q[1]}); addPolyObstacle(P,RMAX,false,-1); }
    fprintf(stderr,"grid %dx%d, %zu pads rasterized, %zu escape strips\n",NX,NY,pads.size(),J["escapes"].size());
    { long hb=0,fr=0; for(size_t c=0;c<N;c++){ if(hardblock[c]) hb++; else if(cellFree(0,c,-5,0.25)) fr++; } fprintf(stderr,"hardblock %ld free(L0,r=.25) %ld of %zu\n",hb,fr,N); }
    // nets
    vector<Net> nets; map<int,int> netIndex;
    for(auto&n:J["nets"]){ Net t; t.id=n["id"]; t.name=n["name"]; t.width=n["width"]; t.clearance=n["clearance"]; t.plane=n["plane"]; t.planeLayer=n["plane_layer"]; t.priority=n["priority"]; t.pair_of=n["pair_of"]; t.viaCost=n["via_cost"];
        for(auto&tm:n["terms"]){ Terminal T; T.pad=tm["pad"]; T.layer=tm["layer"]; T.cx=tm["cx"]; T.cy=tm["cy"]; T.w=tm["w"]; T.nodrop=tm["nodrop"]; t.terms.push_back(T);} netIndex[t.id]=nets.size(); nets.push_back(t); }
    // terminal cells: cells inside pad polygon with netocc==net on the pad layer(s)
    for(auto&n:nets) for(auto&T:n.terms){ Poly&P=pads[T.pad]; double minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9; for(auto&p:P.pts){minx=min(minx,p.first);maxx=max(maxx,p.first);miny=min(miny,p.second);maxy=max(maxy,p.second);}
        for(int y=max(0,(int)floor(miny/RES));y<=min(NY-1,(int)ceil(maxy/RES));y++)for(int x=max(0,(int)floor(minx/RES));x<=min(NX-1,(int)ceil(maxx/RES));x++){ int c=idx(x,y); int L=(T.layer==2)?0:T.layer; if(padowner[L][c]==T.pad) T.cells.push_back({x,y}); }
        if(T.cells.empty()){ int x=(int)round(T.cx/RES), y=(int)round(T.cy/RES); T.cells.push_back({x,y}); } }
    // snapshot obstacle state for multi-pass restarts
    vector<float> S_d1[NL],S_d2[NL]; vector<int> S_o1[NL],S_o2[NL],S_netocc[NL],S_padowner[NL]; vector<float> S_vd1=vd1,S_vd2=vd2,S_vhd=vhd; vector<int> S_vo1=vo1,S_vo2=vo2;
    for(int L=0;L<NL;L++){ S_d1[L]=d1[L]; S_d2[L]=d2[L]; S_o1[L]=o1[L]; S_o2[L]=o2[L]; S_netocc[L]=netocc[L]; S_padowner[L]=padowner[L]; }
    set<int> failedNets; int pass=0; json out;
  restart:
    if(pass>0){ for(int L=0;L<NL;L++){ d1[L]=S_d1[L]; d2[L]=S_d2[L]; o1[L]=S_o1[L]; o2[L]=S_o2[L]; netocc[L]=S_netocc[L]; padowner[L]=S_padowner[L]; } vd1=S_vd1; vd2=S_vd2; vhd=S_vhd; vo1=S_vo1; vo2=S_vo2; for(auto&n:nets){ n.segs.clear(); n.vias.clear(); } }
    // route order: priority asc (failed nets from the previous pass first), then by estimated length
    vector<int> order; for(size_t i=0;i<nets.size();i++) order.push_back(i);
    auto estLen=[&](Net&n){ double s=0; for(size_t i=1;i<n.terms.size();i++){ double b=1e9; for(size_t j=0;j<i;j++) b=min(b,hypot(n.terms[i].cx-n.terms[j].cx,n.terms[i].cy-n.terms[j].cy)); s+=b;} return s; };
    auto prio=[&](int i){ int p=nets[i].priority; if(failedNets.count(nets[i].id)) p-=10; return p; };
    sort(order.begin(),order.end(),[&](int a,int b){ if(prio(a)!=prio(b)) return prio(a)<prio(b); return estLen(nets[a])<estLen(nets[b]); });
    double viaCost=J["via_cost"]; long long maxExpand=J["max_expand"];
    int failures=0; out=json(); out["nets"]=json::array(); set<int> nowFailed;
    // diff pair partner path cells for attraction
    map<int, vector<array<int,3>>> pairPath;
    for(int oi=0;oi<(int)order.size();oi++){
        Net&n=nets[order[oi]]; double r=n.clearance+n.width/2; double rmaxNet=n.clearance+n.width/2+0.01;
        if(getenv("RDUMP") && n.name==string(getenv("RDUMP"))){
            for(int L=0;L<NL;L++){ char fn[64]; sprintf(fn,"/tmp/free_L%d.pgm",L); FILE*f=fopen(fn,"wb"); fprintf(f,"P5\n%d %d\n255\n",NX,NY);
                for(int y=0;y<NY;y++)for(int x=0;x<NX;x++){ int c=idx(x,y); unsigned char v= netocc[L][c]==n.id?0: (cellFree(L,c,n.id,r)?255:100); fputc(v,f);} fclose(f);} }
        vector<int> comp(n.terms.size()); for(size_t i=0;i<comp.size();i++) comp[i]=i;
        function<int(int)> find=[&](int a){ return comp[a]==a?a:comp[a]=find(comp[a]); };
        int nfail=0;
        // attraction map from partner
        vector<array<int,3>>* partner=nullptr; if(n.pair_of>=0 && pairPath.count(n.pair_of)) partner=&pairPath[n.pair_of];
        set<long long> attract; if(partner){ double want=n.width+n.clearance; int rad=(int)ceil((want+RES)/RES); for(auto&p:*partner){ if(p[0]<0)continue; for(int dy=-rad;dy<=rad;dy++)for(int dx=-rad;dx<=rad;dx++){ double d=hypot(dx*RES,dy*RES); if(fabs(d-want)<=RES*0.75){ int x=p[1]+dx,y=p[2]+dy; if(x>=0&&y>=0&&x<NX&&y<NY) attract.insert(((long long)p[0]<<40)|((long long)y<<20)|x);} } } }
        auto extraCost=[&](int L,int x,int y)->double{ if(!partner) return 0.0; long long k=((long long)L<<40)|((long long)y<<20)|x; return attract.count(k)? -RES*0.6 : RES*0.8; };
        int ref=-1; vector<char> onplane(n.terms.size(),0);
        if(n.plane){
            for(size_t ti=0;ti<n.terms.size();ti++){ Terminal&T=n.terms[ti];
                if(T.layer==2){ onplane[ti]=1; if(ref<0) ref=ti; else comp[find(ti)]=find(ref); continue; }
                if(T.nodrop) continue;
                double tw=min(n.width,T.w); double rr=n.clearance+tw/2;
                vector<array<int,3>> src; for(auto&c:T.cells) src.push_back({T.layer,c.first,c.second});
                int box=(int)(4.0/RES);
                int bx0=max(0,(int)(T.cx/RES)-box),by0=max(0,(int)(T.cy/RES)-box),bx1=min(NX-1,(int)(T.cx/RES)+box),by1=min(NY-1,(int)(T.cy/RES)+box);
                auto planeHere=[&](int x,int y){ if(n.planeLayer==1) return true; return in2owner[idx(x,y)]==n.id; };
                auto path=astar(n.id,rr,n.clearance,src,[&](int,int,int){return false;},[&](int,int,int){return 0.0;},bx0,by0,bx1,by1,n.viaCost,true,[&](int,int){return true;},[&](int,int,int){return 0.0;},n.planeLayer,planeHere,60000);
                if(path.empty()) continue;
                vector<Seg> segs; vector<Via> vias; bool inPlane; pathToGeom(path,tw,segs,vias,inPlane);
                for(auto&s:segs){ n.segs.push_back(s); addSegObstacle(s,n.id,RMAX); } for(auto&v:vias){ n.vias.push_back(v); addViaObstacle(v,n.id,RMAX); }
                onplane[ti]=1; if(ref<0) ref=ti; else comp[find(ti)]=find(ref);
                for(auto&p:path){ if(p[0]<0)continue; int cc=idx(p[1],p[2]); for(int L=0;L<NL;L++) if(netocc[L][cc]==n.id && padowner[L][cc]<0) padowner[L][cc]=-(find(ref)+2); }
            }
        }
        if(ref<0) ref=0;
        {
            for(int iter=0;iter<(int)n.terms.size()*2;iter++){
                int a=-1; for(size_t i=0;i<n.terms.size();i++){ if(n.terms[i].nodrop){ comp[find(i)]=find(ref); continue; } if(find(i)!=find(ref)){ a=i; break; } } if(a<0) break;
                Terminal&T=n.terms[a]; int ca=find(a);
                vector<array<int,3>> src; for(auto&c:T.cells) src.push_back({T.layer==2?0:T.layer,c.first,c.second}); if(T.layer==2) for(auto&c:T.cells) src.push_back({1,c.first,c.second});
                auto isGoal=[&](int L,int x,int y){ int c=idx(x,y); if(netocc[L][c]!=n.id) return false; int po=padowner[L][c]; if(po>=0){ for(size_t i=0;i<n.terms.size();i++) if(n.terms[i].pad==po) return find(i)!=ca; return false; } if(po<=-2){ int cc=-(po+2); return find(cc)!=ca; } return false; };
                double minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9; vector<pair<double,double>> goals; for(size_t i=0;i<n.terms.size();i++) if(find(i)!=ca){ goals.push_back({n.terms[i].cx,n.terms[i].cy}); }
                for(auto&g:goals){minx=min(minx,g.first);maxx=max(maxx,g.first);miny=min(miny,g.second);maxy=max(maxy,g.second);} minx=min(minx,T.cx);maxx=max(maxx,T.cx);miny=min(miny,T.cy);maxy=max(maxy,T.cy);
                auto heur=[&](int L,int x,int y){ double b=1e9; double px=cx(x),py=cy(y); for(auto&g:goals) b=min(b,hypot(px-g.first,py-g.second)); return max(0.0,b-1.0)*0.99; };
                double tw=n.width; if(n.plane) tw=min(n.width,T.w); double rr=n.clearance+tw/2;
                vector<array<int,3>> path; double margins[3]={12,35,200};
                for(int m=0;m<3&&path.empty();m++){ int bx0=max(0,(int)((minx-margins[m])/RES)),by0=max(0,(int)((miny-margins[m])/RES)),bx1=min(NX-1,(int)((maxx+margins[m])/RES)),by1=min(NY-1,(int)((maxy+margins[m])/RES));
                    path=astar(n.id,rr,n.clearance,src,isGoal,heur,bx0,by0,bx1,by1,n.viaCost,true,[&](int,int){return true;},extraCost,0,[&](int,int){return false;},maxExpand); }
                if(path.empty()){ nfail++; fprintf(stderr,"  FAILED: %s term %d (%.1f,%.1f)\n",n.name.c_str(),a,T.cx,T.cy); comp[ca]=find(ref); continue; }
                auto&e=path.back(); int c=idx(e[1],e[2]); int po=padowner[e[0]][c]; int hit=-1; if(po>=0){ for(size_t i=0;i<n.terms.size();i++) if(n.terms[i].pad==po) hit=find(i);} else if(po<=-2) hit=find(-(po+2));
                vector<Seg> segs; vector<Via> vias; bool inPlane; pathToGeom(path,tw,segs,vias,inPlane);
                int newc; if(hit>=0){ comp[find(ca)]=hit; newc=find(hit);} else { comp[ca]=find(ref); newc=find(ref); }
                for(auto&s:segs){ n.segs.push_back(s); addSegObstacle(s,n.id,RMAX); } for(auto&v:vias){ n.vias.push_back(v); addViaObstacle(v,n.id,RMAX); }
                for(auto&p:path){ if(p[0]<0)continue; int cc=idx(p[1],p[2]); for(int L=0;L<NL;L++) if(netocc[L][cc]==n.id && padowner[L][cc]<0) padowner[L][cc]=-(newc+2); }
                if(n.pair_of>=0){ auto&pp=pairPath[n.id]; for(auto&p:path) pp.push_back(p); }
            }
        }
        if(nfail){ failures+=nfail; nowFailed.insert(n.id); }
        json jn; jn["id"]=n.id; jn["name"]=n.name; jn["segs"]=json::array(); jn["vias"]=json::array(); jn["fail"]=nfail;
        for(auto&s:n.segs) jn["segs"].push_back({s.layer,s.x1,s.y1,s.x2,s.y2,s.w}); for(auto&v:n.vias) jn["vias"].push_back({v.x,v.y});
        out["nets"].push_back(jn);
        if(oi%20==0) fprintf(stderr,"routed %d/%zu (%s)\n",oi+1,order.size(),n.name.c_str());
    }
    out["failures"]=failures;
    fprintf(stderr,"pass %d: failures=%d\n",pass,failures);
    if(failures>0 && pass<2){ for(int id:nowFailed) failedNets.insert(id); pass++; goto restart; }
    FILE*f=fopen(argv[2],"w"); fputs(out.dump().c_str(),f); fclose(f);
    fprintf(stderr,"done, failures=%d\n",failures);
    return 0;
}
