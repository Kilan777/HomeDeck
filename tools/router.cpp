// Negotiated-congestion grid router (PathFinder style) for 2 signal layers + plane via-drops.
// Hard obstacles: pads, keepouts, escape strips.  Soft obstacles: other nets' tracks/vias (penalised, ripped up on conflict).
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <vector>
#include <string>
#include <queue>
#include <map>
#include <set>
#include <algorithm>
#include <functional>
#include <array>
#include <nlohmann/json.hpp>
using json = nlohmann::json;
using namespace std;

struct Poly { vector<pair<double,double>> pts; int net; int layer; };
struct Seg { int layer; double x1,y1,x2,y2,w; };
struct Via { double x,y; };
struct Terminal { int pad; int layer; vector<pair<int,int>> cells; double cx, cy; double w; bool nodrop; };
struct Net {
    int id; string name; double width, clearance, viaCost; bool plane; int planeLayer;
    vector<Terminal> terms; int priority; int pair_of;
    vector<Seg> segs; vector<Via> vias; vector<array<int,3>> cells; // routed cells (L,x,y), L=-1 marks plane via
    bool routed=false; int fail=0;
};

static int NX, NY; static double RES;
static const int NL = 2;
static double VIA_R = 0.3, VIA_DRILL_R = 0.15;
// hard maps
static vector<float> hd1[NL], hd2[NL]; static vector<int> ho1[NL], ho2[NL];
static vector<float> hvd1, hvd2; static vector<int> hvo1, hvo2; static vector<float> hvhd;
static vector<int> in2owner; static vector<unsigned char> hardblock;
static vector<int> pnetocc[NL], padowner[NL]; static vector<float> areaClr;
// soft maps (tracks of routed nets)
static vector<float> sd1[NL], sd2[NL], sd3[NL]; static vector<int> so1[NL], so2[NL], so3[NL];
static vector<float> svd1, svd2; static vector<int> svo1, svo2; static vector<float> svhd; static vector<int> svhn;
static vector<int> tnetocc[NL], tcomp[NL]; // track occupancy: net id, and comp tag
static vector<float> hist[NL]; // history cost

inline int idx(int x,int y){ return y*NX+x; }
inline double cx(int x){ return x*RES; }
inline double cy(int y){ return y*RES; }

double pointPolyDist(double px,double py,const vector<pair<double,double>>&P, bool &inside){
    int n=P.size(); double best=1e9; inside=false;
    for(int i=0,j=n-1;i<n;j=i++){
        double xi=P[i].first, yi=P[i].second, xj=P[j].first, yj=P[j].second;
        if( ((yi>py)!=(yj>py)) && (px < (xj-xi)*(py-yi)/(yj-yi)+xi) ) inside=!inside;
        double dx=xj-xi, dy=yj-yi; double l2=dx*dx+dy*dy; double t = l2>0? max(0.0,min(1.0,((px-xi)*dx+(py-yi)*dy)/l2)):0;
        double d=hypot(px-(xi+t*dx),py-(yi+t*dy)); if(d<best) best=d;
    }
    return best;
}
void upd3(vector<float>&D1,vector<int>&O1,vector<float>&D2,vector<int>&O2,vector<float>&D3,vector<int>&O3,int c,float d,int net){
    // keep three nearest distinct nets
    float ds[4]={D1[c],D2[c],D3[c],d}; int os[4]={O1[c],O2[c],O3[c],net};
    // merge same net
    for(int i=0;i<3;i++) if(os[i]==net){ if(d<ds[i]) ds[i]=d; ds[3]=1e9f; os[3]=-1; break; }
    // sort by distance
    for(int i=0;i<4;i++) for(int j=i+1;j<4;j++) if(ds[j]<ds[i]){ swap(ds[i],ds[j]); swap(os[i],os[j]); }
    D1[c]=ds[0];O1[c]=os[0];D2[c]=ds[1];O2[c]=os[1];D3[c]=ds[2];O3[c]=os[2];
}
void upd(vector<float>&D1,vector<int>&O1,vector<float>&D2,vector<int>&O2,int c,float d,int net){
    if(O1[c]==net){ if(d<D1[c]) D1[c]=d; return; }
    if(O2[c]==net){ if(d<D2[c]) D2[c]=d; if(D2[c]<D1[c]){ swap(D1[c],D2[c]); swap(O1[c],O2[c]); } return; }
    if(d<D1[c]){ D2[c]=D1[c]; O2[c]=O1[c]; D1[c]=d; O1[c]=net; }
    else if(d<D2[c]){ D2[c]=d; O2[c]=net; }
}
static double RMAX=0.7;

