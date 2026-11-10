"""Fusion-side script (run via `mcp_call.py script`): dump the active design's
timeline with feature definitions, as ground truth for the f3d decoder and the
FreeCAD rebuilder.

Substitutions: __OUT__ = output JSON path, __ROLL__ = 1 to roll the timeline
before each fillet/chamfer so its input edges can be read (modifies the marker,
restores it at the end; never saves).

All lengths are Fusion internal units (cm); angles radians.
"""
import adsk.core, adsk.fusion, json, time, traceback, collections, math

OUT = r"__OUT__"
ROLL = "__ROLL__" == "1"


def pt(p):
    return [p.x, p.y, p.z] if p is not None else None


def vec(v):
    return [v.x, v.y, v.z] if v is not None else None


def matrix(m):
    return list(m.asArray()) if m is not None else None


def param(p):
    if p is None:
        return None
    try:
        return {"name": p.name, "expression": p.expression, "value": p.value, "unit": p.unit}
    except Exception:
        return {"repr": str(p)}


def short_type(o):
    try:
        return o.objectType.split("::")[-1]
    except Exception:
        return type(o).__name__


def safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        return {"error": str(e).splitlines()[0][:200]} if default is None else default


def curve_world(c):
    """Defining points of a sketch curve in model space (for replicating sketches)."""
    sk = c.parentSketch
    w = lambda p: pt(sk.sketchToModelSpace(p))
    t = short_type(c)
    try:
        if t == "SketchLine":
            return {"start": w(c.startSketchPoint.geometry), "end": w(c.endSketchPoint.geometry)}
        if t == "SketchArc":
            ev = c.geometry.evaluator
            ok, t0, t1 = ev.getParameterExtents()
            ok, mid = ev.getPointAtParameter((t0 + t1) / 2.0)
            return {"start": w(c.startSketchPoint.geometry), "mid": w(mid), "end": w(c.endSketchPoint.geometry)}
        if t == "SketchCircle":
            return {"center": w(c.geometry.center), "radius": c.geometry.radius}
        if t in ("SketchFixedSpline", "SketchFittedSpline", "SketchControlPointSpline"):
            ok, cps, degree, knots, rational, weights, periodic = c.geometry.getData()
            return {"poles": [w(p) for p in cps], "degree": degree, "knots": list(knots),
                    "rational": rational, "weights": list(weights), "periodic": periodic}
    except Exception as e:
        return {"error": str(e)[:200]}
    return None


def curve_geom(c):
    t = short_type(c)
    d = {"type": t, "construction": safe(lambda: c.isConstruction, False),
         "world": curve_world(c),
         "fixed": safe(lambda: c.isFixed, False), "reference": safe(lambda: c.isReference, False)}
    g = c.geometry  # sketch space
    if t == "SketchLine":
        d["start"], d["end"] = pt(g.startPoint), pt(g.endPoint)
    elif t == "SketchArc":
        d["center"], d["radius"] = pt(g.center), g.radius
        d["start"], d["end"] = pt(c.startSketchPoint.geometry), pt(c.endSketchPoint.geometry)
        d["startAngle"], d["endAngle"] = g.startAngle, g.endAngle
    elif t == "SketchCircle":
        d["center"], d["radius"] = pt(g.center), g.radius
    elif t in ("SketchEllipse", "SketchEllipticalArc"):
        d["center"], d["major"], d["minor"] = pt(g.center), g.majorRadius, g.minorRadius
        d["majorAxis"] = vec(g.majorAxis)
    elif t in ("SketchFittedSpline", "SketchFixedSpline", "SketchControlPointSpline"):
        d["start"], d["end"] = pt(c.startSketchPoint.geometry), pt(c.endSketchPoint.geometry)
        ok, cps, degree, knots, rational, weights, periodic = g.getData()
        d["degree"], d["controlPoints"], d["knots"] = degree, [pt(p) for p in cps], list(knots)
    return d


def dump_sketch(sk):
    d = {"name": sk.name, "component": sk.parentComponent.name,
         "plane": safe(lambda: {"origin": pt(sk.sketchToModelSpace(adsk.core.Point3D.create(0, 0, 0))),
                                "normal": vec(sk.xDirection.crossProduct(sk.yDirection))}, None),
         "visible": safe(lambda: sk.isVisible, None),
         "transform": matrix(sk.transform),
         "referencePlane": safe(lambda: short_type(sk.referencePlane), None),
         "profiles": safe(lambda: sk.profiles.count, None)}
    d["curves"] = [safe(lambda c=c: curve_geom(c)) for c in sk.sketchCurves]
    d["points"] = [pt(p.geometry) for p in sk.sketchPoints]
    d["constraints"] = dict(collections.Counter(short_type(c) for c in sk.geometricConstraints))
    dims = []
    for dim in sk.sketchDimensions:
        dims.append({"type": short_type(dim), "driving": safe(lambda: dim.isDriving, None),
                     "parameter": param(safe(lambda: dim.parameter, False) or None)})
    d["dimensions"] = dims
    return d


