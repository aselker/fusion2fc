"""Fusion-side: rebuild part of a dumped design as a fresh minimal design (a test case
that mirrors real-world geometry). Run with `--include scripts/dump_features.py`.

__SPEC__  JSON written by tools/make_replica_spec.py: {"name", "userParameters", "records"}
          (records are dump_features timeline records, in order).
__OUTDIR__ output folder for <name>.f3d and <name>.truth.json.

Sketches are recreated on axis-aligned offset planes from the curves' model-space points;
extrudes reuse the dumped extents, choose profiles by model-space centroid and area, and
find from-face start faces by plane and a point on the face. Replication stops at the
first record it cannot reproduce; truth.json records where.
"""
import adsk.core, adsk.fusion, json, os, traceback, math

SPEC = r"__SPEC__"
OUTDIR = r"__OUTDIR__"
P = adsk.core.Point3D.create
V = adsk.core.ValueInput.createByString


class Unsupported(Exception):
    pass


def close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def sketch_plane(root, plane):
    """Axis-aligned construction plane matching the dumped sketch plane. Returns
    (plane entity, sign) where sign is -1 when the base normal is opposite."""
    n, o = plane["normal"], plane["origin"]
    bases = [(root.xYConstructionPlane, 2), (root.xZConstructionPlane, 1), (root.yZConstructionPlane, 0)]
    for base, axis in bases:
        if abs(abs(n[axis]) - 1.0) < 1e-9:
            bn = base.geometry.normal
            bnv = [bn.x, bn.y, bn.z]
            sign = 1 if bnv[axis] * n[axis] > 0 else -1
            offset = o[axis] * bnv[axis]
            if abs(offset) < 1e-12:
                return base, sign
            pi = root.constructionPlanes.createInput()
            pi.setByOffset(base, adsk.core.ValueInput.createByReal(offset))
            return root.constructionPlanes.add(pi), sign
    raise Unsupported("sketch plane not axis-aligned: %s" % (n,))


def add_curve(sk, c):
    w = c.get("world") or {}
    to = lambda p: sk.modelToSketchSpace(P(*p))
    t = c["type"]
    curves = sk.sketchCurves
    if t == "SketchLine":
        e = curves.sketchLines.addByTwoPoints(to(w["start"]), to(w["end"]))
    elif t == "SketchArc":
        e = curves.sketchArcs.addByThreePoints(to(w["start"]), to(w["mid"]), to(w["end"]))
    elif t == "SketchCircle":
        e = curves.sketchCircles.addByCenterRadius(to(w["center"]), w["radius"])
    elif t in ("SketchFixedSpline", "SketchFittedSpline", "SketchControlPointSpline"):
        poles = [to(p) for p in w["poles"]]
        if w.get("rational"):
            nc = adsk.core.NurbsCurve3D.createRational(poles, w["degree"], w["knots"], w["weights"], w["periodic"])
        else:
            nc = adsk.core.NurbsCurve3D.createNonRational(poles, w["degree"], w["knots"], w["periodic"])
        e = curves.sketchFixedSplines.addByNurbsCurve(nc)
    else:
        raise Unsupported("curve type " + t)
    if c.get("construction"):
        e.isConstruction = True
    return e


def find_profiles(sk, refs):
    out = []
    for ref in refs:
        best = None
        for p in sk.profiles:
            ap = p.areaProperties()
            cm = sk.sketchToModelSpace(ap.centroid)
            if abs(ap.area - ref["area"]) <= 1e-6 * max(1.0, ref["area"]) and \
                    close([cm.x, cm.y, cm.z], ref["centroid"], 1e-5):
                best = p
                break
        if best is None:
            raise Unsupported("no replica profile with area %.6g at %s" % (ref["area"], ref["centroid"]))
        out.append(best)
    return out


def find_face(design, sig):
    for comp in design.allComponents:
        for body in comp.bRepBodies:
            for f in body.faces:
                g = f.geometry
                if g.objectType.split("::")[-1] != "Plane":
                    continue
                n = g.normal
                if not close([n.x, n.y, n.z], sig["normal"], 1e-6):
                    continue
                pt = P(*sig["point"])
                ok, param = f.evaluator.getParameterAtPoint(pt)
                if ok and f.evaluator.isParameterOnFace(param):
                    ok2, on = f.evaluator.getPointAtParameter(param)
                    if ok2 and on.distanceTo(pt) < 1e-6:
                        return f
    raise Unsupported("start face not found")


def expr(p, sign):
    e = p["expression"]
    return e if sign > 0 else "-(%s)" % e


