# features-a handoff (pattern, hole, mirror, move)

## Done
- Rectangular-pattern payload distribution block now reads when a 7-byte compact reference follows its zero byte (newer "Active" designs). The block's distance type (0 spacing / 1 extent) overrides the direction record's type; nick0451 patterns have record type 8 yet are adjacent spacing. 3 -> 20 steps on nick0451_Parametric_Battery_Case_v2.
- Direction record distance type 10 accepted (form comes from the payload; unresolved without a readable block).
- Mirror plane: a compact plane selection naming a WorkPlane scope selects that plane (it used to bind a coincidentally numbered face). PacktPublishing_Bracket_Finished 8 -> 15/15.
- Rebuilder: a hole with a single part (simple hole, no counterbore/drill point) used `Part::MultiFuse` with one shape and failed silently; the lone bore is the tool now (ravengraves_NEMA17: Hole1 built).
- Pattern active only in direction two: the one record is direction one's; direction two comes from the payload (zero payload leaves it unresolved; before it silently reused direction one).

## Round 3 (generated cases)
- Tapped holes: extended compact Thread scope now parses for Hole-owned threads (marker `F 02 00 00 00`, F=0 or 1; pitch marker = modeled). `project_hole` attaches the owning Thread (trailer names the Hole record) as a `Threaded` specification and sets the bore to the stored minor diameter (M5x0.8 6H: 4.234 mm). New loss code `feature.hole-thread-hand-assumed`. Rebuilder bores the minor diameter; modeled threads are reported as `approximation` (real helix not built): cosmetic and through cases match, modeled stays 1 step short.
- copy_body: move/copy-paste with copies=1 builds a placed compound copy; select_bodies picks among exactly coincident bodies.
- Not done, with findings: pat_rect_one_dir_extent / pat_rect_symmetric / pat_circ_symmetric: the rectangular-pattern payload in these files has no distribution block the reader accepts. Payload bytes: after `ff ff ff ff` the next byte is 1 for Extent (0 for Spacing), and the symmetric flag sits one byte before the second `01 8e` reference (`... 01 94 .. 00 01 00 01 8e`). The current `exact_rectangular_pattern_distribution` fails on these layouts (no leading zero/compact ref form); extend it. Symmetric needs IR support: LinearOffsets/CircularAngles require offsets starting at zero, so either relax to "strictly increasing, contains 0" or add a symmetric field.
- pat_rect_faces (face pattern), pat_path (curve_driven), cut_across_bodies_participants (participant bodies of a cut, kind native) not started.
- comp_extrude_in_component: truth artifact (step volumes show the final state and the Extrude2 truth mesh is the uncut box); not fixable on our side. two_components: second body volume 253.49 vs 251.33 (1%) unexplained.

## Left (ranked)
1. nick0451 R-Pattern6 (direction two only; payload V direction is zero, record displacement is x but physical layout needs y). Truth removes ~19.7k mm3, matching four seed cuts along y. Where Fusion stores the direction is unknown.
2. Move body selection native (runtimerobotics_rosbot, Ch12 tealight): the Move group's members have no `resolved_body_slot` ("3 affected body slots without a unique active body in its BREP namespace"). `history.rs` Move binding needs a single member.
3. ravengraves_NEMA17 R-Pattern1 "pattern linear unresolved", and other skipped patterns (direction unresolved: administrativetrick, kantoku mirror).
4. Dice R-Pattern2 "pattern of faces" (one pattern, 8 steps); needs face-to-tool-body mapping or face matcher.
5. Apollo Lamp_Mount_Body Hole1 (countersink, angled bottom): Fusion removes 21 mm3 more per hole than ours (about one countersink frustum). Oracle gives no hole data; suspect depth measured from the countersink bottom.

## Gotchas
- `$TMPDIR` is unset in this shell; use the scratchpad for `cadmpeg convert -o ... --force` output.
- `cargo fmt` reformats ~19 files not fmt-clean upstream; run it, then `git checkout` the unrelated ones.
- features.json has no pattern/hole/mirror data for most features (only counts for circular patterns).

## Round 4 (patterns)
- Done: rectangular-pattern distribution block read when the block carries four extra leading zero bytes (generated Active designs): gives Extent vs Spacing and the symmetric flag. Symmetric patterns with an odd count project as `LinearOffsets` / `CircularAngles` with signed offsets (seed at zero). IR change: offsets/angles must be strictly increasing and include zero (no longer start at zero); creo test string updated. Rebuilder `pattern_copies` places compound copies at explicit offsets/angles. pat_rect_one_dir_extent, pat_rect_symmetric, pat_circ_symmetric now pass.
- Even-count symmetric patterns still return no projection (layout not settled; no data).
- pat_rect_faces: rebuilder `face_pattern` re-applies the cut/join tool whose walls carry the selected faces, but the decoder resolves the historical face wrongly (face 124 is the block's x=0 plane, not the hole cylinder), so the step is skipped ("face selection unproven"). Fix the face slot resolution of the R-Pattern face group (group #51910) to finish.
- pat_path: scope PathPattern has no `path_pattern_settings` parsed for this layout (extent distance semantic of "5 instances, distance 1" unclear) and the rebuilder cannot resolve the native path group to a sketch curve. Not attempted.
- nick0451 R-Pattern6 / NEMA17 R-Pattern1: not attempted.
- Gotcha: killing a cargo build mid-link corrupts incremental output (lld undefined hidden symbol); remove target/release/incremental/cadmpeg_codec_f3d-* and deps/libcadmpeg_codec_f3d-* and rebuild. Foreground waits are backgrounded after 180 s; wait on log files with a polling loop.
