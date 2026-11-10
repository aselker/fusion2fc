"""Rebuild a decoded Fusion design (cadmpeg CADIR, slimmed) as a FreeCAD document.

Run with FreeCAD's headless interpreter; arguments come from the environment
because freecadcmd treats extra command-line arguments as files to open:

  F2FC_SLIM=design.slim.json      # sketches, entities, constraints, features, parameters
  F2FC_TOPO=design.topo.json      # feature input topologies (edge geometry), optional
  F2FC_FEATURES=ids.json          # optional: JSON list of CADIR feature ids to build
  F2FC_OUT=design.FCStd
  F2FC_REPORT=report.json
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


class Rebuilder:
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
        self.report = {"features": [], "sketches": {}}

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
                wires = [loop_wire(r["outer_boundary"])] + [loop_wire(h) for h in r.get("holes", [])]
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

    def build_extrude(self, feat):
        d = feat["definition"]
        if not d.get("solid", True):
            raise NotImplementedError("surface extrude")
        prof = d["profile"]
        sid = prof.get("value", {}).get("sketch")
        if sid not in self.sketch_defs:
            raise NotImplementedError("profile kind " + prof["kind"])
        sk, geo_of, edge_of, normal = self.build_sketch(sid, self.sketch_label(sid))
        regions = prof.get("value", {}).get("regions") or []
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
            targets = [s for s in self.solids if self.touches(s, tool)]
            if not targets:
                self.solids += self.split_solids(tool, name)
                return {"op": op, "targets": 0}
            fuse = self.doc.addObject("Part::MultiFuse", "Join")
            fuse.Label = name + " join"
            fuse.Shapes = targets + [tool]
            fuse.Refine = True
            self.solids = [s for s in self.solids if s not in targets] + [fuse]
        elif op in ("cut", "intersect"):
            pool = participants if participants else self.solids
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

    # ----- driver ---------------------------------------------------------
    def sketch_label(self, sid):
        for f in self.slim["features"]:
            sk = f["definition"].get("sketch")
            if isinstance(sk, dict) and sk.get("sketch") == sid:
                return f["name"]
        return sid.rsplit("@", 1)[-1]

    def run(self):
        feats = sorted(self.slim["features"], key=lambda f: f["ordinal"])
        if self.wanted is not None:
            feats = [f for f in feats if f["id"] in self.wanted]
        for f in feats:
            kind = f["definition"].get("definition", "native")
            rec = {"name": f["name"], "kind": kind}
            try:
                if f.get("suppressed"):
                    rec["status"] = "suppressed"
                elif kind == "sketch":
                    ref = f["definition"]["sketch"]
                    if ref.get("space") != "planar":
                        raise NotImplementedError("non-planar sketch")
                    self.build_sketch(ref["sketch"], f["name"])
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
                else:
                    raise NotImplementedError("feature kind " + kind)
            except NotImplementedError as e:
                rec["status"], rec["reason"] = "skipped", str(e)
            except Exception as e:
                rec["status"], rec["reason"] = "failed", "%s: %s" % (type(e).__name__, e)
                rec["trace"] = traceback.format_exc()[-800:]
            rec["volumes"] = sorted((o.Shape.Volume for o in self.solids), reverse=True)
            self.report["features"].append(rec)
        self.doc.recompute()
        bodies = []
        for s in self.solids:
            shp = s.Shape
            bb = shp.BoundBox
            bodies.append({"object": s.Name, "label": s.Label, "valid": shp.isValid(),
                           "volume": shp.Volume, "area": shp.Area,
                           "solids": len(shp.Solids),
                           "centroid": list(shp.Solids[0].CenterOfMass) if len(shp.Solids) == 1 else None,
                           "bbox": [[bb.XMin, bb.YMin, bb.ZMin], [bb.XMax, bb.YMax, bb.ZMax]]})
        self.report["bodies"] = bodies
        return self.report


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
