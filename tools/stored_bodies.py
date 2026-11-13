#!/usr/bin/env python3
"""Export the B-rep of bodies that Base Features store, one STEP file per body.

  stored_bodies.py MODEL.cadir.json OUTDIR [--cadmpeg PATH]

A Base Feature (an imported or direct-edited body, a body moved to a new component, a
pasted body) has no replayable construction: the design stores its result body, which
cadmpeg decodes into the CADIR geometry arenas. For each such body this writes a CADIR
holding only that body's topology and geometry, converts it with `cadmpeg convert` to
OUTDIR/body_NNN.step, and lists the files in OUTDIR/index.json (body id -> file name).
fusion2fc/rebuild.py reads the index from F2FC_BODIES.

The CADIR holds the bodies of the final design. A stored body equals the Base Feature's
own result only while no later feature modifies it; the rebuilder checks that.
"""
import json
import subprocess
import sys
from pathlib import Path

GEOMETRY = ("bodies", "regions", "shells", "faces", "loops", "coedges", "edges", "vertices", "points",
            "surfaces", "curves", "subds", "pcurves", "procedural_surfaces", "procedural_curves")


def stored_body_ids(model):
    ids = []
    for f in model.get("features", []):
        d = f.get("definition") or {}
        if d.get("definition") != "base_feature":
            continue
        sel = d.get("bodies") or {}
        if sel.get("kind") == "resolved":
            ids += [b for b in sel["value"]["bodies"] if b not in ids]
    return ids


def body_cadir(cadir, body):
    """The CADIR restricted to one body and every geometry record it reaches."""
    m = cadir["model"]
    index = {r["id"]: (a, r) for a in GEOMETRY for r in m.get(a, [])}

    def refs(o):
        if isinstance(o, str):
            if o in index:
                yield o
        elif isinstance(o, dict):
            for v in o.values():
                yield from refs(v)
        elif isinstance(o, list):
            for v in o:
                yield from refs(v)

    keep, stack = set(), [body]
    while stack:
        i = stack.pop()
        if i in keep:
            continue
        keep.add(i)
        _, rec = index[i]
        for j in refs({k: v for k, v in rec.items() if k != "id"}):
            # Back references (a region names its body) must not reach other bodies.
            if j not in keep and (index[j][0] != "bodies" or j == body):
                stack.append(j)
    model = {k: ([] if isinstance(v, list) else v) for k, v in m.items()}
    for a in GEOMETRY:
        model[a] = [r for r in m.get(a, []) if r["id"] in keep]
    out = dict(cadir, model=model)
    out["native"] = {}
    return out


def final_body_ids(model):
    """Every solid body of the final design (the shape Fusion stores)."""
    return [b["id"] for b in model.get("bodies", []) if b.get("kind") == "solid"]


def export(cadir, outdir, cadmpeg, ids=None):
    """Export `ids` (default: the Base Feature bodies) to OUTDIR/body_NNN.step."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    index, kinds = {}, {b["id"]: b.get("kind") for b in cadir["model"].get("bodies", [])}
    owner = {b: pd["id"] for pd in cadir["model"].get("product_definitions", []) for b in pd.get("bodies") or []}
    for n, body in enumerate(stored_body_ids(cadir["model"]) if ids is None else ids):
        if body not in kinds:
            continue
        sub, step = outdir / ("body_%03d.cadir.json" % n), outdir / ("body_%03d.step" % n)
        json.dump(body_cadir(cadir, body), open(sub, "w"))
        p = subprocess.run([str(cadmpeg), "convert", str(sub), "-o", str(step), "--force"],
                           capture_output=True, text=True, timeout=600)
        sub.unlink()
        if p.returncode == 0 and step.exists():
            index[body] = {"file": step.name, "kind": kinds[body], "component": owner.get(body)}
        else:
            index[body] = {"error": (p.stdout + p.stderr)[-400:], "kind": kinds[body]}
    json.dump(index, open(outdir / "index.json", "w"), indent=1)
    return index


def main(argv):
    args = argv[1:]
    cadmpeg = Path(__file__).resolve().parent.parent / "cadmpeg" / "target" / "release" / "cadmpeg"
    if "--cadmpeg" in args:
        i = args.index("--cadmpeg")
        cadmpeg = Path(args[i + 1])
        del args[i:i + 2]
    print(json.dumps(export(json.load(open(args[0])), args[1], cadmpeg), indent=1))


if __name__ == "__main__":
    main(sys.argv)
