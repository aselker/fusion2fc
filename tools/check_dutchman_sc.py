"""Check the STEP replayed by `solidcraft-cli run` from Dutchman's .sc output against Fusion truth.
run: freecadcmd tools/check_dutchman_sc.py   (env DUT_OUT). Writes <out>/sccheck/<id>.json."""
import json, os, sys, traceback
import FreeCAD as App
import Part
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.path.join(os.getcwd(), "tools")
ROOT = os.path.dirname(HERE); sys.path.insert(0, HERE)
import corpus_compare as cc  # noqa: E402
OUT = os.environ.get("DUT_OUT", os.path.join(ROOT, "tests/out/dutchman"))
os.makedirs(os.path.join(OUT, "sccheck"), exist_ok=True)
SHARD = os.environ.get("DUT_SHARD", "0/1"); K, N = map(int, SHARD.split("/"))
cache = cc.Cache(os.path.join(OUT, "compare_cache_sc%d.json" % K))
man = json.load(open(os.path.join(ROOT, "tests/corpus/manifest.json")))
for n, e in enumerate(man):
    if n % N != K or os.path.exists(os.path.join(OUT, "sccheck", e["id"] + ".json")): continue
    mid = e["id"]; res = {"id": mid}
    sp = os.path.join(OUT, "scstep", mid + ".step"); tp = os.path.join(ROOT, "tests/corpus/truth", mid, "steps.json")
    try:
        truth = json.load(open(tp)); step = truth["steps"][-1]
        if not os.path.exists(sp): res["status"] = "no_step"
        elif step.get("error") or "bodies" not in step: res["status"] = "no_truth"
        else:
            sh = Part.read(sp)
            if not sh.Solids: res["status"] = "no_solid"
            else:
                bp = os.path.join(OUT, "brep", mid + ".sc.brep"); Part.makeCompound(sh.Solids).exportBrep(bp)
                cache.shapes = {}; cache.tris = {}
                r = cc.compare_step(step, os.path.dirname(tp), bp, truth["deviation_mm"], truth.get("diag") or 100.0, cache,
                                    cc.label_factor(mid, step["name"]))
                res.update(status=r["status"], problems=r.get("problems"), matched_by=r.get("matched_by"))
    except Exception:
        res = {"id": mid, "status": "error", "problems": [traceback.format_exc()[-300:]]}
    json.dump(res, open(os.path.join(OUT, "sccheck", mid + ".json"), "w")); print(mid, res["status"], flush=True)
cache.save()
