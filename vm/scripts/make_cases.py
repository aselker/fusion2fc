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
    # signature: (edges, distanceOne, distanceTwo, isFlipped, isTangentChain). Round 1 passed
    # (True, flip), i.e. isFlipped=True always and flip landing in isTangentChain.
    cs = comp.features.chamferFeatures
    ci = cs.createInput2()
    ci.chamferEdgeSets.addTwoDistancesChamferEdgeSet(coll(edges), V(d1), V(d2), flip, True)
    return cs.add(ci)


def chamfer_angle(comp, edges, d, ang, flip=False):
    cs = comp.features.chamferFeatures
    ci = cs.createInput2()
    ci.chamferEdgeSets.addDistanceAndAngleChamferEdgeSet(coll(edges), V(d), V(ang), flip, True)
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


# ================================================================ round 2: hobby-feature cases
def smallest(sk):
    """Smallest-area profile (a sketch on a face also gets the face outline as a profile)."""
    return min(sk.profiles, key=lambda p: p.areaProperties().area)


def only_body(comp):
    return comp.bRepBodies.item(0)


def line(sk, x0, y0, x1, y1):
    return sk.sketchCurves.sketchLines.addByTwoPoints(P(x0, y0, 0), P(x1, y1, 0))


def join_blind(comp, sk, d="5 mm", op=FO.JoinFeatureOperation):
    return extrude(comp, sk.profiles.item(0), op, blind(d))


def extrude_all(comp, sk, d, op=FO.NewBodyFeatureOperation):
    return extrude(comp, profiles(sk), op, blind(d))


def tangent_arc(sk, l1, end):
    """Arc starting at l1's end point, tangent to l1 (no addTangent in the API: three-point arc
    plus a tangent constraint)."""
    s = l1.endSketchPoint.geometry
    mid = P((s.x + end.x) / 2 + 0.2, (s.y + end.y) / 2 - 0.1, 0)
    arc = sk.sketchCurves.sketchArcs.addByThreePoints(l1.endSketchPoint, mid, end)
    sk.geometricConstraints.addTangent(l1, arc)
    return arc


def poly_pts(sk, pts):
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        line(sk, a[0], a[1], b[0], b[1])


