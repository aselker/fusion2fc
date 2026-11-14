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

## Update (round 6: decoder face-selection gaps; no Rust change)

Findings (no code change; debug prints removed):
- Draft face selections are no longer "native" (rebuild resolves origin/datum neutral planes from the recorded pull direction).
- split_body_by_tool_body: the tool group has role 0x21 with an entity selection of a *body* (not a work plane). `SplitBodyTool` has only `Faces`/`Plane`, so a body tool needs either an IR variant (touches IR, schema, goldens) or the tool body's faces listed as a `FaceSelection::Historical` (like `list_thicken_whole_bodies`). Not done.
- thicken_face: the face operand's own record says active face slot 22 (boundary at y=0, neighbours 14 and 32, identical for the y=20 face), yet Fusion's mesh thickens y=20..21.5. The decoder follows the file; a ground-truth check (VM) of which face `faces.item(0)` is would settle whether the file's slot or the case script is right. Candidate faces in the operand: entity 11, 14, 22, 32.
- appleScreen Shell3: `face_selection_state` returns None because the scope is not in `scope_histories` and `unique_history_state_pair(212, 211)` is ambiguous across histories (printed from instrumented build). Needs scope-to-history binding for this scope (`bind_scope_histories`), not the shell wall logic.
- Hook Thicken1 and digitalsputnik Draft2/3 fail on upstream rebuilt-body mismatches, not on selection.

## Update (round 7)

