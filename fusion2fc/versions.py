"""Version facts of a decoded Fusion file and the check against the range seen in the corpus.

Plain Python (no FreeCAD). `facts(cadir, sidecar)` returns the version facts, the loss counts by code
and the warnings that tools/convert.py hands to rebuild.py (F2FC_FACTS). The known range is
fusion2fc/known_versions.json, written by `tools/survey_versions.py --write`.

Fusion stores no application build number in a design (the container carries only the manifest
version `3-2-0-0`). The version evidence is the ASM (ShapeManager) product string and save date in
each BREP header, and the (type GUID, version) table of the Design stream: records of an unseen
type or version are decoded by guesswork or not at all.
"""
import json
import re
from collections import Counter
from pathlib import Path

KNOWN = Path(__file__).with_name("known_versions.json")
ASM = re.compile(r"ASM (\d+)\.(\d+)\.(\d+)")
# Loss kinds / code suffixes that mean "the decoder met something it does not understand".
NOVEL_KINDS = {"record_not_typed"}
NOVEL_SUFFIXES = ("-native", "-uninterpreted", "-unresolved", "-incomplete", "-untyped", "-unparsed",
                  "-unrecognized")


def asm_versions(attributes):
    """ASM versions named by the CADIR source attributes (active BREP header)."""
    m = ASM.search((attributes or {}).get("product_version", ""))
    return [tuple(int(x) for x in m.groups())] if m else []


def facts(cadir, sidecar=None, known=None):
    known = known if known is not None else (json.load(open(KNOWN)) if KNOWN.exists() else None)
    src = cadir.get("source") or {}
    attrs = src.get("attributes") or {}
    dialects = (src.get("identity") or {}).get("dialects") or {}
    primary = (dialects.get("primary") or {}).get("declared") or {}
    manifest = primary.get("top_level_manifest_version")
    asm = asm_versions(attrs)
    for d in dialects.get("extra") or []:
        maj = (d.get("declared") or {}).get("save_format_major")
        if maj and maj.isdigit():
            asm.append((int(maj), None, None))
    types = {}
    for t in ((cadir.get("native") or {}).get("f3d") or {}).get("design_types") or []:
        types.setdefault(t["type_guid"], set()).add(t.get("version"))
    out = {"manifest": manifest, "product": attrs.get("product_version"), "save_date": attrs.get("save_date"),
           "asm_major": asm[0][0] if asm else None, "types": {g: sorted(v) for g, v in types.items()}}
    counts, novel = Counter(), Counter()
    for l in ((sidecar or {}).get("report") or {}).get("losses") or []:
        c = l["code"]
        if l.get("severity") == "info" and c["kind"] not in NOVEL_KINDS:
            continue
        counts[c["code"]] += 1
        if c["kind"] in NOVEL_KINDS or c["code"].endswith(NOVEL_SUFFIXES):
            novel[c["code"]] += 1
    out["loss_counts"], out["novelty_counts"] = dict(counts), dict(novel)
    out["warnings"] = warnings(out, known)
    return out


def warnings(f, known):
    w = []
    if known is None:
        return ["no known-version table (fusion2fc/known_versions.json); version range not checked"]
    if f["manifest"] and f["manifest"] not in known["manifest"]:
        w.append("container manifest version %s is outside the surveyed %s: the file may be from a newer "
                 "Fusion release" % (f["manifest"], ", ".join(known["manifest"])))
    lo, hi = known["asm_major"]
    if f["asm_major"] is not None and not lo <= f["asm_major"] <= hi:
        w.append("ASM (ShapeManager) version %s is outside the surveyed range %d-%d%s; geometry kernel "
                 "records may be unknown" % (f["product"] or f["asm_major"], lo, hi,
                                             " (newer than any tested file)" if f["asm_major"] > hi else ""))
    kt = known["types"]
    newer = [(g, v) for g, vs in f["types"].items() if g in kt for v in vs if v is not None and v not in kt[g]]
    if newer:
        w.append("%d design record type(s) have versions not seen in the surveyed files (e.g. %s v%s): "
                 "their layout may differ from what the decoder expects" % (len(newer), newer[0][0], newer[0][1]))
    unseen = [g for g, vs in f["types"].items() if g not in kt and any(f["types"][g])]
    if unseen:
        w.append("%d design record type(s) not seen in the surveyed files" % len(unseen))
    if f["novelty_counts"]:
        w.append("decoder met records or features it does not fully understand: " + ", ".join(
            "%s x%d" % kv for kv in sorted(f["novelty_counts"].items(), key=lambda kv: -kv[1])[:8]))
    return w
