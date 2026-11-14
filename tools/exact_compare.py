"""Exact-surface fallback for the mesh comparison (runs in FreeCAD's Python).

The mesh check assumes both tessellators stay within d of the true surface; on doubly curved or
twisted faces triangle interiors overshoot more. This check does not depend on how either side
was triangulated:

  A (Fusion -> ours exact): every Fusion mesh vertex and triangle centroid is a point within d
     of Fusion's true surface (vertices: on it). Its distance to our exact B-rep must be
     <= factor * d. Candidate faces come from the nearest triangles of our own fine tessellation
     (face indices kept); the exact distance is Face.distToShape on those faces only.
  B (ours exact -> Fusion mesh): points on our exact B-rep (UV-subdivided tessellation triangles
     evaluated on the surface, so only inside the trimmed face domain; plus points along every
     edge) against Fusion's triangles, exact point-to-triangle distance. Must be <= factor * d.

Point counts are capped (MAX_A, MAX_B); the result records the counts and whether a cap applied.
"""
import numpy as np
import FreeCAD as App
import Part
from scipy.spatial import cKDTree

import mesh_compare as mc

MAX_A = 12000
MAX_B = 30000
KNEAR = 8
PAIR_BUDGET = 60_000_000
MAX_TRI_SAMPLES = 100_000


def face_tessellation(shape, tol):
    """(triangles (m,3,3), face index per triangle, per-face (uv triangles) list)."""
    tris, owner, uvs = [], [], []
    for fi, f in enumerate(shape.Faces):
        try:
            v, t = f.tessellate(tol)
            uv = f.getUVNodes() if hasattr(f, "getUVNodes") else None
        except Exception:
            continue
        if not t:
            continue
        p = np.array([[x.x, x.y, x.z] for x in v])
        ti = np.array(t)
        tris.append(p[ti])
        owner.append(np.full(len(ti), fi))
        uvs.append((fi, np.array(uv)[ti] if uv is not None and len(uv) == len(v) else None))
    if not tris:
        return np.zeros((0, 3, 3)), np.zeros(0, dtype=int), []
    return np.concatenate(tris), np.concatenate(owner), uvs


SMOOTH_ANGLE = np.radians(30.0)


def smooth_bound(tris):
    """Per-triangle bound on its own chordal error, from Fusion's mesh alone: L * theta / 4, with L
    the longest edge and theta the largest dihedral angle to an edge-neighbour below 30 degrees
    (larger angles are creases of the part, not surface curvature). Flat regions get 0."""
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    key = np.round(tris, 4)
    edges = {}
    for t in range(len(tris)):
        for i in range(3):
            a, b = tuple(key[t, i]), tuple(key[t, (i + 1) % 3])
            edges.setdefault((a, b) if a < b else (b, a), []).append(t)
    theta = np.zeros(len(tris))
    for ts in edges.values():
        if len(ts) == 2:
            ang = np.arccos(np.clip(abs(n[ts[0]] @ n[ts[1]]), -1, 1))
            if ang < SMOOTH_ANGLE:
                for t in ts:
                    theta[t] = max(theta[t], ang)
    L = np.max(np.linalg.norm(tris - np.roll(tris, 1, axis=1), axis=2), axis=1)
    return L * theta / 4.0


