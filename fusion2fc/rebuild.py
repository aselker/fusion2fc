"""Rebuild a decoded Fusion design (cadmpeg CADIR, slimmed) as a FreeCAD document.

Run with FreeCAD's headless interpreter; arguments come from the environment
because freecadcmd treats extra command-line arguments as files to open:

  F2FC_SLIM=design.slim.json      # sketches, entities, constraints, features, parameters
  F2FC_TOPO=design.topo.json      # feature input topologies (edge geometry), optional
  F2FC_FEATURES=ids.json          # optional: JSON list of CADIR feature ids to build
  F2FC_OUT=design.FCStd
  F2FC_REPORT=report.json
  F2FC_STEPS=dir/                 # optional: write the bodies after every feature as
                                  #   dir/step_NNNN.brep (compound, world coordinates)
  F2FC_BODIES=dir/index.json      # optional: Base Feature bodies exported by
                                  #   tools/stored_bodies.py (body id -> STEP file)
  F2FC_FINAL=dir/index.json       # optional: Fusion's stored final bodies (tools/stored_bodies.py
                                  #   final_body_ids); enables the final-shape check and fallback
  F2FC_FACTS=facts.json           # optional: version warnings, loss counts, {"fallback": false}
  F2FC_SUMMARY=report.txt         # optional: write the conversion summary here
  F2FC_NO_FALLBACK=1              # optional: never add the stored final shape
  freecadcmd fusion2fc/rebuild.py

v0 scope: planar sketches (lines, arcs, circles, polynomial and rational B-splines;
coincidence from shared endpoints; horizontal/vertical), extrudes from resolved
profiles/regions with blind, symmetric and two-sided extents, profile-plane or planar
from-face starts (with their offset), and new-body/join/cut/intersect against the bodies
the tool touches (within Fusion's modelling tolerance). Holes (primitive bore, drill
point, counterbore/countersink per placement), feature patterns (seed tools re-applied
through Draft arrays or Part::Mirroring), body patterns and mirrors, revolves, moves and
combines are built when their decoded definitions and body selections resolve. Everything
else is recorded in the report as skipped. CADIR lengths are mm, as in FreeCAD.
"""
import json
import math
import os
import re
import sys
import traceback
from collections import defaultdict

import FreeCAD as App
import Part
import PartDesign  # noqa: F401  (registers PartDesign::SubShapeBinder)
import Sketcher

V = App.Vector
EPS = 1e-6
# Fusion's modelling tolerance (ASM resabs, 1e-6 cm): bodies closer than this touch.
FUSION_RESABS = 1e-5


def vec(d):
    return V(d["x"], d["y"], d["z"])


def uv(d):
    return V(d["u"], d["v"], 0)


# Fusion's display spelling of stored feature-family names that differ from it.
FUSION_DISPLAY_FAMILY = {"WorkPlane": "Plane", "WorkAxis": "Axis", "WorkPoint": "Point"}


def display_name(feat):
    """Fusion's browser name: cadmpeg spells a default name '<family> <n>' (Fusion: 'Plane1')."""
    name, tag = feat.get("name") or "", feat.get("source_tag")
    m = re.fullmatch(r"(.+) (\d+)", name)
    if tag and m and m.group(1) == tag:
        return FUSION_DISPLAY_FAMILY.get(tag, tag) + m.group(2)
    return name


