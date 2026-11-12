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
  freecadcmd fusion2fc/rebuild.py

v0 scope: planar sketches (lines, arcs, circles, B-splines; coincidence from shared
endpoints; horizontal/vertical), extrudes from resolved profiles/regions with blind,
symmetric and two-sided extents, profile-plane or planar from-face starts, and
new-body/join/cut/intersect against the bodies the tool touches. Everything else is
recorded in the report as skipped. CADIR lengths are mm, as in FreeCAD.
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
    FEATURE_BUILDERS = {"sweep": "build_sweep"}

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
        self.steps_dir = os.environ.get("F2FC_STEPS")
        if self.steps_dir:
            os.makedirs(self.steps_dir, exist_ok=True)

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
                if c["poles"].get("form") != "polynomial":
                    skipped["rational nurbs"] += 1
                    continue
                poles = [uv(p) for p in c["poles"]["points"]]
                knots, mults = [], []
                for kv in c["knots"]:
                    if knots and abs(kv - knots[-1]) < 1e-12:
                        mults[-1] += 1
                    else:
                        knots.append(kv)
                        mults.append(1)
                geo = Part.BSplineCurve()
                geo.buildFromPolesMultsKnots(poles, mults, knots, c.get("periodic", False), c["degree"])
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
        if cons:
            sk.addConstraint(cons)
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

        def loop_wire(boundary):
            edges = [seg_edge(s) for s in boundary]
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
            free = [e for e in fused.Edges if len(fused.ancestorsOfType(e, Part.Face)) == 1]
            wires = [Part.Wire(group) for group in Part.sortEdges(free)]
            shape = Part.makeFace(wires, "Part::FaceMakerBullseye")
        else:
            shape = faces[0]
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
        sid = value.get("sketch") if isinstance(value, dict) else None
        if sid not in self.sketch_defs:
            raise NotImplementedError("profile kind " + prof["kind"])
        sk, geo_of, edge_of, normal = self.build_sketch(sid, self.sketch_label(sid))
        regions = value.get("regions") or []
        notes = {}
        if any(r.get("region") == "trimmed" for r in regions):
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
            offset = self.plane_offset(start.get("face", {}), origin, normal)
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
            return a.Shape.distToShape(b.Shape)[0] < 1e-7
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
    def find_edge(self, eg):
        """(body object, 1-based edge index) of the current edge matching recorded geometry."""
        pts = [vec(eg[k]) for k in ("interior", "start", "end") if eg.get(k)]
        for s in self.solids:
            for i, e in enumerate(s.Shape.Edges):
                if all(e.distToShape(Part.Vertex(p))[0] < 1e-6 for p in pts):
                    ends = [v.Point for v in e.Vertexes]
                    if all(any((q - p).Length < 1e-6 for q in ends) for p in pts[1:]):
                        return s, i + 1
        return None, None

    def build_edge_treatment(self, feat, kind):
        d = feat["definition"]
        per_body = defaultdict(list)
        missing = 0
        for g in d.get("groups", []):
            e = g.get("edges", {})
            if e.get("kind") != "historical":
                raise NotImplementedError("edge selection " + str(e.get("kind")))
            if kind == "fillet":
                r = g.get("radius", {})
                if r.get("kind") != "constant":
                    raise NotImplementedError("fillet radius " + str(r.get("kind")))
                size = (r["radius"], r["radius"])
            else:
                spec = g.get("spec", {})
                if spec.get("kind") != "distance":
                    raise NotImplementedError("chamfer spec " + str(spec.get("kind")))
                size = (spec["distance"], spec["distance"])
            for eid in e["value"]["edges"]:
                eg = self.topo_geometry.get(eid)
                body, idx = self.find_edge(eg) if eg else (None, None)
                if body is None:
                    missing += 1
                    continue
                per_body[body].append((idx, size[0], size[1]))
        if missing:
            raise ValueError("%d selected edges not found in the rebuilt bodies" % missing)
        for body, edges in per_body.items():
            obj = self.doc.addObject("Part::Fillet" if kind == "fillet" else "Part::Chamfer", kind.capitalize())
            obj.Label = feat["name"]
            obj.Base = body
            obj.Edges = edges
            self.solids[self.solids.index(body)] = obj
        self.doc.recompute()
        return {"edges": sum(len(v) for v in per_body.values())}

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
                body, idx = self.find_edge(eg) if eg else (None, None)
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
                # Keep the part of the extension on its own side of the bisector plane.
                box = Part.makeBox(4 * size, 4 * size, 2 * size)
                box.Placement = App.Placement(p, App.Rotation(V(0, 0, 1), bis * sign))
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
            tube = [self.static(self.mitered_pipe(wire, c.Radius, name), name) for c in sections]
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
            try:
                if kind == "sketch":
                    rec["name"] = self.sketch_label(f["definition"]["sketch"]["sketch"], f["name"])
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
        return self.report

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