**Done:** split by tool body (decoder lists the tool body's faces from the body recipe operand: `bind_split_tool_body_faces` in history.rs; rebuild splits each target into its parts inside/outside the tool and keeps the tool). Sweep path: an entity selection whose primary identity is a Sketch now resolves to `sketch_curves` even when its secondary identity equals a history edge slot (projection had already produced `historical_edges`; `bind_sweep_sketch_selections` now also replaces those). Rebuild: sweep of a profile that is off a straight path translates it along the path vector.

**Not done (reasons):**
- appleScreen Shell3: instrumented build showed `bind_scope_histories` is never reached for scope #65139 (`scope_candidates` empty: no history holds the pair 212/211 by the direct or chained relation), so no unambiguous binding exists without guessing. Needs the history layout of that model examined (probably the 211 state lives in another history).
- thicken_face: truth `features.json` has no face data for the thicken (only result bodies); the face operand records active face 22 (y=0). Fusion's mesh thickens y=20..21.5. Unresolved without the VM.

## Update (round 8)

**Done:** Move with a native body selection (rosbot: 8 -> 26/26 steps): `bodies_by_recorded_centers` matches rebuilt bodies by the result `body_centers` source property minus the translation (every recorded body must match exactly one rebuilt body; otherwise the old skip stays). Rebuild-side only; the decoder cannot bind these bodies because the three body-recipe operands list candidate faces of three different `.smbh` BREP blobs with no `preceding_*` resolution.

**Diagnosed, not done:**
- case_cut_across_bodies_participants: Extrude4 stays `native` because `scope.extrude_prologue()` is None (first `None` return in `project_extrude`, found with a line-printing build). The scope carries nine `reference:N` records (participant bodies) that the prologue parser (`records/feature/extrude.rs`, `DesignExtrudePrologue`) does not accept. Needs the byte layout of an Extrude prologue with a participant list, then a participants field in the IR (`FeatureOperation::Extrude` has none) or a source property; the rebuilder already limits cuts by `participants` when it is given. `affected_bodies` (2,3) in the feature's source properties equals the participant set.
- Derived Base Feature (Connector_Bracket 19 steps, Example_B 12): the snapshot body lives only in the history state transition (spec f3d.md: "result bodies form a stored snapshot"). Rebuilding it needs the BREP of a historical state, which means replaying the ASM delta states into a body (the decoder exports only the active BREP). That is a decoder project of its own; the rebuilder side (`build_base_feature`, `F2FC_BODIES`, `tools/stored_bodies.py`) already accepts one stored body per feature.

## Update (round 9: participant extrude, not pinned down)

case_cut_across_bodies_participants Extrude4 (class 403, frame 471, nine references, count offset 268; the ordinary one-sided class-403 scope has frame 427 and five references) stays native. Line-printing build: the prologue parse (`exact_current_extrude_prologue_with`, scopes/extrude.rs) reaches the DR-117 refusal ("target option zero with a second-side payload", ~line 1258) and returns None; a closure check near line 1211 (first-side target ordinal) also misses. So the four extra references (44 bytes) are read as a first-side target payload, which DR-117 leaves undefined. The participant list assignment (which of the nine references name the participant bodies, what the target option and second-side payload words mean for a through-all cut with participants) needs controlled Fusion variants (one, two, and all participants; both directions); the VM is paused. No code change this round. Source property `affected_bodies` ("2,3") of the feature already lists the participants and body_centers lists the bodies; once the prologue parses, the rebuilder can cut only the bodies whose recorded centers match (same method as `bodies_by_recorded_centers`), without an IR change.

## Update (round 10: participant cuts)

**Decoded from the five participant cases (scope = last Extrude, class varies):**
- The participants are the members of the construction operand group with role 0x8 (scope reference ordinal 0); each member is a body-recipe operand whose `preceding_body_slots` is the participant body slot (across: [2,3], one: [2], all: [1,2,3], blind: [1,3], reverse: [1]). The feature's source property `affected_bodies` equals this list in all five cases.
- A role 0x5 group with one body member appears for through-all cuts with participants (one: slot 3, across: 3, all: 3, reverse: 1): the farthest body in the cut direction; the decoder reads it as a `to_shape` termination (the 8-reference scopes parse). The blind cut has no 0x5 group.
- Why across (9 references) and all (10) stay native: the prologue stores, before the first-side extent, a u32 "ordinal" of the 0x5 group's record that is 4 in all four through-all cases, while the group's index in the scope reference list is 4 (one, reverse), 5 (across), 6 (all). The closure at scopes/extrude.rs ~1211 requires `reference_members[ordinal] == record`, fails, and the DR-117 refusal follows. Two readings fit: ordinal = index - (participants - 1) (the participant list counts as one entry), or the constant 4. Needs a variant with a different number of references before the 0x5 group (for instance a 0x41 group with two members) to choose; not guessed.

**Rebuilder (done):** `participants_from_centers` limits cut/intersect extrudes to the bodies named by `affected_bodies` (slot to body by the recorded `body_centers` = bounding-box centers, unique matches only); to-shape extrusions travel against the recorded direction when the decoder's `extrude_to_distance` is negative. case_cut_participants_one, _blind, _reverse now pass; across and all still need the decoder ordinal rule.

## Update (round 11)

**Done**
- thicken_face selection (decoder, face_resolve.rs `history.rs` rule scoped to Thicken scopes (first face reference sets the unreferenced lane)): the first face reference of a bounded-face recipe (here token 6 = face 11, the y=20 face) names the selected face. The old "unreferenced candidate" lane picked face 22 (y=0). The rule is scoped to Thicken scopes because solid-body bounded-face recipes (unit tests in history/tests/fallback_faces.rs) name the selected face as the unreferenced one. Thicken1 now matches (case_thicken_face 2/3; Extrude1, the sheet-only step, is the comparator's limit).
- S_Hook_Sweep_Final Sweep1 (7/7): profile sweeps along paths with corners use OCC `makePipeShell(..., transition=1)` (right corner = mitre); a profile lying inside the path (extent fractions 1 and 1) is swept both ways and the halves fused (`sweep_both_ways`).

**Participant extrude ordinal (across/all):** no corpus model or generated case separates the readings. Every parsed scope with first_side_target_ordinal has the identical structure (g8@0 x1, g41@2 x1, g5@4 x1, 8 references, stored ordinal 4); across/all differ only by participants (stored stays 4, group index 5 and 6). Readings: (A) stored = index - (participants - 1); (B) constant 4. A Fusion variant that separates them: a through-all cut with participants whose scope has a different number of references before the 0x5 group, e.g. participants on a cut whose start is "from object" or whose sketch plane is a body face (adds/removes the 0x41 group member), with 1 and 2 participants.

**Loft7 (Handlebars):** neither the decoder nor truth records which profiles of the multi-profile section sketches are lofted (decoder says "whole sketch"). Needs the decoder to read the profile selection of each loft section.

## Update (round 12: participant extrude ordinal)

Eight participant cases decoded (slot 6 reference = the 0x5 target group record; stored ordinal read after the extent slots): stored ordinal is 4 in all seven through-all cases (one, reverse, face_one: group index 4; across, face_two: 5; all: 6; from_object_two: 8, with a 0x11 group and a standalone reference before it). The "index - (participants - 1)" reading predicts 7 for from_object_two, so it is refuted; the constant 4 fits all. The decoder now requires only that the target record is a scope reference at index >= the stored ordinal (scopes/extrude.rs), and `project_extrude` falls back to the scope's only 0x5 group when no group's scope reference ordinal equals the stored one. All eight participant cases pass (across, all, face_one, face_two, from_object_two, one, blind, reverse). Rebuilder: `participants_from_centers` also accepts "all bodies".