def profile_ref(p):
    t = short_type(p)
    if t == "Profile":
        sk = p.parentSketch
        idx = None
        for i, q in enumerate(sk.profiles):
            if q == p:
                idx = i
                break
        ap = p.areaProperties()
        return {"type": t, "sketch": sk.name, "component": sk.parentComponent.name, "index": idx,
                "area": ap.area, "centroid": pt(sk.sketchToModelSpace(ap.centroid))}
    if t == "ObjectCollection":
        return [profile_ref(p.item(i)) for i in range(p.count)]
    return {"type": t}


def extent(e):
    if e is None:
        return None
    t = short_type(e)
    d = {"type": t}
    if t == "DistanceExtentDefinition":
        d["distance"] = param(e.distance)
    elif t == "ToEntityExtentDefinition":
        d["entity"] = short_type(e.entity)
        d["offset"] = param(safe(lambda: e.offset, False) or None)
        d["isChained"] = safe(lambda: e.isChained, None)
    elif t == "ThroughAllExtentDefinition":
        d["direction"] = safe(lambda: e.direction, None)
    elif t in ("ProfilePlaneStartDefinition",):
        pass
    elif t == "OffsetStartDefinition":
        d["offset"] = param(e.offset)
    elif t in ("EntityStartDefinition", "FromEntityStartDefinition"):
        d["entity"] = short_type(e.entity)
        d["offset"] = param(safe(lambda: e.offset, False) or None)
        d["face"] = safe(lambda: face_sig(e.entity), None)
    elif t == "SymmetricExtentDefinition":
        d["distance"] = param(e.distance)
        d["isFullLength"] = safe(lambda: e.isFullLength, None)
    return d


def face_sig(f):
    g = f.geometry
    d = {"surface": short_type(g), "area": safe(lambda: f.area, None),
         "point": safe(lambda: pt(f.pointOnFace), None), "body": safe(lambda: f.body.name, None)}
    if short_type(g) == "Plane":
        d["origin"], d["normal"] = pt(g.origin), vec(g.normal)
        d["reversed"] = safe(lambda: f.isParamReversed, None)
    return d


def bodies(coll):
    try:
        return [{"name": b.name, "component": b.parentComponent.name} for b in coll]
    except Exception as e:
        return {"error": str(e)[:200]}


def edge_sig(e):
    d = {"curve": short_type(e.geometry), "length": safe(lambda: e.length, None),
         "body": safe(lambda: e.body.name, None)}
    d["start"] = safe(lambda: pt(e.startVertex.geometry), None)
    d["end"] = safe(lambda: pt(e.endVertex.geometry), None)
    d["mid"] = safe(lambda: pt(e.pointOnEdge), None)
    return d


def dump_extrude(f):
    d = {"operation": f.operation, "extentType": safe(lambda: f.extentType, None),
         "isSolid": safe(lambda: f.isSolid, None),
         "startExtent": safe(lambda: extent(f.startExtent)),
         "extentOne": safe(lambda: extent(f.extentOne)),
         "extentTwo": safe(lambda: extent(f.extentTwo), None),
         "taperOne": param(safe(lambda: f.taperAngleOne, False) or None),
         "taperTwo": param(safe(lambda: f.taperAngleTwo, False) or None),
         "symmetric": safe(lambda: f.symmetricExtent is not None, None),
         "profile": safe(lambda: profile_ref(f.profile)),
         "participantBodies": bodies(safe(lambda: f.participantBodies, [])),
         "resultBodies": bodies(f.bodies)}
    return d


def dump_edge_feature(f, kind):
    sets = []
    for es in f.edgeSets:
        s = {"type": short_type(es)}
        for attr in ("radius", "distance", "distanceOne", "distanceTwo", "angle"):
            v = safe(lambda: getattr(es, attr), False)
            if v:
                s[attr] = param(v)
        s["isTangentChain"] = safe(lambda: es.isTangentChain, None)
        edges = safe(lambda: es.edges, False) or safe(lambda: es.entities, False)
        s["edges"] = [safe(lambda e=e: edge_sig(e)) for e in edges] if edges else None
        sets.append(s)
    return {"edgeSets": sets, "resultBodies": bodies(f.bodies)}


