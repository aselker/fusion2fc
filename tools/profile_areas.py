"""Profile face area of every extrude in a slim CADIR, for comparison with Fusion.

Run by freecadcmd (inputs via environment, since freecadcmd treats arguments as files):
  F2FC_SLIM=slim.json F2FC_AREAS=out.json freecadcmd tools/profile_areas.py

Builds each extrude's profile the way fusion2fc/rebuild.py does (sketch -> binder face,
or the static trimmed-region face) and writes {feature id: area mm^2 | "error: ..."}.
"""
import json
import os
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = open(os.path.join(HERE, "..", "fusion2fc", "rebuild.py")).read()
exec(compile(SOURCE[:SOURCE.index("\ndef main():")], "rebuild.py", "exec"))


def profile_area(rb, feat):
    d = feat["definition"]
    prof = d["profile"]
    value = prof.get("value")
    sid = value.get("sketch") if isinstance(value, dict) else None
    if sid not in rb.sketch_defs:
        return "error: profile kind " + prof["kind"]
    sk, geo_of, edge_of, normal = rb.build_sketch(sid, rb.sketch_label(sid))
    regions = value.get("regions") or []
    if any(r.get("region") == "trimmed" for r in regions):
        return rb.trimmed_face(sid, regions, sk.Placement).Area
    names = rb.profile_edges(rb.sketch_defs[sid], edge_of, prof)
    base = rb.doc.addObject("PartDesign::SubShapeBinder", "Profile")
    base.Support = [(sk, tuple(names))]
    base.MakeFace = True
    rb.doc.recompute()
    return base.Shape.Area


def run():
    slim = json.load(open(os.environ["F2FC_SLIM"]))
    rb = Rebuilder(slim, None, None)
    out = {}
    for feat in slim["features"]:
        if feat["definition"].get("definition") != "extrude":
            continue
        try:
            out[feat["id"]] = profile_area(rb, feat)
        except Exception as e:
            out[feat["id"]] = "error: %s: %s" % (type(e).__name__, e)
    json.dump(out, open(os.environ["F2FC_AREAS"], "w"), indent=0)
    print("F2FC areas:", len(out))


try:
    run()
except Exception:
    traceback.print_exc()
