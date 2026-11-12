# profiles agent handoff

Done (cadmpeg `f2fc-agent/profiles`, both WIP):
- 529b2a99f1: unselected extrude profiles (`unselected_extrude_profile`: history transition, then compact loops, then stored arrangement reading) + per-selection arrangement work cap. Extrude profile areas matching Fusion 166->215/366; Burninator 42->75/212 (HEAD was 42, not 74: shared cap exhausted). Generated tier/run_cases/crate tests NOT run.
- b0ccd3aded: construction flag from versioned curve-tail flag block (decoder knew 2 of Fusion's 362 construction curves; new reading 315 right, 0 wrong). Unmeasured; regenerate `docs/layouts/f3d.md` (layout_tables test) and run f3d tests/goldens.

Root causes: 116 extrudes have a stored curve selection never tried for `sketch` kind; history transition returns whole loops for overlapping/nested loops (~46 wrong areas, e.g. SG90 Extrude4/7); construction lines treated as profile curves; stale further regions naming deleted curves (~11, Hook); unparsed sketch-profile operand tails with inline type GUIDs (`native`, adafruit_2831).

Next: (1) gates for both commits; (2) prefer stored arrangement reading over history `Loops` when loops overlap/nest (compare c1 mismatches); (3) apply `handoff-tools/native_patch.py`, drop stale further regions.

Gotchas: builds ~15 min via `../cargo-locked.sh`; `handoff-tools/area_check.py` aligns via coordinator result.json.
