"""Fusion-side test-case generator (run via `mcp_call.py script make_cases.py --include
dump_features.py OUTDIR=... ONLY=...`). Each case builds a fresh parametric design, records
ground truth with dump_design() (feature definitions, final bodies, body volumes after
every timeline item), exports <case>.f3d + <case>.truth.json to OUTDIR, and closes the
document without saving. API lengths are cm.
"""
import adsk.core, adsk.fusion, json, os, traceback, math

OUTDIR = r"__OUTDIR__"
ONLY = r"__ONLY__"

P = adsk.core.Point3D.create
Vec = adsk.core.Vector3D.create
V = adsk.core.ValueInput.createByString
FO = adsk.fusion.FeatureOperations
POS = adsk.fusion.ExtentDirections.PositiveExtentDirection
NEG = adsk.fusion.ExtentDirections.NegativeExtentDirection


# ---------------------------------------------------------------- helpers
def coll(items):
    c = adsk.core.ObjectCollection.create()
    for i in items:
        c.add(i)
    return c


def rect(sk, x0, y0, x1, y1):
    return sk.sketchCurves.sketchLines.addTwoPointRectangle(P(x0, y0, 0), P(x1, y1, 0))


def circle(sk, cx, cy, r):
    return sk.sketchCurves.sketchCircles.addByCenterRadius(P(cx, cy, 0), r)


def profiles(sk, pred=lambda p, c, a: True):
    out = []
    for p in sk.profiles:
        ap = p.areaProperties()
        if pred(p, ap.centroid, ap.area):
            out.append(p)
    return out


def extrude(comp, profs, op, setup):
    ex = comp.features.extrudeFeatures
    inp = ex.createInput(profs if not isinstance(profs, list) else coll(profs), op)
    setup(inp)
    return ex.add(inp)


def blind(d):
    return lambda inp: inp.setDistanceExtent(False, V(d))


def block(comp, x0, y0, x1, y1, h, plane=None, op=FO.NewBodyFeatureOperation):
    sk = comp.sketches.add(plane or comp.xYConstructionPlane)
    rect(sk, x0, y0, x1, y1)
    return extrude(comp, sk.profiles.item(0), op, blind(h)).bodies.item(0)


def planar_faces(body):
    return [f for f in body.faces if short_type(f.geometry) == "Plane"]


def top_face(body):
    return max(planar_faces(body), key=lambda f: f.centroid.z)


def vertical_edges(body):
    return [e for e in body.edges if short_type(e.geometry) == "Line3D"
            and abs(e.startVertex.geometry.z - e.endVertex.geometry.z) > 1e-6]


def fillet(comp, edges, radius):
    fs = comp.features.filletFeatures
    fi = fs.createInput()
    try:
        fi.edgeSetInputs.addConstantRadiusEdgeSet(coll(edges), V(radius), True)
    except AttributeError:
        fi.addConstantRadiusEdgeSet(coll(edges), V(radius), True)
    return fs.add(fi)


def chamfer(comp, edges, dist):
    cs = comp.features.chamferFeatures
    try:
        ci = cs.createInput2()
        ci.chamferEdgeSets.addEqualDistanceChamferEdgeSet(coll(edges), V(dist), True)
    except AttributeError:
        ci = cs.createInput(coll(edges), True)
        ci.setToEqualDistance(V(dist))
    return cs.add(ci)


# ---------------------------------------------------------------- cases
CASES = {}


def case(fn):
    CASES[fn.__name__] = fn
    return fn


@case
def extrude_blind(design, root):
    block(root, 0, 0, 2, 1, "5 mm")


@case
def extrude_negative(design, root):
    block(root, 0, 0, 2, 1, "-5 mm")


@case
def extrude_symmetric_half(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, 0, 0, 2, 1)
    extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation,
            lambda inp: inp.setSymmetricExtent(V("4 mm"), False, V("0 deg")))


@case
def extrude_symmetric_full(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, 0, 0, 2, 1)
    extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation,
            lambda inp: inp.setSymmetricExtent(V("4 mm"), True, V("0 deg")))


@case
def extrude_two_sided(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, 0, 0, 2, 1)
    D = adsk.fusion.DistanceExtentDefinition.create
    extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation,
            lambda inp: inp.setTwoSidesExtent(D(V("8 mm")), D(V("3 mm")), V("0 deg"), V("0 deg")))


@case
def extrude_taper(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, 0, 0, 2, 1)
    extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation,
            lambda inp: inp.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(V("5 mm")), POS, V("-5 deg")))


@case
def extrude_offset_start(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, 0, 0, 2, 1)

    def setup(inp):
        inp.startExtent = adsk.fusion.OffsetStartDefinition.create(V("4 mm"))
        inp.setDistanceExtent(False, V("3 mm"))
    extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation, setup)


