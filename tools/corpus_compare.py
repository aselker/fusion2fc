"""Compare a rebuild with Fusion after every timeline step (run by freecadcmd).

  F2FC_TRUTH=truth/<id>/steps.json  F2FC_REPORT=report.json  F2FC_STEPS=steps/
  F2FC_RESULT=result.json  freecadcmd tools/corpus_compare.py

Fusion's timeline steps are aligned with the rebuilt features by name (in order; runs of
unmatched names of equal length pair up by position). Each Fusion step is compared with
the rebuild state after the last feature aligned at or before it.

A step matches when
  - the solid body counts agree,
  - the sorted solid volumes agree to 1e-6 (relative, Fusion's high-accuracy properties
    against OpenCASCADE's), and
  - Fusion's step mesh and the rebuilt bodies tessellated at the same deviation d are
    within 1.25 * 2d of each other in both directions (see mesh_compare).
"""
import difflib
import hashlib
import json
import os
import sys
import traceback

import FreeCAD as App  # noqa: F401
import Part

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import mesh_compare as mc  # noqa: E402

VOL_TOL = 1e-6
MESH_FACTOR = 1.25


def squash(n):
    return "".join((n or "").split()).lower()


def align(fusion_names, rebuild_names):
    """Fusion step index -> rebuild feature index."""
    a, b = [squash(n) for n in fusion_names], [squash(n) for n in rebuild_names]
    pairs = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                pairs[i1 + k] = j1 + k
    return pairs


def vols_match(a, b):
    a, b = sorted(a, reverse=True), sorted(b, reverse=True)
    return len(a) == len(b) and all(abs(x - y) <= VOL_TOL * max(1.0, abs(x), abs(y)) for x, y in zip(a, b))


def fmt(vs):
    return "[" + ", ".join("%.6g" % v for v in sorted(vs, reverse=True)[:6]) + (", ..." if len(vs) > 6 else "") + "]"


class Cache:
    def __init__(self):
        self.fusion, self.rebuild, self.results = {}, {}, {}

    def fusion_tris(self, path):
        if path not in self.fusion:
            self.fusion = {path: mc.read_stl(path) if path else np.zeros((0, 3, 3))}
        return self.fusion[path]

    def rebuild_state(self, path, dev):
        key = (path, dev)
        if key not in self.rebuild:
            if path is None:
                shape, digest = None, "empty"
            else:
                raw = open(path, "rb").read()
                digest = hashlib.sha1(raw).hexdigest()
                shape = Part.Shape()
                shape.importBrep(path)
            if shape is None or not shape.Solids:
                tris, solids = np.zeros((0, 3, 3)), []
            else:
                tris = mc.shape_triangles(shape, dev)
                solids = [s.Volume for s in shape.Solids]
            self.rebuild = {key: (digest, tris, solids)}
        return self.rebuild[key]


def compare_step(step, truth_dir, rebuild_path, dev, diag, cache):
    fusion_solids = [b for b in step.get("bodies", []) if b.get("solid")]
    fusion_vols = [b["volume"] for b in fusion_solids]
    digest, rtris, rvols = cache.rebuild_state(rebuild_path, dev)
    mesh = step.get("mesh")
    key = (mesh, digest)
    if key in cache.results:
        return dict(cache.results[key])
    out = {"fusion_bodies": len(fusion_solids), "rebuilt_bodies": len(rvols),
           "fusion_surfaces": sum(1 for b in step.get("bodies", []) if not b.get("solid"))}
    problems = []
    if len(fusion_solids) != len(rvols):
        problems.append("bodies %d vs %d" % (len(fusion_solids), len(rvols)))
    if not vols_match(fusion_vols, rvols):
        out["volumes"] = {"fusion": sorted(fusion_vols, reverse=True), "rebuilt": sorted(rvols, reverse=True)}
        problems.append("volumes %s vs %s" % (fmt(fusion_vols), fmt(rvols)))
    ftris = cache.fusion_tris(os.path.join(truth_dir, mesh) if mesh else None)
    limit = MESH_FACTOR * 2 * dev
    out["mesh_limit"] = limit
    if len(ftris) or len(rtris):
        r = mc.compare(ftris, rtris, spacing=max(diag / 100.0, 4 * dev), cap=max(20 * limit, 1.0))
        out["hausdorff"] = r["hausdorff"]
        out["fusion_to_rebuilt"] = r["a_to_b"]
        out["rebuilt_to_fusion"] = r["b_to_a"]
        if not r["hausdorff"] <= limit:
            worst = max((r["a_to_b"], r["b_to_a"]), key=lambda x: x.get("max") or 0)
            at = worst.get("at")
            problems.append("mesh distance %.4g mm > %.3g%s" % (
                r["hausdorff"], limit, " at (%.2f, %.2f, %.2f)" % tuple(at) if at else ""))
    else:
        out["hausdorff"] = 0.0
    out["status"] = "match" if not problems else "mismatch"
    out["problems"] = problems
    cache.results[key] = dict(out)
    return out


def main():
    truth_path = os.environ["F2FC_TRUTH"]
    truth = json.load(open(truth_path))
    truth_dir = os.path.dirname(truth_path)
    report = json.load(open(os.environ["F2FC_REPORT"]))
    steps_dir = os.environ["F2FC_STEPS"]
    dev = truth["deviation_mm"]
    diag = truth.get("diag") or 100.0
    steps = truth["steps"]
    feats = report["features"]
    pairs = align([s["name"] for s in steps], [f["name"] for f in feats])
    cache, results, current = Cache(), [], None
    for i, step in enumerate(steps):
        if i in pairs:
            current = pairs[i]
        rec = {"index": step["index"], "name": step["name"], "type": step.get("type"),
               "fusion_health": step.get("health"), "aligned": pairs.get(i),
               "state_from": current}
        if current is not None:
            f = feats[current]
            rec["rebuild"] = {"name": f["name"], "kind": f.get("kind"), "status": f.get("status"),
                              "reason": f.get("reason")}
        if step.get("error") or "bodies" not in step:
            rec.update(status="no truth", problems=["fusion step error"])
        else:
            path = None
            if current is not None and feats[current].get("step_file"):
                path = os.path.join(steps_dir, feats[current]["step_file"])
            try:
                rec.update(compare_step(step, truth_dir, path, dev, diag, cache))
            except Exception:
                rec.update(status="error", problems=[traceback.format_exc()[-400:]])
        results.append(rec)
    n_match = sum(r["status"] == "match" for r in results)
    first = next((r for r in results if r["status"] != "match"), None)
    summary = {"steps": len(results), "match": n_match, "all_match": n_match == len(results),
               "aligned": len(pairs), "rebuilt_features": len(feats),
               "first_mismatch": None if first is None else {
                   "index": first["index"], "name": first["name"], "type": first["type"],
                   "problems": first.get("problems"), "rebuild": first.get("rebuild")}}
    json.dump({"summary": summary, "steps": results, "deviation_mm": dev},
              open(os.environ["F2FC_RESULT"], "w"), indent=1)
    print("F2FC compare: %d/%d steps match" % (n_match, len(results)))


try:
    main()
except Exception:
    traceback.print_exc()
sys.stdout.flush()
