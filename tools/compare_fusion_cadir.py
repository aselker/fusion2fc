#!/usr/bin/env python3
"""Compare a cadmpeg decode (slim CADIR JSON) against a Fusion API ground-truth
dump (vm/scripts/dump_features.py output), feature by feature.

  compare_fusion_cadir.py SLIM.json FUSION.json [--details] [--alignment OUT.json]

Alignment is by timeline order with a sequence match on feature kind, so
renamed features still pair up. Units: CADIR model uses mm, Fusion API cm.
"""
import collections
import difflib
import json
import math
import sys

FUSION_KIND = {
    "Sketch": "sketch", "ExtrudeFeature": "extrude", "FilletFeature": "fillet",
    "ChamferFeature": "chamfer", "ConstructionPlane": "datum_plane",
    "MirrorFeature": "pattern", "CircularPatternFeature": "pattern",
    "RectangularPatternFeature": "pattern", "CombineFeature": "combine",
    "LoftFeature": "loft", "SweepFeature": "sweep", "RevolveFeature": "revolve",
    "SplitBodyFeature": "split_body", "MoveFeature": "move",
    "OffsetFacesFeature": "move_face", "CopyPasteBody": "base_feature",
}
CADIR_KIND = {"spatial_sketch": "sketch", "move_body": "move"}
FUSION_OP = {0: "join", 1: "cut", 2: "intersect", 3: "new_body", 4: "new_component"}
CURVE_KIND = {"SketchLine": "line", "SketchArc": "arc", "SketchCircle": "circle",
              "SketchFittedSpline": "nurbs", "SketchFixedSpline": "nurbs",
              "SketchControlPointSpline": "nurbs", "SketchEllipse": "ellipse",
              "SketchEllipticalArc": "elliptical_arc", "SketchConicCurve": "conic"}


def cadir_kind(f):
    d = f["definition"].get("definition", "native")
    if d == "native":
        tag = f.get("source_tag", "")
        return {"Verschieben": "move", "Fase": "chamfer", "Basiselement": "base_feature",
                "Teilen": "split_body", "Extrusion": "extrude"}.get(tag, "native:" + tag)
    return CADIR_KIND.get(d, d)


def close(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(a), abs(b))


class Report:
    def __init__(self):
        self.stats = collections.defaultdict(collections.Counter)
        self.details = []

    def check(self, kind, what, ok, note=""):
        self.stats[kind][(what, "ok" if ok else "mismatch")] += 1
        if not ok:
            self.details.append(f"  {kind:10s} {what:22s} {note}")

    def skip(self, kind, what):
        self.stats[kind][(what, "undecoded")] += 1


def compare_sketch(r, c, f, slim):
    ref = c["definition"].get("sketch")
    if not isinstance(ref, dict) or ref.get("space") != "planar":
        r.skip("sketch", "spatial sketch")
        return
    sk_id = ref.get("sketch")
    ents = slim["_entities_by_sketch"].get(sk_id, [])
    got = collections.Counter(e["geometry"]["kind"] for e in ents if e["geometry"]["kind"] != "point")
    want = collections.Counter(CURVE_KIND.get(cv.get("type"), cv.get("type")) for cv in f["data"]["curves"])
    r.check("sketch", "curve counts", got == want, f"{f['name']}: cadir {dict(got)} fusion {dict(want)}")
    cons = slim["_constraints_by_sketch"].get(sk_id, [])
    exprs_c = sorted(p["expression"].replace(" ", "") for p in cons if p)
    exprs_f = sorted((d["parameter"] or {}).get("expression", "").replace(" ", "") for d in f["data"]["dimensions"]
                     if d.get("parameter") and isinstance(d["parameter"], dict) and "expression" in d["parameter"])
    r.check("sketch", "dimension exprs", exprs_c == exprs_f,
            f"{f['name']}: cadir {len(exprs_c)} fusion {len(exprs_f)} diff {sorted((collections.Counter(exprs_f) - collections.Counter(exprs_c)).elements())[:5]}")


def extrude_distances_cadir(d):
    ext = d.get("extent", {})
    if ext.get("kind") == "one_sided":
        t = ext["side"]["termination"]
        return [t.get("length")] if t.get("kind") == "blind" else [t.get("kind")]
    if ext.get("kind") == "symmetric":
        t = ext.get("termination", ext.get("side", {}).get("termination", {}))
        return ["sym", t.get("length", t.get("kind"))]
    if ext.get("kind") == "two_sided":
        return [s.get("termination", {}).get("length", s.get("termination", {}).get("kind")) for s in ext.get("sides", [])]
    return [ext.get("kind")]


