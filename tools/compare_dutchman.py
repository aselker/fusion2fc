#!/usr/bin/env python3
"""Join Dutchman results (tests/out/dutchman: json/, runs.json, check/) with fusion2fc corpus results
(F2FC_OUT, default <main checkout>/tests/out/corpus) and write a markdown summary.
usage: compare_dutchman.py [--f2fc DIR] [--md PATH] [--csv PATH]"""
import argparse, collections, csv, json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser()
ap.add_argument("--out", default=os.path.join(ROOT, "tests/out/dutchman"))
ap.add_argument("--f2fc", default="/home/neophile/Documents/Programming/Vibes/fusion/tests/out/corpus")
ap.add_argument("--md", default=os.path.join(ROOT, "docs/dutchman-comparison.md"))
ap.add_argument("--csv", default=os.path.join(ROOT, "docs/dutchman-comparison.csv"))
a = ap.parse_args()
man = json.load(open(os.path.join(ROOT, "tests/corpus/manifest.json")))
runs = {r["id"]: r for r in json.load(open(os.path.join(a.out, "runs.json")))}
DERIVED = ("after the first blocking feature", "part imported as STEP: feature ownership", "an earlier feature cannot be rebuilt")

def norm(s): return re.sub(r"feature \"[^\"]*\": ", "", re.sub(r"\d+", "N", s or ""))[:100]

rows = []
for e in man:
    i = e["id"]; r = {"id": i, "tier": e["tier"], "exit": runs[i]["exit"], "secs": runs[i]["seconds"]}
    # fusion2fc
    p = os.path.join(a.f2fc, i, "result.json"); q = os.path.join(a.f2fc, i, "report.json")
    if os.path.exists(p) and os.path.exists(q):
        res = json.load(open(p)); rep = json.load(open(q)); st = res["steps"]
        r.update(f_steps=len(st), f_match=res["summary"]["match"], f_all=res["summary"]["all_match"],
                 f_final=st[-1]["status"] == "match" if st else False,
                 f_built=sum(f["status"] == "built" for f in rep["features"]), f_total=len(rep["features"]),
                 f_first=(res["summary"]["first_mismatch"] or {}).get("rebuild") or {})
        r["f_full"] = r["f_all"] and r["f_built"] == r["f_total"]
    else:
        r["f_missing"] = True
    # dutchman
    d = json.load(open(os.path.join(a.out, "json", i + ".json"))) if os.path.getsize(os.path.join(a.out, "json", i + ".json")) else {}
    ck = json.load(open(os.path.join(a.out, "check", i + ".json")))
    r["d_err"] = (d.get("error") or {}).get("message", "")[:90] if "error" in d or not d else ("no output" if not d else "")
    if "history" in d:
        h = d["history"]; fs = h["features"]
        r.update(d_mode=d["mode"], d_rebuilt=h["rebuilt"], d_total=h["total"], d_ver=d["verification"]["status"],
                 d_ver_reason=d["verification"].get("reason"))
        roots = [f for f in fs if f["status"] == "blocked" and not any(x in (f["reason"] or "") for x in DERIVED)]
        multi = any("feature ownership across multiple bodies" in (f["reason"] or "") for f in fs)
        r["d_root"] = ("multi-body part imported as STEP" if multi and not roots else
                       ("%s: %s" % (roots[0]["kind"], norm(roots[0]["reason"])) if roots else ""))
        r["d_blocked_kinds"] = sorted({f["kind"] for f in fs if f["status"] == "blocked"})
        r["d_mapped_kinds"] = sorted({f["kind"] for f in fs if f["status"] == "mapped" and f["kind"] not in ("sketch", "datum_plane")})
    r["d_check"] = ck["status"]; r["d_check_prob"] = (ck.get("vis_problems") or ck.get("problems") or [""])[0][:80]
    r["d_fallback_visible"] = ck.get("fallback_visible"); r["d_bodies"] = ck.get("rebuilt_bodies")
    r["d_vis"] = ck.get("vis_status"); r["d_vis_kind"] = ck.get("visible_kind"); r["d_partial"] = ck.get("partial_group")
    r["d_full"] = (r.get("d_mode") == "history" and r.get("d_rebuilt") == r.get("d_total") and ck["status"] == "match"
                   and not ck.get("partial_group") and ck.get("visible_kind") == "history")
    r["d_final_ok"] = ck.get("vis_status") == "match"   # visible final shape right, parametric or not
    # Dutchman -> SolidCraft
    sp = os.path.join(a.out, "scjson", i + ".json"); sd = json.load(open(sp)) if os.path.getsize(sp) else {}
    sk = json.load(open(os.path.join(a.out, "sccheck", i + ".json")))
    r["s_check"] = sk["status"]; r["s_prob"] = (sk.get("problems") or [""])[0][:80]
    r["s_err"] = (sd.get("error") or {}).get("message", "")[:80] if "history" not in sd else ""
    if "history" in sd:
        h = sd["history"]; fs = h["features"]
        r.update(s_mode=sd["mode"], s_rebuilt=h["rebuilt"], s_total=h["total"], s_ver=sd["verification"]["status"])
        roots = [f for f in fs if f["status"] == "blocked" and not any(x in (f["reason"] or "") for x in DERIVED)]
        r["s_root"] = "%s: %s" % (roots[0]["kind"], norm(roots[0]["reason"])) if roots else ""
        r["s_mapped_kinds"] = sorted({f["kind"] for f in fs if f["status"] == "mapped" and f["kind"] not in ("sketch", "datum_plane")})
        r["s_blocked"] = sum(f["status"] == "blocked" for f in fs)
    r["s_full"] = r.get("s_mode") == "history" and r.get("s_blocked") == 0 and sk["status"] == "match"
    r["s_final_ok"] = sk["status"] == "match"
    rows.append(r)