def dump_entity(ent, kind):
    if kind == "Sketch":
        return dump_sketch(ent)
    if kind == "ExtrudeFeature":
        return dump_extrude(ent)
    if kind in ("FilletFeature", "ChamferFeature"):
        return dump_edge_feature(ent, kind)
    if kind == "ConstructionPlane":
        return {"definition": safe(lambda: short_type(ent.definition), None),
                "geometry": safe(lambda: {"origin": pt(ent.geometry.origin), "normal": vec(ent.geometry.normal)})}
    d = {}
    for attr in ("operation", "quantity", "totalAngle", "isSymmetric"):
        v = safe(lambda: getattr(ent, attr), False)
        if v not in (False, None):
            d[attr] = param(v) if hasattr(v, "expression") else v
    d["resultBodies"] = bodies(safe(lambda: ent.bodies, []))
    return d


def body_props(b):
    pp = b.physicalProperties
    bb = b.boundingBox
    return {"component": b.parentComponent.name, "name": b.name, "solid": b.isSolid,
            "visible": safe(lambda: b.isLightBulbOn, None), "volume": pp.volume, "area": pp.area,
            "centroid": pt(pp.centerOfMass), "bbox": [pt(bb.minPoint), pt(bb.maxPoint)],
            "faces": b.faces.count, "edges": b.edges.count}


def all_bodies(design):
    out = []
    for comp in design.allComponents:
        for b in comp.bRepBodies:
            out.append(body_props(b))
    return out


def world_bodies(design):
    """Bodies as placed in the root: proxies through every occurrence, so volumes and
    centroids are in world coordinates (what a flattened rebuild produces)."""
    root = design.rootComponent
    out = [body_props(b) for b in root.bRepBodies]
    for occ in root.allOccurrences:
        for b in occ.bRepBodies:
            d = body_props(b)
            d["occurrence"] = occ.fullPathName
            out.append(d)
    return out


def dump_design(design, roll=True, steps=False):
    """Timeline with feature definitions (rolling before fillets/chamfers/from-face extrudes
    when roll), final bodies, and optionally body volumes after every timeline item."""
    t0 = time.time()
    tl = design.timeline
    # Items inside collapsed groups have no valid index and cannot be rolled to.
    collapsed = [g for g in tl.timelineGroups if g.isCollapsed]
    for g in collapsed:
        g.isCollapsed = False
    flat = []
    for i in range(tl.count):
        it = tl.item(i)
        if it.isGroup:
            continue
        group = safe(lambda: it.parentGroup.name if it.parentGroup else None, None)
        flat.append((it, group))
    records, errors, rolled = [], 0, 0
    for idx, (it, group) in enumerate(flat):
        ent = it.entity
        kind = short_type(ent) if ent else None
        rec = {"index": idx, "name": it.name, "group": group, "type": kind,
               "suppressed": it.isSuppressed,
               "component": safe(lambda: ent.parentComponent.name, None)}
        try:
            needs_roll = kind in ("FilletFeature", "ChamferFeature") or (
                kind == "ExtrudeFeature" and safe(lambda: short_type(ent.startExtent), "") == "FromEntityStartDefinition")
            if roll and needs_roll:
                it.rollTo(True)
                rolled += 1
            rec["data"] = dump_entity(ent, kind) if ent else None
        except Exception:
            errors += 1
            rec["error"] = traceback.format_exc()[-600:]
        if steps:
            try:
                it.rollTo(False)
                rec["after"] = [{"component": b["component"], "name": b["name"], "volume": b["volume"],
                                 "occurrence": b.get("occurrence")} for b in world_bodies(design)]
            except Exception:
                rec["after_error"] = traceback.format_exc()[-300:]
        records.append(rec)
    if rolled or steps:
        tl.moveToEnd()
    for g in collapsed:
        g.isCollapsed = True
    return {"design": design.rootComponent.name, "units": "cm",
            "userParameters": [param(p) | {"comment": p.comment} for p in design.userParameters],
            "timeline": records, "bodies": all_bodies(design), "worldBodies": world_bodies(design),
            "stats": {"items": len(records), "errors": errors, "rolled": rolled, "seconds": round(time.time() - t0, 2)}}


def run(_context: str):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    out = dump_design(design, roll=ROLL, steps=False)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(out["stats"])
