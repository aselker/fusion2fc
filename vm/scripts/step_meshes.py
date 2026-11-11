"""Fusion-side (run via `mcp_call.py script ... --include vm/scripts/dump_features.py`):
open one .f3d in a new document, and after every timeline item record each world body's
exact properties and a triangle mesh. Closes the document without saving.

Substitutions (mcp_call.py KEY=VALUE, each replacing the double-underscored KEY):
  IN      .f3d to open (guest path)
  OUTDIR  output folder (created); gets features.json (first call), steps_<START>.json,
              mesh_<NNNN>.stl.gz
  DEV     mesh surface deviation in mm, or "auto" (2e-4 of the final bounding-box
              diagonal, clamped to [0.002, 0.05] mm)
  START   first timeline step to record (a call stops early when over budget and names
              the step to resume from in "next")
  BUDGET  seconds per call

Meshes are binary STL, in mm, in world coordinates, every body of the step in one file;
each step's JSON body record gives its triangle range. A step whose bodies are unchanged
(same names, volumes, areas, centroids) reuses the previous step's mesh file.
"""
import adsk.core, adsk.fusion, gzip, json, math, os, struct, time, traceback

IN = r"__IN__"
OUTDIR = r"__OUTDIR__"
DEV = r"__DEV__"
START = int(r"__START__")
BUDGET = float(r"__BUDGET__")
HIGH = adsk.fusion.CalculationAccuracy.HighCalculationAccuracy


def body_list(design):
    """(body as placed in the root, native body, occurrence row-major 4x4 or None, path)."""
    root = design.rootComponent
    out = [(b, b, None, None) for b in root.bRepBodies]
    for occ in root.allOccurrences:
        m = list(occ.transform2.asArray())
        for b in occ.bRepBodies:
            out.append((b, b.nativeObject or b, m, occ.fullPathName))
    return out


def props(b):
    pp = b.getPhysicalProperties(HIGH)
    c = pp.centerOfMass
    bb = b.boundingBox
    return {"volume": pp.volume * 1000.0, "area": pp.area * 100.0,
            "centroid": [c.x * 10.0, c.y * 10.0, c.z * 10.0] if c else None,
            "bbox": [[bb.minPoint.x * 10, bb.minPoint.y * 10, bb.minPoint.z * 10],
                     [bb.maxPoint.x * 10, bb.maxPoint.y * 10, bb.maxPoint.z * 10]]}


def apply(m, xyz, transpose=False):
    """Occurrence matrix (translation in cm) applied to a point in mm."""
    x, y, z = xyz
    if transpose:
        return [m[0] * x + m[4] * y + m[8] * z + 10 * m[12], m[1] * x + m[5] * y + m[9] * z + 10 * m[13],
                m[2] * x + m[6] * y + m[10] * z + 10 * m[14]]
    return [m[0] * x + m[1] * y + m[2] * z + 10 * m[3], m[4] * x + m[5] * y + m[6] * z + 10 * m[7],
            m[8] * x + m[9] * y + m[10] * z + 10 * m[11]]


def mesh_body(native, m, dev_cm):
    mc = native.meshManager.createMeshCalculator()
    mc.surfaceTolerance = dev_cm
    tm = mc.calculate()
    c = tm.nodeCoordinatesAsDouble
    pts = [[c[i] * 10.0, c[i + 1] * 10.0, c[i + 2] * 10.0] for i in range(0, len(c), 3)]
    idx = list(tm.nodeIndices)
    tris = [(idx[i], idx[i + 1], idx[i + 2]) for i in range(0, len(idx), 3)]
    return pts, tris


def mesh_centroid(pts, tris):
    """Volume centroid of a closed mesh (divergence theorem); None if volume ~ 0."""
    v6, cx, cy, cz = 0.0, 0.0, 0.0, 0.0
    for a, b, c in tris:
        p, q, r = pts[a], pts[b], pts[c]
        d = (p[0] * (q[1] * r[2] - q[2] * r[1]) - p[1] * (q[0] * r[2] - q[2] * r[0])
             + p[2] * (q[0] * r[1] - q[1] * r[0]))
        v6 += d
        cx += d * (p[0] + q[0] + r[0])
        cy += d * (p[1] + q[1] + r[1])
        cz += d * (p[2] + q[2] + r[2])
    if abs(v6) < 1e-12:
        return None
    return [cx / (4 * v6), cy / (4 * v6), cz / (4 * v6)]


def placed(pts, tris, m, centroid, dev):
    """World-space points; checks the matrix layout against the exact centroid."""
    if m is None:
        return pts, None
    best = None
    for transpose in (False, True):
        w = [apply(m, p, transpose) for p in pts]
        if centroid is None:
            return w, None
        mc = mesh_centroid(w, tris)
        err = math.dist(mc, centroid) if mc else None
        if best is None or (err is not None and (best[1] is None or err < best[1])):
            best = (w, err, transpose)
        if err is not None and err <= 10 * dev + 1e-6:
            break
    return best[0], {"centroid_error": best[1], "transposed": best[2]}



def write_stl(path, chunks):
    tri_count = sum(len(t) for _, t in chunks)
    buf = bytearray(84 + 50 * tri_count)
    buf[0:80] = b"fusion2fc step mesh (mm, world)".ljust(80, b" ")
    struct.pack_into("<I", buf, 80, tri_count)
    off = 84
    for pts, tris in chunks:
        for a, b, c in tris:
            p, q, r = pts[a], pts[b], pts[c]
            ux, uy, uz = q[0] - p[0], q[1] - p[1], q[2] - p[2]
            vx, vy, vz = r[0] - p[0], r[1] - p[1], r[2] - p[2]
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            n = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            struct.pack_into("<12fH", buf, off, nx / n, ny / n, nz / n, *p, *q, *r, 0)
            off += 50
    with gzip.open(path, "wb", compresslevel=6) as f:
        f.write(buf)


