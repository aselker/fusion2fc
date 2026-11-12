# features-b handoff

**Done, verified:** Sweep/pipe (`build_sweep`): S_Hook 2→6/7 steps. Pipes with path corners are mitered (Fusion's mesh confirms); suborusu Pipe1 mesh matches but its volume is 4.6e-6 off (Fusion's spline-pipe approximation; comparator 1e-6).

**Done, unverified (WIP commit):** `build_block/primitive/sphere/torus`; extrude `through_all`; `build_base_feature` (`F2FC_BODIES`) + `tools/stored_bodies.py` (one-body CADIR → `cadmpeg convert` → STEP, works); run_corpus wires it. cadmpeg WIP (never compiled with tests): named Box/Cylinder local frame (scope matrix after repeated refs) composed with the placement construction (box binder `placement_construction/boxes.rs`, loss codes, layout records hand-written in layout.rs, spec + DR-375).

**Gaps:** shell 4/4 models, draft 3/2, thicken 2/2, split 1, delete face 1 (need a face matcher: edge-on-face + exclusion by other recorded edges); loft 7/2 and profile sweeps blocked on `sketch` profiles; surface extrude 5/2 (comparator ignores sheet-only states).

**Next:** 1) build cadmpeg, run f3d tests + layout_tables test, check nick0451/Bicycle/Lattice boxes. 2) face matcher + shell (`Part::Thickness`, Value=-t inward). 3) draft/thicken/delete face.

**Gotchas:** kantoku base body decodes `solid` but has double-sided faces (Fusion: surface). Part::Sweep "Round corner" is wrong; OCC pipes depend on circle seam.
