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

## Update (round 4: loft)

**Done:** `Rebuilder.build_loft` = `Part::Loft` through whole-sketch sections (one outermost planar loop per section; a whole-sketch section selects every region, so an annulus plus its inner disc fills back to the outer loop, which matches Fusion's volumes). Handlebars 9 -> 18/27 steps. No rails/centerline, surface, linearized, or multi-profile sections yet (clear NotImplemented reasons).

**Left:** Doom Keycap lofts (sections are sketches with several disjoint profiles; the decoder says "whole sketch" but the real selection must be a subset: needs region frames from the decoder). Handlebars Loft7 (section sketch is not planar-profile). Surface extrude/thicken: Hook's surface extrude has a `Path` profile and Thicken1's thickness is not in the dump; tealight needs patch/trim/stitch (32 steps, big). Derived Base Feature (Connector_Bracket 19, Example_B 12): the stored snapshot body is not an active body of the final BREP (later features modify it), so the decoder has no geometry to export; needs historical body geometry per state. kantoku Base Feature: stored body decodes as solid with double-sided faces but Fusion treats it as a surface body (rebuilt shows 1 body vs 0). Flange: not attempted.

## Update (round 5: generated-case builders)

**Done:** `build_scale` (uniform/non-uniform), `build_split_body` (datum plane tool; generalFuse), `build_move_face` (planar offset faces with perpendicular neighbours: sweep+fuse/cut), draft with origin/datum neutral plane (anchor native + pull direction; sign verified `outward=false` -> Reversed=False on 2 cases), `build_hollow` (shell without removed faces), sweep taper (exact two-section ruled loft) and twist (sampled loft, straight paths only, whole-sketch sections), surface extrude as a static sheet of side faces, `build_thicken` (planar faces). Loft with exactly two sections is built Ruled.

**Left:** split by tool body (decoder: tool faces `native`); thicken_face: decoder's face id is the y=0 side but Fusion's mesh thickens y=20 (check decoder face selection on sheet bodies); sheet-only steps cannot match (comparator needs solids); sweep_twist and loft_two_rect_circle/offset_centers geometry is exact (mesh vertices within 1e-3 of our surface) but mesh distance exceeds 1.25*2*dev: tessellation limit of warped faces, report to coordinator; loft_three_profiles volume 4e-5 off (Fusion interpolation differs); loft rails unsupported (clear reason).

**Gotchas:** run `../build-decoder.sh` before corpus runs (the binary can be older than HEAD after a merge). Never pkill -f run_corpus (other agents' runs match); kill by cwd-checked PID.