void addPolyHard(const Poly&P, bool markOcc, int padIndex){
    double minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9;
    for(auto&p:P.pts){minx=min(minx,p.first);maxx=max(maxx,p.first);miny=min(miny,p.second);maxy=max(maxy,p.second);}
    int x0=max(0,(int)floor((minx-RMAX)/RES)), x1=min(NX-1,(int)ceil((maxx+RMAX)/RES));
    int y0=max(0,(int)floor((miny-RMAX)/RES)), y1=min(NY-1,(int)ceil((maxy+RMAX)/RES));
    for(int y=y0;y<=y1;y++) for(int x=x0;x<=x1;x++){
        bool inside; double d=pointPolyDist(cx(x),cy(y),P.pts,inside); if(inside) d=0;
        if(d>RMAX) continue; int c=idx(x,y);
        for(int L=0;L<NL;L++) if(P.layer==L||P.layer==2){ upd(hd1[L],ho1[L],hd2[L],ho2[L],c,(float)d,P.net); if(inside&&markOcc&&P.net>0){ pnetocc[L][c]=P.net; padowner[L][c]=padIndex; } }
        upd(hvd1,hvo1,hvd2,hvo2,c,(float)d,P.net);
    }
}
void addSegHard(const Seg&s,int net,int padIndex){
    double minx=min(s.x1,s.x2)-s.w, maxx=max(s.x1,s.x2)+s.w, miny=min(s.y1,s.y2)-s.w, maxy=max(s.y1,s.y2)+s.w;
    int x0=max(0,(int)floor((minx-RMAX)/RES)), x1=min(NX-1,(int)ceil((maxx+RMAX)/RES)), y0=max(0,(int)floor((miny-RMAX)/RES)), y1=min(NY-1,(int)ceil((maxy+RMAX)/RES));
    double dx=s.x2-s.x1, dy=s.y2-s.y1, l2=dx*dx+dy*dy;
    for(int y=y0;y<=y1;y++) for(int x=x0;x<=x1;x++){
        double px=cx(x),py=cy(y); double t=l2>0?max(0.0,min(1.0,((px-s.x1)*dx+(py-s.y1)*dy)/l2)):0;
        double d=hypot(px-(s.x1+t*dx),py-(s.y1+t*dy))-s.w/2; if(d<0)d=0; if(d>RMAX) continue; int c=idx(x,y);
        upd(hd1[s.layer],ho1[s.layer],hd2[s.layer],ho2[s.layer],c,(float)d,net);
        if(d<=0.0001){ pnetocc[s.layer][c]=net; if(padIndex>=0) padowner[s.layer][c]=padIndex; }
        upd(hvd1,hvo1,hvd2,hvo2,c,(float)d,net);
    }
}
void addViaHard(const Via&v,int net,double vr,double vdr,int padIndex){
    int x0=max(0,(int)floor((v.x-vr-RMAX-0.6)/RES)), x1=min(NX-1,(int)ceil((v.x+vr+RMAX+0.6)/RES)), y0=max(0,(int)floor((v.y-vr-RMAX-0.6)/RES)), y1=min(NY-1,(int)ceil((v.y+vr+RMAX+0.6)/RES));
    for(int y=y0;y<=y1;y++) for(int x=x0;x<=x1;x++){
        double dh=hypot(cx(x)-v.x,cy(y)-v.y)-vdr; int c=idx(x,y); if(dh<hvhd[c]) hvhd[c]=(float)dh;
        double d=dh+vdr-vr; if(d<0)d=0; if(d>RMAX) continue;
        for(int L=0;L<NL;L++){ upd(hd1[L],ho1[L],hd2[L],ho2[L],c,(float)d,net); if(d<=0.0001){ pnetocc[L][c]=net; if(padIndex>=0) padowner[L][c]=padIndex; } }
        upd(hvd1,hvo1,hvd2,hvo2,c,(float)d,net);
    }
}
void addSegSoft(const Seg&s,int net,int comp){
    double minx=min(s.x1,s.x2)-s.w, maxx=max(s.x1,s.x2)+s.w, miny=min(s.y1,s.y2)-s.w, maxy=max(s.y1,s.y2)+s.w;
    int x0=max(0,(int)floor((minx-RMAX)/RES)), x1=min(NX-1,(int)ceil((maxx+RMAX)/RES)), y0=max(0,(int)floor((miny-RMAX)/RES)), y1=min(NY-1,(int)ceil((maxy+RMAX)/RES));
    double dx=s.x2-s.x1, dy=s.y2-s.y1, l2=dx*dx+dy*dy;
    for(int y=y0;y<=y1;y++) for(int x=x0;x<=x1;x++){
        double px=cx(x),py=cy(y); double t=l2>0?max(0.0,min(1.0,((px-s.x1)*dx+(py-s.y1)*dy)/l2)):0;
        double d=hypot(px-(s.x1+t*dx),py-(s.y1+t*dy))-s.w/2; if(d<0)d=0; if(d>RMAX) continue; int c=idx(x,y);
        upd3(sd1[s.layer],so1[s.layer],sd2[s.layer],so2[s.layer],sd3[s.layer],so3[s.layer],c,(float)d,net);
        if(d<=0.0001){ tnetocc[s.layer][c]=net; tcomp[s.layer][c]=comp; }
        upd(svd1,svo1,svd2,svo2,c,(float)d,net);
    }
}
void addViaSoft(const Via&v,int net,int comp){
    int x0=max(0,(int)floor((v.x-VIA_R-RMAX-0.6)/RES)), x1=min(NX-1,(int)ceil((v.x+VIA_R+RMAX+0.6)/RES)), y0=max(0,(int)floor((v.y-VIA_R-RMAX-0.6)/RES)), y1=min(NY-1,(int)ceil((v.y+VIA_R+RMAX+0.6)/RES));
    for(int y=y0;y<=y1;y++) for(int x=x0;x<=x1;x++){
        double dh=hypot(cx(x)-v.x,cy(y)-v.y)-VIA_DRILL_R; int c=idx(x,y); if(dh<svhd[c]){ svhd[c]=(float)dh; svhn[c]=net; }
        double d=dh+VIA_DRILL_R-VIA_R; if(d<0)d=0; if(d>RMAX) continue;
        for(int L=0;L<NL;L++){ upd3(sd1[L],so1[L],sd2[L],so2[L],sd3[L],so3[L],c,(float)d,net); if(d<=0.0001){ tnetocc[L][c]=net; tcomp[L][c]=comp; } }
        upd(svd1,svo1,svd2,svo2,c,(float)d,net);
    }
}
void clearSoft(){ size_t N=(size_t)NX*NY; for(int L=0;L<NL;L++){ sd1[L].assign(N,1e9f); sd2[L].assign(N,1e9f); sd3[L].assign(N,1e9f); so1[L].assign(N,-1); so2[L].assign(N,-1); so3[L].assign(N,-1); tnetocc[L].assign(N,0); tcomp[L].assign(N,-1);} svd1.assign(N,1e9f); svd2.assign(N,1e9f); svo1.assign(N,-1); svo2.assign(N,-1); svhd.assign(N,1e9f); svhn.assign(N,-1); }

