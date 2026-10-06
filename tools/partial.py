import os, json, pcbnew, route, gen_pcb
def route_partial(terms, riter="2", drop_box=10.0):
    b=pcbnew.LoadBoard(route.PCB); gen_pcb.setup_board(b)
    out_dir=os.path.join(gen_pcb.KICAD_DIR,"..","out"); rp=os.path.join(out_dir,"partial_in.json"); rr=os.path.join(out_dir,"partial_out.json")
    prob=route.export_problem(b, rp, only_terms=terms, fixed=True, strips=False)
    prob["drop_box"]=drop_box; prob["penalty"]=120.0
    json.dump(prob, open(rp,"w"))
    log=route.run_router(rp, rr, {"RITER": riter})
    ns,nv,ff=route.import_result(b, rr)
    for z in b.Zones(): z.SetIsFilled(False)
    route.fill_zones(b); b.Save(route.PCB)
    return ns,nv,ff,log.strip().splitlines()[-1]
if __name__=="__main__":
    import sys
    terms=[tuple(x.split(".")) for x in sys.argv[1].split(",")]
    print(route_partial(terms))