def compare_extrude(r, c, f):
    d, fd = c["definition"], f["data"]
    if d.get("definition") != "extrude":
        r.skip("extrude", "definition")
        return
    want_op = FUSION_OP.get(fd.get("operation"))
    r.check("extrude", "operation", d.get("op") == want_op, f"{f['name']}: cadir {d.get('op')} fusion {want_op}")
    e1 = fd.get("extentOne") or {}
    if e1.get("type") == "DistanceExtentDefinition" and isinstance(e1.get("distance"), dict):
        want = abs(e1["distance"]["value"]) * 10.0  # cm -> mm
        got = extrude_distances_cadir(d)
        num = [g for g in got if isinstance(g, (int, float))]
        ok = any(close(abs(g), want, 1e-6) for g in num)
        r.check("extrude", "distance", ok, f"{f['name']}: cadir {got} fusion {want:.6g} mm ({e1['distance'].get('expression')})")
    else:
        r.check("extrude", "extent type", False, f"{f['name']}: fusion {e1.get('type')} cadir {extrude_distances_cadir(d)}")
    prof = d.get("profile", {})
    if prof.get("kind") in ("sketch_profiles", "sketch_regions"):
        fp = fd.get("profile")
        n_f = len(fp) if isinstance(fp, list) else 1
        v = prof.get("value", {})
        n_c = len(v.get("profiles", v.get("regions", [])))
        r.check("extrude", "profile count", n_c == n_f, f"{f['name']}: cadir {n_c} fusion {n_f}")
    else:
        r.skip("extrude", "profile:" + prof.get("kind", "?"))


def compare_edge_feature(r, kind, c, f):
    d = c["definition"]
    fsets = f["data"]["edgeSets"]
    if d.get("definition") not in ("fillet", "chamfer"):
        r.skip(kind, "definition")
        return
    groups = d.get("groups") or []
    r.check(kind, "edge-set count", len(groups) == len(fsets), f"{f['name']}: cadir {len(groups)} fusion {len(fsets)}")
    for g, fs in zip(groups, fsets):
        e = g.get("edges", {})
        if e.get("kind") == "historical":
            n_c = len(e["value"].get("edges", []))
            n_f = len(fs.get("edges") or [])
            r.check(kind, "edges per set", n_c == n_f, f"{f['name']}: cadir {n_c} fusion {n_f}")
        else:
            r.skip(kind, "edges:" + str(e.get("kind")))
        size_c = (g.get("radius") or {}).get("radius") or (g.get("distance") or {}).get("distance") \
            or next((v for k, v in g.items() if isinstance(v, (int, float)) and k != "tangency_weight"), None)
        fp = fs.get("radius") or fs.get("distance") or fs.get("distanceOne")
        if fp and isinstance(fp, dict) and size_c is not None:
            r.check(kind, "size", close(size_c, fp["value"] * 10.0), f"{f['name']}: cadir {size_c} fusion {fp['value'] * 10.0} mm")


def main(argv):
    slim = json.load(open(argv[1]))
    fus = json.load(open(argv[2]))
    by_sk = collections.defaultdict(list)
    for e in slim["sketch_entities"]:
        by_sk[e["sketch"]].append(e)
    params = {p["id"]: p for p in slim["parameters"]}
    cons_by_sk = collections.defaultdict(list)
    for k in slim["sketch_constraints"]:
        pid = k["definition"].get("parameter")
        if isinstance(pid, dict):
            pid = pid.get("id")
        if pid in params:
            cons_by_sk[k["sketch"]].append(params[pid])
    slim["_entities_by_sketch"], slim["_constraints_by_sketch"] = by_sk, cons_by_sk

    cf = sorted(slim["features"], key=lambda x: x["ordinal"])
    ff = [x for x in fus["timeline"] if x["type"] != "Occurrence"]
    kc = [cadir_kind(x) for x in cf]
    kf = [FUSION_KIND.get(x["type"], x["type"]) for x in ff]
    sm = difflib.SequenceMatcher(None, kc, kf, autojunk=False)
    r = Report()
    paired = 0
    alignment = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            r.details.append(f"  ALIGN {tag}: cadir {kc[i1:i2]} vs fusion {kf[j1:j2]} at fusion #{ff[j1]['index'] if j1 < len(ff) else '-'}")
            continue
        for a, b in zip(cf[i1:i2], ff[j1:j2]):
            paired += 1
            k = cadir_kind(a)
            comp = b.get("component")
            alignment.append({"cadir": a["id"], "fusion_index": b["index"], "fusion_name": b["name"],
                              "fusion_type": b["type"], "component": comp if isinstance(comp, str) else None})
            if k == "sketch":
                compare_sketch(r, a, b, slim)
            elif k == "extrude":
                compare_extrude(r, a, b)
            elif k in ("fillet", "chamfer"):
                compare_edge_feature(r, k, a, b)
    print(f"features: cadir {len(cf)}, fusion {len(ff)}, paired by kind {paired}")
    for kind, ctr in sorted(r.stats.items()):
        whats = sorted({w for w, _ in ctr})
        print(f"{kind}:")
        for w in whats:
            print(f"   {w:24s} ok {ctr[(w, 'ok')]:4d}  mismatch {ctr[(w, 'mismatch')]:4d}  undecoded {ctr[(w, 'undecoded')]:4d}")
    if "--details" in argv:
        print("\n".join(r.details))
    if "--alignment" in argv:
        with open(argv[argv.index("--alignment") + 1], "w") as fh:
            json.dump(alignment, fh, indent=0)


if __name__ == "__main__":
    main(sys.argv)