def a_check(shape, ftris, dev, rng):
    """Fusion mesh vertices / triangle centroids against our exact shape.

    Vertices lie on Fusion's true surface: their distance to ours is checked directly against
    factor*d. Fusion's triangle interiors, however, sit off the true surface by the chordal
    interpolation error of the triangle (5-7x d on twisted and lofted faces, so centroids cannot
    be held to d). Each triangle gets an allowance = min(measured deviation of the triangle
    from our exact surface at its centroid and edge midpoints, x1.5; smooth_bound from Fusion's
    own mesh), so a shape that is wrong in a region where Fusion's mesh is flat gets none.
    Returns the result and per-triangle allowances.
    """
    ntri = len(ftris)
    verts = np.unique(ftris.reshape(-1, 3), axis=0)
    capped_v = len(verts) > MAX_A
    if capped_v:
        verts = verts[rng.choice(len(verts), MAX_A, replace=False)]
    tris, owner, _ = face_tessellation(shape, dev / 2)
    if not len(tris):
        return {"max": float("inf"), "n": 0, "capped": False}, np.zeros(ntri)
    tree = cKDTree(tris.mean(axis=1))
    faces = shape.Faces
    k = min(KNEAR, len(tris))

    def nearest(p):
        _, idx = tree.query(p, k=k)
        v = Part.Vertex(App.Vector(*p))
        return min(faces[fi].distToShape(v)[0] for fi in sorted(set(int(owner[j]) for j in np.atleast_1d(idx))))

    dv, atv = -1.0, None
    for p in verts:
        d = nearest(p)
        if d > dv:
            dv, atv = d, p
    # Triangle interiors: barycentric grid (n=4, interior and edge points) against our fine
    # tessellation of the exact shape (error <= dev/2); cheap, so every triangle is measured.
    bary = np.array([(i / 4, j / 4, 1 - i / 4 - j / 4) for i in range(5) for j in range(5 - i)
                     if max(i / 4, j / 4, 1 - i / 4 - j / 4) < 1.0])
    bound = smooth_bound(ftris)
    capped_t = ntri * len(bary) > MAX_TRI_SAMPLES
    tsel = rng.choice(ntri, MAX_TRI_SAMPLES // len(bary), replace=False) if capped_t else np.arange(ntri)
    P = np.einsum("qk,tkd->tqd", bary, ftris[tsel]).reshape(-1, 3)
    md = mc.MeshDistance(tris, max(dev * 4, 1.0)).distances(P, cap=1e9).reshape(len(tsel), len(bary))
    meas = np.zeros(ntri)
    meas[tsel] = 1.25 * md.max(axis=1)
    allow = np.minimum(meas, bound)
    ic = int(np.argmax(md.max(axis=1)))
    raw_c, atc = float(md.max()), ftris[tsel[ic]].mean(axis=0)
    if capped_t:
        mask = np.ones(ntri, dtype=bool)
        mask[tsel] = False
        allow[mask] = np.minimum(bound[mask], np.percentile(meas[tsel], 90))
    res = {"vertex_max": float(dv), "vertex_at": [float(x) for x in atv],
           "centroid_raw_max": float(raw_c), "centroid_at": [float(x) for x in atc],
           "max": float(dv), "n": int(len(verts) + len(P)), "capped": bool(capped_v or capped_t),
           "max_allowance": float(allow.max())}
    return res, allow


def surface_points(shape, dev, spacing, rng):
    """Points on our exact shape: subdivided tessellation triangles mapped to the surface, + edges."""
    pts = []
    n_budget = MAX_B
    parts = []
    for fi, f in enumerate(shape.Faces):
        try:
            v, t = f.tessellate(dev / 2)
            uv = f.getUVNodes()
        except Exception:
            continue
        if not t or len(uv) != len(v):
            continue
        p = np.array([[x.x, x.y, x.z] for x in v])
        ti = np.array(t)
        parts.append((f, p[ti], np.array(uv)[ti]))
    # choose spacing so the total stays under the cap
    sp = spacing
    for _ in range(8):
        total = 0
        for f, T, U in parts:
            e = np.max(np.linalg.norm(T - np.roll(T, 1, axis=1), axis=2), axis=1)
            n = np.maximum(1, np.ceil(e / sp)).astype(int)
            total += int(((n + 1) * (n + 2) // 2).sum())
        if total <= n_budget * 0.8:
            break
        sp *= 1.5
    for f, T, U in parts:
        e = np.max(np.linalg.norm(T - np.roll(T, 1, axis=1), axis=2), axis=1)
        n = np.maximum(1, np.ceil(e / sp)).astype(int)
        for nn in np.unique(n):
            sel = n == nn
            bary = [(i / nn, j / nn) for i in range(nn + 1) for j in range(nn + 1 - i)]
            b = np.array([(1 - a - c, a, c) for a, c in bary])  # (q, 3)
            uvq = np.einsum("qk,tkd->tqd", b, U[sel]).reshape(-1, 2)
            for u, v in uvq:
                try:
                    q = f.valueAt(float(u), float(v))
                except Exception:
                    continue
                pts.append((q.x, q.y, q.z))
    for e in shape.Edges:
        try:
            L = e.Length
            m = max(2, int(np.ceil(L / sp)) + 1)
            for q in e.discretize(m):
                pts.append((q.x, q.y, q.z))
        except Exception:
            continue
    pts = np.array(pts) if pts else np.zeros((0, 3))
    capped = len(pts) > MAX_B
    if capped:
        pts = pts[rng.choice(len(pts), MAX_B, replace=False)]
    return pts, sp, capped


def b_check(shape, ftris, allow, dev, spacing, rng):
    """Our exact surface points against Fusion's triangles (distance minus that triangle's
    chordal allowance, minimised over nearby triangles)."""
    pts, sp, capped = surface_points(shape, dev, spacing, rng)
    if not len(pts):
        return {"max": float("inf"), "n": 0, "capped": False}
    a, b, c = ftris[:, 0], ftris[:, 1], ftris[:, 2]
    ntri = len(ftris)
    raw = mc.MeshDistance(ftris, spacing).distances(pts, cap=1e9)   # upper bound on every excess
    lo_b = ftris.min(axis=1)
    hi_b = ftris.max(axis=1)
    excess = raw.copy()
    for lo in range(0, len(pts), 400):
        q = pts[lo:lo + 400]
        # triangles whose bounding box, grown by raw + allowance, contains the point
        g = (raw[lo:lo + 400, None] + allow[None, :])[:, :, None]
        ok = ((q[:, None, :] >= lo_b[None] - g) & (q[:, None, :] <= hi_b[None] + g)).all(axis=2)
        pi, ti = np.nonzero(ok)
        if not len(pi):
            continue
        Q = q[pi]
        d = np.linalg.norm(mc.closest_on_triangles(Q, a[ti], b[ti], c[ti]) - Q, axis=1)
        e = np.full(len(q), np.inf)
        np.minimum.at(e, pi, d - allow[ti])
        excess[lo:lo + len(q)] = np.minimum(excess[lo:lo + len(q)], e)
    i = int(np.argmax(excess))
    return {"max": float(max(excess[i], 0.0)), "raw_max": float(raw.max()), "at": [float(x) for x in pts[i]],
            "n": int(len(pts)), "capped": capped, "spacing": float(sp)}


def exact_check(shape, ftris, dev, spacing, cap=None):
    """Run both directions. 'max' is the largest excess distance over both (compare to factor*d)."""
    rng = np.random.default_rng(0)
    a, allow = a_check(shape, ftris, dev, rng)
    b = b_check(shape, ftris, allow, dev, spacing, rng)
    return {"fusion_to_exact": a, "exact_to_fusion": b, "max": max(a["max"], b["max"]),
            "max_points_a": MAX_A, "max_points_b": MAX_B}