inline double reff(int c,double clr,double w){ double a=areaClr[c]; return (a<clr?a:clr)+w/2; }
static double CUR_W=0.2, CUR_CLR=0.16;
inline bool hardFree(int L,int c,int net,double r){
    r=reff(c,CUR_CLR,CUR_W);
    if(hardblock[c]) return false;
    if(ho1[L][c]!=net && ho1[L][c]!=-1 && hd1[L][c]<r) return false;
    if(ho2[L][c]!=net && ho2[L][c]!=-1 && hd2[L][c]<r) return false;
    return true;
}
inline int softConflictCount(int L,int c,int net,double r){
    r=reff(c,CUR_CLR,CUR_W)-1e-4; int k=0;
    if(so1[L][c]!=net && so1[L][c]!=-1 && sd1[L][c]<r) k++;
    if(so2[L][c]!=net && so2[L][c]!=-1 && sd2[L][c]<r) k++;
    if(so3[L][c]!=net && so3[L][c]!=-1 && sd3[L][c]<r) k++;
    return k;
}
inline bool softConflict(int L,int c,int net,double r){ return softConflictCount(L,c,net,r)>0; }
inline int softConflictWith(int L,int c,int net,double r){ r=reff(c,CUR_CLR,CUR_W)-1e-4; if(so1[L][c]!=net && so1[L][c]!=-1 && sd1[L][c]<r) return so1[L][c]; if(so2[L][c]!=net && so2[L][c]!=-1 && sd2[L][c]<r) return so2[L][c]; if(so3[L][c]!=net && so3[L][c]!=-1 && sd3[L][c]<r) return so3[L][c]; return -1; }
inline bool viaHardFree(int c,int net,double clr){
    clr=min(clr,(double)areaClr[c]);
    if(hardblock[c]) return false; if(hvhd[c]<VIA_DRILL_R+0.5) return false; double r=VIA_R+clr;
    if(hvo1[c]!=net && hvd1[c]<r) return false; if(hvo2[c]!=net && hvd2[c]<r) return false; return true;
}
inline bool viaSoftConflict(int c,int net,double clr){
    clr=min(clr,(double)areaClr[c]);
    if(svhd[c]<VIA_DRILL_R+0.5-1e-4) return true; // any other via too close (own-net stacking also disallowed)
    double r=VIA_R+clr-1e-4;
    if(svo1[c]!=net && svd1[c]<r) return true; if(svo2[c]!=net && svd2[c]<r) return true; return false;
}
inline bool viaSoftConflictOther(int c,int net,double clr){
    // same as above but ignoring this net's own vias (used for post-route conflict detection)
    clr=min(clr,(double)areaClr[c]);
    if(svhd[c]<VIA_DRILL_R+0.5-1e-4 && svhn[c]!=net) return true; double r=VIA_R+clr-1e-4;
    if(svo1[c]!=net && svd1[c]<r) return true; if(svo2[c]!=net && svd2[c]<r) return true; return false;
}

struct Node { double f,g; int L,x,y; bool operator<(const Node&o)const{ return f>o.f; } };
static double PENALTY=3.0; static double HIST_W=1.0;