@case
def cut_through_all(design, root):
    body = block(root, 0, 0, 2, 1, "6 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 1, 0.5, 0.3)
    extrude(root, sk.profiles.item(0), FO.CutFeatureOperation,
            lambda inp: inp.setOneSideExtent(adsk.fusion.ThroughAllExtentDefinition.create(), POS))


@case
def extrude_to_face(design, root):
    tall = block(root, 0, 0, 1, 1, "10 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, 1.5, 0, 2.5, 1)
    target = top_face(tall)
    extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation,
            lambda inp: inp.setOneSideExtent(adsk.fusion.ToEntityExtentDefinition.create(target, False, V("0 mm")), POS))


@case
def cut_from_top_face(design, root):
    """Like Burninator Backplate Extrusion2: sketch on the bottom plane, cut starting at
    the top face going down 3 mm."""
    body = block(root, 0, 0, 2, 1, "6 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 0.5, 0.5, 0.3)
    circle(sk, 1.5, 0.5, 0.3)
    face = top_face(body)

    def setup(inp):
        inp.startExtent = adsk.fusion.FromEntityStartDefinition.create(face, V("0 mm"))
        inp.setDistanceExtent(False, V("-3 mm"))
    extrude(root, profiles(sk), FO.CutFeatureOperation, setup)


@case
def join_from_face_offset(design, root):
    body = block(root, 0, 0, 2, 1, "6 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 1, 0.5, 0.3)
    face = top_face(body)

    def setup(inp):
        inp.startExtent = adsk.fusion.FromEntityStartDefinition.create(face, V("1 mm"))
        inp.setDistanceExtent(False, V("2 mm"))
    extrude(root, profiles(sk), FO.NewBodyFeatureOperation, setup)


def lens_sketch(root):
    """Rectangle 10x6 mm and circle r=4 mm, both centred: five regions (lens, top cap,
    bottom cap, left and right remainders)."""
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, -0.5, -0.3, 0.5, 0.3)
    circle(sk, 0, 0, 0.4)
    return sk


@case
def regions_full_circle(design, root):
    sk = lens_sketch(root)
    sel = profiles(sk, lambda p, c, a: math.hypot(c.x, c.y) < 0.4)
    extrude(root, sel, FO.NewBodyFeatureOperation, blind("2 mm"))


@case
def regions_lens_and_cap(design, root):
    sk = lens_sketch(root)
    sel = profiles(sk, lambda p, c, a: abs(c.x) < 0.2 and c.y > -0.3)
    extrude(root, sel, FO.NewBodyFeatureOperation, blind("2 mm"))


@case
def regions_lens_only(design, root):
    sk = lens_sketch(root)
    sel = profiles(sk, lambda p, c, a: abs(c.x) < 0.2 and abs(c.y) < 0.2)
    extrude(root, sel, FO.NewBodyFeatureOperation, blind("2 mm"))


@case
def regions_outer_ring(design, root):
    sk = lens_sketch(root)
    sel = profiles(sk, lambda p, c, a: abs(c.x) > 0.2)
    extrude(root, sel, FO.NewBodyFeatureOperation, blind("2 mm"))


@case
def disjoint_new_body(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 0, 0, 0.3)
    circle(sk, 1, 0, 0.3)
    extrude(root, profiles(sk), FO.NewBodyFeatureOperation, blind("4 mm"))


@case
def join_bridge(design, root):
    block(root, 0, 0, 1, 1, "4 mm")
    block(root, 2, 0, 3, 1, "4 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, 0.5, 0.25, 2.5, 0.75)
    extrude(root, sk.profiles.item(0), FO.JoinFeatureOperation, blind("2 mm"))


@case
def join_touching_only(design, root):
    block(root, 0, 0, 1, 1, "4 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, 1, 0, 2, 1)
    extrude(root, sk.profiles.item(0), FO.JoinFeatureOperation, blind("4 mm"))


@case
def cut_participant(design, root):
    lower = block(root, 0, 0, 2, 1, "3 mm")
    plane_in = root.constructionPlanes.createInput()
    plane_in.setByOffset(root.xYConstructionPlane, V("3 mm"))
    plane = root.constructionPlanes.add(plane_in)
    upper = block(root, 0, 0, 2, 1, "3 mm", plane=plane)
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 1, 0.5, 0.3)

    def setup(inp):
        inp.setOneSideExtent(adsk.fusion.ThroughAllExtentDefinition.create(), POS)
        inp.participantBodies = [upper]
    extrude(root, sk.profiles.item(0), FO.CutFeatureOperation, setup)


@case
def fillet_vertical_edges(design, root):
    body = block(root, 0, 0, 2, 1, "5 mm")
    fillet(root, vertical_edges(body), "2 mm")


@case
def chamfer_top_edges(design, root):
    body = block(root, 0, 0, 2, 1, "5 mm")
    chamfer(root, list(top_face(body).edges), "1 mm")


@case
def component_offset(design, root):
    m = adsk.core.Matrix3D.create()
    m.setToRotation(math.radians(30), Vec(0, 0, 1), P(0, 0, 0))
    m.translation = Vec(3, 1, 0.5)
    occ = root.occurrences.addNewComponent(m)
    comp = occ.component
    comp.name = "offset_part"
    block(comp, 0, 0, 2, 1, "5 mm")


@case
def params_renamed_suppressed(design, root):
    ups = design.userParameters
    ups.add("width", V("20 mm"), "mm", "block width")
    ups.add("depth", V("7 mm"), "mm", "extrude depth")
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.name = "base_outline"
    lines = rect(sk, 0, 0, 2, 1)
    dim = sk.sketchDimensions.addDistanceDimension(
        lines.item(0).startSketchPoint, lines.item(0).endSketchPoint,
        adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation, P(1, -0.3, 0))
    dim.parameter.expression = "width"
    ext = extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("depth"))
    ext.name = "main_block"
    sk2 = root.sketches.add(root.xYConstructionPlane)
    sk2.name = "hole_sketch"
    circle(sk2, 1, 0.5, 0.2)
    hole = extrude(root, sk2.profiles.item(0), FO.CutFeatureOperation,
                   lambda inp: inp.setOneSideExtent(adsk.fusion.ThroughAllExtentDefinition.create(), POS))
    hole.name = "suppressed_hole"
    hole.timelineObject.isSuppressed = True


def through_all(inp):
    inp.setOneSideExtent(adsk.fusion.ThroughAllExtentDefinition.create(), POS)


def corner_edges(body, xs, ys):
    """Vertical edges whose endpoints sit on the given x/y corner coordinates (cm)."""
    def on(v, vals):
        return any(abs(v - c) < 1e-6 for c in vals)
    return [e for e in vertical_edges(body)
            if on(e.startVertex.geometry.x, xs) and on(e.startVertex.geometry.y, ys)]


@case
def suppressed_default_names(design, root):
    """Suppressed cut and fillet that keep their default names, then an active block."""
    body = block(root, 0, 0, 2, 1, "5 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 1, 0.5, 0.2)
    cut = extrude(root, sk.profiles.item(0), FO.CutFeatureOperation, through_all)
    cut.timelineObject.isSuppressed = True
    fil = fillet(root, corner_edges(body, (0, 2), (0, 1)), "2 mm")
    fil.timelineObject.isSuppressed = True
    block(root, 3, 0, 4, 1, "3 mm")


@case
def renamed_mixed(design, root):
    """Renamed sketches and features; the chamfer is suppressed, the others are active."""
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.name = "outline"
    rect(sk, 0, 0, 2, 1)
    ext = extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("5 mm"))
    ext.name = "plate"
    body = ext.bodies.item(0)
    sk2 = root.sketches.add(root.xYConstructionPlane)
    sk2.name = "bore_sketch"
    circle(sk2, 1, 0.5, 0.2)
    cut = extrude(root, sk2.profiles.item(0), FO.CutFeatureOperation, through_all)
    cut.name = "bore"
    ch = chamfer(root, [e for e in top_face(body).edges if short_type(e.geometry) == "Line3D"], "0.5 mm")
    ch.name = "top_chamfer"
    ch.timelineObject.isSuppressed = True
    fil = fillet(root, corner_edges(body, (0, 2), (0, 1)), "1 mm")
    fil.name = "corner_round"


@case
def rolled_back_marker(design, root):
    """A renamed through cut left after the timeline marker (rolled back, active)."""
    block(root, 0, 0, 2, 1, "5 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 1, 0.5, 0.2)
    cut = extrude(root, sk.profiles.item(0), FO.CutFeatureOperation, through_all)
    cut.name = "late_cut"

    def post():
        design.timeline.markerPosition = 3
    return post


# ---------------------------------------------------------------- driver
def run(_context: str):
    app = adsk.core.Application.get()
    only = [n for n in ONLY.split(",") if n and not n.startswith("__")]
    names = [n for n in CASES if not only or n in only]
    os.makedirs(OUTDIR, exist_ok=True)
    for name in names:
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        try:
            design = adsk.fusion.Design.cast(app.activeProduct)
            design.designType = adsk.fusion.DesignTypes.ParametricDesignType
            root = design.rootComponent
            post = CASES[name](design, root)
            truth = dump_design(design, roll=True, steps=True)
            if callable(post):
                post()
            truth["case"] = name
            truth["doc"] = (CASES[name].__doc__ or "").strip()
            em = design.exportManager
            em.execute(em.createFusionArchiveExportOptions(os.path.join(OUTDIR, name + ".f3d"), root))
            with open(os.path.join(OUTDIR, name + ".truth.json"), "w", encoding="utf-8") as f:
                json.dump(truth, f, indent=1, ensure_ascii=False)
            vols = ["%.4f" % (b["volume"] * 1000) for b in truth["worldBodies"]]
            print("%-28s ok  items %2d  errors %d  bodies(mm3) %s" % (name, truth["stats"]["items"], truth["stats"]["errors"], vols))
        except Exception:
            print("%-28s FAILED\n%s" % (name, traceback.format_exc()[-700:]))
        finally:
            doc.close(False)