def step_record(design, it, idx, group):
    ent = None
    try:
        ent = it.entity
    except Exception:
        pass
    rec = {"index": idx, "name": it.name, "group": group,
           "type": safe(lambda: ent.objectType.split("::")[-1], None) if ent else None,
           "suppressed": safe(lambda: it.isSuppressed, None),
           "health": safe(lambda: int(it.healthState), None),
           "message": safe(lambda: it.errorOrWarningMessage or None, None),
           "component": safe(lambda: ent.parentComponent.name, None) if ent else None}
    return rec


def capture(design, dev):
    bodies, chunks, tri0 = [], [], 0
    for b, native, m, path in body_list(design):
        d = {"name": b.name, "component": safe(lambda: native.parentComponent.name, None),
             "occurrence": path, "solid": b.isSolid,
             "visible": safe(lambda: b.isLightBulbOn and b.isVisible, None)}
        d.update(props(b))
        try:
            pts, tris = mesh_body(native, m, dev / 10.0)
            pts, check = placed(pts, tris, m, d["centroid"] if b.isSolid else None, dev)
            if check:
                d["placement_check"] = check
            d["tri"] = [tri0, len(tris)]
            tri0 += len(tris)
            chunks.append((pts, tris))
        except Exception as e:
            d["mesh_error"] = str(e).splitlines()[0][:200]
        bodies.append(d)
    return bodies, chunks


def signature(bodies):
    return [(d["occurrence"], d["component"], d["name"], round(d["volume"], 6), round(d["area"], 6),
             [round(x, 6) for x in (d["centroid"] or [])]) for d in bodies]


def run(_context: str):
    t0 = time.time()
    app = adsk.core.Application.get()
    os.makedirs(OUTDIR, exist_ok=True)
    doc = app.importManager.importToNewDocument(app.importManager.createFusionArchiveImportOptions(IN))
    if doc is None:
        raise RuntimeError("Fusion did not open " + IN)
    try:
        design = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
        if design is None:
            raise RuntimeError("no design product in " + IN)
        tl = design.timeline
        info = {"source": os.path.basename(IN), "fusion": app.version,
                "designType": int(design.designType), "start": START,
                "marker": safe(lambda: tl.markerPosition, None)}
        if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
            info["error"] = "direct-modeling design (no timeline)"
            final, _ = capture(design, 0.01)
            info["final"] = final
            json.dump(info, open(os.path.join(OUTDIR, "steps_%d.json" % START), "w"), indent=0)
            print("no timeline")
            return
        for g in [g for g in tl.timelineGroups if g.isCollapsed]:
            g.isCollapsed = False
        flat = []
        for i in range(tl.count):
            it = tl.item(i)
            if not it.isGroup:
                flat.append((it, safe(lambda: it.parentGroup.name if it.parentGroup else None, None)))
        if DEV == "auto":
            tl.moveToEnd()
            lo, hi = [1e30] * 3, [-1e30] * 3
            for b, _, _, _ in body_list(design):
                bb = b.boundingBox
                for k, v in enumerate((bb.minPoint.x, bb.minPoint.y, bb.minPoint.z)):
                    lo[k] = min(lo[k], v * 10)
                for k, v in enumerate((bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z)):
                    hi[k] = max(hi[k], v * 10)
            diag = math.dist(lo, hi) if lo[0] < 1e29 else 10.0
            dev = min(max(2e-4 * diag, 0.002), 0.05)
            info["diag"] = diag
        else:
            dev = float(DEV)
        info["deviation_mm"] = dev
        info["steps_total"] = len(flat)
        if START == 0:
            try:
                feats = dump_design(design, roll=False, steps=False)
                json.dump(feats, open(os.path.join(OUTDIR, "features.json"), "w", encoding="utf-8"),
                          ensure_ascii=False)
            except Exception:
                info["features_error"] = traceback.format_exc()[-400:]
        steps, prev_sig, prev_mesh = [], None, None
        info["next"] = None
        for idx in range(START, len(flat)):
            if time.time() - t0 > BUDGET and steps:
                info["next"] = idx
                break
            it, group = flat[idx]
            ts = time.time()
            rec = step_record(design, it, idx, group)
            try:
                it.rollTo(False)
                bodies, chunks = capture(design, dev)
                sig = signature(bodies)
                if sig == prev_sig and prev_mesh:
                    rec["mesh"] = prev_mesh
                    for d, p in zip(bodies, steps[-1]["bodies"]):
                        if "tri" in p:
                            d["tri"] = p["tri"]
                elif chunks:
                    name = "mesh_%04d.stl.gz" % idx
                    write_stl(os.path.join(OUTDIR, name), chunks)
                    rec["mesh"] = name
                else:
                    rec["mesh"] = None
                rec["bodies"] = bodies
                prev_sig, prev_mesh = sig, rec["mesh"]
            except Exception:
                rec["error"] = traceback.format_exc()[-500:]
                prev_sig = prev_mesh = None
            rec["seconds"] = round(time.time() - ts, 2)
            steps.append(rec)
        info["steps"] = steps
        info["seconds"] = round(time.time() - t0, 1)
        with open(os.path.join(OUTDIR, "steps_%d.json" % START), "w", encoding="utf-8") as f:
            json.dump(info, f, indent=0, ensure_ascii=False)
        print("steps %d-%d of %d, dev %.4g mm, %.0f s, next %s" % (
            START, START + len(steps) - 1, len(flat), dev, info["seconds"], info["next"]))
    finally:
        doc.close(False)