vector<array<int,3>> astar(int net,double r,double clr,const vector<array<int,3>>&sources,function<bool(int,int,int)> isGoal,
        function<double(int,int,int)> heur,int bx0,int by0,int bx1,int by1,double viaCost,function<double(int,int,int)> extraCost,
        int planeGoalLayer,function<bool(int,int)> planeGoalHere,long long maxExpand,long long&expandedOut){
    CUR_CLR=clr; CUR_W=2*(r-clr);
    size_t N=(size_t)NX*NY; static vector<float> g[NL]; static vector<int> par[NL]; static vector<unsigned char> closed[NL];
    for(int L=0;L<NL;L++){ if(g[L].size()!=N){ g[L].assign(N,1e30f); par[L].assign(N,-1); closed[L].assign(N,0);} }
    vector<int> touched[NL]; priority_queue<Node> pq;
    vector<array<int,3>> srcs; for(auto&s:sources) if(hardFree(s[0],idx(s[1],s[2]),net,r)) srcs.push_back(s); if(srcs.empty()) srcs=sources;
    for(auto&s:srcs){ int c=idx(s[1],s[2]); if(g[s[0]][c]>0){ g[s[0]][c]=0; par[s[0]][c]=-2; touched[s[0]].push_back(c); pq.push({heur(s[0],s[1],s[2]),0,s[0],s[1],s[2]}); } }
    const int dx8[8]={1,-1,0,0,1,1,-1,-1}, dy8[8]={0,0,1,-1,1,-1,1,-1};
    long long expanded=0; array<int,3> found={-1,-1,-1}; bool planeHit=false;
    while(!pq.empty()){
        Node n=pq.top(); pq.pop(); int c=idx(n.x,n.y);
        if(closed[n.L][c]) continue; closed[n.L][c]=1; expanded++;
        if(expanded>maxExpand) break;
        if(isGoal(n.L,n.x,n.y)){ found={n.L,n.x,n.y}; break; }
        if(planeGoalLayer>0 && planeGoalHere(n.x,n.y) && viaHardFree(c,net,clr) && !viaSoftConflict(c,net,clr)){ found={n.L,n.x,n.y}; planeHit=true; break; }
        for(int k=0;k<8;k++){
            int nx=n.x+dx8[k], ny=n.y+dy8[k]; if(nx<bx0||ny<by0||nx>bx1||ny>by1) continue; int nc=idx(nx,ny);
            if(closed[n.L][nc]) continue; if(!hardFree(n.L,nc,net,r)) continue;
            if(k>=4){ if(!hardFree(n.L,idx(n.x+dx8[k],n.y),net,r)||!hardFree(n.L,idx(n.x,n.y+dy8[k]),net,r)) continue; }
            double step=(k<4?1.0:1.41421356)*RES + extraCost(n.L,nx,ny) + hist[n.L][nc]*HIST_W*RES;
            { int k=softConflictCount(n.L,nc,net,r); if(k) step+=PENALTY*RES*k; }
            double ng=n.g+step; if(ng<g[n.L][nc]){ if(g[n.L][nc]>=1e29f) touched[n.L].push_back(nc); g[n.L][nc]=ng; par[n.L][nc]=c*NL+n.L; pq.push({ng+heur(n.L,nx,ny),ng,n.L,nx,ny}); }
        }
        if(viaHardFree(c,net,clr)){
            int oL=1-n.L; if(!closed[oL][c] && hardFree(oL,c,net,r)){ double ng=n.g+viaCost+(viaSoftConflict(c,net,clr)?PENALTY*RES*6:0)+hist[oL][c]*HIST_W*RES; if(ng<g[oL][c]){ if(g[oL][c]>=1e29f) touched[oL].push_back(c); g[oL][c]=ng; par[oL][c]=c*NL+n.L; pq.push({ng+heur(oL,n.x,n.y),ng,oL,n.x,n.y}); } }
        }
    }
    expandedOut=expanded;
    vector<array<int,3>> path;
    if(found[0]>=0){ int L=found[0], c=idx(found[1],found[2]); while(true){ path.push_back({L,c%NX,c/NX}); int p=par[L][c]; if(p<0) break; L=p%NL; c=p/NL; } reverse(path.begin(),path.end()); if(planeHit) path.push_back({-1,found[1],found[2]}); }
    for(int L=0;L<NL;L++){ for(int c:touched[L]){ g[L][c]=1e30f; par[L][c]=-1; closed[L][c]=0; } }
    return path;
}

void pathToGeom(const vector<array<int,3>>&path,double w,vector<Seg>&segs,vector<Via>&vias){
    if(path.empty()) return; vector<array<int,3>> p=path; if(p.back()[0]==-1){ vias.push_back({cx(p.back()[1]),cy(p.back()[2])}); p.pop_back(); }
    size_t i=0; while(i+1<p.size()){ if(p[i][0]!=p[i+1][0]){ vias.push_back({cx(p[i][1]),cy(p[i][2])}); i++; continue; }
        size_t j=i+1; int ddx=p[j][1]-p[i][1], ddy=p[j][2]-p[i][2]; while(j+1<p.size() && p[j+1][0]==p[j][0] && p[j+1][1]-p[j][1]==ddx && p[j+1][2]-p[j][2]==ddy) j++;
        segs.push_back({p[i][0],cx(p[i][1]),cy(p[i][2]),cx(p[j][1]),cy(p[j][2]),w}); i=j; }
}