def distance_def(ext, sign):
    t = ext["type"]
    if t == "DistanceExtentDefinition":
        return adsk.fusion.DistanceExtentDefinition.create(V(expr(ext["distance"], sign)))
    if t == "ThroughAllExtentDefinition":
        return adsk.fusion.ThroughAllExtentDefinition.create()
    raise Unsupported("extent " + t)


def add_extrude(design, comp, rec, sketches):
    d = rec["data"]
    refs = d["profile"] if isinstance(d["profile"], list) else [d["profile"]]
    if any(r.get("type") != "Profile" for r in refs):
        raise Unsupported("profile reference type")
    sk, sign = sketches[refs[0]["sketch"]]
    profs = find_profiles(sk, refs)
    coll = adsk.core.ObjectCollection.create()
    for p in profs:
        coll.add(p)
    ex = comp.features.extrudeFeatures
    inp = ex.createInput(coll, d["operation"])
    taper1 = V((d.get("taperOne") or {}).get("expression", "0 deg"))
    taper2 = V((d.get("taperTwo") or {}).get("expression", "0 deg"))
    e1, et = d["extentOne"], d.get("extentType")
    if e1["type"] == "SymmetricExtentDefinition":
        inp.setSymmetricExtent(V(e1["distance"]["expression"]), bool(e1.get("isFullLength")), taper1)
    elif et == 1:
        inp.setTwoSidesExtent(distance_def(e1, sign), distance_def(d["extentTwo"], sign), taper1, taper2)
    else:
        direction = adsk.fusion.ExtentDirections.PositiveExtentDirection
        if e1["type"] == "ThroughAllExtentDefinition" and sign < 0:
            direction = adsk.fusion.ExtentDirections.NegativeExtentDirection
        inp.setOneSideExtent(distance_def(e1, sign), direction, taper1)
    st = d.get("startExtent") or {}
    if st.get("type") == "FromEntityStartDefinition":
        face = find_face(design, st["face"])
        inp.startExtent = adsk.fusion.FromEntityStartDefinition.create(face, V(st["offset"]["expression"]))
    elif st.get("type") == "OffsetStartDefinition":
        inp.startExtent = adsk.fusion.OffsetStartDefinition.create(V(expr(st["offset"], sign)))
    elif st.get("type") not in (None, "ProfilePlaneStartDefinition"):
        raise Unsupported("start " + str(st.get("type")))
    f = ex.add(inp)
    f.name = rec["name"]


def run(_context: str):
    spec = json.load(open(SPEC, encoding="utf-8"))
    app = adsk.core.Application.get()
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    status = {"replicated": [], "stopped_at": None}
    try:
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        root = design.rootComponent
        for up in spec.get("userParameters", []):
            design.userParameters.add(up["name"], V(up["expression"]), up["unit"], up.get("comment") or "")
        sketches = {}
        for rec in spec["records"]:
            try:
                if rec["type"] == "Sketch":
                    plane, sign = sketch_plane(root, rec["data"]["plane"])
                    sk = root.sketches.add(plane)
                    sk.name = rec["name"]
                    for c in rec["data"]["curves"]:
                        add_curve(sk, c)
                    sketches[rec["name"]] = (sk, sign)
                elif rec["type"] == "ExtrudeFeature":
                    add_extrude(design, root, rec, sketches)
                elif rec["type"] == "ConstructionPlane":
                    pass
                else:
                    raise Unsupported("feature type " + str(rec["type"]))
                status["replicated"].append(rec["name"])
            except Exception as e:
                status["stopped_at"] = {"record": rec["name"], "type": rec["type"],
                                        "reason": str(e) if isinstance(e, Unsupported) else traceback.format_exc()[-500:]}
                break
        truth = dump_design(design, roll=True, steps=True)
        truth["case"] = spec["name"]
        truth["replica"] = status
        em = design.exportManager
        em.execute(em.createFusionArchiveExportOptions(os.path.join(OUTDIR, spec["name"] + ".f3d"), root))
        with open(os.path.join(OUTDIR, spec["name"] + ".truth.json"), "w", encoding="utf-8") as f:
            json.dump(truth, f, indent=1, ensure_ascii=False)
        vols = ["%.4f" % (b["volume"] * 1000) for b in truth["worldBodies"]]
        print("%s: replicated %d records, stopped at %s, bodies(mm3) %s" % (
            spec["name"], len(status["replicated"]), status["stopped_at"], vols))
    finally:
        doc.close(False)
