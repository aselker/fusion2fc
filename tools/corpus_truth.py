#!/usr/bin/env python3
"""Record Fusion ground truth for tests/corpus: body properties and a mesh after every
timeline step (vm/scripts/step_meshes.py, run in the Fusion VM through its MCP server).

  corpus_truth.py [ID ...] [--tier TIER] [--force] [--budget SECONDS] [--dev MM]

Each model is copied to the VM shared folder, opened in a new Fusion document, stepped
through, and closed without saving; long timelines take several calls (resuming at the
step the previous call reached). Results land in tests/corpus/truth/<id>/:
steps.json, features.json, mesh_NNNN.stl.gz. Models that already have steps.json are
skipped unless --force.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
SHARED_HOST = Path(os.path.expanduser("~/Tech/VirtualBox VMs/Shared")) / "fusion-work"
SHARED_GUEST = r"\\VBOXSVR\Shared\fusion-work"


def record(entry, budget, dev):
    mid = entry["id"]
    src = (CORPUS / entry["file"]).resolve()
    (SHARED_HOST / "corpus-in").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, SHARED_HOST / "corpus-in" / (mid + ".f3d"))
    out_host = SHARED_HOST / "corpus-out" / mid
    if out_host.exists():
        shutil.rmtree(out_host)
    start, parts, t0 = 0, [], time.time()
    while start is not None:
        cmd = [sys.executable, str(ROOT / "vm" / "mcp_call.py"), "script", str(ROOT / "vm" / "scripts" / "step_meshes.py"),
               "--include", str(ROOT / "vm" / "scripts" / "dump_features.py"),
               "IN=%s\\corpus-in\\%s.f3d" % (SHARED_GUEST, mid), "OUTDIR=%s\\corpus-out\\%s" % (SHARED_GUEST, mid),
               "DEV=%s" % dev, "START=%d" % start, "BUDGET=%d" % budget]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=budget * 2 + 600)
        msg = (p.stdout + p.stderr).strip()
        part = out_host / ("steps_%d.json" % start)
        if p.returncode != 0 or not part.exists():
            return "FAILED at step %d: %s" % (start, msg[-400:])
        info = json.load(open(part))
        parts.append(info)
        if "steps" not in info:
            break
        dev = info["deviation_mm"]
        start = info.get("next")
    dest = CORPUS / "truth" / mid
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    merged = dict(parts[0])
    merged["steps"] = [s for part in parts for s in part.get("steps", [])]
    merged.pop("next", None)
    merged.pop("start", None)
    merged["seconds"] = round(time.time() - t0, 1)
    for f in out_host.iterdir():
        if f.name.startswith("mesh_") or f.name == "features.json":
            shutil.copyfile(f, dest / f.name)
    json.dump(merged, open(dest / "steps.json", "w"), indent=0, ensure_ascii=False)
    shutil.rmtree(out_host)
    (SHARED_HOST / "corpus-in" / (mid + ".f3d")).unlink()
    if "steps" not in merged:
        return "no timeline (%s)" % merged.get("error")
    meshes = len([f for f in dest.iterdir() if f.name.startswith("mesh_")])
    return "ok  %d steps, %d meshes, dev %.4g mm, %.0f s" % (len(merged["steps"]), meshes, merged["deviation_mm"], merged["seconds"])


def main(argv):
    args = argv[1:]
    opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
    budget = int(opt("--budget", 900))
    dev = opt("--dev", "auto")
    tier = opt("--tier")
    valued = {"--budget", "--dev", "--tier"}
    ids = [a for i, a in enumerate(args) if not a.startswith("-") and (i == 0 or args[i - 1] not in valued)]
    manifest = json.load(open(CORPUS / "manifest.json"))
    for e in manifest:
        if (ids and e["id"] not in ids) or (tier and e["tier"] != tier):
            continue
        if (CORPUS / "truth" / e["id"] / "steps.json").exists() and "--force" not in args:
            continue
        try:
            status = record(e, budget, dev)
        except Exception as ex:
            status = "FAILED: %s" % ex
        print("%-44s %s" % (e["id"], status), flush=True)


if __name__ == "__main__":
    main(sys.argv)
