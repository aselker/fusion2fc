"""Independent check of Dutchman FCStd output against Fusion truth.
run: freecadcmd tools/check_dutchman.py   (env DUT_OUT=tests/out/dutchman, optional DUT_IDS="a b")
For each model: take the shapes of the rebuilt PartDesign::Body objects (not the embedded-STEP
'OriginalBody'/'OriginalGeometry' fallback), export them as one compound BRep, and run
corpus_compare.compare_step against the last Fusion truth step.  Writes <out>/check/<id>.json.
"""
import json, os, sys, traceback
import FreeCAD as App
import Part
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.path.join(os.getcwd(), "tools")
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import corpus_compare as cc  # noqa: E402

OUT = os.environ.get("DUT_OUT", os.path.join(ROOT, "tests/out/dutchman"))
os.makedirs(os.path.join(OUT, "check"), exist_ok=True); os.makedirs(os.path.join(OUT, "brep"), exist_ok=True)
ids = os.environ.get("DUT_IDS", "").split()
man = json.load(open(os.path.join(ROOT, "tests/corpus/manifest.json")))
cache = cc.Cache(os.path.join(OUT, "compare_cache%s.json" % os.environ.get("DUT_SHARD", "")))

def is_fallback(b):
    t = getattr(b, "Tip", None)
    return (t is not None and t.Name.startswith("OriginalGeometry")) or "(original STEP)" in b.Label

def gshape(o):
    s = o.Shape.copy()
    try:
        s.Placement = o.getGlobalPlacement()
    except Exception:
        pass
    return s

def visible(o):
    seen = 0
    while o is not None and seen < 20:
        if not getattr(o, "Visibility", True):
            return False
        o = o.getParentGroup() or o.getParentGeoFeatureGroup(); seen += 1
    return True

def compare(step, tp, truth, mid, shapes, tag):
    comp = Part.makeCompound([s for sh in shapes for s in sh.Solids])
    p = os.path.join(OUT, "brep", "%s.%s.brep" % (mid, tag)); comp.exportBrep(p)
    cache.shapes = {}; cache.tris = {}
    r = cc.compare_step(step, os.path.dirname(tp), p, truth["deviation_mm"], truth.get("diag") or 100.0, cache,
                        cc.label_factor(mid, step["name"]))
    return r

def check(e):
    mid = e["id"]; res = {"id": mid}
    fc = os.path.join(OUT, "fcstd", mid + ".FCStd")
    tp = os.path.join(ROOT, "tests/corpus/truth", mid, "steps.json")
    if not os.path.exists(fc):
        res["status"] = "no_fcstd"; return res
    truth = json.load(open(tp)); step = truth["steps"][-1]
    doc = App.openDocument(fc)
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    good = [b for b in bodies if not is_fallback(b) and b.Shape.Solids]
    fb = [b for b in bodies if is_fallback(b)]
    res.update(rebuilt_bodies=len(good), fallback_bodies=len(fb),
               fallback_visible=any(getattr(b, "Visibility", False) for b in fb),
               other_shapes=[o.Name for o in doc.Objects if o.TypeId.startswith("Part::") and getattr(o, "Shape", None) and o.Shape.Solids])
    res["tip_ok"] = [b.Name for b in good]
    res["partial_group"] = any(o.TypeId == "App::DocumentObjectGroup" and "Partial" in o.Name for o in doc.Objects)
    vis = [b for b in bodies if b.Shape.Solids and visible(b)]
    res["visible_kind"] = ("none" if not vis else "step" if all(is_fallback(b) for b in vis)
                           else "history" if not any(is_fallback(b) for b in vis) else "mixed")
    if step.get("error") or "bodies" not in step:
        res["status"] = res["vis_status"] = "no_truth"
    else:
        for key, bs in (("status", good), ("vis_status", vis)):
            if not bs:
                res[key] = "no_history_solid" if key == "status" else "no_visible_solid"; continue
            r = compare(step, tp, truth, mid, [gshape(b) for b in bs], "hist" if key == "status" else "vis")
            res[key] = r["status"]
            res[key.replace("status", "problems")] = r.get("problems")
            res[key.replace("status", "matched_by")] = r.get("matched_by")
            if key == "status":
                res["fusion_bodies"] = r["fusion_bodies"]; res["rebuilt_solids"] = r["rebuilt_bodies"]
    App.closeDocument(doc.Name)
    return res

for e in man:
    if ids and e["id"] not in ids: continue
    try:
        r = check(e)
    except Exception:
        r = {"id": e["id"], "status": "error", "problems": [traceback.format_exc()[-400:]]}
    json.dump(r, open(os.path.join(OUT, "check", e["id"] + ".json"), "w"))
    print(r["id"], r["status"], r.get("vis_status"), flush=True)
cache.save()