class Rebuilder:
    # Feature kind -> builder method (features beyond sketches, extrudes, edge treatments).
    FEATURE_BUILDERS = {"hole": "build_hole", "pattern": "build_pattern", "revolve": "build_revolve",
                        "move_body": "build_move_body", "combine": "build_combine",
                        "sweep": "build_sweep", "block": "build_block", "primitive": "build_primitive",
                        "sphere": "build_sphere", "torus": "build_torus", "base_feature": "build_base_feature",
                        "shell": "build_shell", "delete_face": "build_delete_face", "draft": "build_draft", "loft": "build_loft",
                        "scale": "build_scale", "split_body": "build_split_body", "move_face": "build_move_face"}

    def __init__(self, slim, topo, wanted):
        self.slim = slim
        self.doc = App.newDocument("fusion2fc")
        self.wanted = wanted
        self.entities = defaultdict(list)
        for e in slim["sketch_entities"]:
            self.entities[e["sketch"]].append(e)
        self.constraints = defaultdict(list)
        for c in slim["sketch_constraints"]:
            self.constraints[c["sketch"]].append(c)
        self.sketch_defs = {s["id"]: s for s in slim["sketches"]}
        self.topo_edges = {}  # history face id -> list of edge geometry records
        self.topo_geometry = {}  # history edge id -> edge geometry record
        for state in topo or []:
            for eg in state.get("edge_geometry") or []:
                self.topo_geometry[eg["edge"]] = eg
                for fid in eg.get("faces") or []:
                    self.topo_edges.setdefault(fid, []).append(eg)
        self.sketches = {}  # cadir sketch id -> (sketch object, entity->geo, entity->edge name)
        self.solids = []  # current result objects (FreeCAD objects), one per Fusion body
        self.body_component = {}  # solid object name -> CADIR component id (product definition)
        self.component = None  # component of the feature being built
        self.world = self.component_placements(slim.get("occurrences") or [])
        self.report = {"features": [], "sketches": {}}
        self.state_bodies = {state["id"]: state.get("bodies") or [] for state in topo or []}
        self.body_faces = {state["id"]: {b["body"]: b["faces"] for b in state.get("body_faces") or []}
                           for state in topo or []}  # input state -> historical body -> its faces
        self.feature_tools = defaultdict(list)  # CADIR feature id -> [{"tool", "op"}], one per boolean
        self.feature = None  # feature being built
        self.steps_dir = os.environ.get("F2FC_STEPS")
        if self.steps_dir:
            os.makedirs(self.steps_dir, exist_ok=True)
        bodies = os.environ.get("F2FC_BODIES")
        self.stored = json.load(open(bodies)) if bodies else None
        self.stored_dir = os.path.dirname(bodies) if bodies else None

    # ----- components -----------------------------------------------------
    @staticmethod
    def component_placements(occurrences):
        """Component id -> world matrices, one per occurrence (parents composed). Bodies are
        built in their component's coordinates and placed by these on output."""
        by_id = {o["id"]: o for o in occurrences}

        def matrix(o):
            t = o.get("transform") or [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]
            m = App.Matrix(*(t[0] + t[1] + t[2] + [0, 0, 0, 1]))
            parent = (o.get("parent") or {}).get("occurrence")
            if parent in by_id and parent != o["id"]:
                m = matrix(by_id[parent]).multiply(m)
            return m

        world = defaultdict(list)
        for o in occurrences:
            comp = (o.get("prototype") or {}).get("definition")
            if comp:
                world[comp].append(matrix(o))
        return world

    def same_component(self, solids):
        return [s for s in solids if self.body_component.get(s.Name) == self.component]

    def world_shapes(self):
        """Every body as placed in the root: one copy per occurrence of its component."""
        out = []
        for s in self.solids:
            if s.Shape.isNull():
                continue
            mats = self.world.get(self.body_component.get(s.Name)) or [None]
            for m in mats:
                out.append(s.Shape if m is None or m.isUnity() else s.Shape.transformGeometry(m))
        return out

    # ----- sketches -------------------------------------------------------
    def placement(self, frame):
        o, n, u = vec(frame["origin"]), vec(frame["normal"]), vec(frame["u_axis"])
        n.normalize()
        u.normalize()
        v = n.cross(u)
        m = App.Matrix(u.x, v.x, n.x, 0, u.y, v.y, n.y, 0, u.z, v.z, n.z, 0, 0, 0, 0, 1)
        return App.Placement(o, App.Rotation(m)), n

    def build_sketch(self, sid, label):
        if sid in self.sketches:
            return self.sketches[sid]
        sdef = self.sketch_defs[sid]
        pl = sdef.get("placement", {})
        if pl.get("kind") != "resolved":
            raise ValueError("sketch placement not resolved")
        sk = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        sk.Label = label
        sk.Placement, normal = self.placement(pl["frame"])
        geo_of, edge_of = {}, {}
        ends = []  # (position, geo index, pos id)
        skipped = defaultdict(int)
        for e in self.entities[sid]:
            g = e["geometry"]
            k = g["kind"]
            if k == "line":
                geo = Part.LineSegment(uv(g["start"]), uv(g["end"]))
            elif k == "arc":
                a0, a1 = g["start_angle"], g["end_angle"]
                if a1 <= a0:
                    a1 += 2 * math.pi
                geo = Part.ArcOfCircle(Part.Circle(uv(g["center"]), V(0, 0, 1), g["radius"]), a0, a1)
            elif k == "circle":
                geo = Part.Circle(uv(g["center"]), V(0, 0, 1), g["radius"])
            elif k == "nurbs":
                c = g["curve"]
                form = c["poles"].get("form")
                if form == "polynomial":
                    poles, weights = [uv(p) for p in c["poles"]["points"]], None
                elif form == "rational":
                    poles = [uv(p["point"]) for p in c["poles"]["points"]]
                    weights = [p["weight"] for p in c["poles"]["points"]]
                else:
                    skipped["nurbs " + str(form)] += 1
                    continue
                knots, mults = [], []
                for kv in c["knots"]:
                    if knots and abs(kv - knots[-1]) < 1e-12:
                        mults[-1] += 1
                    else:
                        knots.append(kv)
                        mults.append(1)
                geo = Part.BSplineCurve()
                args = [poles, mults, knots, c.get("periodic", False), c["degree"]] + ([weights] if weights else [])
                geo.buildFromPolesMultsKnots(*args)
            elif k == "point":
                continue
            else:
                skipped[k] += 1
                continue
            idx = sk.addGeometry(geo, bool(e.get("construction")))
            geo_of[e["id"]] = idx
            if k in ("line", "arc", "nurbs"):
                ends.append((geo.StartPoint, idx, 1))
                ends.append((geo.EndPoint, idx, 2))
        # Fusion curves share sketch points; FreeCAD needs explicit coincidence.
        clusters = []
        for p, idx, pos in ends:
            for cl in clusters:
                if (cl[0][0] - p).Length < EPS:
                    cl.append((p, idx, pos))
                    break
            else:
                clusters.append([(p, idx, pos)])
        cons = []
        for cl in clusters:
            for (_, i0, p0), (_, i1, p1) in zip(cl, cl[1:]):
                if i0 != i1:
                    cons.append(Sketcher.Constraint("Coincident", i0, p0, i1, p1))
        mapped = defaultdict(int)
        for c in self.constraints[sid]:
            d = c["definition"]
            if d.get("kind") in ("horizontal", "vertical") and d.get("entity") in geo_of:
                gi = geo_of[d["entity"]]
                if isinstance(sk.Geometry[gi], Part.LineSegment):
                    cons.append(Sketcher.Constraint(d["kind"].capitalize(), gi))
                    mapped[d["kind"]] += 1
                    continue
            mapped["unmapped:" + str(d.get("kind"))] += 1
        redundant = 0
        if cons:
            sk.addConstraint(cons)
            # Coincident curves (for example duplicated lines) make derived constraints
            # redundant, and FreeCAD refuses to solve a sketch with redundant constraints.
            sk.solve()
            redundant = len(sk.RedundantConstraints)
            if redundant:
                sk.autoRemoveRedundants()
        self.doc.recompute()
        # The sketch shape orders edges by wire connectivity, not geometry index; the
        # element map ties each geometry id to its edge. Mapped names (";g<id>;SKT.EdgeN")
        # keep binder references valid when the sketch changes.
        by_gid = {}
        for key, element in sk.Shape.ElementMap.items():
            m = re.match(r"g(\d+);SKT(?:;|$)", key)
            if m and element.startswith("Edge"):
                by_gid.setdefault(int(m.group(1)), (key, element))
        for eid, gi in geo_of.items():
            if sk.getConstruction(gi):
                continue
            hit = by_gid.get(sk.getGeometryId(gi))
            if hit:
                edge_of[eid] = ";%s.%s" % hit
        self.sketches[sid] = (sk, geo_of, edge_of, normal)
        self.report["sketches"][label] = {"geometry": len(geo_of), "coincident_clusters": len(clusters),
                                          "constraints": dict(mapped), "skipped_geometry": dict(skipped)}
        if redundant:
            self.report["sketches"][label]["redundant_removed"] = redundant
        return self.sketches[sid]

    # ----- extrude --------------------------------------------------------
    def profile_edges(self, sdef, edge_of, prof):
        kind, val = prof["kind"], prof.get("value", {})
        loops = sdef.get("profiles") or []
        if kind == "sketch_profiles":
            chosen = [loops[i] for i in val["profiles"]]
        elif kind == "sketch_regions":
            chosen = []
            for r in val["regions"]:
                if r.get("region") != "loops":
                    raise ValueError("region form %s" % r.get("region"))
                chosen.append(loops[r["outer"]])
                chosen += [loops[h] for h in r.get("holes", [])]
        else:
            raise NotImplementedError("profile kind " + kind)
        names = []
        for loop in chosen:
            for ref in loop:
                name = edge_of.get(ref["entity"])
                if name is None:
                    raise ValueError("profile references a curve with no sketch edge")
                if name not in names:
                    names.append(name)
        return names

    def face_points(self, face_ref):
        """Boundary points of historical faces, from the feature input topology."""
        if face_ref.get("kind") == "resolved":
            raise NotImplementedError("resolved face reference has no boundary points")
        if face_ref.get("kind") != "historical":
            raise NotImplementedError("face reference " + str(face_ref.get("kind")))
        pts = []
        for fid in face_ref["value"]["faces"]:
            for eg in self.topo_edges.get(fid, []):
                pts += [vec(eg[k]) for k in ("start", "end", "interior") if eg.get(k)]
        if len(pts) < 3:
            raise ValueError("face has no recorded boundary geometry")
        return pts

    def plane_offset(self, face_ref, origin, normal):
        """Signed distance along normal from origin to a face parallel to the sketch."""
        if face_ref.get("kind") == "resolved":
            planes = [self.slim.get("face_planes", {}).get(fid) for fid in face_ref["value"]["faces"]]
            if not planes or any(p is None for p in planes):
                raise NotImplementedError("resolved face without a planar surface")
            offs = []
            for p in planes:
                if abs(abs(vec(p["normal"]).dot(normal)) - 1.0) > 1e-9:
                    raise NotImplementedError("face not parallel to the sketch plane")
                offs.append((vec(p["origin"]) - origin).dot(normal))
            if max(offs) - min(offs) > 1e-5:
                raise ValueError("resolved faces lie in different planes")
            return offs[0]
        offs = [(p - origin).dot(normal) for p in self.face_points(face_ref)]
        if max(offs) - min(offs) > 1e-5:
            raise NotImplementedError("face not parallel to the sketch plane")
        return sum(offs) / len(offs)

    def trimmed_face(self, sid, regions, placement):
        """Faces for regions bounded by partial sketch curves (cadmpeg `trimmed` form).
        Static geometry: the region cannot follow later sketch edits."""
        ents = {e["id"]: e for e in self.entities[sid]}

        def seg_edge(seg):
            g = ents[seg["entity"]]["geometry"]
            t0, t1 = seg["parameter_range"]
            if g["kind"] == "line":
                a, b = uv(g["start"]), uv(g["end"])
                return Part.LineSegment(a + (b - a) * t0, a + (b - a) * t1).toShape()
            if g["kind"] in ("circle", "arc"):
                return Part.Circle(uv(g["center"]), V(0, 0, 1), g["radius"]).toShape(t0, t1)
            raise NotImplementedError("trimmed %s" % g["kind"])

        def merged(boundary):
            """Consecutive pieces of one curve with contiguous parameter ranges join into
            one piece (a circle stored as two half arcs becomes one closed edge)."""
            segs = [dict(s, parameter_range=list(s["parameter_range"])) for s in boundary]
            if len({s["entity"] for s in segs}) > 1:
                return segs  # another curve meets the split point, which then needs its vertex
            changed = True
            while changed and len(segs) > 1:
                changed = False
                for i in range(len(segs)):
                    a_, b_ = segs[i], segs[(i + 1) % len(segs)]
                    if a_ is b_ or a_["entity"] != b_["entity"] or a_.get("reversed") != b_.get("reversed"):
                        continue
                    kind = ents[a_["entity"]]["geometry"]["kind"]
                    if kind not in ("circle", "arc"):
                        continue
                    t0, t1 = a_["parameter_range"]
                    u0, u1 = b_["parameter_range"]
                    if abs(t1 - u0) < 1e-9 and (u1 - t0) <= 2 * math.pi + 1e-9:
                        a_["parameter_range"] = [t0, u1]
                        del segs[(i + 1) % len(segs)]
                        changed = True
                        break
            return segs

        def loop_wire(boundary):
            edges = [seg_edge(s) for s in merged(boundary)]
            return Part.Wire(Part.__sortEdges__(edges))

        faces = []
        for r in regions:
            if r.get("region") == "trimmed":
                wires = [loop_wire(r["outer_boundary"])] + [loop_wire(h) for h in r.get("hole_boundaries", [])]
            elif r.get("region") == "loops":
                loops = self.sketch_defs[sid]["profiles"]
                wires = [loop_wire([{"entity": x["entity"], "parameter_range": self.full_range(ents[x["entity"]])}
                                    for x in loops[i]]) for i in [r["outer"]] + r.get("holes", [])]
            else:
                raise NotImplementedError("region form %s" % r.get("region"))
            face = Part.Face(wires[0]).cut([Part.Face(w) for w in wires[1:]]) if len(wires) > 1 else Part.Face(wires[0])
            for f in face.Faces:  # orient every region along +Z so adjacent regions merge
                if f.normalAt(*f.Surface.parameter(f.CenterOfMass)).z < 0:
                    f.reverse()
            faces += face.Faces
        if len(faces) > 1:
            # Union of adjacent regions: rebuild one face from the boundary of the union
            # (edges owned by a single face), so the extrude yields one body per lump.
            fused = faces[0].fuse(faces[1:])
            free = self.join_circle_pieces(
                [e for e in fused.Edges if len(fused.ancestorsOfType(e, Part.Face)) == 1])
            wires = [Part.Wire(group) for group in Part.sortEdges(free)]
            shape = Part.makeFace(wires, "Part::FaceMakerBullseye")
        else:
            shape = faces[0]
        try:  # pieces of one circle (split where regions met) become one edge again
            unified = shape.removeSplitter()
            if unified.isValid() and abs(unified.Area - shape.Area) < 1e-9 * max(shape.Area, 1.0):
                shape = unified
        except Exception:
            pass
        shape.Placement = placement
        return shape

    def bare_sketch_regions(self, sid):
        """Loop regions (outer loop, directly nested loops as holes) for every stored loop of a
        sketch whose loops nest or stay apart. None when loops cross or are not buildable."""
        n = len(self.sketch_defs[sid].get("profiles") or [])
        if not n:
            return None
        try:
            faces = self.loop_faces(sid, range(n))
        except Exception:
            return None
        inside = {}
        for i in range(n):
            for j in range(n):
                if i != j:
                    both = faces[i].common(faces[j]).Area
                    inside[i, j] = both >= faces[j].Area * (1 - 1e-7)  # j inside i
                    if not inside[i, j] and both > 1e-7 * min(faces[i].Area, faces[j].Area):
                        if not (faces[j].common(faces[i]).Area >= faces[i].Area * (1 - 1e-7)):
                            return None
        regions = []
        for i in range(n):
            inner = [j for j in range(n) if inside.get((i, j)) and not inside.get((j, i))]
            direct = [j for j in inner if not any(k != j and inside.get((k, j)) and k in inner for k in range(n))]
            regions.append({"region": "loops", "outer": i, "holes": direct})
        return regions

    def loop_faces(self, sid, idxs):
        """Planar faces (sketch coordinates) of whole stored loops made of lines, circles and arcs."""
        ents = {e["id"]: e for e in self.entities[sid]}
        loops = self.sketch_defs[sid]["profiles"]
        faces = []
        for i in idxs:
            edges = []
            for x in loops[i]:
                e = ents[x["entity"]]
                g, (t0, t1) = e["geometry"], self.full_range(e)
                if g["kind"] == "line":
                    a, b = uv(g["start"]), uv(g["end"])
                    edges.append(Part.LineSegment(a + (b - a) * t0, a + (b - a) * t1).toShape())
                elif g["kind"] in ("circle", "arc"):
                    edges.append(Part.Circle(uv(g["center"]), V(0, 0, 1), g["radius"]).toShape(t0, t1))
                else:
                    raise NotImplementedError("loop curve " + g["kind"])
            faces.append(Part.Face(Part.Wire(Part.__sortEdges__(edges))))
        return faces

    @staticmethod
    def join_circle_pieces(edges):
        """Edges that are pieces of one full circle (split where regions met) become the
        single closed circle edge, as the sketch curve is."""
        groups = defaultdict(list)
        out = []
        for e in edges:
            c = e.Curve
            if isinstance(c, Part.Circle):
                key = tuple(round(x, 6) for x in (c.Center.x, c.Center.y, c.Center.z, c.Radius,
                                                  abs(c.Axis.x), abs(c.Axis.y), abs(c.Axis.z)))
                groups[key].append(e)
            else:
                out.append(e)
        others = [v.Point for e in out for v in e.Vertexes]
        for es in groups.values():
            c = es[0].Curve
            whole = len(es) > 1 and abs(sum(e.Length for e in es) - 2 * math.pi * c.Radius) < 1e-6 * c.Radius
            # Only a ring of its own: another edge meeting a split point needs that vertex.
            if whole and not any((v.Point - q).Length < 1e-7 for e in es for v in e.Vertexes for q in others):
                out.append(Part.Circle(c.Center, c.Axis, c.Radius).toShape())
            else:
                out += es
        return out

    def crossing_loops(self, sid, regions):
        """True when a `loops` region has a hole loop that crosses its outer loop (neither
        inside it nor around it), which a face maker cannot build; such regions need the
        boolean construction of `trimmed_face`."""
        if not any(r.get("region") == "loops" and r.get("holes") for r in regions):
            return False
        try:
            for r in regions:
                if r.get("region") != "loops":
                    continue
                faces = self.loop_faces(sid, [r["outer"]] + r.get("holes", []))
                for h in faces[1:]:
                    both = faces[0].common(h).Area
                    if both < h.Area * (1 - 1e-7) and both < faces[0].Area * (1 - 1e-7):
                        return True
        except Exception:
            return False
        return False

    def overlapping_profile_union(self, sid, idxs, placement):
        """The union face of whole stored loops when two of them partly overlap (Fusion's
        selected regions of overlapping closed curves add up to their union; nested loops
        alternate solid and hole). None when no two loops cross or a loop is not buildable."""
        if len(idxs) < 2:
            return None
        try:
            faces = self.loop_faces(sid, idxs)
        except Exception:
            return None
        n = len(faces)
        inside, overlap = {}, {}
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                both = faces[i].common(faces[j]).Area
                inside[i, j] = both >= faces[j].Area * (1 - 1e-7)  # j inside i
                overlap[i, j] = both > 1e-7 * min(faces[i].Area, faces[j].Area)
        crossing = any(not inside[i, j] and not inside[j, i] and overlap[i, j]
                       for i in range(n) for j in range(i + 1, n))
        if not crossing:
            return None
        depth = [sum(1 for k in range(n) if k != i and inside[k, i] and (not inside[i, k] or k < i)) for i in range(n)]
        solids = []
        for i in range(n):
            if depth[i] % 2:
                continue
            f = faces[i]
            holes = [faces[j] for j in range(n) if depth[j] == depth[i] + 1 and inside[i, j]]
            solids.append(f.cut(holes) if holes else f)
        shape = solids[0].fuse(solids[1:]) if len(solids) > 1 else solids[0]
        shape = shape.removeSplitter()
        free = [e for e in shape.Edges if len(shape.ancestorsOfType(e, Part.Face)) == 1]
        shape = Part.makeFace([Part.Wire(g) for g in Part.sortEdges(free)], "Part::FaceMakerBullseye")
        if shape.normalAt(*shape.Surface.parameter(shape.CenterOfMass)).z < 0:
            shape.reverse()
        shape.Placement = placement
        return shape

    @staticmethod
    def full_range(e):
        g = e["geometry"]
        if g["kind"] == "line":
            return [0.0, 1.0]
        if g["kind"] == "circle":
            return [0.0, 2 * math.pi]
        if g["kind"] == "arc":
            a0, a1 = g["start_angle"], g["end_angle"]
            return [a0, a1 if a1 > a0 else a1 + 2 * math.pi]
        raise NotImplementedError("loop curve %s" % g["kind"])

    def scene_size(self, extra=None):
        bb = App.BoundBox()
        for s in self.solids:
            bb.add(s.Shape.BoundBox)
        if extra is not None:
            bb.add(extra.BoundBox)
        return max(bb.DiagonalLength, 1.0) * 2 + 10.0

    def build_extrude(self, feat, suppressed=False):
        """Build an extrude; a suppressed one keeps its hidden tool out of the boolean chain."""
        d = feat["definition"]
        if not d.get("solid", True):
            raise NotImplementedError("surface extrude")
        prof = d["profile"]
        value = prof.get("value")
        if prof["kind"] == "sketch" and value in self.sketch_defs:
            # No selection record narrowed the sketch down: every region of it is extruded.
            regions = self.bare_sketch_regions(value)
            if regions:
                prof = {"kind": "sketch_regions", "value": {"sketch": value, "regions": regions, "static": True}}
                value = prof["value"]
        sid = value.get("sketch") if isinstance(value, dict) else None
        if sid not in self.sketch_defs:
            raise NotImplementedError("profile kind " + prof["kind"])
        sk, geo_of, edge_of, normal = self.build_sketch(sid, self.sketch_label(sid))
        regions = value.get("regions") or []
        notes = {}
        union = (self.overlapping_profile_union(sid, value["profiles"], sk.Placement)
                 if prof["kind"] == "sketch_profiles" else None)
        if union is not None:
            base = self.doc.addObject("Part::Feature", "ProfileFace")
            base.Shape = union
            notes["profile"] = "static union of overlapping loops"
        elif (value.get("static") or any(r.get("region") == "trimmed" for r in regions)
              or self.crossing_loops(sid, regions)):
            base = self.doc.addObject("Part::Feature", "ProfileFace")
            base.Shape = self.trimmed_face(sid, regions, sk.Placement)
            notes["profile"] = "static trimmed regions"
        else:
            names = self.profile_edges(self.sketch_defs[sid], edge_of, prof)
            base = self.doc.addObject("PartDesign::SubShapeBinder", "Profile")
            base.Support = [(sk, tuple(names))]
            base.MakeFace = True
        base.Label = feat["name"] + " profile"
        direction = normal if d["direction"]["kind"] == "profile_normal" else -normal
        origin = sk.Placement.Base
        start = d.get("start", {"kind": "profile_plane"})
        offset = 0.0  # along the sketch normal
        if start["kind"] == "from_face":
            # The start offset is a displacement along the extrusion direction.
            offset = self.plane_offset(start.get("face", {}), origin, normal)
            offset += (start.get("offset") or 0.0) * normal.dot(direction)
        elif start["kind"] == "offset_profile_plane":
            offset = start["offset"]
        elif start["kind"] != "profile_plane":
            raise NotImplementedError("start " + start["kind"])
        self.doc.recompute()
        through = []  # target faces of through-shape terminations

        def length(side, sign):
            """Length of one side; sign is +1 along `direction`, -1 against it."""
            t = side["termination"]
            k = t.get("kind")
            if k == "blind":
                return t["length"]
            if k == "to_face":
                if t.get("offset"):
                    raise NotImplementedError("to_face offset")
                dist = self.plane_offset(t["face"], origin, normal) - offset
                along = dist * normal.dot(direction) * sign
                if along <= 0:
                    raise NotImplementedError("to_face behind the start plane")
                return along
            if k == "to_shape":
                if d["op"] not in ("cut", "intersect"):
                    raise NotImplementedError("to_shape termination for " + d["op"])
                through.append(t.get("target", {}))
                return self.scene_size(base.Shape)
            if k == "through_all":
                # Through every body: a length past the whole scene from the start plane.
                return self.scene_size(base.Shape)
            raise NotImplementedError("termination " + str(k))

        ex = self.doc.addObject("Part::Extrusion", "Extrude")
        ex.Label = feat["name"]
        ex.Base = base
        ex.DirMode = "Custom"
        ex.Dir = direction
        ex.Solid = True
        ext = d["extent"]
        if ext["kind"] == "one_sided":
            ex.LengthFwd = length(ext["side"], 1)
            ex.TaperAngle = math.degrees(ext["side"].get("draft", 0.0))
        elif ext["kind"] == "symmetric":
            ex.LengthFwd = length(ext["side"], 1)
            ex.Symmetric = True
            ex.TaperAngle = math.degrees(ext["side"].get("draft", 0.0))
        elif ext["kind"] == "two_sided":
            ex.LengthFwd = length(ext["first"], 1)
            ex.LengthRev = length(ext["second"], -1)
            ex.TaperAngle = math.degrees(ext["first"].get("draft", 0.0))
            ex.TaperAngleRev = math.degrees(ext["second"].get("draft", 0.0))
        else:
            raise NotImplementedError("extent " + ext["kind"])
        if offset:
            ex.Placement = App.Placement(normal * offset, App.Rotation())
        self.doc.recompute()
        if ex.Shape.isNull() or ex.Shape.Volume <= 0:
            raise ValueError("empty extrusion")
        if (d["op"] == "cut" and ext["kind"] == "one_sided"
                and ext["side"]["termination"].get("kind") == "through_all"
                and not any(self.overlaps(ex, s) for s in self.solids)):
            # A through-all cut that meets no body cannot be a Fusion feature (it fails
            # with "no intersection"), so the recorded direction was read backwards.
            ex.Dir = -direction
            self.doc.recompute()
            notes["direction"] = "flipped: through-all cut met no body"
        if suppressed:
            ex.Label = feat["name"] + " (suppressed)"
            ex.Visibility = False
            return {"tool": ex.Name}
        participants = None
        if through and all(t.get("kind") == "historical" for t in through):
            participants = self.bodies_owning(through)
        res = self.apply_op(d["op"], ex, feat["name"], participants)
        res.update(notes)
        return res

    def bodies_owning(self, face_refs):
        """Current bodies whose surface carries the boundary points of the given faces."""
        pts = [p for ref in face_refs for p in self.face_points(ref)]
        owners = []
        for s in self.solids:
            shp = s.Shape
            if pts and all(shp.distToShape(Part.Vertex(p))[0] < 1e-5 for p in pts[:12]):
                owners.append(s)
        return owners or None

    # ----- booleans -------------------------------------------------------
    def touches(self, a, b):
        try:
            return a.Shape.distToShape(b.Shape)[0] < FUSION_RESABS
        except Exception:
            return False

    def overlaps(self, a, b):
        try:
            return a.Shape.common(b.Shape).Volume > 1e-9
        except Exception:
            return False

    def split_solids(self, obj, name):
        """One object per solid of `obj` (Fusion makes a body per disjoint lump)."""
        n = len(obj.Shape.Solids)
        if n <= 1:
            return [obj]
        import CompoundTools.CompoundFilter as CF
        parts = []
        for i in range(n):
            f = CF.makeCompoundFilter("Body")
            f.Label = "%s body %d" % (name, i + 1)
            f.Base = obj
            f.FilterType = "specific items"
            f.items = str(i)
            parts.append(f)
        self.doc.recompute()
        return parts

    def apply_op(self, op, tool, name, participants=None):
        if self.feature is not None:  # patterns re-apply the tools of their seed features
            self.feature_tools[self.feature["id"]].append({"tool": tool, "op": op})
        if op == "new_body":
            parts = self.split_solids(tool, name)
            self.solids += parts
            return {"op": op, "targets": 0, "bodies": len(parts)}
        if op == "join":
            targets = [s for s in self.same_component(self.solids) if self.touches(s, tool)]
            if not targets:
                self.solids += self.split_solids(tool, name)
                return {"op": op, "targets": 0}
            fuse = self.doc.addObject("Part::MultiFuse", "Join")
            fuse.Label = name + " join"
            fuse.Shapes = targets + [tool]
            fuse.Refine = True
            self.doc.recompute()
            # Bodies the join leaves unconnected stay separate bodies.
            self.solids = [s for s in self.solids if s not in targets] + self.split_solids(fuse, name)
        elif op in ("cut", "intersect"):
            pool = participants if participants else self.same_component(self.solids)
            targets = [s for s in pool if self.overlaps(s, tool)]
            for t in targets:
                b = self.doc.addObject("Part::Cut" if op == "cut" else "Part::Common", op.capitalize())
                b.Label = name + " " + op
                b.Base, b.Tool = t, tool
                b.Refine = True
                self.solids[self.solids.index(t)] = b
        else:
            raise NotImplementedError("operation " + op)
        self.doc.recompute()
        return {"op": op, "targets": len(targets)}

    # ----- edge treatments ------------------------------------------------
    EDGE_TOL = 1e-4  # mm: recorded edge point to rebuilt edge
    TANGENT_TOL = 1e-3  # 1 - |cos| between recorded and rebuilt edge tangents

    @staticmethod
    def edge_tangent(edge, p):
        try:
            u = edge.Curve.parameter(p)
            t = edge.tangentAt(min(max(u, edge.FirstParameter), edge.LastParameter))
            return t if t.Length > EPS else None
        except Exception:
            return None

    @staticmethod
    def dist_to_point(shape, p):
        """Distance from `shape` to point p; BRepExtrema fails on some degenerate edges and
        faces, then the nearest of the shape's sampled edge points stands in."""
        try:
            return shape.distToShape(Part.Vertex(p))[0]
        except RuntimeError:
            pts = []
            for e in shape.Edges:
                try:
                    pts += e.discretize(64)
                except Exception:
                    pass
            return min(((q - p).Length for q in pts), default=float("inf"))

    def find_edge(self, eg):
        """(body object, 1-based edge index) of the current edge matching recorded geometry,
        and the distance of the nearest edge (for the report). A rebuilt edge matches when it
        passes through the recorded interior point along the recorded tangent. Among those,
        one whose vertices are the recorded start and end wins (for a closed edge: a closed
        edge through the recorded vertex, wherever its own seam lies), then one carrying
        both recorded vertices (OCC merged the edge with a neighbour), then a piece of a
        recorded edge that OCC split (fillets and chamfers propagate along the G1 chain)."""
        p = vec(eg["interior"])
        t = vec(eg["tangent"]) if eg.get("tangent") else None
        ends = [vec(eg[k]) for k in ("start", "end") if eg.get(k)]
        closed = len(ends) == 2 and (ends[0] - ends[1]).Length < self.EDGE_TOL
        tol = self.EDGE_TOL
        own = self.same_component(self.solids)
        pool = own + [s for s in self.solids if s not in own]
        best = None
        for s in pool:
            for i, e in enumerate(s.Shape.Edges):
                bb = e.BoundBox
                bb.enlarge(tol)
                if not bb.isInside(p):
                    continue
                d = self.dist_to_point(e, p)
                if d > tol:
                    continue
                if t is not None:
                    te = self.edge_tangent(e, p)
                    if te is None or 1 - abs(te.normalize().dot(t)) > self.TANGENT_TOL:
                        continue
                verts = [v.Point for v in e.Vertexes]
                on = all(self.dist_to_point(e, q) < tol for q in ends)
                if closed:
                    exact = e.isClosed() and on
                else:
                    exact = len(ends) == 2 and len(verts) == 2 and all(
                        any((q - v).Length < tol for v in verts) for q in ends)
                key = (0 if exact else 1 if on else 2, s not in own, d)
                if best is None or key < best[0]:
                    best = (key, s, i + 1)
        if best is not None:
            return best[1], best[2], best[0][2]
        shapes = [s.Shape for s in pool if not s.Shape.isNull()]
        nearest = min((self.dist_to_point(sh, p) for sh in shapes), default=float("inf"))
        return None, None, nearest

    # ----- face selection ---------------------------------------------------
    def find_face(self, fid):
        """(body object, 0-based face index) of the rebuilt face that a historical face names.
        The decoder samples every edge that bounds a selected face (with the faces that use
        it); each is located like a fillet edge, and the face is the one that all of them
        bound. Edges OCC merged or split still count (find_edge accepts pieces). When several
        faces remain, the one with the fewest edges outside the recorded set wins only if it
        is unique; otherwise the match is ambiguous and raises."""
        egs = self.topo_edges.get(fid)
        if not egs:
            raise ValueError("face has no recorded boundary edges")
        body, cands = None, None
        for eg in egs:
            b, i, dist = self.find_edge(eg)
            if b is None:
                raise ValueError("a boundary edge of the selected face is not in the rebuilt bodies (nearest %.3g mm)" % dist)
            if body is None:
                body = b
            elif b is not body:
                raise ValueError("boundary edges of the selected face lie in different bodies")
            edge = b.Shape.Edges[i - 1]
            hit = {k for k, f in enumerate(b.Shape.Faces) if any(e.isSame(edge) for e in f.Edges)}
            cands = hit if cands is None else cands & hit
        if not cands:
            raise ValueError("no rebuilt face carries all recorded boundary edges")
        if len(cands) > 1:
            n = {k: len(body.Shape.Faces[k].Edges) for k in cands}
            low = min(n.values())
            cands = {k for k in cands if n[k] == low}
            if len(cands) > 1:
                raise ValueError("ambiguous face match (%d rebuilt faces share the recorded edges)" % len(cands))
        return body, next(iter(cands))

    def selected_faces(self, ref):
        """{body object: sorted face indices} for a historical face selection."""
        if ref.get("kind") != "historical":
            raise NotImplementedError("face selection " + str(ref.get("kind")))
        per_body = defaultdict(set)
        for fid in ref["value"]["faces"]:
            body, k = self.find_face(fid)
            per_body[body].add(k)
        return {b: sorted(v) for b, v in per_body.items()}

    def build_shell(self, feat):
        d = feat["definition"]
        if d.get("mode") not in (None, "inside", "outside"):
            raise NotImplementedError("shell mode " + str(d.get("mode")))
        t = float(d["thickness"])
        rf = d["removed_faces"]
        if rf.get("kind") == "faces" and not rf.get("value"):
            return self.build_hollow(feat, t, bool(d.get("outward")))
        per_body = self.selected_faces(rf)
        made = []
        for body, faces in per_body.items():
            obj = self.doc.addObject("Part::Thickness", "Shell")
            obj.Label = feat["name"]
            obj.Faces = (body, ["Face%d" % (k + 1) for k in faces])
            obj.Value = t if d.get("outward") else -t
            obj.Mode = 0
            obj.Join = 2
            obj.Intersection = True
            obj.SelfIntersection = False
            made.append((body, obj))
        self.doc.recompute()
        bad = [o for _, o in made if o.Shape.isNull() or not o.Shape.Solids or "Invalid" in o.State]
        if bad:
            for _, o in made:
                self.doc.removeObject(o.Name)
            self.doc.recompute()
            raise ValueError("OCC shell failed on %d of %d bodies" % (len(bad), len(made)))
        for body, obj in made:
            self.solids[self.solids.index(body)] = obj
        return {"faces": sum(len(v) for v in per_body.values())}

    def build_hollow(self, feat, t, outward):
        """Shell without removed faces: the body becomes a closed hollow (inward wall of
        thickness t, or an outer wall around the original volume when outward)."""
        bodies = self.select_bodies(feat["definition"]["bodies"])
        for b in bodies:
            shp = b.Shape
            off = shp.makeOffsetShape(t if outward else -t, 1e-6, False, False, 0, 0)
            inner = Part.Solid(off.Shells[0]) if off.Shells else off
            res = inner.cut(shp) if outward else shp.cut(inner)
            self.replace_with_shape(b, res, feat)
        self.doc.recompute()
        return {"bodies": len(bodies)}

    def replace_with_shape(self, body, shape, feat):
        """Replace a rebuilt body by a Part::Feature holding `shape` (an OCC operation without
        a parametric FreeCAD feature)."""
        if shape.isNull() or not shape.Solids or not shape.isValid():
            raise ValueError("OCC result is not a valid solid")
        obj = self.doc.addObject("Part::Feature", feat["name"].replace(" ", "_"))
        obj.Label = feat["name"]
        obj.Shape = shape
        self.solids[self.solids.index(body)] = obj
        return obj

    def build_delete_face(self, feat):
        d = feat["definition"]
        if not d.get("heal", True):
            raise NotImplementedError("delete face without healing")
        made = []
        for body, faces in self.selected_faces(d["faces"]).items():
            shp = body.Shape.defeaturing([body.Shape.Faces[k] for k in faces])
            if abs(shp.Volume - body.Shape.Volume) < 1e-9 * max(1.0, body.Shape.Volume) and len(shp.Faces) >= len(body.Shape.Faces):
                raise ValueError("OCC defeaturing removed nothing")
            made.append((body, shp))
        for body, shp in made:
            self.replace_with_shape(body, shp, feat)
        self.doc.recompute()
        return {"bodies": len(made)}

    def build_draft(self, feat):
        d = feat["definition"]
        anchor = d.get("anchor") or {}
        if anchor.get("kind") != "neutral_plane":
            raise NotImplementedError("draft anchor " + str(anchor.get("kind")))
        per_body = self.selected_faces(d["faces"])
        if len(per_body) != 1:
            raise NotImplementedError("draft over several bodies")
        body = next(iter(per_body))
        pull = anchor.get("pull") or {}
        if anchor["plane"].get("kind") == "native" and pull.get("direction"):
            # a datum plane the decoder named, or an origin plane (through the origin)
            if pull.get("plane"):
                origin, normal = self.datum_plane_of({"plane": pull["plane"]})
            else:
                origin, normal = V(0, 0, 0), vec(pull["direction"])
            normal.normalize()
            hits = [k for k, f in enumerate(body.Shape.Faces) if self.face_on_plane(f, (origin, normal))]
            if len(hits) != 1:
                raise NotImplementedError("draft neutral plane that is not a face of the body (%d faces)" % len(hits))
            nb = {body: hits}
        else:
            nb = self.selected_faces(anchor["plane"])
        if list(nb) != list(per_body) or sum(len(v) for v in nb.values()) != 1:
            raise NotImplementedError("draft over several bodies or neutral planes")
        neutral = body.Shape.Faces[nb[body][0]]
        if neutral.Surface.TypeId != "Part::GeomPlane":
            raise NotImplementedError("non-planar draft neutral face")
        pb = self.doc.addObject("PartDesign::Body", "DraftBody")
        pb.BaseFeature = body
        dr = pb.newObject("PartDesign::Draft", "Draft")
        dr.Base = (body, ["Face%d" % (k + 1) for k in per_body[body]])
        dr.NeutralPlane = (body, "Face%d" % (nb[body][0] + 1))
        dr.Angle = math.degrees(float(d["angle"]))
        dr.Reversed = bool(d.get("outward"))
        self.doc.recompute()
        if pb.Shape.isNull() or "Invalid" in dr.State or not pb.Shape.Solids:
            self.doc.removeObject(dr.Name)
            self.doc.removeObject(pb.Name)
            self.doc.recompute()
            raise ValueError("OCC draft failed")
        self.solids[self.solids.index(body)] = pb
        return {"faces": len(per_body[body])}

    # ----- scale, split body, offset faces -----------------------------------
    def build_scale(self, feat):
        """Scale: each selected body is replaced by a scaled copy of its shape about the center."""
        d = feat["definition"]
        f = d.get("factors") or {}
        c = d.get("center") or {}
        if c.get("kind") != "point":
            raise NotImplementedError("scale center " + str(c.get("kind")))
        center = vec(c["value"])
        bodies = self.select_bodies(d["bodies"])
        if f.get("kind") == "uniform":
            fx = fy = fz = float(f["factor"])
        elif f.get("kind") == "non_uniform":
            fx, fy, fz = (float(f[k]) for k in ("x", "y", "z"))
        else:
            raise NotImplementedError("scale factors " + str(f.get("kind")))
        for b in bodies:
            shp = b.Shape.copy()
            if fx == fy == fz:
                shp.scale(fx, center)
            else:
                m = App.Matrix()
                m.move(center * -1)
                m.scale(fx, fy, fz)
                m.move(center)
                shp = shp.transformGeometry(m)
            self.replace_with_shape(b, shp, feat)
        self.doc.recompute()
        return {"bodies": len(bodies)}

    def datum_plane_of(self, ref):
        """(origin, normal) of the datum plane feature a split tool names."""
        for f in self.slim["features"]:
            if f["id"] == ref.get("plane"):
                fr = (f.get("definition") or {}).get("frame")
                if fr:
                    return vec(fr["origin"]), vec(fr["normal"])
        raise NotImplementedError("split plane is not a resolved datum plane")

    def build_split_body(self, feat):
        d = feat["definition"]
        tool = d.get("tool") or {}
        if tool.get("kind") != "plane":
            raise NotImplementedError("split tool " + str(tool.get("kind")) + " " + str((tool.get("value") or {}).get("kind")))
        origin, normal = self.datum_plane_of(tool["value"])
        normal.normalize()
        bodies = self.select_bodies(d["targets"])
        for b in bodies:
            big = 4 * max(b.Shape.BoundBox.DiagonalLength, 1.0)
            pl = Part.makePlane(2 * big, 2 * big, origin, normal)
            pl.translate(-(pl.CenterOfMass - origin))
            parts = b.Shape.generalFuse([pl])[0].Solids
            if len(parts) < 2:
                raise ValueError("the split plane does not cut the body")
            comp = self.doc.addObject("Part::Feature", "Split")
            comp.Label = feat["name"]
            comp.Shape = Part.Compound(parts)
            self.doc.recompute()
            i = self.solids.index(b)
            self.solids[i:i + 1] = self.split_solids(comp, feat["name"])
        return {"bodies": len(bodies)}

    def build_move_face(self, feat):
        """Offset faces (press/pull) of planar faces whose neighbours are perpendicular to
        them: the face is swept along its normal and fused (outward) or cut (inward)."""
        d = feat["definition"]
        m = d.get("motion") or {}
        if m.get("kind") != "offset":
            raise NotImplementedError("move face motion " + str(m.get("kind")))
        dist = float(m["distance"])
        per_body = self.selected_faces(d["faces"])
        for body, faces in per_body.items():
            shp = body.Shape
            for k in faces:
                face = shp.Faces[k]
                if not isinstance(face.Surface, Part.Plane):
                    raise NotImplementedError("offset of a non-planar face")
                n = face.normalAt(*face.Surface.parameter(face.CenterOfMass))
                for g in shp.Faces:
                    if g.isSame(face) or not any(e.isSame(x) for e in face.Edges for x in g.Edges):
                        continue
                    if not isinstance(g.Surface, Part.Plane) or abs(g.normalAt(*g.Surface.parameter(g.CenterOfMass)).dot(n)) > 1e-6:
                        raise NotImplementedError("offset face with a neighbour that is not perpendicular")
                prism = face.extrude(n * dist)
                shp = shp.fuse(prism).removeSplitter() if dist > 0 else shp.cut(prism).removeSplitter()
            self.replace_with_shape(body, shp, feat)
        self.doc.recompute()
        return {"faces": sum(len(v) for v in per_body.values())}

    def require_uniform_corner_radii(self, body, edges):
        """Fillets of different radii that meet at a vertex get a corner blend that OCC builds
        differently from Fusion (case_fillet_corner_mixed_radii: 987.06 vs 985.63)."""
        shape = body.Shape
        at_vertex = []
        for idx, r0, r1 in edges:
            for vtx in shape.Edges[idx - 1].Vertexes:
                at_vertex.append((vtx, idx, r0, r1))
        for i, (v, idx, r0, r1) in enumerate(at_vertex):
            for w, jdx, q0, q1 in at_vertex[i + 1:]:
                if jdx != idx and v.isSame(w) and max(abs(r0 - q0), abs(r1 - q1), abs(r0 - q1), abs(r1 - q0)) > 1e-9 \
                        and abs(r0 - r1) < 1e-9 and abs(q0 - q1) < 1e-9:
                    raise NotImplementedError("corner blend of unequal fillet radii (OCC corner differs from Fusion's)")

    @staticmethod
    def chamfer_first_planes(feat):
        """slot -> (is_first, origin, normal): a planar support of the edge and whether it
        carries the first distance (else the second) of a two-distance or distance-angle
        chamfer, as the decoder measured it from the feature's transition (source property
        chamfer_first_faces, DR-341)."""
        out = {}
        for item in (feat.get("source_properties", {}).get("chamfer_first_faces") or "").split(";"):
            if ":" not in item:
                continue
            slot, role, nums = item.split(":", 2)
            v = [float(x) for x in nums.split(",")]
            o, n = V(*v[:3]), V(*v[3:])
            n.normalize()
            out[int(slot)] = (role == "first", o, n)
        return out

    @staticmethod
    def face_on_plane(face, plane):
        if not isinstance(face.Surface, Part.Plane):
            return False
        ax = face.Surface.Axis
        return abs(abs(ax.dot(plane[1])) - 1.0) < 1e-6 and abs((face.Surface.Position - plane[0]).dot(plane[1])) < 1e-4

    def asymmetric_chamfer(self, body, idx, spec, planes, slot):
        """(first, second) distances in the order OCC reads them for edge `idx` of `body`:
        the first is measured on the first face OCC finds for the edge (Part.Shape.
        ancestorsOfType), the second on the other. The decoder names the support plane that
        carries the first distance (or the distance of a distance-and-angle chamfer); an edge
        without its own entry takes the plane of the group's other edges that bounds it."""
        shape = body.Shape
        edge = shape.Edges[idx - 1]
        faces = shape.ancestorsOfType(edge, Part.Face)
        if len(faces) != 2:
            raise ValueError("edge lies between %d faces" % len(faces))
        own = [planes[slot]] if slot in planes else list(planes.values())
        # an edge without its own entry takes the group's planes that bound it
        votes = set()
        for is_first, o, n in own:
            for i in range(2):
                if self.face_on_plane(faces[i], (o, n)):
                    votes.add(i if is_first else 1 - i)
        if len(votes) != 1:
            raise ValueError("the reference face of the first distance is not recorded (DR-341)")
        first = votes.pop()
        u = 0.5 * (edge.FirstParameter + edge.LastParameter)
        mid = edge.valueAt(u)
        normals = [f.normalAt(*f.Surface.parameter(mid)) for f in faces]
        if spec["kind"] == "two_distances":
            d_first, d_second = spec["first"], spec["second"]
        else:
            theta = math.pi - math.acos(max(-1.0, min(1.0, normals[0].dot(normals[1]))))
            ang = spec["angle"]
            d_first = spec["distance"]
            d_second = d_first * math.sin(ang) / math.sin(theta + ang)
        return (d_first, d_second) if first == 0 else (d_second, d_first)

    def shaped_fillet(self, body, idx, eg, r):
        """(start, end) radii of one edge for a variable-radius fillet (linear between the
        recorded ends) or a chord-length fillet (radius from the chord of the blend arc)."""
        shape = body.Shape
        edge = shape.Edges[idx - 1]
        if r["kind"] == "variable":
            r0, r1 = r["points"][0]["radius"], r["points"][1]["radius"]
            if edge.isClosed() or not eg.get("start") or not eg.get("end"):
                raise ValueError("variable radius on a closed edge")
            a, b = vec(eg["start"]), vec(eg["end"])
            p0, p1 = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
            fwd = (p0 - a).Length + (p1 - b).Length
            rev = (p0 - b).Length + (p1 - a).Length
            return (r0, r1) if fwd <= rev else (r1, r0)
        faces = shape.ancestorsOfType(edge, Part.Face)
        if len(faces) != 2:
            raise ValueError("edge lies between %d faces" % len(faces))
        u = 0.5 * (edge.FirstParameter + edge.LastParameter)
        mid = edge.valueAt(u)
        n = [f.normalAt(*f.Surface.parameter(mid)) for f in faces]
        turn = math.acos(max(-1.0, min(1.0, n[0].dot(n[1]))))
        if turn < 1e-6:
            raise ValueError("chord length on a tangent edge")
        rad = r["chord_length"] / (2 * math.sin(turn / 2))
        return (rad, rad)

    def build_edge_treatment(self, feat, kind):
        d = feat["definition"]
        per_body = defaultdict(list)
        missing = []
        unresolved = defaultdict(int)  # selection kind -> groups or operands left out
        groups = []
        for g in d.get("groups", []):
            e = g.get("edges", {})
            k = e.get("kind")
            if k == "historical_partial":
                unresolved["unresolved operands"] += len(e["value"].get("unresolved") or [])
            elif k != "historical":
                unresolved["%s groups" % k] += 1
                continue
            if e["value"].get("edges"):
                groups.append(g)
        if not groups:
            kinds = sorted({str(g.get("edges", {}).get("kind")) for g in d.get("groups", [])})
            raise NotImplementedError("edge selection " + "/".join(kinds))
        for g in groups:
            e = g["edges"]
            if kind == "fillet":
                r = g.get("radius", {})
                rk = r.get("kind")
                if rk == "constant":
                    size = (r["radius"], r["radius"])
                elif rk == "variable":
                    # OCC interpolates the radius linearly; Fusion's smooth transition does not
                    # (case_fillet_variable_radius: 981.46 vs 981.05), so no build is better
                    # than a close wrong one. shaped_fillet keeps the linear form for F2FC_VARIABLE=1.
                    pts = r.get("points") or []
                    if os.environ.get("F2FC_VARIABLE") != "1" or len(pts) != 2:
                        raise NotImplementedError("fillet radius variable (OCC law is linear, Fusion's is not)")
                    size = None
                elif rk == "chordal":
                    size = None
                else:
                    raise NotImplementedError("fillet radius " + str(rk))
            else:
                spec = g.get("spec", {})
                if spec.get("kind") == "distance":
                    size = (spec["distance"], spec["distance"])
                elif spec.get("kind") in ("two_distances", "distance_angle"):
                    size = None  # per edge, once the faces it lies between are known
                else:
                    raise NotImplementedError("chamfer spec " + str(spec.get("kind")))
            first_planes = self.chamfer_first_planes(feat) if kind == "chamfer" else {}
            for eid in e["value"]["edges"]:
                eg = self.topo_geometry.get(eid)
                if eg is None:
                    missing.append("no geometry")
                    continue
                body, idx, dist = self.find_edge(eg)
                if body is None:
                    missing.append("%.3g mm" % dist)
                    continue
                if all(i != idx for i, _, _ in per_body[body]):
                    if size is None and kind == "fillet":
                        sz = self.shaped_fillet(body, idx, eg, r)
                    elif size is None:
                        try:
                            sz = self.asymmetric_chamfer(body, idx, spec, first_planes, int(eid.rsplit(":", 1)[1]))
                        except ValueError as ex:
                            raise ValueError("chamfer orientation: %s" % ex)
                    else:
                        sz = size
                    per_body[body].append((idx, sz[0], sz[1]))
        if missing:
            raise ValueError("%d selected edges not found in the rebuilt bodies (nearest: %s)"
                             % (len(missing), ", ".join(missing[:6])))
        for body, edges in per_body.items():
            if kind == "fillet":
                self.require_uniform_corner_radii(body, edges)
        # A radius that consumes a whole adjacent face exactly (a fillet as tall as the step
        # it rounds) is degenerate for OCC; Fusion accepts it. Retry shrunk by a hair, which
        # leaves a sliver face but a volume within 1e-7 of the exact result.
        for shrink in (0.0, 1e-7, 1e-6):
            made = []
            for body, edges in per_body.items():
                obj = self.doc.addObject("Part::Fillet" if kind == "fillet" else "Part::Chamfer", kind.capitalize())
                obj.Label = feat["name"]
                obj.Base = body
                obj.Edges = [(i, a * (1 - shrink), b * (1 - shrink)) for i, a, b in edges]
                made.append((body, obj))
            self.doc.recompute()
            bad = [o for _, o in made if o.Shape.isNull() or not o.Shape.Solids or "Invalid" in o.State]
            if not bad:
                break
            if shrink == 0.0 and os.environ.get("F2FC_DEBUG_EDGES"):
                import json as _j
                for i, (b_, o) in enumerate(made):
                    b_.Shape.exportBrep("%s/%s_%d.brep" % (os.environ["F2FC_DEBUG_EDGES"], feat["name"], i))
                    _j.dump({"kind": kind, "edges": o.Edges}, open("%s/%s_%d.json" % (os.environ["F2FC_DEBUG_EDGES"], feat["name"], i), "w"))
            for _, o in made:
                self.doc.removeObject(o.Name)
            self.doc.recompute()
        if bad:
            raise ValueError("OCC %s failed on %d of %d bodies" % (kind, len(bad), len(made)))
        for body, obj in made:
            self.solids[self.solids.index(body)] = obj
        res = {"edges": sum(len(v) for v in per_body.values())}
        if unresolved:
            # Only the proven part of the selection is built.
            res["partial_selection"] = dict(unresolved)
        return res

    def build_datum_plane(self, feat):
        frame = feat["definition"].get("frame")
        if not frame:
            raise NotImplementedError("datum plane without a resolved frame")
        pl = self.doc.addObject("Part::Plane", "DatumPlane")
        pl.Label = feat["name"]
        pl.Length = pl.Width = 10
        pl.Placement, _ = self.placement(frame)
        pl.Visibility = False
        return {}

    # ----- holes, patterns, revolves, moves, combines ----------------------
    @staticmethod
    def axis_placement(origin, direction):
        """Placement whose local +Z axis runs along `direction` from `origin`."""
        d = V(direction)
        d.normalize()
        return App.Placement(origin, App.Rotation(V(0, 0, 1), d))

    def primitive(self, kind, label, placement, **props):
        obj = self.doc.addObject(kind, kind.split("::")[1])
        obj.Label = label
        for k, v in props.items():
            setattr(obj, k, v)
        obj.Placement = placement
        return obj

    def hole_parts(self, name, d, pos, axis):
        """Primitive solids of one hole instance: bore, drill point, and entry treatment.
        `pos` is the entry point on the placement face, `axis` the unit drilling direction."""
        shape = d["shape"]
        con = shape.get("construction") or {}
        if con.get("construction") != "form":
            raise NotImplementedError("hole construction " + str(con.get("construction")))
        form = con.get("kind") or {}
        r = (shape.get("diameter") or 0) / 2
        if r <= 0:
            raise NotImplementedError("hole without a bore diameter")
        ext = d.get("extent") or {}
        bottom = d.get("bottom") or {"kind": "flat"}
        tip = 0.0
        if ext.get("kind") == "blind":
            depth = ext["length"]
            if bottom.get("kind") == "angled":
                tip = r / math.tan(bottom["included_angle"] / 2)
                if bottom.get("depth_to_tip"):
                    depth -= tip
        elif ext.get("kind") == "through_all":
            depth = self.scene_size()
        else:
            raise NotImplementedError("hole extent " + str(ext.get("kind")))

        def at(dist):
            return self.axis_placement(pos + axis * dist, axis)

        parts = [self.primitive("Part::Cylinder", name + " bore", at(0), Radius=r, Height=depth)]
        if tip > EPS:
            parts.append(self.primitive("Part::Cone", name + " drill point", at(depth),
                                        Radius1=r, Radius2=0, Height=tip))
        k = form.get("kind")
        if k in ("counterbore", "counterbore_drilled"):
            parts.append(self.primitive("Part::Cylinder", name + " counterbore", at(0),
                                        Radius=form["diameter"] / 2, Height=form["depth"]))
        elif k == "countersink":
            rc = form["diameter"] / 2
            parts.append(self.primitive("Part::Cone", name + " countersink", at(0), Radius1=rc, Radius2=r,
                                        Height=(rc - r) / math.tan(form["angle"] / 2)))
        elif k not in ("simple", "simple_drilled"):
            raise NotImplementedError("hole form " + str(k))
        return parts

    def build_hole(self, feat):
        """Hole: per placement, a bore with its drill point and entry treatment, cut from the
        bodies it overlaps."""
        d = feat["definition"]
        placements = d.get("placements")
        if not placements:
            raise NotImplementedError("hole placement not resolved")
        parts = []
        for i, p in enumerate(placements):
            if p.get("kind") != "directed":
                raise NotImplementedError("hole placement " + str(p.get("kind")))
            axis = vec(p["direction"])
            axis.normalize()
            label = feat["name"] if len(placements) == 1 else "%s %d" % (feat["name"], i + 1)
            parts += self.hole_parts(label, d, vec(p["position"]), axis)
        if len(parts) == 1:  # a lone bore (MultiFuse needs two shapes)
            tool = parts[0]
            tool.Label = feat["name"] + " tool"
        else:
            tool = self.doc.addObject("Part::MultiFuse", "HoleTool")
            tool.Label = feat["name"] + " tool"
            tool.Shapes = parts
            tool.Refine = True
        self.doc.recompute()
        res = self.apply_op("cut", tool, feat["name"])
        res["holes"] = len(placements)
        return res

    def pattern_copies(self, src, p, label):
        """Parametric copies of `src` at the pattern's instances, the seed instance excluded."""
        k = p.get("kind")
        if k == "mirror":
            m = self.doc.addObject("Part::Mirroring", "Mirror")
            m.Label = label
            m.Source = src
            m.Base = vec(p["plane_origin"])
            m.Normal = vec(p["plane_normal"])
            self.doc.recompute()
            return m
        import Draft
        if k == "circular":
            angle = p["angle"]
            # Draft spaces a full turn by angle/count and a partial one by angle/(count-1),
            # as Fusion does; a full turn must be exactly 360 for Draft to see it.
            deg = 360.0 if abs(angle - 2 * math.pi) < 1e-9 else math.degrees(angle)
            axis = vec(p["axis_dir"])
            axis.normalize()
            arr = Draft.make_polar_array(src, number=p["count"], angle=deg, center=vec(p["axis_origin"]),
                                         use_link=False)
            arr.Axis = axis
        elif k == "linear":
            if not p.get("direction"):
                raise NotImplementedError("linear pattern direction unresolved")
            d1 = vec(p["direction"])
            d1.normalize()
            v_y, n_y = V(0, 1, 0), 1
            sec = p.get("second")
            if sec:
                d2 = vec(sec["direction"])
                d2.normalize()
                v_y, n_y = d2 * sec["spacing"], sec["count"]
            arr = Draft.make_ortho_array(src, v_x=d1 * p["spacing"], v_y=v_y, v_z=V(0, 0, 1),
                                         n_x=p["count"], n_y=n_y, n_z=1, use_link=False)
        else:
            raise NotImplementedError("pattern form " + str(k if k != "unresolved" else "unresolved " + str(p.get("form"))))
        arr.Label = label
        # Instance 0 of a Draft array is the seed itself; Fusion adds only the other instances.
        hidden = [0]
        if k == "linear":  # Draft orders the grid as index u * n_y + v
            hidden += [u * n_y + v for u, v in p.get("omitted_instances") or []]
        if not hasattr(arr, "VisibilityList"):
            arr.addProperty("App::PropertyBoolList", "VisibilityList", "Draft", "Instances built (default: all)")
        arr.VisibilityList = [i not in hidden for i in range(max(hidden) + 1)]
        self.doc.recompute()
        return arr

    def build_pattern(self, feat):
        d = feat["definition"]
        p = d.get("pattern") or {}
        if p.get("kind") == "unresolved":
            raise NotImplementedError("pattern %s unresolved" % p.get("form"))
        seeds = d.get("seeds") or []
        kinds = {s.get("kind") for s in seeds}
        if not seeds:
            raise NotImplementedError("pattern seeds unresolved")
        if kinds == {"feature"}:
            return self.feature_pattern(feat, seeds, p)
        if kinds == {"bodies"}:
            return self.body_pattern(feat, seeds, p)
        raise NotImplementedError("pattern of " + "/".join(sorted(map(str, kinds))))

    def feature_pattern(self, feat, seeds, p):
        """Re-apply each seed feature's boolean with its tool copied to every instance."""
        by_id = {f["id"]: f for f in self.slim["features"]}
        tools = []
        for s in seeds:
            seed = by_id.get(s["value"])
            used = self.feature_tools.get(s["value"])
            if not used:
                raise NotImplementedError("seed %s has no rebuilt tool" % (seed["name"] if seed else s["value"]))
            tools += used
        targets = 0
        for i, t in enumerate(tools):
            copies = self.pattern_copies(t["tool"], p, "%s copies %d" % (feat["name"], i + 1))
            targets += self.apply_op(t["op"], copies, feat["name"]).get("targets", 0)
        return {"seeds": len(seeds), "tools": len(tools), "targets": targets}

    @staticmethod
    def historical_bodies(sel):
        """(input state, historical body ids) of a historical body selection, else (None, None)."""
        kind, val = sel.get("kind"), sel.get("value") or {}
        if kind == "historical":
            return val.get("state"), list(val.get("bodies") or [])
        if kind == "historical_set":
            return val.get("state"), [m["body"] for m in val.get("members") or []]
        return None, None

    def locate_body(self, state, body, pool):
        """The rebuilt body whose boundary carries the recorded edges of a historical body's faces."""
        pts = [vec(eg["interior"]) for f in self.body_faces.get(state, {}).get(body) or []
               for eg in self.topo_edges.get(f, [])]
        if not pts:
            return None
        pts = pts[::max(1, len(pts) // 16)]
        hits = [s for s in pool if all(s.Shape.distToShape(Part.Vertex(p))[0] < self.EDGE_TOL for p in pts)]
        return hits[0] if len(hits) == 1 else None

    def select_bodies(self, *sels):
        """Rebuilt bodies (current solids of this component) that body selections name together.
        A historical body is found by the recorded edges of its faces when the decoder states
        them. Otherwise a selection resolves when it names every body of its input state, or the
        component has one body; selections of one state that together name all its bodies
        resolve to all."""
        pool = self.same_component(self.solids)
        located = []
        for sel in sels:
            state, ids = self.historical_bodies(sel)
            hits = [self.locate_body(state, b, pool) for b in ids or []]
            if not hits or None in hits:
                located = None
                break
            located += [h for h in hits if h not in located]
        if located:
            return located
        states, picked = set(), set()
        for sel in sels:
            state, ids = self.historical_bodies(sel)
            if state is None:
                if sel.get("kind") == "resolved" and len(pool) == 1:
                    picked.update((sel.get("value") or {}).get("bodies") or [])
                    continue
                raise NotImplementedError("body selection " + str(sel.get("kind")))
            states.add(state)
            picked.update(ids)
        if len(pool) == 1 and len(picked) == 1:
            return pool
        in_state = self.state_bodies.get(next(iter(states))) if len(states) == 1 else None
        if in_state and set(in_state) == picked and len(in_state) == len(pool):
            return pool
        raise NotImplementedError("selection of %d of %s bodies (%d rebuilt)" % (
            len(picked), len(in_state) if in_state else "?", len(pool)))

    def body_pattern(self, feat, seeds, p):
        """Copies of the seed bodies. A mirrored body that touches its seed is joined to it
        (Fusion's Mirror Join; the decoded definition carries no operation)."""
        bodies = []
        for s in seeds:
            bodies += [b for b in self.select_bodies(s["value"]) if b not in bodies]
        res = {"seeds": len(bodies), "joined": 0, "bodies": 0}
        for b in bodies:
            copies = self.pattern_copies(b, p, "%s of %s" % (feat["name"], b.Label))
            if p.get("kind") == "mirror" and self.touches(b, copies):
                fuse = self.doc.addObject("Part::MultiFuse", "Join")
                fuse.Label = feat["name"] + " join"
                fuse.Shapes = [b, copies]
                fuse.Refine = True
                self.doc.recompute()
                parts = self.split_solids(fuse, feat["name"])
                i = self.solids.index(b)
                self.solids[i:i + 1] = parts
                res["joined"] += 1
                res["op"] = "join (assumed: the mirror touches its seed)"
            else:
                parts = self.split_solids(copies, feat["name"])
                self.solids += parts
                res["bodies"] += len(parts)
        return res

    def profile_base(self, feat, prof):
        """(face object, sketch record) for a planar sketch profile, as for an extrude."""
        value = prof.get("value")
        sid = value.get("sketch") if isinstance(value, dict) else None
        if sid not in self.sketch_defs:
            raise NotImplementedError("profile kind " + prof["kind"])
        sk_rec = self.build_sketch(sid, self.sketch_label(sid))
        sk, geo_of, edge_of, normal = sk_rec
        regions = value.get("regions") or []
        if any(r.get("region") == "trimmed" for r in regions) or self.crossing_loops(sid, regions):
            base = self.doc.addObject("Part::Feature", "ProfileFace")
            base.Shape = self.trimmed_face(sid, regions, sk.Placement)
        else:
            names = self.profile_edges(self.sketch_defs[sid], edge_of, prof)
            base = self.doc.addObject("PartDesign::SubShapeBinder", "Profile")
            base.Support = [(sk, tuple(names))]
            base.MakeFace = True
        base.Label = feat["name"] + " profile"
        self.doc.recompute()
        return base, sk_rec

    def build_revolve(self, feat):
        d = feat["definition"]
        c = d.get("construction") or {}
        if c.get("state") != "resolved":
            raise NotImplementedError("revolve %s unresolved" % c.get("missing"))
        if c.get("solid") is False:
            raise NotImplementedError("surface revolve")
        base, _ = self.profile_base(feat, c["profile"])
        ext = c["extent"]

        def angle(t):
            if t.get("kind") != "angle":
                raise NotImplementedError("revolve termination " + str(t.get("kind")))
            return math.degrees(t["angle"])

        axis = vec(c["axis"]["direction"])
        axis.normalize()
        origin = vec(c["axis"]["origin"])
        rev = self.doc.addObject("Part::Revolution", "Revolve")
        rev.Label = feat["name"]
        rev.Source = base
        rev.Base = origin
        rev.Axis = axis
        rev.Solid = True
        if ext["kind"] == "one_sided":
            rev.Angle = angle(ext["termination"])
        elif ext["kind"] == "symmetric":
            rev.Angle = angle(ext["termination"])
            rev.Symmetric = True
        else:
            raise NotImplementedError("revolve extent " + str(ext["kind"]))
        self.doc.recompute()
        if rev.Shape.isNull() or rev.Shape.Volume <= 0:
            raise ValueError("empty revolution")
        return self.apply_op(d.get("op", "new_body"), rev, feat["name"])

    def build_move_body(self, feat):
        """Move: each selected body is replaced by a placed compound of it (or copied)."""
        d = feat["definition"]
        bodies = self.select_bodies(d["bodies"])
        m = App.Placement(vec(d["translation"]), App.Rotation())
        rot = d.get("rotation")
        if rot:
            axis = vec(rot["direction"])
            axis.normalize()
            m = m.multiply(App.Placement(App.Vector(), App.Rotation(axis, math.degrees(rot["angle"])),
                                         vec(rot["origin"])))
        copies = d.get("copies", 0)
        if copies:
            raise NotImplementedError("move with %d copies" % copies)
        for b in bodies:
            mv = self.doc.addObject("Part::Compound", "Move")
            mv.Label = "%s of %s" % (feat["name"], b.Label)
            mv.Links = [b]
            mv.Placement = m
            self.solids[self.solids.index(b)] = mv
        self.doc.recompute()
        return {"bodies": len(bodies)}

    def build_combine(self, feat):
        d = feat["definition"]
        ops = d["operands"]
        op = d["op"]
        try:
            target = self.select_bodies(ops["target"])
            tools = self.select_bodies(ops["tools"])
        except NotImplementedError:
            if op != "join":
                raise
            # A join is symmetric: when target and tools are all the bodies, any one is the target.
            both = self.select_bodies(ops["target"], ops["tools"])
            target, tools = both[:1], both[1:]
        if len(target) != 1:
            raise NotImplementedError("combine of %d target bodies" % len(target))
        target = target[0]
        tools = [t for t in tools if t is not target]
        if not tools:
            raise ValueError("combine without tool bodies")
        if op == "join":
            b = self.doc.addObject("Part::MultiFuse", "Combine")
            b.Shapes = [target] + tools
        elif op in ("cut", "intersect"):
            b = self.doc.addObject("Part::Cut" if op == "cut" else "Part::Common", "Combine")
            if len(tools) == 1:
                tool = tools[0]
            else:
                tool = self.doc.addObject("Part::MultiFuse", "CombineTools")
                tool.Shapes = tools
            b.Base, b.Tool = target, tool
        else:
            raise NotImplementedError("combine " + str(op))
        b.Label = feat["name"]
        b.Refine = True
        self.doc.recompute()
        i = self.solids.index(target)
        self.solids[i:i + 1] = self.split_solids(b, feat["name"])
        if not d.get("keep_tools"):
            self.solids = [s for s in self.solids if s not in tools]
        return {"op": op, "tools": len(tools)}
    # ----- solid primitives ----------------------------------------------
    @staticmethod
    def rigid_placement(rows):
        """Placement of a CADIR rigid 3x4 (or 4x4) row-major transform, in mm."""
        m = App.Matrix(*(list(rows[0]) + list(rows[1]) + list(rows[2]) + [0, 0, 0, 1]))
        return App.Placement(m)

    def primitive_solid(self, kind, label, placement, **props):
        obj = self.primitive(kind, label, placement, **props)
        self.doc.recompute()
        if obj.Shape.isNull() or obj.Shape.Volume <= 0:
            raise ValueError("empty primitive")
        return obj

    def build_block(self, feat):
        d = feat["definition"]
        if not d.get("dimensions") or not d.get("placement"):
            raise NotImplementedError("box primitive without resolved dimensions or placement")
        length, width, height = d["dimensions"]
        box = self.primitive_solid("Part::Box", feat["name"], self.rigid_placement(d["placement"]),
                                   Length=length, Width=width, Height=height)
        return self.apply_op(d["op"], box, feat["name"])

    def build_primitive(self, feat):
        d = feat["definition"]
        if not d.get("placement"):
            raise NotImplementedError("primitive without a resolved placement")
        solid = d["solid"]
        pl = self.rigid_placement(d["placement"])
        k = solid.get("kind")
        full = 2 * math.pi
        if k == "cylinder":
            obj = self.primitive_solid("Part::Cylinder", feat["name"], pl, Radius=solid["radius"],
                                       Height=solid["height"], Angle=math.degrees(solid.get("angle", full)))
        elif k == "cone":
            obj = self.primitive_solid("Part::Cone", feat["name"], pl, Radius1=solid["radius1"],
                                       Radius2=solid["radius2"], Height=solid["height"],
                                       Angle=math.degrees(solid.get("angle", full)))
        elif k == "box":
            obj = self.primitive_solid("Part::Box", feat["name"], pl, Length=solid["length"],
                                       Width=solid["width"], Height=solid["height"])
        else:
            raise NotImplementedError("primitive solid " + str(k))
        return self.apply_op(d["op"], obj, feat["name"])

    def build_sphere(self, feat):
        d = feat["definition"]
        obj = self.primitive_solid("Part::Sphere", feat["name"], App.Placement(vec(d["center"]), App.Rotation()),
                                   Radius=d["radius"])
        return self.apply_op(d["op"], obj, feat["name"])

    def build_torus(self, feat):
        d = feat["definition"]
        obj = self.primitive_solid("Part::Torus", feat["name"], self.axis_placement(vec(d["center"]), vec(d["axis"])),
                                   Radius1=d["major_radius"], Radius2=d["minor_radius"])
        return self.apply_op(d["op"], obj, feat["name"])

    # ----- base features (stored bodies) ---------------------------------
    def build_base_feature(self, feat):
        """Insert the bodies a Base Feature stores, as static solids. The decoded bodies are
        those of the final design, so a body that a later feature modifies is refused. A
        current body that coincides with a stored body is the body that the Base Feature
        takes over (Body to Component), and the stored body replaces it."""
        sel = feat["definition"].get("bodies") or {}
        if sel.get("kind") != "resolved":
            raise NotImplementedError("base feature bodies " + str(sel.get("kind")))
        if self.stored is None:
            raise NotImplementedError("stored bodies not exported (F2FC_BODIES)")
        later = set()
        for f in self.slim["features"]:
            if f["ordinal"] > feat["ordinal"] and not f.get("suppressed"):
                later.update(f.get("outputs") or [])
        res = {"bodies": 0, "replaced": 0}
        for bid in sel["value"]["bodies"]:
            rec = self.stored.get(bid) or {}
            if not rec.get("file"):
                raise ValueError("stored body %s was not exported: %s" % (bid, rec.get("error", "missing")))
            if bid in later:
                raise NotImplementedError("stored body modified by later features")
            shape = Part.Shape()
            shape.read(os.path.join(self.stored_dir, rec["file"]))
            if rec.get("kind") == "solid":
                if not shape.Solids:
                    raise ValueError("stored solid body has no solid")
                shape = shape.Solids[0] if len(shape.Solids) == 1 else Part.makeCompound(shape.Solids)
            obj = self.doc.addObject("Part::Feature", "StoredBody")
            obj.Shape = shape
            obj.Label = "%s body %d" % (feat["name"], res["bodies"] + 1)
            self.body_component[obj.Name] = self.component
            twin = self.coincident_body(obj)
            if twin is not None:
                self.solids.remove(twin)
                twin.Visibility = False
                res["replaced"] += 1
            self.solids.append(obj)
            res["bodies"] += 1
        return res

    def world_shape(self, obj):
        mats = self.world.get(self.body_component.get(obj.Name)) or [None]
        m = mats[0]
        return obj.Shape if m is None or m.isUnity() else obj.Shape.transformGeometry(m)

    def coincident_body(self, obj):
        """The current body that occupies the same space as `obj` (world coordinates)."""
        mine = self.world_shape(obj)
        if not mine.Solids:
            return None
        for s in self.solids:
            other = self.world_shape(s)
            if not other.Solids or abs(other.Volume - mine.Volume) > 1e-6 * max(mine.Volume, 1.0):
                continue
            if other.BoundBox.isInside(mine.BoundBox.Center) and \
                    abs(other.common(mine).Volume - mine.Volume) <= 1e-6 * max(mine.Volume, 1.0):
                return s
        return None

    # ----- sweep, loft (profile loops and paths) -------------------------
    def sketch_edge(self, sk, name):
        """The sketch shape's edge for a mapped name ';g<id>;SKT.EdgeN' (world coordinates)."""
        return sk.Shape.getElement(name.rsplit(".", 1)[-1])

    def profile_loops(self, prof):
        """(sketch object, [(outer loop edge names, [hole loop edge names])]) of a resolved
        sketch profile. Nesting of `sketch_profiles` loops is found geometrically, as the
        extrude's face maker does."""
        kind, val = prof.get("kind"), prof.get("value")
        sid = val.get("sketch") if isinstance(val, dict) else None
        if sid not in self.sketch_defs or kind not in ("sketch_profiles", "sketch_regions"):
            raise NotImplementedError("profile kind " + str(kind))
        sk, geo_of, edge_of, normal = self.build_sketch(sid, self.sketch_label(sid))
        loops = self.sketch_defs[sid].get("profiles") or []

        def names(i):
            out = []
            for ref in loops[i]:
                n = edge_of.get(ref["entity"])
                if n is None:
                    raise ValueError("profile references a curve with no sketch edge")
                if n not in out:
                    out.append(n)
            return out

        if kind == "sketch_regions":
            groups = []
            for r in val["regions"]:
                if r.get("region") != "loops":
                    raise NotImplementedError("region form %s" % r.get("region"))
                groups.append((names(r["outer"]), [names(h) for h in r.get("holes", [])]))
            return sk, groups
        chosen = [names(i) for i in val["profiles"]]
        faces = [Part.Face(Part.Wire(Part.__sortEdges__([self.sketch_edge(sk, n) for n in loop])))
                 for loop in chosen]
        depth = [sum(1 for j, g in enumerate(faces) if j != i and g.Area > f.Area
                     and g.isInside(f.Wires[0].Vertexes[0].Point, 1e-7, True)) for i, f in enumerate(faces)]
        groups = []
        for i in range(len(chosen)):
            if depth[i] % 2 == 0:
                holes = [chosen[j] for j in range(len(chosen)) if depth[j] == depth[i] + 1
                         and faces[i].isInside(faces[j].Wires[0].Vertexes[0].Point, 1e-7, True)]
                groups.append((chosen[i], holes))
        return sk, groups

    def loop_object(self, sk, names, label):
        """A binder holding one closed sketch loop as a wire."""
        b = self.doc.addObject("PartDesign::SubShapeBinder", "Loop")
        b.Support = [(sk, tuple(names))]
        b.MakeFace = False
        b.Label = label
        b.Visibility = False
        return b

    def path_spine(self, path):
        """(owner object, element names, edges) of a sweep path: sketch curves or
        historical body edges."""
        k, v = path.get("kind"), path.get("value")
        if k == "sketch_curves":
            sid = v["sketch"]
            if sid not in self.sketch_defs:
                raise NotImplementedError("path in a non-planar sketch")
            sk, geo_of, edge_of, normal = self.build_sketch(sid, self.sketch_label(sid))
            names = []
            for eid in v["curves"]:
                n = edge_of.get(eid)
                if n is None:
                    raise ValueError("path curve with no sketch edge")
                names.append(n)
            return sk, names, [self.sketch_edge(sk, n) for n in names]
        if k == "historical_edges":
            found = []
            for eid in v["edges"]:
                eg = self.topo_geometry.get(eid)
                body, idx, _ = self.find_edge(eg) if eg else (None, None, None)
                if body is None:
                    raise ValueError("path edge not found in the rebuilt bodies")
                found.append((body, idx))
            if len({b.Name for b, _ in found}) != 1:
                raise NotImplementedError("path edges on several bodies")
            body = found[0][0]
            return body, ["Edge%d" % i for _, i in found], [body.Shape.Edges[i - 1] for _, i in found]
        raise NotImplementedError("sweep path " + str(k))

    @staticmethod
    def chain(names, edges, near=None):
        """Order path edges into one connected chain. It starts at the chain end nearest
        to `near`, else at the free end of the first selected edge. Returns the ordered
        names and their wire."""
        tol = 1e-6
        ends = [(e.Vertexes[0].Point, e.Vertexes[-1].Point) for e in edges]

        def degree(p):
            return sum((a - p).Length < tol for pair in ends for a in pair)

        free = [p for pair in ends for p in pair if degree(p) == 1]
        if near is not None and free:
            p = min(free, key=lambda q: (q - near).Length)
        elif free:
            p = next((q for q in ends[0] if degree(q) == 1), free[0])
        else:
            p = ends[0][0]
        order, used = [], set()
        while len(order) < len(edges):
            nxt = [i for i in range(len(edges)) if i not in used
                   and any((a - p).Length < tol for a in ends[i])]
            if not nxt:
                raise ValueError("sweep path is not one connected chain")
            i = nxt[0]
            used.add(i)
            order.append(i)
            a, b = ends[i]
            p = b if (a - p).Length < tol else a
        return [names[i] for i in order], Part.Wire([edges[i] for i in order])

    @staticmethod
    def path_corners(wire):
        """(point, incoming tangent, outgoing tangent) where consecutive path edges meet
        at an angle (unit tangents, along the wire)."""
        edges, verts = wire.OrderedEdges, wire.OrderedVertexes

        def tangent(e, p):
            t = e.tangentAt(e.Curve.parameter(p))
            t.normalize()
            return t

        out = []
        for i in range(len(edges) - 1):
            p = verts[i + 1].Point
            t_in, t_out = tangent(edges[i], p), tangent(edges[i + 1], p)
            # Orient both along the wire: edge i runs from verts[i] to p.
            if (edges[i].valueAt(edges[i].Curve.parameter(p)) - p).Length > 1e-6:
                continue
            if (verts[i].Point - p).dot(t_in) > 0:
                t_in = -t_in
            if (verts[i + 2].Point - p).dot(t_out) < 0 and len(edges[i + 1].Vertexes) > 1:
                t_out = -t_out
            if t_in.getAngle(t_out) > 1e-9:
                out.append((p, t_in, t_out))
        return out

    def mitered_pipe(self, wire, radius, label):
        """Solid pipe of a circle along a path with corners. Fusion joins the segments
        with a miter: each segment continues straight along its end tangent up to the
        plane that bisects the corner. Static geometry."""
        edges, verts = wire.OrderedEdges, wire.OrderedVertexes
        corners = {(c[0].x, c[0].y, c[0].z): c for c in self.path_corners(wire)}
        parts = []
        for i, e in enumerate(edges):
            p0 = verts[i].Point
            t = e.tangentAt(e.Curve.parameter(p0))
            t.normalize()
            if (verts[i + 1].Point - p0).dot(t) < 0 and e.Curve.__class__.__name__ == "Line":
                t = -t
            seg = Part.Wire(e).makePipeShell([Part.Wire(Part.Circle(p0, t, radius).toShape())], True, False, 0)
            parts.append(seg)
        size = 4 * radius
        for p, t_in, t_out in corners.values():
            bis = t_in + t_out
            bis.normalize()
            half = t_in.getAngle(t_out) / 2
            reach = radius * math.tan(half) * 1.5 + 1e-3
            for t, sign in ((t_in, 1), (t_out, -1)):
                ext = Part.makeCylinder(radius, reach, p, t * sign)
                # Keep the part of the extension on its own segment's side of the
                # bisector plane (behind it for the incoming segment).
                box = Part.makeBox(4 * size, 4 * size, 2 * size)
                box.Placement = App.Placement(p, App.Rotation(V(0, 0, 1), bis * -sign))
                box.translate(-box.Placement.Rotation.multVec(V(2 * size, 2 * size, 0)))
                parts.append(ext.common(box))
        shape = parts[0].fuse(parts[1:]).removeSplitter() if len(parts) > 1 else parts[0]
        if not shape.isValid() or len(shape.Solids) != 1:
            raise ValueError("mitered pipe is not one valid solid")
        return shape

    def sweep_solid(self, section, link, wire, label):
        """Solid swept by one closed section along a G1 path wire. The parametric
        Part::Sweep is kept when it reproduces OCC's pipe shell of the same inputs;
        otherwise a static copy of the pipe shell replaces it."""
        self.doc.recompute()
        profile = Part.Wire(Part.__sortEdges__(section.Shape.Edges))
        direct = wire.makePipeShell([profile], True, False, 0)
        if not direct.isValid():
            direct.fix(1e-7, 1e-7, 1e-7)
        if not direct.isValid() or not direct.Solids:
            raise ValueError("sweep result is not a valid solid")
        sw = self.doc.addObject("Part::Sweep", "Sweep")
        sw.Sections = [section]
        sw.Spine = link
        sw.Solid = True
        sw.Frenet = False
        sw.Transition = "Transformed"
        sw.Label = label
        self.doc.recompute()
        got = sw.Shape
        if not got.isNull() and got.isValid() and abs(got.Volume - direct.Volume) <= 1e-9 * direct.Volume:
            return sw
        self.doc.removeObject(sw.Name)
        return self.static(direct, label)

    def static(self, shape, label):
        obj = self.doc.addObject("Part::Feature", "Sweep")
        obj.Shape = shape
        obj.Label = label + " (static)"
        self.notes.setdefault("static", []).append(label)
        return obj

    def subtract(self, base, tools, label):
        """base minus the tools (holes of a hollow section), as one parametric object."""
        if not tools:
            return base
        base.Visibility = False
        cut = self.doc.addObject("Part::Cut", "Cut")
        cut.Base = base
        if len(tools) == 1:
            cut.Tool = tools[0]
        else:
            fuse = self.doc.addObject("Part::MultiFuse", "Fusion")
            fuse.Shapes = tools
            cut.Tool = fuse
        for t in tools:
            t.Visibility = False
        cut.Label = label
        return cut

    def union(self, objs, label):
        if len(objs) == 1:
            return objs[0]
        fuse = self.doc.addObject("Part::MultiFuse", "Fusion")
        fuse.Shapes = objs
        fuse.Refine = True
        fuse.Label = label
        return fuse

    def build_sweep(self, feat):
        d = feat["definition"]
        shape = d["shape"]
        if shape.get("mode") != "solid":
            raise NotImplementedError("%s sweep" % shape.get("mode"))
        if shape.get("sections"):
            raise NotImplementedError("sweep with several sections")
        for key in ("guide_rail", "twist", "taper", "scale"):
            if d.get(key) not in (None, 0, 0.0, 1, 1.0):
                raise NotImplementedError("sweep " + key)
        if d.get("orientation") not in (None, "perpendicular"):
            raise NotImplementedError("sweep orientation " + str(d.get("orientation")))
        ext = d.get("path_extent") or {"along_fraction": 1.0, "against_fraction": 0.0}
        owner, names, edges = self.path_spine(d["path"])
        sec = shape["section"]
        name = feat["name"]
        if sec.get("kind") == "generated":
            names, wire = self.chain(names, edges)
            start = wire.OrderedVertexes[0].Point
            e0 = wire.OrderedEdges[0]
            t = e0.tangentAt(e0.Curve.parameter(start))
            g = sec["value"]
            if g.get("shape") != "circular_region":
                raise NotImplementedError("generated section " + str(g.get("shape")))
            # Fusion's pipe section is centred on the path start, normal to the path.
            radii = [g["region"]["outer_radius"]]
            if g["region"].get("wall_thickness"):
                radii.append(radii[0] - g["region"]["wall_thickness"])
            # Keep the section seam where OCC puts it for a circle with this normal, as
            # the static pipe shells do.
            circle = Part.Circle(start, t, 1.0)
            x, n = circle.XAxis, circle.Axis
            y = n.cross(x)
            rot = App.Rotation(App.Matrix(x.x, y.x, n.x, 0, x.y, y.y, n.y, 0, x.z, y.z, n.z, 0, 0, 0, 0, 1))
            sections = []
            for r in radii:
                c = self.doc.addObject("Part::Circle", "PipeSection")
                c.Radius = r
                c.Placement = App.Placement(start, rot)
                c.Visibility = False
                sections.append(c)
            groups = [(sections[0], sections[1:])]
            at_start = True
        elif sec.get("kind") == "profile":
            sk, loops = self.profile_loops(sec["value"])
            groups = [(self.loop_object(sk, o, name + " section"),
                       [self.loop_object(sk, h, name + " section hole") for h in holes]) for o, holes in loops]
            self.doc.recompute()
            section = groups[0][0].Shape
            names, wire = self.chain(names, edges, section.CenterOfMass)
            at_start = section.distToShape(wire.OrderedVertexes[0])[0] < 1e-6
            if not at_start and section.distToShape(wire.OrderedVertexes[-1])[0] < 1e-6:
                wire.reverse()
                at_start = section.distToShape(wire.OrderedVertexes[0])[0] < 1e-6
            if not at_start and min(ext["along_fraction"], ext["against_fraction"]) < 1.0 - 1e-9:
                raise NotImplementedError("sweep profile away from the path ends")
        else:
            raise NotImplementedError("sweep section " + str(sec.get("kind")))
        # Fusion consumes a fraction of the path on each side of the profile; the whole
        # path is swept when the profile is at its start and the fraction along it is 1.
        fractions = (ext["along_fraction"], ext["against_fraction"])
        if any(1e-9 < f < 1.0 - 1e-9 for f in fractions) or max(fractions) < 1.0 - 1e-9:
            raise NotImplementedError("partial sweep path extent")
        link = (owner, names)
        self.notes = {}
        solids = []
        if self.path_corners(wire):
            if sec.get("kind") != "generated":
                raise NotImplementedError("profile sweep along a path with corners")
            tube = [self.static(self.mitered_pipe(wire, c.Radius.Value, name), name) for c in sections]
            groups = []
            solids.append(self.subtract(tube[0], tube[1:], name))
        for outer, holes in groups:
            body = self.sweep_solid(outer, link, wire, name)
            cut = [self.sweep_solid(h, link, wire, name + " hole") for h in holes]
            solids.append(self.subtract(body, cut, name))
        tool = self.union(solids, name)
        self.doc.recompute()
        if tool.Shape.isNull() or not tool.Shape.Solids:
            raise ValueError("empty sweep")
        res = self.apply_op(shape["op"], tool, name)
        res.update(self.notes)
        return res

    def build_loft(self, feat):
        """Loft through whole-sketch sections (one closed loop each) with no rails or
        centerline: `Part::Loft` through the loop wires."""
        d = feat["definition"]
        if (d.get("guidance") or {}).get("path"):
            raise NotImplementedError("loft with rails or centerline")
        if d.get("solid") is False:
            raise NotImplementedError("surface loft")
        if d.get("linearize"):
            raise NotImplementedError("linearized loft")
        name = feat["name"]
        # A whole-sketch section selects every profile region, so nested loops (an annulus
        # and its inner disc) fill back to the outermost loop.
        objs = []
        for sec in d["sections"]:
            v = sec.get("value")
            if sec.get("kind") != "sketch" or v not in self.sketch_defs:
                raise NotImplementedError("loft section " + str(sec.get("kind")))
            n = len(self.sketch_defs[v].get("profiles") or [])
            sk, groups = self.profile_loops({"kind": "sketch_profiles",
                                             "value": {"sketch": v, "profiles": list(range(n))}})
            if len(groups) != 1:
                raise NotImplementedError("loft section with several profiles")
            objs.append(self.loop_object(sk, groups[0][0], name + " section"))
        if len(objs) < 2:
            raise NotImplementedError("loft with fewer than two sections")
        loft = self.doc.addObject("Part::Loft", "Loft")
        loft.Sections = objs
        loft.Solid = True
        loft.Ruled = bool(d.get("ruled"))
        loft.Closed = bool(d.get("closed"))
        loft.Label = name
        self.doc.recompute()
        if loft.Shape.isNull() or not loft.Shape.Solids or loft.Shape.Volume <= 0:
            raise ValueError("empty loft")
        return self.apply_op(d.get("op", "new_body"), loft, name)

    # ----- driver ---------------------------------------------------------
    def sketch_label(self, sid, fallback=None):
        """The sketch's stored name; cadmpeg names a sketch without one by its entity id."""
        name = (self.sketch_defs.get(sid) or {}).get("name")
        if name and not re.fullmatch(r"\d+_\d+", name):
            return name
        if fallback:
            return fallback
        for f in self.slim["features"]:
            sk = f["definition"].get("sketch")
            if isinstance(sk, dict) and sk.get("sketch") == sid:
                return f["name"]
        return sid.rsplit("@", 1)[-1]

    def spatial_sketch_label(self, sid, fallback):
        for sk in self.slim.get("spatial_sketches", []):
            if sk["id"] == sid and sk.get("name") and not re.fullmatch(r"\d+_\d+", sk["name"]):
                return sk["name"]
        return fallback

    def run(self):
        feats = sorted(self.slim["features"], key=lambda f: f["ordinal"])
        for f in feats:
            f["name"] = display_name(f)
        if self.wanted is not None:
            feats = [f for f in feats if f["id"] in self.wanted]
        for f in feats:
            kind = f["definition"].get("definition", "native")
            rec = {"name": f["name"], "kind": kind}
            self.component = f.get("product_definition")
            self.feature = f
            try:
                if kind == "sketch":
                    ref = f["definition"]["sketch"]
                    if "sketch" not in ref:
                        raise NotImplementedError("sketch space " + str(ref.get("space")))
                    rec["name"] = self.sketch_label(ref["sketch"], f["name"])
                elif kind == "spatial_sketch":
                    rec["name"] = self.spatial_sketch_label(f["definition"]["sketch"], f["name"])
                if f.get("suppressed"):
                    rec["status"] = "suppressed"
                    if kind == "extrude":
                        try:
                            rec.update(self.build_extrude(f, suppressed=True))
                        except Exception as e:
                            rec["reason"] = "tool not built: %s" % e
                elif kind == "sketch":
                    ref = f["definition"]["sketch"]
                    if ref.get("space") != "planar":
                        raise NotImplementedError("non-planar sketch")
                    self.build_sketch(ref["sketch"], rec["name"])
                    rec["status"] = "built"
                elif kind == "extrude":
                    rec.update(self.build_extrude(f))
                    rec["status"] = "built"
                elif kind in ("fillet", "chamfer"):
                    rec.update(self.build_edge_treatment(f, kind))
                    rec["status"] = "built"
                elif kind == "datum_plane":
                    rec.update(self.build_datum_plane(f))
                    rec["status"] = "built"
                elif kind in self.FEATURE_BUILDERS:
                    rec.update(getattr(self, self.FEATURE_BUILDERS[kind])(f))
                    rec["status"] = "built"
                else:
                    raise NotImplementedError("feature kind " + kind)
            except NotImplementedError as e:
                rec["status"], rec["reason"] = "skipped", str(e)
            except Exception as e:
                rec["status"], rec["reason"] = "failed", "%s: %s" % (type(e).__name__, e)
                rec["trace"] = traceback.format_exc()[-800:]
            for o in self.solids:
                self.body_component.setdefault(o.Name, self.component)
            world = self.world_shapes()
            rec["volumes"] = []
            for w in world:
                try:
                    rec["volumes"].append(w.Volume)
                except Exception as e:  # an invalid result shape (OCC refuses its properties)
                    rec.setdefault("invalid_bodies", []).append(str(e))
            rec["volumes"].sort(reverse=True)
            if self.steps_dir:
                rec["step_file"] = "step_%04d.brep" % len(self.report["features"])
                Part.Compound(world).exportBrep(os.path.join(self.steps_dir, rec["step_file"]))
            self.report["features"].append(rec)
        self.doc.recompute()
        bodies = []
        for s in self.solids:
            mats = self.world.get(self.body_component.get(s.Name)) or [None]
            for m in mats:
                bodies.append(self.body_record(s, m))
        self.report["bodies"] = bodies
        self.finish()
        return self.report

    # ----- final-shape check, fallback and conversion report -----------------
    FINAL_RTOL = 1e-4  # relative volume tolerance against Fusion's stored final bodies

    def stored_final_shapes(self, index):
        """Fusion's stored final solids, placed in the root: [(body id, shape)]."""
        out = []
        for bid, rec in index.items():
            if not rec.get("file"):
                raise ValueError("final body %s not exported: %s" % (bid, rec.get("error", "missing")))
            shape = Part.Shape()
            shape.read(os.path.join(os.path.dirname(os.environ["F2FC_FINAL"]), rec["file"]))
            for m in self.world.get(rec.get("component")) or [None]:
                out.append((bid, shape if m is None or m.isUnity() else shape.transformGeometry(m)))
        return out

    def compare_final(self, stored, rebuilt):
        """Count, volumes and bounding box of the rebuilt final bodies against the stored ones."""
        def solids(shapes):
            return [x for s in shapes for x in s.Solids]
        a, b = solids(stored), solids(rebuilt)
        res = {"stored_solids": len(a), "rebuilt_solids": len(b), "problems": []}
        va, vb = sorted(x.Volume for x in a), sorted(x.Volume for x in b)
        res["stored_volume"], res["rebuilt_volume"] = sum(va), sum(vb)
        if len(a) != len(b):
            res["problems"].append("solid count %d (Fusion) vs %d (rebuilt)" % (len(a), len(b)))
        else:
            for x, y in zip(va, vb):
                if abs(x - y) > self.FINAL_RTOL * max(abs(x), abs(y), 1e-9):
                    res["problems"].append("volume %.6g mm3 (Fusion) vs %.6g (rebuilt)" % (x, y))
                    break
        if a and b:
            ba, bb = Part.makeCompound(a).BoundBox, Part.makeCompound(b).BoundBox
            tol = max(0.01, 1e-4 * ba.DiagonalLength)
            d = max(abs(ba.XMin - bb.XMin), abs(ba.YMin - bb.YMin), abs(ba.ZMin - bb.ZMin),
                    abs(ba.XMax - bb.XMax), abs(ba.YMax - bb.YMax), abs(ba.ZMax - bb.ZMax))
            res["bbox_max_deviation_mm"] = d
            if d > tol:
                res["problems"].append("bounding box differs by %.4g mm" % d)
        res["match"] = not res["problems"]
        return res

    def finish(self):
        """Compare with Fusion's stored final bodies, add them as a separate non-parametric group
        when the rebuild is incomplete or differs, and write the conversion summary. Active only
        when the driver (tools/convert.py) sets F2FC_FINAL / F2FC_FACTS."""
        facts = json.load(open(os.environ["F2FC_FACTS"])) if os.environ.get("F2FC_FACTS") else {}
        rep = self.report
        feats = rep["features"]
        lost = [r for r in feats if r["status"] in ("skipped", "failed")]
        final = {"checked": False}
        stored = None
        if os.environ.get("F2FC_FINAL"):
            try:
                stored = self.stored_final_shapes(json.load(open(os.environ["F2FC_FINAL"])))
                self.doc.recompute()
                final = dict(self.compare_final([s for _, s in stored], self.world_shapes()), checked=True)
            except Exception as e:
                final = {"checked": False, "error": "%s: %s" % (type(e).__name__, e)}
        incomplete = bool(lost) or (final.get("checked") and not final["match"])
        want = facts.get("fallback", True) and not os.environ.get("F2FC_NO_FALLBACK")
        used = False
        if incomplete and want and stored:
            grp = self.doc.addObject("App::DocumentObjectGroup", "FusionFinalShape")
            grp.Label = "Fusion final shape (not parametric)"
            for n, (bid, shape) in enumerate(stored):
                o = self.doc.addObject("Part::Feature", "FusionFinalBody")
                o.Shape = shape
                o.Label = "Fusion final body %d (not parametric)" % (n + 1)
                grp.addObject(o)
            for s in self.solids:
                s.Label = s.Label + " (INCOMPLETE rebuild)"
                s.Visibility = False
            used = True
        final.update(incomplete=incomplete, fallback_used=used, fallback_wanted=want)
        rep["final_shape"] = final
        rep["facts"] = facts
        rep["summary_text"] = self.summary_text(facts, lost, final)
        print(rep["summary_text"])
        if os.environ.get("F2FC_SUMMARY"):
            open(os.environ["F2FC_SUMMARY"], "w").write(rep["summary_text"] + "\n")
        if facts or os.environ.get("F2FC_FINAL"):
            t = self.doc.addObject("App::TextDocument", "ConversionReport")
            t.Label = "Conversion report"
            try:
                t.Text = rep["summary_text"]
            except Exception:
                pass

    def summary_text(self, facts, lost, final):
        feats = self.report["features"]
        st = defaultdict(int)
        for r in feats:
            st[r["status"]] += 1
        lines = ["Conversion report", "  features: %s" % ", ".join("%d %s" % (v, k) for k, v in sorted(st.items()))]
        for r in lost[:40]:
            lines.append("    %s %s (%s): %s" % (r["status"].upper(), r["name"], r["kind"], str(r.get("reason", ""))[:140]))
        if len(lost) > 40:
            lines.append("    ... %d more" % (len(lost) - 40))
        if final.get("checked"):
            lines.append("  final shape vs Fusion's stored bodies: %s (%d solids rebuilt, %d stored; volume %.6g vs %.6g mm3)" % (
                "MATCH" if final["match"] else "DIFFERS", final["rebuilt_solids"], final["stored_solids"],
                final["rebuilt_volume"], final["stored_volume"]))
            for p in final["problems"]:
                lines.append("    " + p)
        else:
            lines.append("  final shape: not checked" + (" (%s)" % final["error"] if final.get("error") else ""))
        if final.get("fallback_used"):
            lines.append("  FALLBACK: Fusion's stored final bodies were added as 'Fusion final shape (not parametric)'; "
                         "the parametric rebuild is incomplete and hidden.")
        elif final.get("incomplete"):
            lines.append("  WARNING: the parametric rebuild is incomplete" +
                         ("; fallback disabled." if not final.get("fallback_wanted") else "; no final bodies available."))
        for w in facts.get("warnings", []):
            lines.append("  WARNING: " + w)
        lc = facts.get("loss_counts") or {}
        if lc:
            lines.append("  decoder losses by code: " + ", ".join("%s x%d" % kv for kv in sorted(lc.items(), key=lambda kv: -kv[1])[:12]))
        return "\n".join(lines)

    @staticmethod
    def body_record(s, m):
        """Report entry for one placed copy of a body (m: occurrence world matrix or None)."""
        if s.Shape.isNull():
            return {"object": s.Name, "label": s.Label, "valid": False, "null": True}
        shp = s.Shape if m is None or m.isUnity() else s.Shape.transformGeometry(m)
        bb = shp.BoundBox
        return {"object": s.Name, "label": s.Label, "valid": shp.isValid(),
                "volume": shp.Volume, "area": shp.Area,
                "solids": len(shp.Solids),
                "centroid": list(shp.Solids[0].CenterOfMass) if len(shp.Solids) == 1 else None,
                "bbox": [[bb.XMin, bb.YMin, bb.ZMin], [bb.XMax, bb.YMax, bb.ZMax]]}


def main():
    slim = json.load(open(os.environ["F2FC_SLIM"]))
    topo = json.load(open(os.environ["F2FC_TOPO"])) if os.environ.get("F2FC_TOPO") else None
    wanted = set(json.load(open(os.environ["F2FC_FEATURES"]))) if os.environ.get("F2FC_FEATURES") else None
    rb = Rebuilder(slim, topo, wanted)
    report = rb.run()
    rb.doc.saveAs(os.environ["F2FC_OUT"])
    with open(os.environ["F2FC_REPORT"], "w") as f:
        json.dump(report, f, indent=1)
    st = defaultdict(int)
    for r in report["features"]:
        st[r["status"]] += 1
    print("F2FC features:", dict(st), "| bodies:", len(report["bodies"]))


try:
    main()
except Exception:
    traceback.print_exc()
sys.stdout.flush()