int main(int argc,char**argv){
    if(argc<3){ fprintf(stderr,"usage: router in.json out.json\n"); return 1; }
    json J; { FILE*f=fopen(argv[1],"r"); string s; char buf[65536]; size_t n; while((n=fread(buf,1,sizeof buf,f))>0) s.append(buf,n); fclose(f); J=json::parse(s); }
    double W=J["width"], H=J["height"]; RES=J["res"]; NX=(int)ceil(W/RES)+1; NY=(int)ceil(H/RES)+1; VIA_R=J["via_dia"].get<double>()/2; RMAX=J["rmax"];
    size_t N=(size_t)NX*NY;
    for(int L=0;L<NL;L++){ hd1[L].assign(N,1e9f); hd2[L].assign(N,1e9f); ho1[L].assign(N,-1); ho2[L].assign(N,-1); pnetocc[L].assign(N,0); padowner[L].assign(N,-1); hist[L].assign(N,0.f);}
    hvd1.assign(N,1e9f); hvd2.assign(N,1e9f); hvo1.assign(N,-1); hvo2.assign(N,-1); hvhd.assign(N,1e9f); in2owner.assign(N,0); hardblock.assign(N,0);
    double edge=J["edge_clearance"];
    for(auto&h:J["holes"]){ double hx=h[0],hy=h[1],hr=h[2]; int hn=h.size()>3?h[3].get<int>():0;
        { double r2=hr-0.1; int x0=max(0,(int)floor((hx-r2-1.0)/RES)),x1=min(NX-1,(int)ceil((hx+r2+1.0)/RES)),y0=max(0,(int)floor((hy-r2-1.0)/RES)),y1=min(NY-1,(int)ceil((hy+r2+1.0)/RES));
          for(int y=y0;y<=y1;y++)for(int x=x0;x<=x1;x++){ double d=hypot(cx(x)-hx,cy(y)-hy)-r2; int c=idx(x,y); if(d<hvhd[c]) hvhd[c]=(float)d; } }
        if(hn>0) continue;
        int x0=max(0,(int)floor((hx-hr-RMAX)/RES)),x1=min(NX-1,(int)ceil((hx+hr+RMAX)/RES)),y0=max(0,(int)floor((hy-hr-RMAX)/RES)),y1=min(NY-1,(int)ceil((hy+hr+RMAX)/RES));
        for(int y=y0;y<=y1;y++)for(int x=x0;x<=x1;x++){ double d=hypot(cx(x)-hx,cy(y)-hy)-hr; if(d<0)d=0; if(d>RMAX)continue; int c=idx(x,y); for(int L=0;L<NL;L++) upd(hd1[L],ho1[L],hd2[L],ho2[L],c,(float)d,0); upd(hvd1,hvo1,hvd2,hvo2,c,(float)d,0);} }
    { vector<pair<double,double>> P; for(auto&p:J["outline"]) P.push_back({p[0],p[1]});
      for(int y=0;y<NY;y++)for(int x=0;x<NX;x++){ bool inside; double d=pointPolyDist(cx(x),cy(y),P,inside); int c=idx(x,y); if(!inside||d<edge) hardblock[c]=1; else if(d<edge+RMAX){ for(int L=0;L<NL;L++) upd(hd1[L],ho1[L],hd2[L],ho2[L],c,(float)(d-edge),0); upd(hvd1,hvo1,hvd2,hvo2,c,(float)(d-edge),0);} } }
    for(auto&sl:J["slots"]){ vector<pair<double,double>> P; for(auto&p:sl) P.push_back({p[0],p[1]}); double minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9; for(auto&p:P){minx=min(minx,p.first);maxx=max(maxx,p.first);miny=min(miny,p.second);maxy=max(maxy,p.second);}
        for(int y=max(0,(int)((miny-2)/RES));y<=min(NY-1,(int)((maxy+2)/RES));y++)for(int x=max(0,(int)((minx-2)/RES));x<=min(NX-1,(int)((maxx+2)/RES));x++){ bool inside; double d=pointPolyDist(cx(x),cy(y),P,inside); int c=idx(x,y); if(inside||d<edge) hardblock[c]=1; else if(d<edge+RMAX){ for(int L=0;L<NL;L++) upd(hd1[L],ho1[L],hd2[L],ho2[L],c,(float)(d-edge),0); upd(hvd1,hvo1,hvd2,hvo2,c,(float)(d-edge),0);} } }
    for(auto&z:J["in2"]){ int net=z["net"]; vector<pair<double,double>> P; for(auto&p:z["poly"]) P.push_back({p[0],p[1]}); double minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9; for(auto&p:P){minx=min(minx,p.first);maxx=max(maxx,p.first);miny=min(miny,p.second);maxy=max(maxy,p.second);}
        for(int y=max(0,(int)(miny/RES));y<=min(NY-1,(int)(maxy/RES));y++)for(int x=max(0,(int)(minx/RES));x<=min(NX-1,(int)(maxx/RES));x++){ bool inside; double d=pointPolyDist(cx(x),cy(y),P,inside); if(inside && d>0.8) in2owner[idx(x,y)]=net; } }
    vector<Poly> pads; int pi=0;
    for(auto&p:J["pads"]){ Poly P; P.net=p["net"]; P.layer=p["layer"]; for(auto&q:p["poly"]) P.pts.push_back({q[0],q[1]}); pads.push_back(P); addPolyHard(P,true,pi); pi++; }
    for(auto&e:J["escapes"]){ Poly P; P.net=e["net"]; P.layer=e["layer"]; for(auto&q:e["poly"]) P.pts.push_back({q[0],q[1]}); addPolyHard(P,false,-1); }
    if(J.contains("tracks")) for(auto&t:J["tracks"]){ Seg sg{t[0],t[1],t[2],t[3],t[4],t[5]}; addSegHard(sg,t[6],t.size()>7?t[7].get<int>():-1); }
    if(J.contains("fixed_vias")) for(auto&v:J["fixed_vias"]){ Via vv{v[0],v[1]}; addViaHard(vv,v[2],v.size()>3?v[3].get<double>():VIA_R,v.size()>4?v[4].get<double>():VIA_DRILL_R,v.size()>5?v[5].get<int>():-1); }
    areaClr.assign(N,1.0f);
    if(J.contains("clr_areas")) for(auto&a:J["clr_areas"]){ double ax0=a[0],ay0=a[1],ax1=a[2],ay1=a[3]; float cl=a[4]; for(int y=max(0,(int)(ay0/RES));y<=min(NY-1,(int)(ay1/RES));y++)for(int x=max(0,(int)(ax0/RES));x<=min(NX-1,(int)(ax1/RES));x++) areaClr[idx(x,y)]=cl; }
    fprintf(stderr,"grid %dx%d, %zu pads, %zu escape strips\n",NX,NY,pads.size(),J["escapes"].size());
    vector<Net> nets; map<int,int> netIndex;
    for(auto&n:J["nets"]){ Net t; t.id=n["id"]; t.name=n["name"]; t.width=n["width"]; t.clearance=n["clearance"]; t.plane=n["plane"]; t.planeLayer=n["plane_layer"]; t.priority=n["priority"]; t.pair_of=n["pair_of"]; t.viaCost=n["via_cost"];
        for(auto&tm:n["terms"]){ Terminal T; T.pad=tm["pad"]; T.layer=tm["layer"]; T.cx=tm["cx"]; T.cy=tm["cy"]; T.w=tm["w"]; T.nodrop=tm["nodrop"]; if(tm.contains("cells")) for(auto&c:tm["cells"]) T.cells.push_back({c[0],c[1]}); t.terms.push_back(T);} netIndex[t.id]=nets.size(); nets.push_back(t); }
    for(auto&n:nets) for(auto&T:n.terms){ if(!T.cells.empty()) continue; Poly&P=pads[T.pad]; double minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9; for(auto&p:P.pts){minx=min(minx,p.first);maxx=max(maxx,p.first);miny=min(miny,p.second);maxy=max(maxy,p.second);}
        for(int y=max(0,(int)floor(miny/RES));y<=min(NY-1,(int)ceil(maxy/RES));y++)for(int x=max(0,(int)floor(minx/RES));x<=min(NX-1,(int)ceil(maxx/RES));x++){ int c=idx(x,y); int L=(T.layer==2)?0:T.layer; if(padowner[L][c]==T.pad) T.cells.push_back({x,y}); }
        if(T.cells.empty()){ T.cells.push_back({(int)round(T.cx/RES),(int)round(T.cy/RES)}); } }
    long long maxExpand=J["max_expand"]; int maxIter=J.value("max_iter",12); if(getenv("RITER")) maxIter=atoi(getenv("RITER"));
    auto estLen=[&](Net&n){ double s=0; for(size_t i=1;i<n.terms.size();i++){ double b=1e9; for(size_t j=0;j<i;j++) b=min(b,hypot(n.terms[i].cx-n.terms[j].cx,n.terms[i].cy-n.terms[j].cy)); s+=b;} return s; };
    vector<int> order; for(size_t i=0;i<nets.size();i++) order.push_back(i);
    sort(order.begin(),order.end(),[&](int a,int b){ if(nets[a].priority!=nets[b].priority) return nets[a].priority<nets[b].priority; return estLen(nets[a])<estLen(nets[b]); });
    set<int> toRoute(order.begin(),order.end());

    auto routeNet=[&](Net&n){
        n.segs.clear(); n.vias.clear(); n.cells.clear(); n.fail=0; double r=n.clearance+n.width/2;
        vector<int> comp(n.terms.size()); for(size_t i=0;i<comp.size();i++) comp[i]=i;
        function<int(int)> find=[&](int a){ return comp[a]==a?a:comp[a]=find(comp[a]); };
        set<long long> attract; Net* partner=nullptr; if(n.pair_of>=0 && netIndex.count(n.pair_of)){ partner=&nets[netIndex[n.pair_of]]; if(!partner->routed) partner=nullptr; }
        if(partner){ double want=n.width+n.clearance+0.12; int rad=(int)ceil((want+0.2)/RES); map<long long,double> mind;
            for(auto&p:partner->cells){ if(p[0]<0)continue; for(int dy=-rad;dy<=rad;dy++)for(int dx=-rad;dx<=rad;dx++){ int x=p[1]+dx,y=p[2]+dy; if(x<0||y<0||x>=NX||y>=NY) continue; double d=hypot(dx*RES,dy*RES); long long k=((long long)p[0]<<40)|((long long)y<<20)|x; auto it=mind.find(k); if(it==mind.end()||d<it->second) mind[k]=d; } }
            for(auto&kv:mind) if(kv.second>=want+0.02 && kv.second<=want+0.16) attract.insert(kv.first); }
        auto extraCost=[&](int L,int x,int y)->double{ if(!partner) return 0.0; long long k=((long long)L<<40)|((long long)y<<20)|x; return attract.count(k)? -RES*0.6 : RES*0.8; };
        int ref=-1; long long ex; set<int> dropped;
        if(n.plane){
            for(size_t ti=0;ti<n.terms.size();ti++){ Terminal&T=n.terms[ti];
                if(T.layer==2){ int cc0=idx((int)round(T.cx/RES),(int)round(T.cy/RES)); bool onp=(n.planeLayer==1)||(in2owner[cc0]==n.id); if(onp){ if(ref<0) ref=ti; else comp[find(ti)]=find(ref); dropped.insert(ti); } continue; }
                if(T.nodrop) continue;
                { bool near=false; for(size_t tj=0;tj<ti;tj++){ if(dropped.count(tj) && hypot(n.terms[tj].cx-T.cx,n.terms[tj].cy-T.cy)<2.0){ near=true; break; } } if(near) continue; }
                double tw=min(n.width,T.w); double rr=n.clearance+tw/2; vector<array<int,3>> src; for(auto&c:T.cells) src.push_back({T.layer,c.first,c.second});
                int box=(int)(J.value("drop_box",4.0)/RES); int bx0=max(0,(int)(T.cx/RES)-box),by0=max(0,(int)(T.cy/RES)-box),bx1=min(NX-1,(int)(T.cx/RES)+box),by1=min(NY-1,(int)(T.cy/RES)+box);
                auto planeHere=[&](int x,int y){ if(n.planeLayer==1) return true; return in2owner[idx(x,y)]==n.id; };
                auto path=astar(n.id,rr,n.clearance,src,[&](int,int,int){return false;},[&](int,int,int){return 0.0;},bx0,by0,bx1,by1,n.viaCost,[&](int,int,int){return 0.0;},n.planeLayer,planeHere,80000,ex);
                if(path.empty()) continue;
                vector<Seg> segs; vector<Via> vias; pathToGeom(path,tw,segs,vias);
                if(ref<0) ref=ti; else comp[find(ti)]=find(ref); dropped.insert(ti);
                int cc=find(ref); for(auto&s:segs){ n.segs.push_back(s); addSegSoft(s,n.id,cc);} for(auto&v:vias){ n.vias.push_back(v); addViaSoft(v,n.id,cc);} for(auto&p:path) n.cells.push_back(p);
            }
        }
        if(ref<0) ref=0;
        for(int iter=0;iter<(int)n.terms.size()*2;iter++){
            int a=-1; for(size_t i=0;i<n.terms.size();i++){ if(n.terms[i].nodrop){ comp[find(i)]=find(ref); continue; } if(find(i)!=find(ref)){ a=i; break; } } if(a<0) break;
            Terminal&T=n.terms[a]; int ca=find(a);
            vector<array<int,3>> src; for(auto&c:T.cells) src.push_back({T.layer==2?0:T.layer,c.first,c.second}); if(T.layer==2) for(auto&c:T.cells) src.push_back({1,c.first,c.second});
            auto isGoal=[&](int L,int x,int y){ int c=idx(x,y); if(pnetocc[L][c]==n.id){ int po=padowner[L][c]; for(size_t i=0;i<n.terms.size();i++) if(n.terms[i].pad==po) return find(i)!=ca; return false; } if(tnetocc[L][c]==n.id){ int cc=tcomp[L][c]; return cc>=0 && find(cc)!=ca; } return false; };
            double minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9; vector<pair<double,double>> goals; for(size_t i=0;i<n.terms.size();i++) if(find(i)!=ca) goals.push_back({n.terms[i].cx,n.terms[i].cy});
            for(auto&g:goals){minx=min(minx,g.first);maxx=max(maxx,g.first);miny=min(miny,g.second);maxy=max(maxy,g.second);} minx=min(minx,T.cx);maxx=max(maxx,T.cx);miny=min(miny,T.cy);maxy=max(maxy,T.cy);
            auto heur=[&](int L,int x,int y){ double b=1e9; double px=cx(x),py=cy(y); for(auto&g:goals) b=min(b,hypot(px-g.first,py-g.second)); return max(0.0,b-1.0)*0.99; };
            double tw=n.width; if(n.plane) tw=min(n.width,T.w); double rr=n.clearance+tw/2;
            vector<array<int,3>> path; double margins[3]={15,40,200};
            for(int m=0;m<3&&path.empty();m++){ int bx0=max(0,(int)((minx-margins[m])/RES)),by0=max(0,(int)((miny-margins[m])/RES)),bx1=min(NX-1,(int)((maxx+margins[m])/RES)),by1=min(NY-1,(int)((maxy+margins[m])/RES));
                path=astar(n.id,rr,n.clearance,src,isGoal,heur,bx0,by0,bx1,by1,n.viaCost,extraCost,0,[&](int,int){return false;},maxExpand,ex); }
            if(path.empty()){ n.fail++; fprintf(stderr,"  FAILED: %s term %d (%.1f,%.1f) expanded=%lld srcfree=%d/%zu\n",n.name.c_str(),a,T.cx,T.cy,ex,(int)count_if(src.begin(),src.end(),[&](const array<int,3>&s0){ CUR_CLR=n.clearance; CUR_W=tw; return hardFree(s0[0],idx(s0[1],s0[2]),n.id,rr);}),src.size());
                if(getenv("RDEBUG")){ for(auto&s0:src){ int c=idx(s0[1],s0[2]); fprintf(stderr,"      src L%d (%.1f,%.1f) hard=%d o1=%d d1=%.3f o2=%d d2=%.3f\n",s0[0],cx(s0[1]),cy(s0[2]),hardblock[c],ho1[s0[0]][c],hd1[s0[0]][c],ho2[s0[0]][c],hd2[s0[0]][c]); } }
                comp[ca]=find(ref); continue; }
            auto&e=path.back(); int c=idx(e[1],e[2]); int hit=-1; if(pnetocc[e[0]][c]==n.id){ int po=padowner[e[0]][c]; for(size_t i=0;i<n.terms.size();i++) if(n.terms[i].pad==po) hit=find(i);} else if(tnetocc[e[0]][c]==n.id) hit=find(tcomp[e[0]][c]);
            int newc; if(hit>=0){ comp[find(ca)]=hit; newc=find(hit);} else { comp[ca]=find(ref); newc=find(ref); }
            vector<Seg> segs; vector<Via> vias; pathToGeom(path,tw,segs,vias);
            for(auto&s:segs){ n.segs.push_back(s); addSegSoft(s,n.id,newc);} for(auto&v:vias){ n.vias.push_back(v); addViaSoft(v,n.id,newc);} for(auto&p:path) n.cells.push_back(p);
        }
        n.routed=true;
    };
    auto rebuildSoft=[&](const set<int>&skip){ clearSoft(); for(size_t i=0;i<nets.size();i++){ if(skip.count(i)) continue; Net&n=nets[i]; if(!n.routed) continue; for(auto&s:n.segs) addSegSoft(s,n.id,0); for(auto&v:n.vias) addViaSoft(v,n.id,0); } };
    auto conflicts=[&](Net&n)->int{ int k=0; CUR_CLR=n.clearance; CUR_W=n.width; for(auto&p:n.cells){ int c=idx(p[1],p[2]); if(p[0]<0){ if(viaSoftConflictOther(c,n.id,n.clearance)) k++; continue; } double r=n.clearance+n.width/2; if(softConflict(p[0],c,n.id,r)) k++; } for(auto&v:n.vias){ int c=idx((int)round(v.x/RES),(int)round(v.y/RES)); if(viaSoftConflictOther(c,n.id,n.clearance)) k++; } return k; };
    PENALTY=J.value("penalty",4.0);
    size_t bestBad=1e9; vector<Net> best; set<int> lastBad;
    HIST_W=J.value("hist_w",3.0);
    for(int it=0;it<maxIter;it++){
        int cnt=0;
        if(it==0){ clearSoft(); for(auto&n:nets) n.routed=false; for(int oi:order){ routeNet(nets[oi]); cnt++; } }
        else {
            // rip-up and reroute only nets that had conflicts, each seeing all other nets' current routes
            for(int oi:order){ if(!lastBad.count(oi)) continue; set<int> skip; skip.insert(oi); rebuildSoft(skip); routeNet(nets[oi]); cnt++; }
        }
        rebuildSoft(set<int>());
        set<int> bad; int totalConf=0, fails=0;
        for(size_t i=0;i<nets.size();i++){ Net&n=nets[i]; int k=conflicts(n); fails+=n.fail; if(k>0||n.fail>0){ bad.insert(i); totalConf+=k; double r=n.clearance+n.width/2; CUR_CLR=n.clearance; CUR_W=n.width; for(auto&p:n.cells){ if(p[0]<0) continue; int c=idx(p[1],p[2]); if(softConflict(p[0],c,n.id,r)) hist[p[0]][c]+=1.0f; } } }
        fprintf(stderr,"iter %d: routed %d nets, nets with conflicts/fails: %zu (conflict cells %d, fails %d), penalty %.1f\n",it,cnt,bad.size(),totalConf,fails,PENALTY);
        if(bad.empty()) break;
        lastBad=bad;
        if(bad.size()<bestBad){ bestBad=bad.size(); best=nets; }
        PENALTY*=1.6; if(PENALTY>400) PENALTY=400;
    }
    { rebuildSoft(set<int>()); set<int> bad; for(size_t i=0;i<nets.size();i++){ Net&n=nets[i]; if(conflicts(n)>0||n.fail>0) bad.insert(i);} if(bad.size()<bestBad){ bestBad=bad.size(); best=nets; } }
    if(!best.empty()) nets=best;
    json out; out["nets"]=json::array(); int failures=0;
    for(auto&n:nets){ json jn; jn["id"]=n.id; jn["name"]=n.name; jn["segs"]=json::array(); jn["vias"]=json::array(); jn["fail"]=n.fail; failures+=n.fail;
        for(auto&s:n.segs) jn["segs"].push_back({s.layer,s.x1,s.y1,s.x2,s.y2,s.w}); for(auto&v:n.vias) jn["vias"].push_back({v.x,v.y}); out["nets"].push_back(jn); }
    rebuildSoft(set<int>()); int confNets=0; map<pair<string,string>,int> pairs;
    for(auto&n:nets){ int k=conflicts(n); if(k>0) confNets++; double r=n.clearance+n.width/2; CUR_CLR=n.clearance; CUR_W=n.width; for(auto&p:n.cells){ if(p[0]<0) continue; int o=softConflictWith(p[0],idx(p[1],p[2]),n.id,r); if(o>=0){ string on=netIndex.count(o)?nets[netIndex[o]].name:"?"; pairs[{n.name,on}]++; if(getenv("RPAIR") && n.name==string(getenv("RPAIR"))) fprintf(stderr,"    cell L%d (%.1f,%.1f) vs %s d=%.3f/%.3f r=%.3f\n",p[0],cx(p[1]),cy(p[2]),on.c_str(),sd1[p[0]][idx(p[1],p[2])],sd2[p[0]][idx(p[1],p[2])],r); } } }
    if(getenv("RDEBUG")){ vector<pair<int,pair<string,string>>> v; for(auto&kv:pairs) v.push_back({kv.second,kv.first}); sort(v.rbegin(),v.rend()); for(size_t i=0;i<v.size()&&i<40;i++) fprintf(stderr,"  conflict %s <-> %s : %d cells\n",v[i].second.first.c_str(),v[i].second.second.c_str(),v[i].first); }
    { json cc=json::array(); for(auto&n:nets){ double r=n.clearance+n.width/2; CUR_CLR=n.clearance; CUR_W=n.width; for(auto&p:n.cells){ if(p[0]<0) continue; int o=softConflictWith(p[0],idx(p[1],p[2]),n.id,r); if(o>=0) cc.push_back({p[0],cx(p[1]),cy(p[2]),n.name,netIndex.count(o)?nets[netIndex[o]].name:"?"}); } } out["conflict_cells"]=cc; }
    out["failures"]=failures; out["conflict_nets"]=confNets;
    FILE*f=fopen(argv[2],"w"); fputs(out.dump().c_str(),f); fclose(f);
    fprintf(stderr,"done: failures=%d conflict nets=%d\n",failures,confNets);
    return 0;
}
