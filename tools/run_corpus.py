#!/usr/bin/env python3
"""Step-by-step geometric comparison of fusion2fc rebuilds with Fusion, over tests/corpus.

  run_corpus.py [ID ...] [--tier TIER] [-j N] [--cadmpeg PATH] [--out DIR]
                [--save-baseline] [-v]

For every manifest entry with Fusion ground truth (tests/corpus/truth/<id>/steps.json,
written by tools/corpus_truth.py): decode with cadmpeg, rebuild with fusion2fc/rebuild.py
(saving the bodies after every feature), and compare the rebuild with Fusion after every
timeline step (tools/corpus_compare.py: body count, volumes, and two-sided mesh distance
against Fusion's own tessellation). Prints one line per model and a summary, and the
models that improved or regressed against tests/corpus/baseline.json.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from slim_cadir import slim  # noqa: E402
from stored_bodies import export as export_stored_bodies, stored_body_ids  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
DEFAULT_CADMPEG = ROOT / "cadmpeg" / "target" / "release" / "cadmpeg"


def dump_stamp(cadmpeg, model):
    st = cadmpeg.stat()
    return "%s %d %d %s" % (cadmpeg.resolve(), st.st_size, st.st_mtime_ns,
                            hashlib.sha256(model.read_bytes()).hexdigest())


def run_model(entry, cadmpeg, out):
    """Decode, rebuild, and compare one model. The CADIR dump is reused while the cadmpeg
    binary and the model are unchanged (work/dump.stamp)."""
    mid = entry["id"]
    truth = CORPUS / "truth" / mid / "steps.json"
    work = out / mid
    keep = ("model.cadir.json", "dump.log", "dump.stamp")
    if work.exists():
        for f in work.iterdir():
            if f.name not in keep:
                shutil.rmtree(f) if f.is_dir() else f.unlink()
    work.mkdir(parents=True, exist_ok=True)
    res = {"id": mid, "tier": entry["tier"]}
    if not truth.exists():
        res["status"] = "no truth"
        return res
    t = json.load(open(truth))
    if "steps" not in t:
        res["status"] = "no timeline" if t.get("designType") == 0 else "truth error"
        return res
    cadir, stamp_file = work / "model.cadir.json", work / "dump.stamp"
    stamp = dump_stamp(cadmpeg, CORPUS / entry["file"])
    if not (cadir.exists() and stamp_file.exists() and stamp_file.read_text() == stamp):
        stamp_file.unlink(missing_ok=True)
        p = subprocess.run([str(cadmpeg), "dump", str(CORPUS / entry["file"]), "-o", str(cadir), "--force"],
                           capture_output=True, text=True, timeout=900)
        (work / "dump.log").write_text(p.stdout + p.stderr)
        if p.returncode != 0 or not cadir.exists():
            cadir.unlink(missing_ok=True)
            res["status"] = "decode failed (exit %d)" % p.returncode
            res["summary"] = {"steps": len(t["steps"]), "match": 0}
            return res
        stamp_file.write_text(stamp)
    model = json.load(open(cadir))
    s, topo = slim(model)
    json.dump(s, open(work / "slim.json", "w"))
    json.dump(topo, open(work / "topo.json", "w"))
    env = dict(os.environ, F2FC_SLIM=str(work / "slim.json"), F2FC_TOPO=str(work / "topo.json"),
               F2FC_OUT=str(work / "rebuilt.FCStd"), F2FC_REPORT=str(work / "report.json"),
               F2FC_STEPS=str(work / "steps"))
    if stored_body_ids(model["model"]):
        export_stored_bodies(model, work / "bodies", cadmpeg)
        env["F2FC_BODIES"] = str(work / "bodies" / "index.json")
    del model
    env.pop("F2FC_FEATURES", None)
    p = subprocess.run(["freecadcmd", str(ROOT / "fusion2fc" / "rebuild.py")], env=env,
                       capture_output=True, text=True, timeout=1800)
    (work / "rebuild.log").write_text(p.stdout + p.stderr)
    if not (work / "report.json").exists():
        res["status"] = "rebuild crashed"
        res["summary"] = {"steps": len(t["steps"]), "match": 0}
        return res
    env = dict(os.environ, F2FC_TRUTH=str(truth), F2FC_REPORT=str(work / "report.json"),
               F2FC_STEPS=str(work / "steps"), F2FC_RESULT=str(work / "result.json"))
    p = subprocess.run(["freecadcmd", str(ROOT / "tools" / "corpus_compare.py")], env=env,
                       capture_output=True, text=True, timeout=3600)
    (work / "compare.log").write_text(p.stdout + p.stderr)
    if not (work / "result.json").exists():
        res["status"] = "compare crashed"
        res["summary"] = {"steps": len(t["steps"]), "match": 0}
        return res
    r = json.load(open(work / "result.json"))
    res["summary"] = r["summary"]
    res["status"] = "PASS" if r["summary"]["all_match"] else "FAIL"
    shutil.rmtree(work / "steps", ignore_errors=True)
    return res


def describe(res):
    s = res.get("summary") or {}
    line = "%-44s %-9s %-5s" % (res["id"][:44], res["tier"], res["status"] if res["status"] in ("PASS", "FAIL") else "-")
    if "steps" in s:
        line += " steps %3d/%-3d" % (s["match"], s["steps"])
    if res["status"] not in ("PASS", "FAIL"):
        line += " " + res["status"]
    fm = s.get("first_mismatch")
    if fm:
        line += "  first: #%d %s (%s): %s" % (fm["index"], fm["name"], fm["type"], "; ".join(fm.get("problems") or []))
        rb = fm.get("rebuild") or {}
        if rb.get("status") not in (None, "built"):
            line += "  [rebuild %s: %s %s]" % (rb.get("name"), rb.get("status"), (rb.get("reason") or "")[:80])
    return line


def main(argv):
    args = argv[1:]
    opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
    cadmpeg = Path(opt("--cadmpeg", DEFAULT_CADMPEG))
    out = Path(opt("--out", ROOT / "tests" / "out" / "corpus"))
    tier = opt("--tier")
    jobs = int(opt("-j", os.cpu_count() // 2 or 1))
    valued = {"--cadmpeg", "--out", "--tier", "-j"}
    ids = [a for i, a in enumerate(args) if not a.startswith("-") and (i == 0 or args[i - 1] not in valued)]
    manifest = json.load(open(CORPUS / "manifest.json"))
    entries = [e for e in manifest if (not ids or e["id"] in ids) and (not tier or e["tier"] == tier)]
    out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(lambda e: run_model(e, cadmpeg, out), entries))
    for r in results:
        print(describe(r))
    print()
    tiers = sorted({r["tier"] for r in results})
    for t in tiers + ["all"]:
        rs = [r for r in results if (t == "all" or r["tier"] == t) and "summary" in r]
        if not rs:
            continue
        steps = sum(r["summary"]["steps"] for r in rs)
        match = sum(r["summary"]["match"] for r in rs)
        print("%-10s models %3d/%-3d all steps match   steps %5d/%-5d (%.1f%%)" % (
            t, sum(r["status"] == "PASS" for r in rs), len(rs), match, steps, 100.0 * match / max(steps, 1)))
    missing = [r["id"] for r in results if r["status"] == "no truth"]
    if missing:
        print("%d models have no Fusion ground truth yet (tools/corpus_truth.py)" % len(missing))
    base_path = CORPUS / "baseline.json"
    current = {r["id"]: {"match": r["summary"]["match"], "steps": r["summary"]["steps"]}
               for r in results if "summary" in r}
    if base_path.exists():
        base = json.load(open(base_path))
        for mid, cur in sorted(current.items()):
            b = base.get(mid)
            if b and cur["match"] != b["match"]:
                print("%s %s: %d -> %d of %d steps" % ("IMPROVED " if cur["match"] > b["match"] else "REGRESSED",
                                                       mid, b["match"], cur["match"], cur["steps"]))
    if "--save-baseline" in args:
        base = json.load(open(base_path)) if base_path.exists() else {}
        base.update(current)
        json.dump(dict(sorted(base.items())), open(base_path, "w"), indent=1)
        print("baseline saved:", base_path)
    json.dump(results, open(out / "results.json", "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv)
