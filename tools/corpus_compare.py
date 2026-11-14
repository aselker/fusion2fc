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
The mesh distance is computed only when the body counts and volumes agree; it cannot
change the outcome of a step that already fails.

Results are cached by (Fusion mesh, digest of the rebuilt step's BREP) in
F2FC_COMPARE_CACHE (JSON), which is discarded when this file or mesh_compare.py changes,
so unchanged steps cost nothing on the next run.
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
import exact_compare as ec  # noqa: E402

VOL_TOL = 1e-6
MESH_FACTOR = 1.25
MAX_LABEL_FACTOR = 2.5
COMPARATOR_VERSION = 2  # bump to invalidate cached results
TOL_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tests", "corpus", "tolerances.json")


def label_factor(case_id, step_name):
    """Per-test loosened distance factor (None when the step has no label)."""
    try:
        tol = json.load(open(TOL_FILE)).get(case_id)
    except (OSError, ValueError):
        return None
    if not tol or not tol.get("reason"):
        return None
    steps = tol.get("steps", "*")
    if steps != "*" and step_name not in steps:
        return None
    return min(float(tol["mesh_factor"]), MAX_LABEL_FACTOR)


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


HERE = os.path.dirname(os.path.abspath(__file__))
CODE_DIGEST = hashlib.sha1(b"".join(open(os.path.join(HERE, f), "rb").read()
                                    for f in ("corpus_compare.py", "mesh_compare.py", "exact_compare.py"))).hexdigest()


class Cache:
    """Per-run caches of meshes and rebuilt shapes, and the persistent result cache."""

    def __init__(self, path=None):
        self.path, self.fusion, self.shapes, self.tris, self.digests = path, {}, {}, {}, {}
        self.results = {}
        if path and os.path.exists(path):
            try:
                saved = json.load(open(path))
                if saved.get("code") == CODE_DIGEST:
                    self.results = saved.get("results", {})
            except ValueError:
                pass

    def save(self):
        if self.path:
            json.dump({"code": CODE_DIGEST, "results": self.results}, open(self.path, "w"))

    def fusion_tris(self, path):
        if path not in self.fusion:
            self.fusion = {path: mc.read_stl(path) if path else np.zeros((0, 3, 3))}
        return self.fusion[path]

    def digest(self, path):
        if path not in self.digests:
            self.digests[path] = "empty" if path is None else hashlib.sha1(open(path, "rb").read()).hexdigest()
        return self.digests[path]

    def solids(self, path):
        """Solid volumes of a rebuilt step and its shape (None when empty)."""
        if path not in self.shapes:
            shape = None
            if path is not None:
                shape = Part.Shape()
                shape.importBrep(path)
                if not shape.Solids:
                    shape = None
            self.shapes = {path: (shape, [s.Volume for s in shape.Solids] if shape else [])}
        return self.shapes[path]

    def rebuild_tris(self, path, dev):
        key = (path, dev)
        if key not in self.tris:
            shape, _ = self.solids(path)
            self.tris = {key: mc.shape_triangles(shape, dev) if shape else np.zeros((0, 3, 3))}
        return self.tris[key]


def geometry_check(out, problems, notes, ftris, rtris, rshape, dev, diag, factor=None):
    """Mesh distance, then (only if that fails) the exact-surface check, then a label's factor.
    Fills `out`, appends to `problems` (failures) and `notes` (how a match was reached)."""
    limit = MESH_FACTOR * 2 * dev
    if not (len(ftris) or len(rtris)):
        out["hausdorff"] = 0.0
        return
    r = mc.compare(ftris, rtris, spacing=max(diag / 100.0, 4 * dev), cap=max(20 * limit, 1.0))
    out["hausdorff"] = r["hausdorff"]
    out["fusion_to_rebuilt"] = r["a_to_b"]
    out["rebuilt_to_fusion"] = r["b_to_a"]
    if r["hausdorff"] <= limit:
        return
    ex = None
    if rshape is not None and len(ftris):
        ex = ec.exact_check(rshape, ftris, dev, max(diag / 100.0, 4 * dev))
        ex["limit"] = MESH_FACTOR * dev
        out["exact_check"] = ex
    if ex is not None and ex["max"] <= ex["limit"]:
        out["matched_by"] = "exact-surface check"
        notes.append("matched by exact-surface check (mesh distance %.4g > %.3g; exact excess %.4g <= %.3g)" % (
            r["hausdorff"], limit, ex["max"], ex["limit"]))
    elif factor and factor > MESH_FACTOR and ex is not None and ex["max"] <= factor * dev:
        out["matched_by"] = "loosened tolerance"
        out["loosened_factor"] = factor
        notes.append("loosened tolerance x%.3g (exact excess %.4g <= %.3g)" % (factor, ex["max"], factor * dev))
    else:
        worst = max((r["a_to_b"], r["b_to_a"]), key=lambda x: x.get("max") or 0)
        at = worst.get("at")
        msg = "mesh distance %.4g mm > %.3g%s" % (
            r["hausdorff"], limit, " at (%.2f, %.2f, %.2f)" % tuple(at) if at else "")
        if ex is not None:
            msg += "; exact-surface check %.4g mm > %.3g" % (ex["max"], ex["limit"])
        problems.append(msg)


def compare_step(step, truth_dir, rebuild_path, dev, diag, cache, factor=None):
    fusion_solids = [b for b in step.get("bodies", []) if b.get("solid")]
    fusion_vols = [b["volume"] for b in fusion_solids]
    mesh = step.get("mesh")
    key = "v%d|%s|%s|%r|%r" % (COMPARATOR_VERSION, mesh, cache.digest(rebuild_path), dev, factor)
    if key in cache.results:
        return dict(cache.results[key])
    _, rvols = cache.solids(rebuild_path)
    out = {"fusion_bodies": len(fusion_solids), "rebuilt_bodies": len(rvols),
           "fusion_surfaces": sum(1 for b in step.get("bodies", []) if not b.get("solid"))}
    problems, notes = [], []
    if len(fusion_solids) != len(rvols):
        problems.append("bodies %d vs %d" % (len(fusion_solids), len(rvols)))
    if not vols_match(fusion_vols, rvols):
        out["volumes"] = {"fusion": sorted(fusion_vols, reverse=True), "rebuilt": sorted(rvols, reverse=True)}
        problems.append("volumes %s vs %s" % (fmt(fusion_vols), fmt(rvols)))
    limit = MESH_FACTOR * 2 * dev
    out["mesh_limit"] = limit
    if problems:
        out["hausdorff"] = None
    else:
        ftris = cache.fusion_tris(os.path.join(truth_dir, mesh) if mesh else None)
        rtris = cache.rebuild_tris(rebuild_path, dev)
        fshape, _ = cache.solids(rebuild_path)
        geometry_check(out, problems, notes, ftris, rtris, fshape, dev, diag, factor)
    out["status"] = "match" if not problems else "mismatch"
    out["problems"] = problems + notes
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
    cache, results, current = Cache(os.environ.get("F2FC_COMPARE_CACHE")), [], None
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
                rec.update(compare_step(step, truth_dir, path, dev, diag, cache,
                                        label_factor(os.path.basename(truth_dir), step["name"])))
            except Exception:
                rec.update(status="error", problems=[traceback.format_exc()[-400:]])
        results.append(rec)
    n_match = sum(r["status"] == "match" for r in results)
    first = next((r for r in results if r["status"] != "match"), None)
    n_exact = sum(r.get("matched_by") == "exact-surface check" for r in results)
    n_loose = sum(r.get("matched_by") == "loosened tolerance" for r in results)
    summary = {"steps": len(results), "match": n_match, "matched_by_exact": n_exact,
               "matched_by_label": n_loose, "all_match": n_match == len(results),
               "aligned": len(pairs), "rebuilt_features": len(feats),
               "first_mismatch": None if first is None else {
                   "index": first["index"], "name": first["name"], "type": first["type"],
                   "problems": first.get("problems"), "rebuild": first.get("rebuild")}}
    cache.save()
    json.dump({"summary": summary, "steps": results, "deviation_mm": dev},
              open(os.environ["F2FC_RESULT"], "w"), indent=1)
    print("F2FC compare: %d/%d steps match" % (n_match, len(results)))


if "F2FC_TRUTH" in os.environ:   # not when imported (tools/negative_controls.py)
    try:
        main()
    except Exception:
        traceback.print_exc()
    sys.stdout.flush()