with open(a.csv, "w", newline="") as fh:
    keys = ["id", "tier", "f_steps", "f_match", "f_all", "f_final", "f_built", "f_total", "f_full", "d_mode", "d_rebuilt",
            "d_total", "d_ver", "d_check", "d_check_prob", "d_vis", "d_vis_kind", "d_partial", "d_full", "d_fallback_visible", "d_root", "s_mode", "s_rebuilt", "s_total", "s_ver", "s_check", "s_prob", "s_full", "s_root", "s_err", "exit", "secs", "d_err"]
    w = csv.DictWriter(fh, keys, extrasaction="ignore"); w.writeheader(); w.writerows(rows)

L = []; P = L.append
P("# Dutchman 0.2.9 vs fusion2fc on the corpus\n")
P("Generated by `tools/compare_dutchman.py` from `tests/out/dutchman` (git-ignored) and the main checkout's `tests/out/corpus`. Per-model rows: `docs/dutchman-comparison.csv`.\n")
P("Two Dutchman paths were run, both with `dutchman convert` only: `--to fcstd` (no SolidCraft available to it, so fillet/chamfer are blocked) and `--to solidcraft --solidcraft <cli>` (SolidCraft 0.41.0 verifies history; the .sc is then replayed with `solidcraft-cli run --out X.step`, and that STEP is what we check).\n")
tiers = ["generated", "supported", "extended"]
P("## Headline (models)\n")
P("`fully parametric` = every feature rebuilt and the final shape matches Fusion truth (fusion2fc: all timeline steps match and every feature built; Dutchman: mode history, rebuilt == total, the visible shapes are the rebuilt Bodies, no hidden partial-history group, and they match the last truth step by `compare_step`).\n")
P("| tier | models | f2fc all steps match | f2fc final step match | f2fc fully parametric | Dutchman visible final shape matches (any kind) | Dutchman fully parametric | Dutchman self-reports verified | Dutchman history mode | Dutchman conversion failed |")
P("|---|---|---|---|---|---|---|---|---|---|")
def cnt(rs, f): return sum(1 for x in rs if f(x))
for t in tiers + ["all"]:
    rs = [x for x in rows if t == "all" or x["tier"] == t]
    P("| %s | %d | %d | %d | %d | %d | %d | %d | %d | %d |" % (t, len(rs), cnt(rs, lambda x: x.get("f_all")), cnt(rs, lambda x: x.get("f_final")),
        cnt(rs, lambda x: x.get("f_full")), cnt(rs, lambda x: x["d_final_ok"]), cnt(rs, lambda x: x["d_full"]),
        cnt(rs, lambda x: x.get("d_ver") == "verified"), cnt(rs, lambda x: x.get("d_mode") == "history"),
        cnt(rs, lambda x: x["d_check"] == "no_fcstd")))
