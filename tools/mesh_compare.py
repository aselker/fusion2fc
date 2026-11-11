"""Two-sided distance between triangle meshes (numpy + scipy; runs in FreeCAD's Python).

Each mesh is sampled at its vertices and at the centroids of its triangles after
subdividing them to edges no longer than `spacing`. A sample's distance to the other
mesh is the exact point-to-triangle distance, found among the triangles whose
(subdivided) centroids lie within reach of the nearest one. Distances above `cap` are
reported as an upper bound only.

If both meshes tessellate the same exact surface with deviations d1 and d2, a vertex of
one lies within d_other of the other mesh and a triangle centroid within d1 + d2, so
`hausdorff <= d1 + d2` (up to tessellator overshoot) is the match criterion.
"""
import gzip
import struct

import numpy as np
from scipy.spatial import cKDTree


def read_stl(path):
    """Binary STL (optionally .gz) -> triangles (m, 3, 3) float64."""
    data = (gzip.open if str(path).endswith(".gz") else open)(path, "rb").read()
    (n,) = struct.unpack_from("<I", data, 80)
    rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]),
                        count=n, offset=84)
    return rec["v"].astype(np.float64)


def write_stl(path, tris):
    tris = np.asarray(tris, dtype=np.float32)
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    rec = np.zeros(len(tris), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["n"], rec["v"] = n, tris
    with (gzip.open if str(path).endswith(".gz") else open)(path, "wb") as f:
        f.write(b"fusion2fc".ljust(80, b" ") + struct.pack("<I", len(tris)) + rec.tobytes())


def shape_triangles(shape, deviation, angular=0.5):
    """Tessellate a FreeCAD shape (linear deflection `deviation`, absolute) -> (m, 3, 3)."""
    import MeshPart

    if not shape.Faces:
        return np.zeros((0, 3, 3))
    mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=deviation,
                                  AngularDeflection=angular, Relative=False)
    pts, facets = mesh.Topology
    if not facets:
        return np.zeros((0, 3, 3))
    p = np.array([[v.x, v.y, v.z] for v in pts])
    return p[np.array(facets)]


def subdivide(tris, spacing, max_tris=3_000_000):
    """Split triangles at their longest edge until every edge is <= spacing."""
    tris = np.asarray(tris, dtype=np.float64)
    if len(tris) == 0:
        return tris
    area = 0.5 * np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1).sum()
    spacing = max(spacing, np.sqrt(4.0 * area / max_tris))
    done = []
    while len(tris):
        e = np.stack([np.linalg.norm(tris[:, 1] - tris[:, 2], axis=1),
                      np.linalg.norm(tris[:, 2] - tris[:, 0], axis=1),
                      np.linalg.norm(tris[:, 0] - tris[:, 1], axis=1)], axis=1)
        k = e.argmax(axis=1)
        long = e[np.arange(len(tris)), k] > spacing
        done.append(tris[~long])
        t, k = tris[long], k[long]
        if not len(t):
            break
        # Rotate so the longest edge is (1, 2), opposite vertex 0.
        r = np.arange(len(t))[:, None]
        order = (np.arange(3)[None, :] + k[:, None]) % 3
        t = t[r, order]
        mid = 0.5 * (t[:, 1] + t[:, 2])
        a = np.stack([t[:, 0], t[:, 1], mid], axis=1)
        b = np.stack([t[:, 0], mid, t[:, 2]], axis=1)
        tris = np.concatenate([a, b])
    return np.concatenate(done)


