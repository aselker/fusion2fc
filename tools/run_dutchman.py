#!/usr/bin/env python3
"""Convert every corpus model with `dutchman convert --to fcstd --json` (copies of the inputs).

usage: run_dutchman.py [--out tests/out/dutchman] [-j 3] [ID ...]
Writes <out>/in/<id>.<ext> (copy), <out>/fcstd/<id>.FCStd, <out>/json/<id>.json,
<out>/log/<id>.err and <out>/runs.json (status, runtime).  Only `convert` is used.
"""
import argparse, json, os, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.environ.get("DUTCHMAN_BIN", "dutchman")
SC = os.environ.get("SOLIDCRAFT_CLI", "solidcraft-cli")
MODE = "fcstd"

def run_sc(e, out):
    """Dutchman -> SolidCraft (.sc) with --solidcraft verification, then solidcraft-cli run -> STEP."""
    mid = e["id"]; src = os.path.join(ROOT, "tests/corpus", e["file"]); ext = os.path.splitext(src)[1]
    cp = os.path.join(out, "in", mid + ext); sc = os.path.join(out, "sc", mid + ".sc"); step = os.path.join(out, "scstep", mid + ".step")
    shutil.copyfile(src, cp)
    for f in (sc, step):
        if os.path.exists(f): os.remove(f)
    t = time.time(); r = {"id": mid}
    def go(cmd, to):
        try:
            p = subprocess.run(["nice"] + cmd, capture_output=True, text=True, timeout=to, stdin=subprocess.DEVNULL)
            return p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as x:
            return "timeout", "", ""
    rc, so, se = go([BIN, "convert", cp, "--to", "solidcraft", "-o", sc, "--json", "--quiet", "--yes", "--solidcraft", SC], 900)
    open(os.path.join(out, "scjson", mid + ".json"), "w").write(so); open(os.path.join(out, "log", mid + ".sc.err"), "w").write(se)
    r.update(exit=rc, seconds=round(time.time() - t, 1), sc=os.path.exists(sc))
    if os.path.exists(sc):
        t2 = time.time()
        rc2, so2, se2 = go([SC, "run", "--in", sc, "--out", step, "--quiet"], 600)
        open(os.path.join(out, "log", mid + ".run.err"), "w").write((so2 or "")[-2000:] + (se2 or "")[-4000:])
        r.update(run_exit=rc2, run_seconds=round(time.time() - t2, 1), step=os.path.exists(step))
    return r

def run(e, out):
    if MODE == "sc":
        return run_sc(e, out)
    mid = e["id"]; src = os.path.join(ROOT, "tests/corpus", e["file"])
    ext = os.path.splitext(src)[1]
    cp = os.path.join(out, "in", mid + ext); dst = os.path.join(out, "fcstd", mid + ".FCStd")
    shutil.copyfile(src, cp)
    if os.path.exists(dst): os.remove(dst)
    t = time.time(); status = None
    try:
        p = subprocess.run(["nice", BIN, "convert", cp, "--to", "fcstd", "-o", dst, "--json", "--quiet",
                            "--yes", "--freecad-timeout", "300"], capture_output=True, text=True,
                           timeout=900, stdin=subprocess.DEVNULL)
        status = p.returncode; so, se = p.stdout, p.stderr
    except subprocess.TimeoutExpired as x:
        status = "timeout"; so = (x.stdout or b"").decode() if isinstance(x.stdout, bytes) else (x.stdout or ""); se = ""
    dt = time.time() - t
    open(os.path.join(out, "json", mid + ".json"), "w").write(so)
    open(os.path.join(out, "log", mid + ".err"), "w").write(se)
    return {"id": mid, "exit": status, "seconds": round(dt, 1), "fcstd": os.path.exists(dst)}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("ids", nargs="*")
    ap.add_argument("--mode", default="fcstd", choices=["fcstd", "sc"]); ap.add_argument("--out", default=os.path.join(ROOT, "tests/out/dutchman")); ap.add_argument("-j", type=int, default=3)
    a = ap.parse_args()
    global MODE; MODE = a.mode
    for d in ("in", "fcstd", "json", "log", "sc", "scjson", "scstep"): os.makedirs(os.path.join(a.out, d), exist_ok=True)
    man = json.load(open(os.path.join(ROOT, "tests/corpus/manifest.json")))
    if a.ids: man = [e for e in man if e["id"] in a.ids]
    rp = os.path.join(a.out, "runs.json" if a.mode == "fcstd" else "runs_sc.json")
    runs = {r["id"]: r for r in json.load(open(rp))} if os.path.exists(rp) else {}
    man = [e for e in man if e["id"] not in runs]
    with ThreadPoolExecutor(a.j) as ex:
        for r in ex.map(lambda e: run(e, a.out), man):
            runs[r["id"]] = r; print(r, flush=True)
            json.dump(list(runs.values()), open(rp, "w"))
main()
