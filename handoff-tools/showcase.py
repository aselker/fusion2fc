import json, sys, re
mid, fname = sys.argv[1], sys.argv[2]
base = "/home/neophile/Documents/Programming/Vibes/fusion/tests/out/corpus/%s/" % mid
c = json.load(open(base + "model.cadir.json")); n = c["native"]["f3d"]
def stream(i): return i.split(":design-")[0]
fe = [f for f in c["model"]["features"] if f["name"] == fname][0]
sc = [s for s in n["design_parameter_scopes"] if s["id"] == fe["native_ref"]][0]
print("scope", sc["kind"], "rec", sc["record_index"], "hist", sc.get("history_state_id"), sc.get("previous_history_state_id"), "op", json.dumps(fe.get("definition", {}).get("op")))
ep = sc.get("extrude_profile", {})
sk = ep.get("entity_suffix")
s = json.load(open(base + "slim.json"))
sid = None
for x in s["sketches"]:
    if x["id"].endswith("@%s" % sk):
        sid = x["id"]
        print("loops", [[(u["entity"].split("@")[1].split("c", 1)[1], u["reversed"]) for u in l] for l in x["profiles"]])
for e in s["sketch_entities"]:
    if e["sketch"] == sid and e["geometry"]["kind"] != "point":
        g = e["geometry"]; gg = {k: (round(v, 3) if isinstance(v, float) else ({kk: round(vv, 3) for kk, vv in v.items()} if isinstance(v, dict) and "u" in v else v)) for k, v in g.items() if k != "curve"}
        print("  ", e["id"].split("@")[1].split("c", 1)[1], "C" if e["construction"] else " ", gg)
for p in n["design_profile_curve_selections"]:
    if stream(p["id"]) == stream(sc["id"]) and p["scope_record_index"] == sc["record_index"]:
        for g in p["groups"]:
            print(" region", [([(e["primary_id"], e["secondary_id"], e["entry_fields"]) for e in r["entries"]], r["outer"]) for r in g["region"]])
            for fr in g["further"]:
                print("  further", [([(e["primary_id"], e["secondary_id"], e["entry_fields"]) for e in r["entries"]], r["outer"]) for r in fr])
rs = ep.get("region_selection")
if rs:
    for r in rs["regions"]:
        print(" regsel", [(m["curve_primary_id"], m["incidence_words"]) for m in r["members"]])
fj = json.load(open("/home/neophile/Documents/Programming/Vibes/fusion/.worktrees/profiles/tests/corpus/truth/%s/features.json" % mid))
skname = None
for it in fj["timeline"]:
    if it["type"] == "ExtrudeFeature" and "".join(it["name"].split()) == "".join(fname.split()):
        prof = it["data"].get("profile"); prof = prof if isinstance(prof, list) else [prof]
        for p in prof:
            print(" fusion", p.get("index"), round(p.get("area", 0) * 100, 4), [round(x * 10, 3) for x in p.get("centroid", [])])
            skname = p.get("sketch")
for it in fj["timeline"]:
    if it["type"] == "Sketch" and it["name"] == skname:
        print(" fusion sketch profiles", it["data"]["profiles"])
