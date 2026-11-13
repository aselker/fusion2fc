#!/usr/bin/env python3
"""Convert one Fusion design to a FreeCAD document, end to end.

  convert.py DESIGN.f3d [OUT.FCStd] [--no-fallback] [--cadmpeg PATH] [--keep DIR]

Decodes with cadmpeg, slims the CADIR, exports Fusion's stored bodies to STEP, rebuilds the
timeline with fusion2fc/rebuild.py (freecadcmd), compares the rebuilt final bodies with
Fusion's stored final bodies and, when a feature was skipped or failed or the shapes differ,
adds the stored bodies as the group "Fusion final shape (not parametric)" (unless
--no-fallback). Prints a short conversion report and writes it next to the output as
OUT.report.txt (also stored in the document as the text object "Conversion report"); the full
machine-readable report is OUT.report.json. Needs python3.14 only for tools/survey_versions.py.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
from slim_cadir import slim  # noqa: E402
from stored_bodies import export as export_bodies, final_body_ids, stored_body_ids  # noqa: E402
from fusion2fc import versions  # noqa: E402


def main(argv):
    args = argv[1:]
    cadmpeg = ROOT / "cadmpeg" / "target" / "release" / "cadmpeg"
    keep = None
    fallback = "--no-fallback" not in args
    args = [a for a in args if a != "--no-fallback"]
    for flag in ("--cadmpeg", "--keep"):
        if flag in args:
            i = args.index(flag)
            val = Path(args[i + 1])
            cadmpeg, keep = (val, keep) if flag == "--cadmpeg" else (cadmpeg, val)
            del args[i:i + 2]
    if not args:
        sys.exit(__doc__)
    src = Path(args[0])
    out = Path(args[1]) if len(args) > 1 else src.with_suffix(".FCStd")
    work = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="f2fc-"))
    work.mkdir(parents=True, exist_ok=True)
    cadir = work / "model.cadir.json"
    p = subprocess.run([str(cadmpeg), "dump", str(src), "-o", str(cadir), "--force"], capture_output=True, text=True)
    (work / "dump.log").write_text(p.stdout + p.stderr)
    if p.returncode != 0 or not cadir.exists():
        sys.exit("decode failed (exit %d); see %s" % (p.returncode, work / "dump.log"))
    model = json.load(open(cadir))
    sidecar = work / "model.cadir.fidelity.json"
    facts = versions.facts(model, json.load(open(sidecar)) if sidecar.exists() else None)
    facts["fallback"] = fallback
    json.dump(facts, open(work / "facts.json", "w"))
    s, topo = slim(model)
    json.dump(s, open(work / "slim.json", "w"))
    json.dump(topo, open(work / "topo.json", "w"))
    env = dict(os.environ, F2FC_SLIM=str(work / "slim.json"), F2FC_TOPO=str(work / "topo.json"),
               F2FC_OUT=str(out), F2FC_REPORT=str(out.with_suffix(".report.json")),
               F2FC_SUMMARY=str(out.with_suffix(".report.txt")), F2FC_FACTS=str(work / "facts.json"))
    env.pop("F2FC_FEATURES", None)
    env.pop("F2FC_STEPS", None)
    if stored_body_ids(model["model"]):
        export_bodies(model, work / "bodies", cadmpeg)
        env["F2FC_BODIES"] = str(work / "bodies" / "index.json")
    export_bodies(model, work / "final", cadmpeg, final_body_ids(model["model"]))
    env["F2FC_FINAL"] = str(work / "final" / "index.json")
    del model
    p = subprocess.run(["freecadcmd", str(ROOT / "fusion2fc" / "rebuild.py")], env=env, capture_output=True, text=True)
    (work / "rebuild.log").write_text(p.stdout + p.stderr)
    if not out.exists():
        sys.exit("rebuild crashed; see %s" % (work / "rebuild.log"))
    print(out.with_suffix(".report.txt").read_text() if out.with_suffix(".report.txt").exists() else p.stdout)
    print("wrote", out)
    if not keep:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv)