def closest_on_triangles(p, a, b, c):
    """Closest points on triangles (a, b, c) to points p, all (n, 3) (Ericson 5.1.5)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = p - b
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = p - c
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    with np.errstate(divide="ignore", invalid="ignore"):
        denom = 1.0 / (va + vb + vc)
        v = vb * denom
        w = vc * denom
        out = a + ab * v[:, None] + ac * w[:, None]
        # Edge regions.
        m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        t = d1 / (d1 - d3)
        out = np.where(m[:, None], a + ab * t[:, None], out)
        m2 = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        t = d2 / (d2 - d6)
        out = np.where(m2[:, None], a + ac * t[:, None], out)
        m3 = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        out = np.where(m3[:, None], b + (c - b) * t[:, None], out)
    # Vertex regions (checked last so they win).
    out = np.where(((d3 >= 0) & (d4 <= d3))[:, None], b, out)
    out = np.where(((d6 >= 0) & (d5 <= d6))[:, None], c, out)
    out = np.where(((d1 <= 0) & (d2 <= 0))[:, None], a, out)
    # Degenerate triangles: fall back to the nearest vertex.
    bad = ~np.isfinite(out).all(1)
    if bad.any():
        cand = np.stack([a[bad], b[bad], c[bad]], 1)
        j = np.linalg.norm(cand - p[bad][:, None], axis=2).argmin(1)
        out[bad] = cand[np.arange(bad.sum()), j]
    return out


class MeshDistance:
    """Distance queries against one mesh."""

    def __init__(self, tris, spacing):
        self.tris = subdivide(tris, spacing)
        cent = self.tris.mean(axis=1)
        self.reach = float(np.linalg.norm(self.tris - cent[:, None], axis=2).max()) if len(cent) else 0.0
        self.tree = cKDTree(cent) if len(cent) else None

    def distances(self, pts, cap):
        pts = np.asarray(pts, dtype=np.float64)
        if self.tree is None:
            return np.full(len(pts), np.inf)
        _, j = self.tree.query(pts)
        t = self.tris[j]
        upper = np.linalg.norm(closest_on_triangles(pts, t[:, 0], t[:, 1], t[:, 2]) - pts, axis=1)
        out = upper.copy()
        near = np.nonzero(upper <= cap)[0]
        for lo in range(0, len(near), 20000):
            sel = near[lo:lo + 20000]
            lists = self.tree.query_ball_point(pts[sel], upper[sel] + self.reach)
            lens = np.fromiter((len(x) for x in lists), dtype=np.int64, count=len(lists))
            if not lens.sum():
                continue
            cand = np.fromiter((i for x in lists for i in x), dtype=np.int64, count=int(lens.sum()))
            owner = np.repeat(np.arange(len(sel)), lens)
            q = pts[sel][owner]
            t = self.tris[cand]
            d = np.linalg.norm(closest_on_triangles(q, t[:, 0], t[:, 1], t[:, 2]) - q, axis=1)
            best = np.full(len(sel), np.inf)
            np.minimum.at(best, owner, d)
            out[sel] = np.minimum(out[sel], best)
        return out


def samples(tris, spacing):
    """Vertices plus centroids of the subdivided triangles."""
    tris = np.asarray(tris, dtype=np.float64)
    if not len(tris):
        return np.zeros((0, 3))
    verts = np.unique(tris.reshape(-1, 3), axis=0)
    return np.concatenate([verts, subdivide(tris, spacing).mean(axis=1)])


def compare(tris_a, tris_b, spacing, cap):
    """One-sided maxima (a -> b, b -> a) and where they occur."""
    res = {}
    for key, src, dst in (("a_to_b", tris_a, tris_b), ("b_to_a", tris_b, tris_a)):
        if not len(src):
            res[key] = {"max": 0.0 if not len(dst) else None, "n": 0}
            continue
        if not len(dst):
            res[key] = {"max": float("inf"), "n": len(src)}
            continue
        pts = samples(src, spacing)
        d = MeshDistance(dst, spacing).distances(pts, cap)
        i = int(np.argmax(d))
        res[key] = {"max": float(d[i]), "at": [float(x) for x in pts[i]], "n": len(pts),
                    "p99": float(np.percentile(d, 99))}
    vals = [r["max"] for r in res.values() if r.get("max") is not None]
    res["hausdorff"] = max(vals) if vals else 0.0
    return res
