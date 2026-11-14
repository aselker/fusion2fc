#!/usr/bin/env python3
"""Profile areas of every corpus extrude vs Fusion truth.

  area_check.py OUTDIR [ID ...] [-j N] [--cadmpeg BIN] [--base OUTDIR2]

Decodes (cached by binary stamp), slims, runs tools/profile_areas.py, and compares the
profile area of each extrude with the sum of Fusion's selected profile areas. Feature
alignment comes from the coordinator's baseline result.json (names are unchanged).
"""
import json, os, subprocess, sys, hashlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
WT = Path("/home/neophile/Documents/Programming/Vibes/fusion/.worktrees/profiles")
sys.path.insert(0, str(WT / "tools"))
from slim_cadir import slim  # noqa
CORPUS = WT / "tests" / "corpus"
BASE = Path("/home/neophile/Documents/Programming/Vibes/fusion/tests/out/corpus")

def stamp(binp, model):
    st = binp.stat()
    return "%s %d %d %s" % (binp.resolve(), st.st_size, st.st_mtime_ns, hashlib.sha256(model.read_bytes()).hexdigest())

def fusion_areas(mid):
    rp, fp = BASE / mid / "result.json", CORPUS / "truth" / mid / "features.json"
    if not rp.exists() or not fp.exists():
        return {}
    r = json.load(open(rp)); fj = json.load(open(fp))
    tl = {it["index"]: it for it in fj["timeline"]}
    s = json.load(open(BASE / mid / "slim.json"))
    feats = sorted(s["features"], key=lambda f: f["ordinal"])
    out = {}
    for st in r["steps"]:
        a = st.get("aligned")
        if a is None or a >= len(feats):
            continue
        it = tl.get(st["index"], {})
        if it.get("type") != "ExtrudeFeature":
            continue
        p = (it.get("data") or {}).get("profile")
        p = p if isinstance(p, list) else ([p] if p else [])
        area = None
        if p and all(isinstance(x, dict) and "area" in x for x in p):
            area = sum(x["area"] for x in p) * 100.0
        out[feats[a]["id"]] = (area, it["name"], st["index"])
    return out

def run(mid, outdir, binp):
    entry = MAN[mid]
    work = outdir / mid
    work.mkdir(parents=True, exist_ok=True)
    model = CORPUS / entry["file"]
    cadir = work / "model.cadir.json"
    sf = work / "dump.stamp"
    stp = stamp(binp, model)
    if NODECODE:
        if not (work / "slim.json").exists():
            (work / "slim.json").symlink_to(BASE / mid / "slim.json")
    elif not (cadir.exists() and sf.exists() and sf.read_text() == stp):
        p = subprocess.run(["nice", "timeout", "900", str(binp), "dump", str(model), "-o", str(cadir), "--force"],
                           capture_output=True, text=True)
        (work / "dump.log").write_text(p.stdout + p.stderr)
        if p.returncode != 0:
            return mid, None
        sf.write_text(stp)
        (work / "model.cadir.fidelity.json").unlink(missing_ok=True)
        s, topo = slim(json.load(open(cadir)))
        json.dump(s, open(work / "slim.json", "w"))
        (work / "areas.json").unlink(missing_ok=True)
    if not (work / "areas.json").exists():
        env = dict(os.environ, F2FC_SLIM=str(work / "slim.json"), F2FC_AREAS=str(work / "areas.json"))
        p = subprocess.run(["nice", "timeout", "900", "freecadcmd", str(WT / "tools" / "profile_areas.py")], env=env,
                           capture_output=True, text=True)
        (work / "areas.log").write_text(p.stdout + p.stderr)
    if not (work / "areas.json").exists():
        return mid, None
    return mid, json.load(open(work / "areas.json"))

def status(ar, fa):
    if fa is None: return "nofusion"
    if isinstance(ar, str): return "unbuilt"
    return "match" if abs(ar - fa) <= 1e-6 * max(1, fa) else "mismatch"

def main(argv):
    args = argv[1:]
    opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
    outdir = Path(args[0]); jobs = int(opt("-j", 2)); binp = Path(opt("--cadmpeg", WT / "cadmpeg/target/release/cadmpeg"))
    valued = {"-j", "--cadmpeg", "--base"}
    ids = [a for i, a in enumerate(args[1:], 1) if not a.startswith("-") and args[i - 1] not in valued]
    global MAN, NODECODE
    NODECODE = "--nodecode" in args
    MAN = {e["id"]: e for e in json.load(open(CORPUS / "manifest.json"))}
    ids = ids or [m for m in MAN if (BASE / m / "result.json").exists()]
    with ThreadPoolExecutor(jobs) as pool:
        res = dict(pool.map(lambda m: run(m, outdir, binp), ids))
    total = Counter(); per = {}
    for mid in ids:
        fa = fusion_areas(mid); ar = res.get(mid) or {}
        c = Counter()
        for fid, (area, name, idx) in fa.items():
            a = ar.get(fid, "error: missing")
            st = status(a, area); c[st] += 1
            per[mid + "|" + fid] = (st, a, area, name, idx)
        total.update(c)
    json.dump(per, open(outdir / "area_status.json", "w"), indent=0)
    print("TOTAL", dict(total))
    base = opt("--base")
    if base:
        old = json.load(open(Path(base) / "area_status.json"))
        trans = Counter((old[k][0], per[k][0]) for k in per if k in old)
        print(trans)
        for k in sorted(per):
            if k in old and old[k][0] == "match" and per[k][0] != "match":
                print("REGRESSED", k.split("|")[0], per[k])
        for k in sorted(per):
            if k in old and old[k][0] != "match" and per[k][0] == "match":
                print("IMPROVED", k.split("|")[0], per[k][3])

if __name__ == "__main__":
    main(sys.argv)