P("\n### Three-way, per tier (fully parametric with correct final shape / final shape correct in any mode)\n")
P("| tier | models | fusion2fc param | Dutchman->FreeCAD param | Dutchman->SolidCraft param | f2fc final correct | D->FreeCAD visible final correct | D->SC replayed STEP correct | D->SC mode history | D->SC verified | D->SC partial_history | D->SC import |")
P("|---|---|---|---|---|---|---|---|---|---|---|---|")
for t in tiers + ["all"]:
    rs = [x for x in rows if t == "all" or x["tier"] == t]
    P("| %s | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d |" % (t, len(rs), cnt(rs, lambda x: x.get("f_full")), cnt(rs, lambda x: x["d_full"]),
        cnt(rs, lambda x: x["s_full"]), cnt(rs, lambda x: x.get("f_final")), cnt(rs, lambda x: x["d_final_ok"]), cnt(rs, lambda x: x["s_final_ok"]),
        cnt(rs, lambda x: x.get("s_mode") == "history"), cnt(rs, lambda x: x.get("s_ver") == "verified"),
        cnt(rs, lambda x: x.get("s_mode") == "partial_history"), cnt(rs, lambda x: x.get("s_mode") == "import")))
P("\nSolidCraft path: `fully parametric` = mode history, no blocked feature, and the replayed STEP matches the last truth step. Partial-history and import modes contain the imported original shape, so a correct STEP there is a fallback, not a parametric success.")
P("\nFeature counts (all models): fusion2fc built %d of %d; Dutchman rebuilt %d of %d (its `history.rebuilt`, which counts reference sketches)." % (
    sum(x.get("f_built", 0) for x in rows), sum(x.get("f_total", 0) for x in rows),
    sum(x.get("d_rebuilt", 0) for x in rows), sum(x.get("d_total", 0) for x in rows)))
P("\n## Only one tool fully parametric\n")
P("| tier | f2fc only | Dutchman only | both | neither |"); P("|---|---|---|---|---|")
for t in tiers + ["all"]:
    rs = [x for x in rows if t == "all" or x["tier"] == t]
    P("| %s | %d | %d | %d | %d |" % (t, cnt(rs, lambda x: x.get("f_full") and not x["d_full"]), cnt(rs, lambda x: x["d_full"] and not x.get("f_full")),
        cnt(rs, lambda x: x.get("f_full") and x["d_full"]), cnt(rs, lambda x: not x.get("f_full") and not x["d_full"])))
P("\nPairwise (all models): D->SC only vs f2fc: %d; f2fc only vs D->SC: %d; D->SC only vs D->FreeCAD: %d; D->FreeCAD only vs D->SC: %d." % (
    cnt(rows, lambda x: x["s_full"] and not x.get("f_full")), cnt(rows, lambda x: x.get("f_full") and not x["s_full"]),
    cnt(rows, lambda x: x["s_full"] and not x["d_full"]), cnt(rows, lambda x: x["d_full"] and not x["s_full"])))
