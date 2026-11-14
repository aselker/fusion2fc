"""Negative controls for the comparator (run: freecadcmd tools/negative_controls.py).

Synthetic shapes stand in for Fusion's truth (tessellated at deviation d) and for our rebuild.
Wrong shapes with the right volume must be REJECTED by the whole chain (mesh distance, then the
exact-surface fallback); the same shape tessellated differently must be ACCEPTED.
"""
import math
import os
import sys

import FreeCAD as App
import Part

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import mesh_compare as mc  # noqa: E402
import corpus_compare as cc  # noqa: E402

V = App.Vector
D = 0.01


def twisted(deg, h=20.0, w=8.0, n=9):
    secs = []
    for i in range(n):
        a = math.radians(deg * i / (n - 1))
        c, s = math.cos(a), math.sin(a)
        pts = [V(c * x - s * y, s * x + c * y, h * i / (n - 1)) for x, y in
               ((-w, -w / 2), (w, -w / 2), (w, w / 2), (-w, w / 2))]
        secs.append(Part.makePolygon(pts + [pts[0]]))
    return Part.makeLoft(secs, True, False)


def box(dx=0, dy=0, dz=0):
    return Part.makeBox(20, 20, 20, V(dx, dy, dz))


def holed(dx):
    b = Part.makeBox(30, 30, 20)
    h = Part.makeCylinder(2.0, 20, V(15 + dx, 15, 0))
    return b.cut(h)


def prism_equal_volume(r, hgt, n):
    side_r = r * math.sqrt(math.pi / (0.5 * n * math.sin(2 * math.pi / n)))
    pts = [V(side_r * math.cos(2 * math.pi * i / n), side_r * math.sin(2 * math.pi * i / n), 0) for i in range(n)]
    return Part.Face(Part.makePolygon(pts + [pts[0]])).extrude(V(0, 0, hgt))


def verdict(truth, rebuilt, truth_dev=D, truth_angular=0.5, dev=D):
    ftris = mc.shape_triangles(truth, truth_dev, truth_angular)
    rtris = mc.shape_triangles(rebuilt, dev)
    out, problems, notes = {}, [], []
    cc.geometry_check(out, problems, notes, ftris, rtris, rebuilt, dev, 40.0)
    vol = abs(truth.Volume - rebuilt.Volume) / truth.Volume
    ex = out.get("exact_check")
    return {"accepted": not problems, "dvol": vol, "mesh": out.get("hausdorff"), "mesh_limit": cc.MESH_FACTOR * 2 * dev,
            "exact": None if ex is None else ex["max"], "exact_limit": None if ex is None else ex["limit"],
            "by": out.get("matched_by", "mesh")}


CASES = [
    # name, truth, rebuilt, expected accepted?
    ("(a) twist 90 vs 0 deg (equal volume)", lambda: (twisted(90), twisted(0)), False),
    ("(a2) twist 90 vs 80 deg (equal volume)", lambda: (twisted(90), twisted(80)), False),
    ("(a3) twist 90 vs 89.5 deg", lambda: (twisted(90), twisted(89.5)), False),
    ("(b) box translated 5d", lambda: (box(), box(5 * D)), False),
    ("(b2) box translated 2.6d", lambda: (box(), box(2.6 * D)), False),
    ("(c) through-hole moved 3d", lambda: (holed(0), holed(3 * D)), False),
    ("(c2) through-hole moved 6d", lambda: (holed(0), holed(6 * D)), False),
    ("(d) cylinder vs 16-gon prism (equal volume)", lambda: (Part.makeCylinder(5, 20), prism_equal_volume(5, 20, 16)), False),
    ("(d2) cylinder vs 24-gon prism (equal volume)", lambda: (Part.makeCylinder(5, 20), prism_equal_volume(5, 20, 24)), False),
    ("ok: twisted 90, truth mesh at d, rebuilt at d", lambda: (twisted(90), twisted(90)), True),
    ("ok: twisted 90, truth mesh coarse (3d, 1.0 rad)", lambda: (twisted(90), twisted(90)), True, dict(truth_dev=3 * D, truth_angular=1.0)),
    ("ok: cylinder, truth mesh at d/2", lambda: (Part.makeCylinder(5, 20), Part.makeCylinder(5, 20)), True, dict(truth_dev=D / 2)),
    ("ok: holed box, truth mesh angular 0.2", lambda: (holed(0), holed(0)), True, dict(truth_angular=0.2)),
    ("ok: box", lambda: (box(), box()), True),
]


def main():
    bad = 0
    for item in CASES:
        name, make, want = item[:3]
        kw = item[3] if len(item) > 3 else {}
        t, r = make()
        v = verdict(t, r, **kw)
        flag = "OK " if v["accepted"] == want else "BAD"
        bad += v["accepted"] != want
        print("%s %-52s %-8s dvol %.1e mesh %.4g (limit %.3g) exact %s (limit %s) by %s" % (
            flag, name, "ACCEPTED" if v["accepted"] else "REJECTED", v["dvol"], v["mesh"], v["mesh_limit"],
            "-" if v["exact"] is None else "%.4g" % v["exact"],
            "-" if v["exact_limit"] is None else "%.3g" % v["exact_limit"], v["by"]))
    print("negative controls: %s" % ("ALL AS EXPECTED" if not bad else "%d UNEXPECTED" % bad))


main()
