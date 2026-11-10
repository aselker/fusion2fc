#!/usr/bin/env python3
"""Run the f3d -> CADIR -> FreeCAD pipeline on every test case and compare with Fusion.

  run_cases.py [CASE ...] [--cadmpeg PATH] [--out DIR] [-v]

Each tests/cases/<case>.f3d has a <case>.truth.json written by vm/scripts/make_cases.py
(Fusion API ground truth: feature definitions, final world bodies, and body volumes
after every timeline item). For each case this runs `cadmpeg dump`, slims the CADIR,
rebuilds it with fusion2fc/rebuild.py under freecadcmd, and reports:
  decode  - cadmpeg exit status and feature count vs Fusion
  built   - rebuild feature statuses
  steps   - first timeline step whose volumes differ (rel. tol 1e-6)
  final   - final body volumes match
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "tests" / "cases"
DEFAULT_CADMPEG = ROOT / "cadmpeg" / "target" / "release" / "cadmpeg"
TOL = 1e-6


def slim(cadir):
    m = cadir["model"]
    keep = ("features", "sketches", "sketch_entities", "sketch_constraints", "parameters", "spatial_sketches")
    s = {k: m.get(k, []) for k in keep}
    s["bodies"] = [{"id": b.get("id"), "name": b.get("name")} for b in m.get("bodies", [])]
    topo = [{"id": t["id"], "input_of": t.get("input_of"), "edge_geometry": t.get("edge_geometry")}
            for t in m.get("feature_input_topologies", [])]
    return s, topo


def vols_match(a, b):
    a, b = sorted(a, reverse=True), sorted(b, reverse=True)
    return len(a) == len(b) and all(abs(x - y) <= TOL * max(1.0, abs(x), abs(y)) for x, y in zip(a, b))


def fmt(vs):
    return "[" + ", ".join("%.4g" % v for v in sorted(vs, reverse=True)) + "]"


def run_case(name, cadmpeg, out, verbose):
    f3d, truth_path = CASES / (name + ".f3d"), CASES / (name + ".truth.json")
    truth = json.load(open(truth_path))
    work = out / name
    work.mkdir(parents=True, exist_ok=True)
    res = {"case": name}
    cadir_path = work / "model.cadir.json"
    p = subprocess.run([str(cadmpeg), "dump", str(f3d), "-o", str(cadir_path), "--force"],
                       capture_output=True, text=True, timeout=600)
    (work / "dump.log").write_text(p.stdout + p.stderr)
    if p.returncode != 0 or not cadir_path.exists():
        res["decode"] = "FAILED (exit %d)" % p.returncode
        return res
    s, topo = slim(json.load(open(cadir_path)))
    json.dump(s, open(work / "slim.json", "w"))
    json.dump(topo, open(work / "topo.json", "w"))
    fus_items = [r for r in truth["timeline"] if r["type"] != "Occurrence"]
    res["decode"] = "ok %d/%d feats" % (len(s["features"]), len(fus_items))

    env = dict(os.environ, F2FC_SLIM=str(work / "slim.json"), F2FC_TOPO=str(work / "topo.json"),
               F2FC_OUT=str(work / "rebuilt.FCStd"), F2FC_REPORT=str(work / "report.json"))
    env.pop("F2FC_FEATURES", None)
    p = subprocess.run(["freecadcmd", str(ROOT / "fusion2fc" / "rebuild.py")], env=env,
                       capture_output=True, text=True, timeout=600)
    (work / "rebuild.log").write_text(p.stdout + p.stderr)
    if not (work / "report.json").exists():
        res["built"] = "REBUILD CRASHED"
        return res
    rep = json.load(open(work / "report.json"))
    st = {}
    for r in rep["features"]:
        st[r["status"]] = st.get(r["status"], 0) + 1
    res["built"] = " ".join("%s=%d" % kv for kv in sorted(st.items()))
    res["problems"] = ["%s: %s %s" % (r["name"], r["status"], r.get("reason", "")) for r in rep["features"] if r["status"] != "built"]

    # Step comparison: CADIR features in ordinal order vs Fusion non-occurrence items.
    steps_c = [r.get("volumes", []) for r in rep["features"]]
    steps_f = [[b["volume"] * 1000.0 for b in r.get("after", [])] for r in fus_items]
    res["steps"] = "ok"
    for i, (a, b) in enumerate(zip(steps_c, steps_f)):
        if not vols_match(a, b):
            res["steps"] = "#%d %s: fusion %s rebuilt %s" % (i, fus_items[i]["name"], fmt(b), fmt(a))
            break
    if len(steps_c) != len(steps_f):
        res["steps"] += " (step count %d vs %d)" % (len(steps_c), len(steps_f))
    want = [b["volume"] * 1000.0 for b in truth["worldBodies"]]
    got = [b["volume"] for b in rep["bodies"]]
    res["final"] = "MATCH" if vols_match(want, got) else "fusion %s rebuilt %s" % (fmt(want), fmt(got))
    return res


def main(argv):
    args = [a for a in argv[1:]]
    verbose = "-v" in args
    cadmpeg = Path(args[args.index("--cadmpeg") + 1]) if "--cadmpeg" in args else DEFAULT_CADMPEG
    out = Path(args[args.index("--out") + 1]) if "--out" in args else ROOT / "tests" / "out"
    skip = {a for i, a in enumerate(args) if i > 0 and args[i - 1] in ("--cadmpeg", "--out")}
    names = [a for a in args if not a.startswith("-") and a not in skip] or \
        sorted(p.stem for p in CASES.glob("*.f3d"))
    n_ok = 0
    for name in names:
        r = run_case(name, cadmpeg, out, verbose)
        ok = r.get("final") == "MATCH" and r.get("steps") == "ok"
        n_ok += ok
        print("%-27s %-4s decode: %-14s built: %-22s final: %s" % (
            name, "PASS" if ok else "FAIL", r.get("decode", ""), r.get("built", ""), r.get("final", "")))
        if not ok or verbose:
            if r.get("steps") not in (None, "ok"):
                print("      first divergence %s" % r["steps"])
            for prob in r.get("problems", []):
                print("      " + prob)
    print("\n%d/%d cases pass" % (n_ok, len(names)))


if __name__ == "__main__":
    main(sys.argv)
