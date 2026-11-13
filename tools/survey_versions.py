#!/usr/bin/env python3
"""Survey the version evidence of the corpus and generated cases (read-only).

  survey_versions.py [--write] [--cadmpeg PATH]

For every model in tests/corpus/manifest.json: the container manifest version, the ASM
(ShapeManager) product string and save date of every BREP blob, and the (type GUID, version)
table of the Design stream (from `cadmpeg dump`, native.f3d.design_types). Prints the spread and,
with --write, stores the known range in fusion2fc/known_versions.json for fusion2fc/versions.py.
Needs python3.14 (zipfile with zstd).
"""
import collections
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
ASM = re.compile(rb"\x07.(Autodesk [ -~]*?)\x07.(ASM (\d+)\.(\d+)\.(\d+)[ -~]*?)\x07.([ -~]*?)[\x06\x04]")


def brep_headers(z):
    for n in z.namelist():
        if "Breps.BlobParts/" in n and n.endswith((".smb", ".smbh")):
            m = ASM.search(z.read(n)[:200])
            if m:
                yield m.group(2).decode(), m.group(6).decode()


def main(argv):
    cadmpeg = ROOT / "cadmpeg" / "target" / "release" / "cadmpeg"
    if "--cadmpeg" in argv:
        cadmpeg = Path(argv[argv.index("--cadmpeg") + 1])
    manifest = collections.Counter()
    asm, dates = collections.Counter(), []
    types = collections.defaultdict(collections.Counter)
    per_model = {}
    tmp = Path(tempfile.mkdtemp())
    for e in json.load(open(CORPUS / "manifest.json")):
        path = CORPUS / e["file"]
        z = zipfile.ZipFile(path)
        manifest[z.read("Manifest.dat")[4:11].decode()] += 1
        mine = set(brep_headers(z))
        for prod, date in mine:
            asm[prod] += 1
            try:
                dates.append((datetime.strptime(" ".join(date.split()), "%a %b %d %H:%M:%S %Y"), prod))
            except ValueError:
                pass
        cadir = tmp / "m.json"
        subprocess.run([str(cadmpeg), "dump", str(path), "-o", str(cadir), "--force"], capture_output=True)
        if cadir.exists():
            for t in json.load(open(cadir))["native"]["f3d"].get("design_types") or []:
                types[t["type_guid"]][t["version"]] += 1
            cadir.unlink()
        per_model[e["id"]] = sorted(p for p, _ in mine)
    majors = sorted({int(re.search(r"ASM (\d+)", p).group(1)) for p in asm})
    print("models:", len(per_model))
    print("container manifest versions:", dict(manifest))
    print("ASM major versions: %d..%d, %d distinct builds" % (majors[0], majors[-1], len(asm)))
    for p, n in sorted(asm.items(), key=lambda kv: [int(x) for x in re.findall(r"\d+", kv[0])[:3]]):
        print("  %-26s %3d blobs" % (p, n))
    dates.sort()
    print("ASM save dates: %s (%s) .. %s (%s)" % (dates[0][0].date(), dates[0][1], dates[-1][0].date(), dates[-1][1]))
    multi = {g: dict(c) for g, c in types.items() if len(c) > 1}
    print("design record types: %d; %d appear at more than one version, e.g. %s" % (
        len(types), len(multi), list(multi.items())[:3]))
    print("Fusion application version: not stored in the files (no build string in any member).")
    if "--write" in argv:
        out = ROOT / "fusion2fc" / "known_versions.json"
        json.dump({"manifest": sorted(manifest), "asm_major": [majors[0], majors[-1]], "asm": sorted(asm),
                   "types": {g: sorted(c) for g, c in sorted(types.items())}}, open(out, "w"), indent=0)
        print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1:])