# ---- sketch features feeding an extrude
@case
def sk_slot_center_to_center(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.addCenterToCenterSlot(P(0, 0, 0), P(2, 0, 0), V("8 mm"), False)
    extrude_all(root, sk, "4 mm")


@case
def sk_slot_overall_cut(design, root):
    block(root, -1, -1, 3, 1, "5 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.addOverallSlot(P(0, 0, 0), P(2, 0, 0), V("6 mm"), False)
    extrude(root, profiles(sk), FO.CutFeatureOperation, through_all)


@case
def sk_polygon_hexagon(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.sketchCurves.sketchLines.addScribedPolygon(P(0, 0, 0), 6, 0.0, 1.0, True)
    extrude_all(root, sk, "6 mm")


@case
def sk_polygon_circumscribed_pentagon(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.sketchCurves.sketchLines.addScribedPolygon(P(0, 0, 0), 5, math.radians(20), 1.0, False)
    extrude_all(root, sk, "6 mm")


@case
def sk_fillet_corners(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    pts = [(0, 0), (3, 0), (3, 1), (1.5, 2), (0, 1)]
    poly_pts(sk, pts)
    lines = list(sk.sketchCurves.sketchLines)
    arcs = sk.sketchCurves.sketchArcs
    for i in (0, 1, 2):
        l1, l2 = lines[i], lines[i + 1]
        arcs.addFillet(l1, l1.endSketchPoint.geometry, l2, l2.startSketchPoint.geometry, 0.25)
    extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("4 mm"))


@case
def sk_chamfer_corners(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    ls = rect(sk, 0, 0, 3, 2)
    L = sk.sketchCurves.sketchLines
    a, b, c = ls.item(0), ls.item(1), ls.item(2)
    L.addDistanceChamfer(a, a.endSketchPoint.geometry, b, b.startSketchPoint.geometry, 0.5, 0.5)
    L.addDistanceChamfer(b, b.startSketchPoint.geometry, c, c.startSketchPoint.geometry, 0.3, 0.3)
    extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("4 mm"))


@case
def sk_offset_curves_ring(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, 0, 0, 3, 2)
    curves = sk.findConnectedCurves(sk.sketchCurves.sketchLines.item(0))
    sk.offset(curves, P(1.5, 1, 0), 0.4)
    # ring between outer rect and inset rect
    extrude(root, [p for p in sk.profiles if p.profileLoops.count == 2], FO.NewBodyFeatureOperation, blind("4 mm"))


@case
def sk_spline_fit(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    pts = coll([P(0, 0, 0), P(1, 0.6, 0), P(2, 0.2, 0), P(3, 0.8, 0)])
    sp = sk.sketchCurves.sketchFittedSplines.add(pts)
    line(sk, 3, 0.8, 3, -1)
    line(sk, 3, -1, 0, -1)
    line(sk, 0, -1, 0, 0)
    extrude_all(root, sk, "5 mm")


@case
def sk_spline_control_point(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    pts = [P(0, 0, 0), P(1, 1, 0), P(2, -0.5, 0), P(3, 0.5, 0)]
    sk.sketchCurves.sketchControlPointSplines.add(pts, 3)
    line(sk, 3, 0.5, 3, -1.5)
    line(sk, 3, -1.5, 0, -1.5)
    line(sk, 0, -1.5, 0, 0)
    extrude_all(root, sk, "5 mm")


@case
def sk_arc_three_point(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.sketchCurves.sketchArcs.addByThreePoints(P(0, 0, 0), P(1.5, 0.8, 0), P(3, 0, 0))
    line(sk, 3, 0, 0, 0)
    extrude_all(root, sk, "4 mm")


@case
def sk_arc_tangent(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    l1 = line(sk, 0, 0, 2, 0)
    arc = tangent_arc(sk, l1, P(3, 1, 0))
    e = arc.endSketchPoint.geometry
    L = sk.sketchCurves.sketchLines
    top = L.addByTwoPoints(arc.endSketchPoint, P(0, e.y, 0))
    L.addByTwoPoints(top.endSketchPoint, l1.startSketchPoint)
    extrude_all(root, sk, "4 mm")


@case
def sk_arc_center_start_end(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.sketchCurves.sketchArcs.addByCenterStartSweep(P(0, 0, 0), P(1.5, 0, 0), math.radians(120))
    sk.sketchCurves.sketchLines.addByTwoPoints(sk.sketchCurves.sketchArcs.item(0).endSketchPoint,
                                               sk.sketchCurves.sketchArcs.item(0).centerSketchPoint)
    sk.sketchCurves.sketchLines.addByTwoPoints(sk.sketchCurves.sketchArcs.item(0).centerSketchPoint,
                                               sk.sketchCurves.sketchArcs.item(0).startSketchPoint)
    extrude_all(root, sk, "4 mm")


@case
def sk_ellipse(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.sketchCurves.sketchEllipses.add(P(0, 0, 0), P(2, 0, 0), P(0, 1, 0))
    extrude_all(root, sk, "5 mm")


@case
def sk_ellipse_rotated_cut(design, root):
    block(root, -2, -2, 2, 2, "5 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    sk.sketchCurves.sketchEllipses.add(P(0, 0, 0), P(1.2, 0.7, 0), P(-0.3, 0.5, 0))
    extrude(root, profiles(sk), FO.CutFeatureOperation, through_all)


@case
def sk_construction_lines_mixed(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, 0, 0, 3, 2)
    d = line(sk, 0, 0, 3, 2)
    d.isConstruction = True
    c = circle(sk, 1.5, 1, 0.5)
    c.isConstruction = True
    line(sk, 1.5, 0, 1.5, 2).isConstruction = True
    extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("4 mm"))


@case
def sk_projected_edges(design, root):
    b = block(root, 0, 0, 3, 2, "4 mm")
    sk = root.sketches.add(top_face(b))
    sk.project(top_face(b).edges.item(0))
    sk.project(top_face(b).edges.item(1))
    sk.project(top_face(b).edges.item(2))
    sk.project(top_face(b).edges.item(3))
    # inset rectangle drawn relative to the projected outline
    rect(sk, 0.3, 0.3, 2.7, 1.7)
    extrude(root, [p for p in sk.profiles if p.profileLoops.count == 1 and p.areaProperties().area < 5.0],
            FO.CutFeatureOperation, blind("-2 mm"))


@case
def sk_intersect_plane(design, root):
    b = block(root, 0, 0, 3, 2, "6 mm")
    cyl_sk = root.sketches.add(root.xYConstructionPlane)
    circle(cyl_sk, 1.5, 1, 0.6)
    extrude(root, cyl_sk.profiles.item(0), FO.JoinFeatureOperation, blind("12 mm"))
    pl = offset_plane(root, root.xYConstructionPlane, "9 mm")
    sk = root.sketches.add(pl)
    sk.intersectWithSketchPlane([only_body(root)])
    rect(sk, 0.5, 0.2, 2.5, 1.8)
    extrude(root, [p for p in sk.profiles], FO.NewBodyFeatureOperation, blind("3 mm"))


@case
def sk_mirror_in_sketch(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    axis = line(sk, 0, -2, 0, 2)
    axis.isConstruction = True
    pts = [(0, 0), (1.5, 0), (1.5, 1), (0.5, 1.5), (0, 1.5)]
    ls = [line(sk, *pts[i], *pts[i + 1]) for i in range(4)]
    ls.append(line(sk, 0, 1.5, 0, 0))
    ls[-1].isConstruction = True
    sk.mirror(ls[:4], axis)
    extrude_all(root, sk, "4 mm")


@case
def sk_copy_pattern_in_sketch(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    c = circle(sk, 0, 0, 0.3)
    for i in (1, 2, 3):
        m = adsk.core.Matrix3D.create()
        m.translation = Vec(i * 1.0, 0.0, 0.0)
        sk.copy(coll([c]), m)
    extrude_all(root, sk, "4 mm")


@case
def sk_dimension_params(design, root):
    up = design.userParameters
    up.add("w", V("30 mm"), "mm", "")
    up.add("h", V("15 mm"), "mm", "")
    sk = root.sketches.add(root.xYConstructionPlane)
    ls = rect(sk, 0, 0, 1, 1)
    sk.sketchDimensions.addDistanceDimension(ls.item(0).startSketchPoint, ls.item(0).endSketchPoint,
                                             adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation,
                                             P(0.5, -0.5, 0)).parameter.expression = "w"
    sk.sketchDimensions.addDistanceDimension(ls.item(1).startSketchPoint, ls.item(1).endSketchPoint,
                                             adsk.fusion.DimensionOrientations.VerticalDimensionOrientation,
                                             P(3.5, 0.5, 0)).parameter.expression = "h"
    extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation, lambda inp: inp.setDistanceExtent(False, V("w / 3")))


@case
def sk_on_face_boss(design, root):
    b = block(root, 0, 0, 3, 2, "4 mm")
    sk = root.sketches.add(top_face(b))
    circle(sk, 1.5, 1, 0.5)
    extrude(root, smallest(sk), FO.JoinFeatureOperation, blind("6 mm"))


@case
def sk_on_side_face_cut(design, root):
    b = block(root, 0, 0, 3, 2, "6 mm")
    f = [f for f in planar_faces(b) if abs(f.centroid.y) < 1e-6 and abs(f.centroid.z - 0.3) < 1e-6][0]
    sk = root.sketches.add(f)
    circle(sk, 0, 0, 0.3)
    extrude(root, smallest(sk), FO.CutFeatureOperation, blind("-8 mm"))


@case
def sk_on_angled_plane(design, root):
    b = block(root, 0, 0, 3, 2, "4 mm")
    e = edge_at(b, (0, 0, TOP * 0.8), (3, 0, TOP * 0.8))
    pi = root.constructionPlanes.createInput()
    pi.setByAngle(e, V("30 deg"), root.xYConstructionPlane)
    pl = root.constructionPlanes.add(pi)
    sk = root.sketches.add(pl)
    circle(sk, 1.5, 0.8, 0.4)
    extrude(root, sk.profiles.item(0), FO.JoinFeatureOperation, blind("8 mm"))


@case
def sk_on_offset_plane(design, root):
    block(root, 0, 0, 3, 2, "4 mm")
    pl = offset_plane(root, root.xYConstructionPlane, "-6 mm")
    sk = root.sketches.add(pl)
    rect(sk, 0.5, 0.5, 2.5, 1.5)
    extrude(root, sk.profiles.item(0), FO.JoinFeatureOperation, blind("6 mm"))


@case
def sk_text_extrude(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    ti = sk.sketchTexts.createInput("AB", 1.0, P(0, 0, 0))
    t = sk.sketchTexts.add(ti)
    extrude(root, t, FO.NewBodyFeatureOperation, blind("2 mm"))


# ---- revolve
def revolve(comp, profs, axis, angle, op=FO.NewBodyFeatureOperation):
    rf = comp.features.revolveFeatures
    ri = rf.createInput(profs, axis, op)
    ri.setAngleExtent(False, V(angle))
    return rf.add(ri)


def half_profile(sk):
    poly_pts(sk, [(0.5, 0), (1.5, 0), (1.5, 1), (1, 2), (0.5, 2)])


@case
def rev_full_axis(design, root):
    sk = root.sketches.add(root.xZConstructionPlane)
    half_profile(sk)
    revolve(root, sk.profiles.item(0), root.zConstructionAxis, "360 deg")


@case
def rev_partial_angle(design, root):
    sk = root.sketches.add(root.xZConstructionPlane)
    half_profile(sk)
    revolve(root, sk.profiles.item(0), root.zConstructionAxis, "100 deg")


@case
def rev_about_sketch_line(design, root):
    sk = root.sketches.add(root.xZConstructionPlane)
    half_profile(sk)
    ax = line(sk, 0, 0, 0, 3)
    ax.isConstruction = True
    revolve(root, [p for p in sk.profiles][0], ax, "360 deg")


@case
def rev_about_profile_edge(design, root):
    sk = root.sketches.add(root.xZConstructionPlane)
    poly_pts(sk, [(0, 0), (1.2, 0), (1.2, 1.5), (0, 1)])
    ax = sk.sketchCurves.sketchLines.item(3)
    revolve(root, sk.profiles.item(0), ax, "270 deg")


@case
def rev_symmetric(design, root):
    sk = root.sketches.add(root.xZConstructionPlane)
    half_profile(sk)
    rf = root.features.revolveFeatures
    ri = rf.createInput(sk.profiles.item(0), root.zConstructionAxis, FO.NewBodyFeatureOperation)
    ri.setAngleExtent(True, V("120 deg"))
    rf.add(ri)


@case
def rev_cut_groove(design, root):
    sk0 = root.sketches.add(root.xYConstructionPlane)
    circle(sk0, 0, 0, 1.0)
    extrude(root, sk0.profiles.item(0), FO.NewBodyFeatureOperation, blind("20 mm"))
    sk = root.sketches.add(root.xZConstructionPlane)
    poly_pts(sk, [(0.7, -0.8), (1.2, -0.8), (1.2, -1.2), (0.7, -1.2)])
    revolve(root, sk.profiles.item(0), root.zConstructionAxis, "360 deg", FO.CutFeatureOperation)


@case
def rev_join_flange(design, root):
    sk0 = root.sketches.add(root.xYConstructionPlane)
    circle(sk0, 0, 0, 0.6)
    extrude(root, sk0.profiles.item(0), FO.NewBodyFeatureOperation, blind("20 mm"))
    sk = root.sketches.add(root.xZConstructionPlane)
    poly_pts(sk, [(0.5, -0.5), (1.4, -0.5), (1.4, -0.8), (0.5, -0.8)])
    revolve(root, sk.profiles.item(0), root.zConstructionAxis, "360 deg", FO.JoinFeatureOperation)


# ---- sweep
def sweep(comp, prof, path_curves, op=FO.NewBodyFeatureOperation, setup=None):
    path = comp.features.createPath(path_curves)
    sf = comp.features.sweepFeatures
    si = sf.createInput(prof, path, op)
    if setup:
        setup(si)
    return sf.add(si)


def yz_profile(root, r=0.3, x=0.0):
    sk = root.sketches.add(root.yZConstructionPlane)
    circle(sk, 0, 0, r)
    return sk.profiles.item(0)


@case
def sweep_line(design, root):
    prof = yz_profile(root)
    sk = root.sketches.add(root.xZConstructionPlane)
    sweep(root, prof, line(sk, 0, 0, 4, 0))


@case
def sweep_arc_path(design, root):
    prof = yz_profile(root)
    sk = root.sketches.add(root.xZConstructionPlane)
    arc = sk.sketchCurves.sketchArcs.addByThreePoints(P(0, 0, 0), P(1.5, 0.8, 0), P(3, 0, 0))
    sweep(root, prof, arc)


@case
def sweep_line_arc_path(design, root):
    prof = yz_profile(root)
    sk = root.sketches.add(root.xZConstructionPlane)
    l1 = line(sk, 0, 0, 2, 0)
    a = tangent_arc(sk, l1, P(3, 1, 0))
    sweep(root, prof, coll([l1, a]))


@case
def sweep_spline_path(design, root):
    prof = yz_profile(root, 0.25)
    sk = root.sketches.add(root.xZConstructionPlane)
    sp = sk.sketchCurves.sketchFittedSplines.add(coll([P(0, 0, 0), P(1, 0.5, 0), P(2, 0, 0), P(3, 0.7, 0)]))
    sweep(root, prof, sp)


@case
def sweep_twist(design, root):
    sk0 = root.sketches.add(root.yZConstructionPlane)
    rect(sk0, -0.3, -0.2, 0.3, 0.2)
    sk = root.sketches.add(root.xZConstructionPlane)
    sweep(root, sk0.profiles.item(0), line(sk, 0, 0, 4, 0), setup=lambda si: setattr(si, "twistAngle", V("90 deg")) or None)


@case
def sweep_taper(design, root):
    sk0 = root.sketches.add(root.yZConstructionPlane)
    rect(sk0, -0.4, -0.4, 0.4, 0.4)
    sk = root.sketches.add(root.xZConstructionPlane)
    sweep(root, sk0.profiles.item(0), line(sk, 0, 0, 4, 0), setup=lambda si: setattr(si, "taperAngle", V("-5 deg")) or None)


@case
def sweep_cut_groove(design, root):
    block(root, 0, -1, 4, 1, "6 mm")
    sk0 = root.sketches.add(root.yZConstructionPlane)
    circle(sk0, 0, 0.5, 0.2)
    sk = root.sketches.add(root.xZConstructionPlane)
    sweep(root, sk0.profiles.item(0), line(sk, 0, 0.5, 4, 0.5), FO.CutFeatureOperation)


# ---- loft
def loft(comp, profs, op=FO.NewBodyFeatureOperation, setup=None):
    lf = comp.features.loftFeatures
    li = lf.createInput(op)
    for p in profs:
        li.loftSections.add(p)
    if setup:
        setup(li)
    return lf.add(li)


def loft_sketches(root, spec):
    out = []
    for z, kind, dims in spec:
        pl = root.xYConstructionPlane if z == 0 else offset_plane(root, root.xYConstructionPlane, "%g mm" % (z * 10))
        sk = root.sketches.add(pl)
        if kind == "rect":
            rect(sk, *dims)
        else:
            circle(sk, *dims)
        out.append(sk.profiles.item(0))
    return out


@case
def loft_two_rect_circle(design, root):
    loft(root, loft_sketches(root, [(0, "rect", (-1, -1, 1, 1)), (1, "circle", (0, 0, 0.5))]))


@case
def loft_three_profiles(design, root):
    loft(root, loft_sketches(root, [(0, "rect", (-1, -1, 1, 1)), (1, "circle", (0, 0, 0.8)), (2, "rect", (-0.4, -0.4, 0.4, 0.4))]))


@case
def loft_offset_centers(design, root):
    loft(root, loft_sketches(root, [(0, "circle", (0, 0, 0.8)), (1, "circle", (1, 0.5, 0.4))]))


@case
def loft_with_rail(design, root):
    ps = loft_sketches(root, [(0, "circle", (0, 0, 0.8)), (1, "circle", (0, 0, 0.4))])
    sk = root.sketches.add(root.xZConstructionPlane)
    rail = line(sk, 0.8, 0, 0.4, -1.0)

    def setup(li):
        li.centerLineOrRails.addRail(root.features.createPath(rail))
    loft(root, ps, setup=setup)


# ---- holes
def hole_block(root, h="8 mm"):
    b = block(root, 0, 0, 3, 2, h)
    return b


def hole_sketch_point(root, face, x=1.5, y=1.0):
    sk = root.sketches.add(face)
    pt = sk.sketchPoints.add(P(x, y, 0))
    return pt


def hole_feature(root, fi):
    return root.features.holeFeatures.add(fi)


@case
def hole_simple_blind(design, root):
    b = hole_block(root)
    pt = hole_sketch_point(root, top_face(b))
    fi = root.features.holeFeatures.createSimpleInput(V("6 mm"))
    fi.setPositionBySketchPoint(pt)
    fi.setDistanceExtent(V("5 mm"))
    hole_feature(root, fi)


@case
def hole_simple_through_all(design, root):
    b = hole_block(root)
    pt = hole_sketch_point(root, top_face(b))
    fi = root.features.holeFeatures.createSimpleInput(V("6 mm"))
    fi.setPositionBySketchPoint(pt)
    fi.setAllExtent(adsk.fusion.ExtentDirections.PositiveExtentDirection)
    hole_feature(root, fi)


@case
def hole_counterbore(design, root):
    b = hole_block(root)
    pt = hole_sketch_point(root, top_face(b))
    fi = root.features.holeFeatures.createCounterboreInput(V("5 mm"), V("10 mm"), V("3 mm"))
    fi.setPositionBySketchPoint(pt)
    fi.setDistanceExtent(V("6 mm"))
    hole_feature(root, fi)


@case
def hole_countersink(design, root):
    b = hole_block(root)
    pt = hole_sketch_point(root, top_face(b))
    fi = root.features.holeFeatures.createCountersinkInput(V("5 mm"), V("10 mm"), V("90 deg"))
    fi.setPositionBySketchPoint(pt)
    fi.setDistanceExtent(V("6 mm"))
    hole_feature(root, fi)


def tapped(root, modeled, through=False):
    b = hole_block(root, "12 mm")
    pt = hole_sketch_point(root, top_face(b))
    tq = root.features.threadFeatures.threadDataQuery
    tt = tq.defaultMetricThreadType
    _ok, des, cls = tq.recommendThreadData(0.5, True, tt)
    info = adsk.fusion.ThreadInfo.create(False, True, tt, des, cls, True)
    fi = root.features.holeFeatures.createSimpleInput(V("5 mm"))
    fi.setPositionBySketchPoint(pt)
    fi.setToTappedHole(info)
    fi.isModeled = modeled
    if through:
        fi.setAllExtent(adsk.fusion.ExtentDirections.PositiveExtentDirection)
    else:
        fi.setDistanceExtent(V("10 mm"))
        fi.setLengthAndOffset(V("6 mm"), V("0 mm"))
    hole_feature(root, fi)


@case
def hole_tapped_cosmetic(design, root):
    tapped(root, False)


@case
def hole_tapped_modeled(design, root):
    tapped(root, True)


@case
def hole_tapped_through(design, root):
    tapped(root, False, through=True)


@case
def hole_two_points_on_face(design, root):
    b = hole_block(root)
    sk = root.sketches.add(top_face(b))
    p1 = sk.sketchPoints.add(P(0.8, 1.0, 0))
    p2 = sk.sketchPoints.add(P(2.2, 1.0, 0))
    fi = root.features.holeFeatures.createSimpleInput(V("4 mm"))
    fi.setPositionBySketchPoints(coll([p1, p2]))
    fi.setDistanceExtent(V("4 mm"))
    hole_feature(root, fi)


@case
def hole_on_offset_face_plane(design, root):
    b = hole_block(root)
    pl = offset_plane(root, root.xYConstructionPlane, "8 mm")
    sk = root.sketches.add(pl)
    pt = sk.sketchPoints.add(P(1.5, 1.0, 0))
    fi = root.features.holeFeatures.createSimpleInput(V("6 mm"))
    fi.setPositionBySketchPoint(pt)
    fi.setDistanceExtent(V("5 mm"))
    hole_feature(root, fi)


# ---- patterns
def rect_pattern(root, ents, qty1, d1, dir1, qty2=None, d2=None, dir2=None, extent=False, sym1=False, sym2=False):
    pf = root.features.rectangularPatternFeatures
    pi = pf.createInput(coll(ents), dir1, V(str(qty1)), V(d1),
                        adsk.fusion.PatternDistanceType.ExtentPatternDistanceType if extent
                        else adsk.fusion.PatternDistanceType.SpacingPatternDistanceType)
    pi.isSymmetricInDirectionOne = sym1
    if qty2:
        pi.setDirectionTwo(dir2, V(str(qty2)), V(d2))
        pi.isSymmetricInDirectionTwo = sym2
    return pf.add(pi)


def pin_block(root):
    b = block(root, 0, 0, 6, 4, "4 mm")
    sk = root.sketches.add(top_face(b))
    circle(sk, 0.6, 0.6, 0.3)
    f = extrude(root, smallest(sk), FO.JoinFeatureOperation, blind("4 mm"))
    return f


@case
def pat_rect_one_dir_spacing(design, root):
    f = pin_block(root)
    rect_pattern(root, [f], 4, "12 mm", root.xConstructionAxis)


@case
def pat_rect_one_dir_extent(design, root):
    f = pin_block(root)
    rect_pattern(root, [f], 4, "36 mm", root.xConstructionAxis, extent=True)


@case
def pat_rect_two_dirs(design, root):
    f = pin_block(root)
    rect_pattern(root, [f], 3, "15 mm", root.xConstructionAxis, 3, "12 mm", root.yConstructionAxis)


@case
def pat_rect_symmetric(design, root):
    b = block(root, -3, -2, 3, 2, "4 mm")
    sk = root.sketches.add(top_face(b))
    circle(sk, 0, 0, 0.3)
    f = extrude(root, smallest(sk), FO.JoinFeatureOperation, blind("4 mm"))
    rect_pattern(root, [f], 3, "15 mm", root.xConstructionAxis, sym1=True)


@case
def pat_rect_bodies(design, root):
    b = block(root, 0, 0, 1, 1, "5 mm")
    rect_pattern(root, [b], 3, "15 mm", root.xConstructionAxis, 2, "15 mm", root.yConstructionAxis)


@case
def pat_rect_faces(design, root):
    b = block(root, 0, 0, 3, 2, "6 mm")
    sk = root.sketches.add(top_face(b))
    circle(sk, 0.5, 1.0, 0.3)
    extrude(root, smallest(sk), FO.CutFeatureOperation, blind("-3 mm"))
    b = cur(root)
    cyl = [f for f in b.faces if short_type(f.geometry) == "Cylinder"]
    rect_pattern(root, cyl, 3, "10 mm", root.xConstructionAxis)


def circ_pattern(root, ents, qty, angle, axis, sym=False):
    pf = root.features.circularPatternFeatures
    pi = pf.createInput(coll(ents), axis)
    pi.quantity = V(str(qty))
    pi.totalAngle = V(angle)
    pi.isSymmetric = sym
    return pf.add(pi)


def disc_with_peg(root):
    b = block(root, -2, -2, 2, 2, "3 mm")
    sk = root.sketches.add(top_face(b))
    circle(sk, 1.3, 0, 0.25)
    return extrude(root, smallest(sk), FO.JoinFeatureOperation, blind("4 mm"))


@case
def pat_circ_full(design, root):
    f = disc_with_peg(root)
    circ_pattern(root, [f], 6, "360 deg", root.zConstructionAxis)


@case
def pat_circ_partial(design, root):
    f = disc_with_peg(root)
    circ_pattern(root, [f], 4, "120 deg", root.zConstructionAxis)


@case
def pat_circ_symmetric(design, root):
    f = disc_with_peg(root)
    circ_pattern(root, [f], 3, "120 deg", root.zConstructionAxis, sym=True)


@case
def pat_circ_bodies(design, root):
    b = block(root, 1, -0.3, 2, 0.3, "5 mm")
    circ_pattern(root, [b], 5, "360 deg", root.zConstructionAxis)


@case
def pat_path(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    peg = circle(sk, 0, 0, 0.3)
    b = extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("4 mm")).bodies.item(0)
    sk2 = root.sketches.add(root.xYConstructionPlane)
    arc = sk2.sketchCurves.sketchArcs.addByThreePoints(P(0, 0, 0), P(2, 1, 0), P(4, 0, 0))
    path = root.features.createPath(arc)
    pf = root.features.pathPatternFeatures
    pi = pf.createInput(coll([b]), path, V("5"), V("1"), adsk.fusion.PatternDistanceType.ExtentPatternDistanceType)
    pf.add(pi)


@case
def mirror_feature(design, root):
    b = block(root, 0, 0, 3, 2, "4 mm")
    sk = root.sketches.add(top_face(b))
    circle(sk, 0.8, 1.0, 0.4)
    f = extrude(root, smallest(sk), FO.JoinFeatureOperation, blind("5 mm"))
    mf = root.features.mirrorFeatures
    mi = mf.createInput(coll([f]), root.yZConstructionPlane)
    mf.add(mi)


@case
def mirror_feature_mid_plane(design, root):
    b = block(root, 0, 0, 3, 2, "4 mm")
    sk = root.sketches.add(top_face(b))
    circle(sk, 0.8, 0.7, 0.4)
    f = extrude(root, smallest(sk), FO.JoinFeatureOperation, blind("5 mm"))
    pl = offset_plane(root, root.xZConstructionPlane, "10 mm")
    mf = root.features.mirrorFeatures
    mf.add(mf.createInput(coll([f]), pl))


@case
def mirror_body(design, root):
    b = block(root, 1, 0.5, 2, 1.5, "5 mm")
    mf = root.features.mirrorFeatures
    mf.add(mf.createInput(coll([b]), root.yZConstructionPlane))


# ---- combine / split / shell / draft / thicken / offset / move / scale
def two_blocks(root, overlap=True):
    a = block(root, 0, 0, 2, 2, "6 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, 1, 1, 3, 3)
    b = extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("4 mm")).bodies.item(0)
    return root.bRepBodies.item(0), b


def combine(root, target, tools, op, keep=False):
    cf = root.features.combineFeatures
    ci = cf.createInput(target, coll(tools))
    ci.operation = op
    ci.isKeepToolBodies = keep
    return cf.add(ci)


@case
def comb_join(design, root):
    a, b = two_blocks(root)
    combine(root, a, [b], FO.JoinFeatureOperation)


@case
def comb_cut(design, root):
    a, b = two_blocks(root)
    combine(root, a, [b], FO.CutFeatureOperation)


@case
def comb_intersect(design, root):
    a, b = two_blocks(root)
    combine(root, a, [b], FO.IntersectFeatureOperation)


@case
def comb_cut_keep_tools(design, root):
    a, b = two_blocks(root)
    combine(root, a, [b], FO.CutFeatureOperation, keep=True)


@case
def comb_join_three_bodies(design, root):
    a, b = two_blocks(root)
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, 2.5, 0, 4, 1.5)
    c = extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("5 mm")).bodies.item(0)
    combine(root, a, [b, c], FO.JoinFeatureOperation)


@case
def split_body_plane(design, root):
    b = block(root, 0, 0, 3, 2, "6 mm")
    pl = offset_plane(root, root.xZConstructionPlane, "10 mm")
    sf = root.features.splitBodyFeatures
    sf.add(sf.createInput(b, pl, True))


@case
def split_body_plane_yz(design, root):
    b = block(root, 0, 0, 3, 2, "6 mm")
    pl = offset_plane(root, root.yZConstructionPlane, "12 mm")
    sf = root.features.splitBodyFeatures
    sf.add(sf.createInput(b, pl, True))


@case
def split_body_by_tool_body(design, root):
    b = block(root, 0, 0, 3, 2, "6 mm")
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 1.5, 1.0, 0.5)
    t = extrude(root, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("20 mm")).bodies.item(0)
    sf = root.features.splitBodyFeatures
    sf.add(sf.createInput(b, t, True))


def shell(root, ents, thick, direction=None):
    sf = root.features.shellFeatures
    si = sf.createInput(coll(ents), False)
    si.insideThickness = V(thick)
    return sf.add(si)


@case
def shell_inside(design, root):
    b = block(root, 0, 0, 3, 2, "8 mm")
    shell(root, [top_face(b)], "1.5 mm")


@case
def shell_outside(design, root):
    b = block(root, 0, 0, 3, 2, "8 mm")
    sf = root.features.shellFeatures
    si = sf.createInput(coll([top_face(b)]), False)
    si.outsideThickness = V("1.5 mm")
    sf.add(si)


@case
def shell_two_faces(design, root):
    b = block(root, 0, 0, 3, 2, "8 mm")
    side = [f for f in planar_faces(b) if abs(f.centroid.x) < 1e-6][0]
    shell(root, [top_face(b), side], "1.2 mm")


@case
def shell_whole_body(design, root):
    b = block(root, 0, 0, 3, 2, "8 mm")
    sf = root.features.shellFeatures
    si = sf.createInput(coll([b]), False)
    si.insideThickness = V("1 mm")
    sf.add(si)


@case
def draft_side_faces(design, root):
    b = block(root, 0, 0, 3, 2, "10 mm")
    sides = [f for f in planar_faces(b) if abs(f.centroid.z - 0.5) < 1e-6]
    df = root.features.draftFeatures
    di = df.createInput(sides, root.xYConstructionPlane, False)
    di.setSingleAngle(False, V("5 deg"))
    df.add(di)


@case
def draft_single_face(design, root):
    b = block(root, 0, 0, 3, 2, "10 mm")
    side = [f for f in planar_faces(b) if abs(f.centroid.x - 3) < 1e-6][0]
    df = root.features.draftFeatures
    di = df.createInput([side], root.xYConstructionPlane, False)
    di.setSingleAngle(False, V("10 deg"))
    df.add(di)


@case
def thicken_face(design, root):
    sk = root.sketches.add(root.xYConstructionPlane)
    rect(sk, 0, 0, 3, 2)
    srf = root.features.extrudeFeatures
    ei = srf.createInput(sk.profiles.item(0), FO.NewBodyFeatureOperation)
    ei.isSolid = False
    ei.setDistanceExtent(False, V("5 mm"))
    ex = srf.add(ei)
    face = ex.bodies.item(0).faces.item(0)
    tf = root.features.thickenFeatures
    tf.add(tf.createInput(coll([face]), V("1.5 mm"), False, FO.NewBodyFeatureOperation))


@case
def offset_face_press_pull(design, root):
    b = block(root, 0, 0, 3, 2, "6 mm")
    of = root.features.offsetFacesFeatures
    of.add(of.createInput([top_face(b)], V("3 mm")))


@case
def offset_face_side_inward(design, root):
    b = block(root, 0, 0, 3, 2, "6 mm")
    side = [f for f in planar_faces(b) if abs(f.centroid.x - 3) < 1e-6][0]
    of = root.features.offsetFacesFeatures
    of.add(of.createInput([side], V("-4 mm")))


@case
def move_body_translate(design, root):
    b = block(root, 0, 0, 3, 2, "6 mm")
    mf = root.features.moveFeatures
    m = adsk.core.Matrix3D.create()
    m.translation = Vec(1.0, 0.5, 0.2)
    mf.add(_move_input(mf, [b], m))


def _move_input(mf, ents, m):
    mi = mf.createInput2(coll(ents))
    mi.defineAsFreeMove(m)
    return mi


@case
def move_body_rotate(design, root):
    b = block(root, 0, 0, 3, 2, "6 mm")
    m = adsk.core.Matrix3D.create()
    m.setToRotation(math.radians(30), Vec(0, 0, 1), P(0, 0, 0))
    mf = root.features.moveFeatures
    mf.add(_move_input(mf, [b], m))


@case
def copy_body(design, root):
    b = block(root, 0, 0, 3, 2, "6 mm")
    root.features.copyPasteBodies.add(coll([b]))
    mf = root.features.moveFeatures
    m = adsk.core.Matrix3D.create()
    m.translation = Vec(4.0, 0, 0)
    mf.add(_move_input(mf, [root.bRepBodies.item(root.bRepBodies.count - 1)], m))


@case
def scale_body_uniform(design, root):
    b = block(root, 0, 0, 3, 2, "6 mm")
    sf = root.features.scaleFeatures
    sf.add(sf.createInput(coll([b]), root.originConstructionPoint, V("1.5")))


@case
def scale_body_about_corner(design, root):
    b = block(root, 1, 1, 3, 2, "6 mm")
    sf = root.features.scaleFeatures
    sf.add(sf.createInput(coll([b]), root.originConstructionPoint, V("0.6")))


# ---- multi-body & components
@case
def comp_new_from_body(design, root):
    b = block(root, 0, 0, 3, 2, "5 mm")
    nb = b.createComponent()
    comp = nb.parentComponent
    sk = comp.sketches.add(comp.xYConstructionPlane)
    rect(sk, 4, 0, 5, 1)
    extrude(comp, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("5 mm"))


@case
def comp_extrude_in_component(design, root):
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    sk = comp.sketches.add(comp.xYConstructionPlane)
    rect(sk, 0, 0, 2, 1)
    extrude(comp, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("5 mm"))
    sk2 = comp.sketches.add(comp.xYConstructionPlane)
    circle(sk2, 1, 0.5, 0.2)
    extrude(comp, sk2.profiles.item(0), FO.CutFeatureOperation, through_all)


@case
def comp_moved_occurrence(design, root):
    m = adsk.core.Matrix3D.create()
    m.translation = Vec(3.0, 0.0, 0.0)
    occ = root.occurrences.addNewComponent(m)
    comp = occ.component
    sk = comp.sketches.add(comp.xYConstructionPlane)
    rect(sk, 0, 0, 2, 1)
    extrude(comp, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("5 mm"))


@case
def two_components(design, root):
    for dx in (0.0, 3.0):
        m = adsk.core.Matrix3D.create()
        m.translation = Vec(dx, 0.0, 0.0)
        comp = root.occurrences.addNewComponent(m).component
        sk = comp.sketches.add(comp.xYConstructionPlane)
        circle(sk, 0.5, 0.5, 0.4)
        extrude(comp, sk.profiles.item(0), FO.NewBodyFeatureOperation, blind("5 mm"))


@case
def cut_across_bodies_participants(design, root):
    block(root, 0, 0, 2, 1, "3 mm")
    b2 = block(root, 0, 0, 2, 1, "3 mm", plane=offset_plane(root, root.xYConstructionPlane, "5 mm"))
    b3 = block(root, 0, 0, 2, 1, "3 mm", plane=offset_plane(root, root.xYConstructionPlane, "10 mm"))
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 1, 0.5, 0.3)

    def setup(inp):
        inp.setOneSideExtent(adsk.fusion.ThroughAllExtentDefinition.create(), POS)
        inp.participantBodies = [b2, b3]
    extrude(root, sk.profiles.item(0), FO.CutFeatureOperation, setup)


# participant-cut variants (decoder layout of the Extrude prologue reference list)
def _three_stacked(root):
    b1 = block(root, 0, 0, 2, 1, "3 mm")
    b2 = block(root, 0, 0, 2, 1, "3 mm", plane=offset_plane(root, root.xYConstructionPlane, "5 mm"))
    b3 = block(root, 0, 0, 2, 1, "3 mm", plane=offset_plane(root, root.xYConstructionPlane, "10 mm"))
    return b1, b2, b3


@case
def cut_participants_one(design, root):
    """Through-all cut whose participants are only the middle body."""
    b1, b2, b3 = _three_stacked(root)
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 1, 0.5, 0.3)

    def setup(inp):
        inp.setOneSideExtent(adsk.fusion.ThroughAllExtentDefinition.create(), POS)
        inp.participantBodies = [b2]
    extrude(root, sk.profiles.item(0), FO.CutFeatureOperation, setup)


@case
def cut_participants_all(design, root):
    """Through-all cut naming all three bodies as participants."""
    b1, b2, b3 = _three_stacked(root)
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 1, 0.5, 0.3)

    def setup(inp):
        inp.setOneSideExtent(adsk.fusion.ThroughAllExtentDefinition.create(), POS)
        inp.participantBodies = [b1, b2, b3]
    extrude(root, sk.profiles.item(0), FO.CutFeatureOperation, setup)


@case
def cut_participants_blind(design, root):
    """Blind 12 mm cut reaching all bodies, participants the bottom and top body."""
    b1, b2, b3 = _three_stacked(root)
    sk = root.sketches.add(root.xYConstructionPlane)
    circle(sk, 1, 0.5, 0.3)

    def setup(inp):
        inp.setDistanceExtent(False, V("12 mm"))
        inp.participantBodies = [b1, b3]
    extrude(root, sk.profiles.item(0), FO.CutFeatureOperation, setup)


@case
def cut_participants_reverse(design, root):
    """Through-all cut downward from a sketch above the stack, participant the bottom body."""
    b1, b2, b3 = _three_stacked(root)
    sk = root.sketches.add(offset_plane(root, root.xYConstructionPlane, "15 mm"))
    circle(sk, 1, 0.5, 0.3)

    def setup(inp):
        inp.setOneSideExtent(adsk.fusion.ThroughAllExtentDefinition.create(), NEG)
        inp.participantBodies = [b1]
    extrude(root, sk.profiles.item(0), FO.CutFeatureOperation, setup)


@case
def multi_body_join_extrude(design, root):
    block(root, 0, 0, 2, 1, "3 mm")
    block(root, 3, 0, 5, 1, "3 mm")
    sk = root.sketches.add(offset_plane(root, root.xYConstructionPlane, "3 mm"))
    rect(sk, 1.5, 0.2, 3.5, 0.8)
    extrude(root, sk.profiles.item(0), FO.JoinFeatureOperation, blind("-3 mm"))


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