d_only = [x for x in rows if x["d_full"] and not x.get("f_full")]
P("\nDutchman fully parametric, fusion2fc not: " + (", ".join("`%s`" % x["id"] for x in d_only) or "none"))
P("\n## Dutchman root blockers (first blocked feature per model; models whose whole part fell back to STEP counted as multi-body)\n")
rc = collections.Counter(x["d_root"] for x in rows if x.get("d_root"))
P("| models | blocker |"); P("|---|---|")
for k, v in rc.most_common(25): P("| %d | %s |" % (v, k.replace("|", "/")))
P("\nConversion failures (%d): %s\n" % (cnt(rows, lambda x: x["d_check"] == "no_fcstd"), "; ".join("`%s` (%s)" % (x["id"], x["d_err"][:60]) for x in rows if x["d_check"] == "no_fcstd")))
P("\n## Dutchman->SolidCraft: root blockers (first blocked feature)\n")
rc2 = collections.Counter(x["s_root"] for x in rows if x.get("s_root"))
P("| models | blocker |"); P("|---|---|")
for k, v in rc2.most_common(25): P("| %d | %s |" % (v, k.replace("|", "/")))
sc_only = [x for x in rows if x["s_full"] and not x.get("f_full")]
P("\n## Dutchman->SolidCraft parametric where fusion2fc is not fully parametric (%d)\n" % len(sc_only))
P("| id | tier | f2fc steps / built / first failure | D->SC features (non-sketch kinds) |"); P("|---|---|---|---|")
for x in sc_only:
    ff = x.get("f_first") or {}
    P("| %s | %s | %s/%s, %s/%s, %s %s: %s | %s |" % (x["id"], x["tier"], x.get("f_match"), x.get("f_steps"), x.get("f_built"), x.get("f_total"),
      ff.get("kind"), ff.get("name"), (ff.get("reason") or "")[:90].replace("|", "/"), ", ".join(x.get("s_mapped_kinds", []))))
fk = collections.Counter(k for x in sc_only for k in x.get("s_mapped_kinds", []))
P("\nFeature kinds in those models: " + ", ".join("%s x%d" % kv for kv in fk.most_common()))
def near(x, key):
    m = re.match(r"volumes \[([^\]]*)\] vs \[([^\]]*)\]", x.get(key) or "")
    if not m: return False
    try:
        f = [float(v) for v in m.group(1).split(",")]; g = [float(v) for v in m.group(2).split(",")]
    except ValueError: return False
    return len(f) == len(g) and all(abs(u - v) <= 1e-3 * max(abs(u), 1e-9) for u, v in zip(f, g))
