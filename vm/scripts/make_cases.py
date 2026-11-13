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

# ---------------------------------------------------------------- fillet / chamfer cases
# Blocks are (0,0)-(2,1) cm, 5 mm high unless stated. Edges are picked by endpoint position.
def _pt(v):
    g = v.geometry
    return (g.x, g.y, g.z)


def _near(a, b, t=1e-5):
    return all(abs(x - y) < t for x, y in zip(a, b))


def edge_at(body, p0, p1):
    for e in body.edges:
        a, b = _pt(e.startVertex), _pt(e.endVertex)
        if (_near(a, p0) and _near(b, p1)) or (_near(a, p1) and _near(b, p0)):
            return e
    raise RuntimeError("no edge %s-%s" % (p0, p1))


def edges_at_vertex(body, p):
    return [e for e in body.edges if _near(_pt(e.startVertex), p) or _near(_pt(e.endVertex), p)]


def circle_edges(body, z=None, cx=None):
    out = []
    for e in body.edges:
        if short_type(e.geometry) != "Circle3D":
            continue
        c = e.geometry.center
        if z is not None and abs(c.z - z) > 1e-6:
            continue
        if cx is not None and abs(c.x - cx) > 1e-6:
            continue
        out.append(e)
    return out


def cur(comp):
    return comp.bRepBodies.item(0)


def fillet_sets(comp, sets, rolling=True, g2=False):
    """sets: list of (kind, edges, args...) -> one fillet feature with several edge sets."""
    fs = comp.features.filletFeatures
    fi = fs.createInput()
    for st in sets:
        kind, edges, args = st[0], st[1], st[2:]
        es = fi.edgeSetInputs
        if kind == "const":
            es.addConstantRadiusEdgeSet(coll(edges), V(args[0]), args[1] if len(args) > 1 else True)
        elif kind == "var":
            es.addVariableRadiusEdgeSet(coll(edges), V(args[0]), V(args[1]), True)
        elif kind == "chord":
            es.addChordLengthEdgeSet(coll(edges), V(args[0]), True)
        elif kind == "asym":
            es.addAsymmetricRadiusEdgeSet(coll(edges), V(args[0]), V(args[1]), True)
    fi.isRollingBallCorner = rolling
    if g2:
        fi.isG2 = True
    return fs.add(fi)


def chamfer_two(comp, edges, d1, d2, flip=False):
    cs = comp.features.chamferFeatures
    ci = cs.createInput2()
    ci.chamferEdgeSets.addTwoDistancesChamferEdgeSet(coll(edges), V(d1), V(d2), True, flip)
    return cs.add(ci)


def chamfer_angle(comp, edges, d, ang, flip=False):
    cs = comp.features.chamferFeatures
    ci = cs.createInput2()
    ci.chamferEdgeSets.addDistanceAndAngleChamferEdgeSet(coll(edges), V(d), V(ang), True, flip)
    return cs.add(ci)


def offset_plane(comp, base, d):
    pi = comp.constructionPlanes.createInput()
    pi.setByOffset(base, V(d))
    return comp.constructionPlanes.add(pi)


def rounded_rect_block(root, h="5 mm", r=0.3):
    sk = root.sketches.add(root.xYConstructionPlane)
    ls = rect(sk, 0, 0, 2, 1)
    arcs = sk.sketchCurves.sketchArcs
    pts = [(0, 0), (2, 0), (2, 1), (0, 1)]
    for i in range(4):
        l1, l2 = ls.item(i), ls.item((i + 1) % 4)
        arcs.addFillet(l1, l1.endSketchPoint.geometry, l2, l2.startSketchPoint.geometry, r)
    return extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind(h)).bodies.item(0)


def plate_boss(root, round_boss=False):
    block(root, 0, 0, 3, 2, "4 mm")
    pl = offset_plane(root, root.xYConstructionPlane, "4 mm")
    sk = root.sketches.add(pl)
    if round_boss:
        circle(sk, 1.5, 1, 0.4)
    else:
        rect(sk, 1, 0.5, 2, 1.5)
    extrude(root, sk.profiles.item(0), FO.JoinFeatureOperation, blind("8 mm"))
    return cur(root)


