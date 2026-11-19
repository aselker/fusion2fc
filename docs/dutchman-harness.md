# Dutchman evaluation harness

Results: `docs/dutchman-comparison.md` (summary + per-model table) and `docs/dutchman-comparison.csv`.
Dutchman 0.2.9 (`convert` only) and SolidCraft 0.41.0 (`solidcraft-cli run` only). No investigate/report/diagnose/MCP/GUI.

Pipeline (all outputs under git-ignored `tests/out/dutchman/`; inputs are copies in `in/`):
1. `tools/run_dutchman.py [--mode fcstd|sc] -j 3` converts every manifest entry (240 entries; the brief said 237).
   fcstd: `convert --to fcstd --json`; sc: `convert --to solidcraft --solidcraft CLI --json`, then `solidcraft-cli run --in X.sc --out X.step`.
   Needs `DUTCHMAN_BIN` and `SOLIDCRAFT_CLI` env vars.
2. `freecadcmd tools/check_dutchman.py` (env DUT_IDS, DUT_SHARD optional): exports the rebuilt PartDesign Bodies (not the
   `OriginalBody` embedded-STEP fallback) and the visible shapes, runs `corpus_compare.compare_step` vs the last truth step.
3. `freecadcmd tools/check_dutchman_sc.py` (DUT_SHARD=k/n): same for the replayed STEP.
4. `python3 tools/compare_dutchman.py`: joins with main's `tests/out/corpus/<id>/{result,report}.json`, writes the docs.

Notes
- FreeCAD output with a blocked feature is "partial": hidden `PartialHistory` group + visible embedded STEP as final shape. So "final shape correct" there is a fallback, not parametric.
- Comparator is the strict one (1e-6 volume). STEP round-trips often fail only on volume at 1e-5..1e-4; the summary lists these as `near`.
- In our FreeCAD 1.1.3 / Python 3.14, Dutchman's own headless rebuild verification reports `differs ... syntax error` in about 44 models whose history is fully mapped (runtime error in the generated macro, "Rebuild failed; original STEP restored: syntax error"); macro parses fine. Possibly environment-specific; not investigated further.
- f2fc "fully parametric" = all steps match and every feature status built (suppressed features count as unbuilt, so two Dutchman-only wins, case_params_renamed_suppressed and case_suppressed_default_names, are an artifact of that).