P("\nNote: the comparator demands 1e-6 relative volume agreement; STEP round trips often differ at 1e-5..1e-4. Mismatches where only the volume line fails and every volume is within 1e-3 are listed as `near` below (mesh distance was not evaluated for them).")
sn = [x for x in rows if x["s_check"] == "mismatch" and near(x, "s_prob")]
P("\nD->SC replayed STEP `near` (volume-only, <1e-3): %d models (%d of them in mode history)." % (len(sn), sum(1 for x in sn if x.get("s_mode") == "history")))
dn = [x for x in rows if x["d_vis"] == "mismatch" and near(x, "d_check_prob")]
P("D->FreeCAD visible shape `near`: %d models." % len(dn))
sfn = [x for x in rows if x.get("s_mode") == "history" and x.get("s_blocked") == 0 and (x["s_check"] == "match" or (x["s_check"] == "mismatch" and near(x, "s_prob")))]
P("D->SC fully parametric counting `near` as correct: %d models (generated %d, supported %d, extended %d)." % (len(sfn), cnt(sfn, lambda x: x["tier"] == "generated"), cnt(sfn, lambda x: x["tier"] == "supported"), cnt(sfn, lambda x: x["tier"] == "extended")))
sv = collections.Counter((x.get("s_ver"), x["s_check"]) for x in rows if x.get("s_mode") == "history")
P("\nD->SC mode history: Dutchman verification vs our check of the replayed STEP\n"); P("| Dutchman verification | our check | models |"); P("|---|---|---|")
for k, v in sorted(sv.items(), key=lambda kv: -kv[1]): P("| %s | %s | %d |" % (k[0], k[1], v))
sdis = [x for x in rows if x.get("s_mode") == "history" and x.get("s_ver") == "verified" and x["s_check"] != "match"]
P("\nSolidCraft 'history verified' but our check does not match: " + (", ".join("`%s` (%s: %s)%s" % (x["id"], x["s_check"], x["s_prob"], " near" if near(x, "s_prob") else "") for x in sdis) or "none"))
sdis2 = [x for x in rows if x.get("s_mode") == "history" and x.get("s_ver") != "verified" and x["s_check"] == "match"]
P("\nNot verified by Dutchman but our check matches: " + (", ".join("`%s` (%s)" % (x["id"], x.get("s_ver")) for x in sdis2) or "none"))
P("\n## Dutchman->FreeCAD self-report vs independent check\n")
vm = collections.Counter((x.get("d_ver"), x["d_vis"]) for x in rows if x.get("d_mode") == "history")
P("| Dutchman verification | our check of its visible final shape | models |"); P("|---|---|---|")
for k, v in sorted(vm.items(), key=lambda kv: -kv[1]): P("| %s | %s | %d |" % (k[0], k[1], v))
vf = [x for x in rows if x.get("d_ver") == "verified" and x["d_vis"] == "mismatch"]
P("\nVerified by Dutchman but mismatching Fusion truth: " + (", ".join("`%s` (%s)" % (x["id"], x["d_check_prob"]) for x in vf) or "none"))
nv = [x for x in rows if x.get("d_ver") == "differs" and x["d_vis"] == "match"]
P("\nReported `differs` but matching Fusion truth: " + (", ".join("`%s`" % x["id"] for x in nv) or "none"))
P("\n## Runtime\n")
tot = sum(x["secs"] for x in rows); mx = max(rows, key=lambda x: x["secs"])
P("Dutchman->FreeCAD: total %.0f s for %d conversions (3 parallel, mean %.1f s, max %.0f s `%s`). Exit status 1: %d; timeouts: %d." % (
    tot, len(rows), tot / len(rows), mx["secs"], mx["id"], cnt(rows, lambda x: x["exit"] == 1), cnt(rows, lambda x: x["exit"] == "timeout")))
sr = json.load(open(os.path.join(a.out, "runs_sc.json")))
P("\nDutchman->SolidCraft (convert with SolidCraft verification, then `solidcraft-cli run`): convert total %.0f s (max %.0f s), replay total %.0f s (max %.1f s); convert exit!=0: %d; replay failed: %d; timeouts: %d." % (
    sum(x["seconds"] for x in sr), max(x["seconds"] for x in sr), sum(x.get("run_seconds", 0) for x in sr), max(x.get("run_seconds", 0) for x in sr),
    cnt(sr, lambda x: x["exit"] not in (0,)), cnt(sr, lambda x: x.get("run_exit") not in (0, None)), cnt(sr, lambda x: "timeout" in (str(x["exit"]), str(x.get("run_exit"))))))
P("\n## Per-model table\n")
P("| id | tier | f2fc steps | f2fc final | f2fc built | D mode | D rebuilt | D verif | D visible (kind) | D rebuilt-Body check | SC mode | SC rebuilt | SC verif | SC STEP check |"); P("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for x in rows:
    P("| %s | %s | %s/%s | %s | %s/%s | %s | %s/%s | %s | %s (%s) | %s | %s | %s/%s | %s | %s |" % (x["id"], x["tier"], x.get("f_match", "-"), x.get("f_steps", "-"),
      "Y" if x.get("f_final") else "n", x.get("f_built", "-"), x.get("f_total", "-"), x.get("d_mode", "-"), x.get("d_rebuilt", "-"),
      x.get("d_total", "-"), x.get("d_ver", "-"), x["d_vis"], x["d_vis_kind"], x["d_check"], x.get("s_mode", "-"), x.get("s_rebuilt", "-"), x.get("s_total", "-"), x.get("s_ver", "-"), x["s_check"]))
os.makedirs(os.path.dirname(a.md), exist_ok=True)
open(a.md, "w").write("\n".join(L) + "\n")
json.dump(rows, open(os.path.join(a.out, "rows.json"), "w"))
print("\n".join(L[:60]))