def boss_base_edges(body, zc=0.4):
    return [e for e in body.edges
            if abs(e.startVertex.geometry.z - zc) < 1e-6 and abs(e.endVertex.geometry.z - zc) < 1e-6
            and 0.9 < e.startVertex.geometry.x < 2.1 and 0.4 < e.startVertex.geometry.y < 1.6] \
        or [e for e in circle_edges(body, z=zc)]


def holed_block(root):
    body = block(root, 0, 0, 2, 1, "5 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 1, 0.5, 0.3)
    extrude(root, sk.profiles.item(0), FO.CutFeatureOperation, through_all)
    return cur(root)


TOP, BOT = 0.5, 0.0


@case
def fillet_single_edge(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet(root, [edge_at(b, (0, 0, 0), (0, 0, TOP))], "2 mm")


@case
def fillet_single_top_edge(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet(root, [edge_at(b, (0, 0, TOP), (2, 0, TOP))], "1.5 mm")


@case
def fillet_box_all_edges(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet(root, list(b.edges), "1 mm")


@case
def fillet_top_face_edges(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet(root, list(top_face(b).edges), "1.5 mm")


@case
def fillet_cylinder_top_edge(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 0, 0, 0.5)
    extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("8 mm"))
    fillet(root, circle_edges(cur(root), z=0.8), "2 mm")


@case
def fillet_tangent_chain_rounded_rect(design, root):
    """Rounded-rectangle outline (sketch fillets); one edge selected, tangent chain picks the loop."""
    b = rounded_rect_block(root)
    top = [e for e in top_face(b).edges]
    line = [e for e in top if short_type(e.geometry) == "Line3D"][0]
    fillet_sets(root, [("const", [line], "1.5 mm", True)])


@case
def fillet_tangent_chain_off(design, root):
    """Same outline, tangent chain disabled: only the selected straight edge is rounded."""
    b = rounded_rect_block(root)
    line = [e for e in top_face(b).edges if short_type(e.geometry) == "Line3D"][0]
    fillet_sets(root, [("const", [line], "1.5 mm", False)])


@case
def fillet_vertical_then_top(design, root):
    """Two fillet features in sequence: vertical corners, then the (now tangent) top loop."""
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet(root, vertical_edges(b), "3 mm")
    b = cur(root)
    line = [e for e in top_face(b).edges if short_type(e.geometry) == "Line3D"][0]
    fillet_sets(root, [("const", [line], "1.5 mm", True)])


@case
def fillet_two_features_disjoint(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet(root, [edge_at(b, (0, 0, 0), (0, 0, TOP))], "2 mm")
    b = cur(root)
    fillet(root, [edge_at(b, (2, 1, TOP), (0, 1, TOP))], "1 mm")


@case
def fillet_hole_top_edge(design, root):
    b = holed_block(root)
    fillet(root, circle_edges(b, z=TOP), "1 mm")


@case
def fillet_hole_both_edges(design, root):
    b = holed_block(root)
    fillet(root, circle_edges(b), "1 mm")


@case
def fillet_concave_boss_square(design, root):
    b = plate_boss(root)
    fillet(root, boss_base_edges(b), "1.5 mm")


@case
def fillet_concave_boss_round(design, root):
    b = plate_boss(root, True)
    fillet(root, circle_edges(b, z=0.4), "1.5 mm")


@case
def fillet_boss_base_and_top(design, root):
    """Convex top rim and concave base of a round boss in one feature, two radii."""
    b = plate_boss(root, True)
    fillet_sets(root, [("const", circle_edges(b, z=0.4), "1.5 mm"),
                       ("const", circle_edges(b, z=1.2), "0.8 mm")])


@case
def fillet_corner_three_edges(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet(root, edges_at_vertex(b, (0, 0, TOP)), "2 mm")


@case
def fillet_corner_mixed_radii(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    es = edges_at_vertex(b, (0, 0, TOP))
    fillet_sets(root, [("const", [es[0]], "1 mm"), ("const", [es[1]], "2 mm"), ("const", [es[2]], "1.5 mm")])


@case
def fillet_corner_setback(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet_sets(root, [("const", edges_at_vertex(b, (0, 0, TOP)), "2 mm")], rolling=False)


@case
def fillet_corner_rolling_ball_explicit(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet_sets(root, [("const", edges_at_vertex(b, (0, 0, TOP)), "2 mm")], rolling=True)


@case
def fillet_two_edge_sets(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet_sets(root, [("const", [edge_at(b, (0, 0, TOP), (2, 0, TOP)), edge_at(b, (0, 1, TOP), (2, 1, TOP))], "1 mm"),
                       ("const", [edge_at(b, (0, 0, 0), (0, 1, 0)), edge_at(b, (2, 0, 0), (2, 1, 0))], "2 mm")])


@case
def fillet_variable_radius(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet_sets(root, [("var", [edge_at(b, (0, 0, TOP), (2, 0, TOP))], "1 mm", "3 mm")])


@case
def fillet_chord_length(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet_sets(root, [("chord", [edge_at(b, (0, 0, TOP), (2, 0, TOP))], "3 mm")])


@case
def fillet_asymmetric(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet_sets(root, [("asym", [edge_at(b, (0, 0, TOP), (2, 0, TOP))], "1 mm", "2.5 mm")])


@case
def fillet_g2_continuity(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet_sets(root, [("const", [edge_at(b, (0, 0, TOP), (2, 0, TOP))], "2 mm")], g2=True)


@case
def fillet_after_pattern(design, root):
    b = block(root, 0, 0, 4, 1.5, "5 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 0.5, 0.75, 0.2)
    cut = extrude(root, sk.profiles.item(0), FO.CutFeatureOperation, through_all)
    pf = root.features.rectangularPatternFeatures
    pi = pf.createInput(coll([cut]), root.xConstructionAxis, V("3"), V("12 mm"),
                        adsk.fusion.PatternDistanceType.SpacingPatternDistanceType)
    pf.add(pi)
    fillet(root, circle_edges(cur(root), z=TOP), "0.8 mm")


@case
def chamfer_single_edge(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    chamfer(root, [edge_at(b, (0, 0, TOP), (2, 0, TOP))], "1.5 mm")


@case
def chamfer_box_all_edges(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    chamfer(root, list(b.edges), "1 mm")


@case
def chamfer_two_distances(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    chamfer_two(root, [edge_at(b, (0, 0, TOP), (2, 0, TOP))], "1 mm", "2.5 mm")


@case
def chamfer_two_distances_swapped(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    chamfer_two(root, [edge_at(b, (0, 0, TOP), (2, 0, TOP))], "2.5 mm", "1 mm")


@case
def chamfer_two_distances_flipped(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    chamfer_two(root, [edge_at(b, (0, 0, TOP), (2, 0, TOP))], "1 mm", "2.5 mm", True)


@case
def chamfer_distance_angle_flipped(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    chamfer_angle(root, [edge_at(b, (0, 0, TOP), (2, 0, TOP))], "2 mm", "30 deg", True)


@case
def chamfer_distance_angle(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    chamfer_angle(root, [edge_at(b, (0, 0, TOP), (2, 0, TOP))], "2 mm", "30 deg")


@case
def chamfer_hole_edge(design, root):
    b = holed_block(root)
    chamfer(root, circle_edges(b, z=TOP), "1 mm")


@case
def chamfer_corner_three_edges(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    chamfer(root, edges_at_vertex(b, (0, 0, TOP)), "1.5 mm")


@case
def chamfer_tangent_chain(design, root):
    b = rounded_rect_block(root)
    line = [e for e in top_face(b).edges if short_type(e.geometry) == "Line3D"][0]
    cs = root.features.chamferFeatures
    ci = cs.createInput2()
    ci.chamferEdgeSets.addEqualDistanceChamferEdgeSet(coll([line]), V("1 mm"), True)
    cs.add(ci)


@case
def chamfer_concave_boss(design, root):
    b = plate_boss(root)
    chamfer(root, boss_base_edges(b), "1.5 mm")


@case
def chamfer_and_fillet_adjacent(design, root):
    """Fillet one vertical edge, then chamfer the adjacent top edge that runs into it."""
    b = block(root, 0, 0, 2, 1, "5 mm")
    fillet(root, [edge_at(b, (0, 0, 0), (0, 0, TOP))], "2 mm")
    b = cur(root)
    chamfer(root, [edge_at(b, (0.2, 0, TOP), (2, 0, TOP))], "1 mm")


@case
def chamfer_then_fillet_same_corner(design, root):
    b = block(root, 0, 0, 2, 1, "5 mm")
    chamfer(root, [edge_at(b, (0, 0, TOP), (2, 0, TOP))], "1 mm")
    b = cur(root)
    fillet(root, [edge_at(b, (0, 0, 0), (0, 0, TOP - 0.1))], "2 mm")


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
