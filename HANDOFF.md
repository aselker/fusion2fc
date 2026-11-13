# features-b handoff

**Done, verified:** Sweep/pipe (`build_sweep`): S_Hook 2→6/7 steps. Pipes with path corners are mitered (Fusion's mesh confirms); suborusu Pipe1 mesh matches but its volume is 4.6e-6 off (Fusion's spline-pipe approximation; comparator 1e-6).

**Done, unverified (WIP commit):** `build_block/primitive/sphere/torus`; extrude `through_all`; `build_base_feature` (`F2FC_BODIES`) + `tools/stored_bodies.py` (one-body CADIR → `cadmpeg convert` → STEP, works); run_corpus wires it. cadmpeg WIP (never compiled with tests): named Box/Cylinder local frame (scope matrix after repeated refs) composed with the placement construction (box binder `placement_construction/boxes.rs`, loss codes, layout records hand-written in layout.rs, spec + DR-375).

**Gaps:** shell 4/4 models, draft 3/2, thicken 2/2, split 1, delete face 1 (need a face matcher: edge-on-face + exclusion by other recorded edges); loft 7/2 and profile sweeps blocked on `sketch` profiles; surface extrude 5/2 (comparator ignores sheet-only states).

**Next:** 1) build cadmpeg, run f3d tests + layout_tables test, check nick0451/Bicycle/Lattice boxes. 2) face matcher + shell (`Part::Thickness`, Value=-t inward). 3) draft/thicken/delete face.

**Gotchas:** kantoku base body decodes `solid` but has double-sided faces (Fusion: surface). Part::Sweep "Round corner" is wrong; OCC pipes depend on circle seam.

## Update (face matcher, shell, delete face, draft)

**Done:** `Rebuilder.find_face(fid)` locates a rebuilt face from the decoder's recorded boundary edges (`topo_edges`: every edge of a selected face with its `faces` list), using `find_edge` for each, intersecting the faces that carry them, then the fewest-edges rule; ambiguity raises. `build_shell` = `Part::Thickness` (Value=-t inward, Mode skin, Join intersection). Decoder: a `Shell` scope that spans several transitions (brick Shell1: state 26, previous 23, transition's previous 24) now binds its removed faces (`shell_walls::spanned_transition`). plate_v8 Shell2 and brick Shell1 build and match. `build_delete_face` (OCC `defeaturing`) and `build_draft` (`PartDesign::Draft` in a Body, Reversed = outward) are in but unverified: no model reaches them with a matching upstream body.

**Left:** appleScreen shell (scope not bound to a unique history pair; also blocked by native extrude profile upstream); Handlebars Shell3 fails to find a boundary edge (upstream loft missing); Dice DeleteFace1 face is a lone circle edge and defeaturing removes nothing (upstream pattern mismatch too); thicken needs surface bodies (Hook Thicken1 follows a skipped surface extrude; tealight Thicken faces are native); split body tool faces are native. Draft sign convention (angle sign vs `outward`) untested against Fusion.

**Gotchas:** never run two `run_corpus.py` on the same model at once (they share `steps/`). `Part::Thickness` needs `Intersection=True` for sharp inside corners.
