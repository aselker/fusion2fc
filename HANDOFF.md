# edges handoff

Done, verified, merged to main (44ef6fd): `rebuild.py` finds edges by interior point plus tangent. It handles closed edges (circle seams) and edges that OCC splits or merges. It keeps the body when OCC fails and builds the proven part of `historical_partial` selections. Al_Pipe x2 now pass. Encoder_Button 2->4 steps.

WIP (cadmpeg 05d2b75782, type-checked only): `history/chamfer_bevels.rs` gives a one-group Chamfer its edges from the transition's bevel faces. A debug run resolved 8 chamfers in 5 models. The spec and FORK.md are updated.

Root causes:
- About 90% of "edges not found" failures follow upstream profile/feature failures. Decoded edge geometry lies on Fusion's input mesh (70+ features checked).
- 8 nick0451 fillets are native because Fusion lost their references (health 2). Skipping them is correct.
- Fillet blend proof fails three ways:
  - Persisting face on a copied, identical plane carrier: N2 Fillet2/3, DINRail Fillet2.
  - Spline blend with no spine: tealight, Hook F4, DINRail F4.
  - Equal-radius groups: DINRail F3, Lego F2, appleScreen.
- Two-distance and distance-angle chamfers need a reference face (DR-341): 4 features.

Next:
1. Run the `chamfer_bevels` unit tests, then the goldens (`UPDATE_GOLDEN`), then a corpus run on the edge models.
2. Treat a persisting face whose new carrier is an identical plane as unchanged, in both proofs.
3. Measure setbacks from the bevel faces to orient two-distance chamfers.

Gotchas:
- Build f3d-only with `--no-default-features --features f3d -j 3` (about 25 min).
- `pkill -f` kills its own shell.
- Mesh oracle checks give false positives for small radii and touching bodies.

## edges agent, round 2

Done (rebuild.py, commit see git log):
- Asymmetric chamfers: `two_distances` and `distance_angle` build. The first distance goes on the face of the edge's first coedge (the face whose inward direction is n x t for the recorded edge tangent t); validated by volume on PacktPublishing_Bracket_Solid Chamfer1 (now matches) and the B10P small body. `F2FC_CHAMFER_FIRST=back` flips the convention for experiments. distance_angle uses the second leg d sin(a)/sin(theta+a).
- Degenerate fillets/chamfers: Fusion accepts a radius that consumes a whole adjacent face exactly (WilkoV Fillet1, Pizero, Lamp_Mount Chamfer1); OCC fails. The builder retries with sizes x(1-1e-7), x(1-1e-6); volume error below 1e-7 relative. Lamp_Mount 2->6 steps.
- `find_edge` no longer dies on BRepExtrema failures (`dist_to_point` falls back to sampled edge points).
- `F2FC_DEBUG_EDGES=<dir>` dumps the base body (brep) and edge list of an OCC failure.

Findings:
- badger2040 Fillet2: r=3 on an 8 mm edge whose end face is 1.6 mm wide; OCC cannot, Fusion could (unknown how).
- Co2SensorEnclosure Chamfer1 (Cover): truth volume unchanged after the chamfer (resultBodies empty); rebuild removes material. Not a rebuild bug we can fix.

- Chord-length fillets build (radius = chord / (2 sin(turn/2))). Variable radius is reported unsupported: OCC's linear law gives 981.46 vs Fusion's 981.05 (case_fillet_variable_radius).
- Default first chamfer distance is on the face OTHER than the one whose boundary runs along the recorded edge direction ("back"). That passes all 5 generated asymmetric chamfer cases; PacktPublishing_Bracket_Solid (UI-made) needs "forward" (F2FC_CHAMFER_FIRST=forward). Needs DR-341: the decoder must read the stored reference face (IR `flip_direction` exists, always false).

Left:
- andyeske_N2_Pencil Fillet2: spline blend has no radius row and only ONE support face in `treatment_face_supports` (supports=[10410]); Fillet3: a persisting face with a new non-plane carrier. A spineless-blend reading was tried (shared deleted edge of two supports) and dropped for lack of a second support.
- case_fillet_tangent_chain_off (OCC always follows tangent chains), corner_setback, corner_mixed_radii (OCC corner blend differs), asymmetric fillet (no OCC equivalent through Part::Fillet).
- badger2040 Fillet2/3 (radius exceeds the 1.6 mm end face), the rest of "edges not found" follow wrong upstream bodies.
Gotchas: run `../build-decoder.sh` from the worktree root (from elsewhere it fails silently under grep). Never splice rebuild.py with s[:a]+x+s[b:] when b may precede a.

## edges agent, round 3

Done:
- DR-341 chamfer reference face: there is no stored flip bit. The byte 21 bytes after the edge-recipe's next header (flag in the edge-operand frame) is the API's 5th argument, which make_cases.py misnames `flip`: it is `isTangentChain` for chamfers (case `*_flipped` = tangent chain on; geometry identical to the unflipped case). The decoder now measures the assignment from the exact transition (`history/chamfer_bevels.rs`, `annotate_chamfer_reference_faces`): setback of the bevel plane (or revolved bevel circle) on each planar support, matched to the stated distances, published as the feature source property `chamfer_first_faces` (`slot:first|second:origin,normal`). `rebuild.py` picks the OCC face on that plane; edges without their own entry use the group's other planes; no entry gives a clear "not recorded" refusal. The F2FC_CHAMFER_FIRST knob and the "back" guess are gone. All 5 generated asymmetric cases, PacktPublishing_Bracket_Solid (now 5/5) and Co2SensorEnclosure Chamfer (circle edge, revolved bevel) are measured.
- Fillets of unequal radii that meet at a vertex are refused (OCC corner blend differs from Fusion's: case_fillet_corner_mixed_radii).

Findings / left:
- Tangent chain: no stored signal (fillet operand flag byte is 0 in both case_fillet_tangent_chain_off and the chain-on case). A refusal when the selection leaves a G1 neighbour out regressed uwearzt_DINRailMount Fillet2 (Fusion's chain is on there and the stored selection lists only the clicked edges), so it was dropped. OCC always follows chains.
- WilkoV_03_Refinements Fillet1: radius equals both the cylinder radius and its height (Fusion yields a hemisphere, 2.0944e6); OCC "command not done" even shrunk, and the step is reported built with the body unchanged. Needs a sphere/cap special construction.
- corner_setback, asymmetric fillet and variable radius: no OCC equivalent through Part::Fillet (unchanged, asymmetric/variable refused).
- edge selection native fillets (tealight, nick0451 x8, N2_Pencil Fillet2/3): not progressed; see round 2 notes (single-support spline blend; Fusion-lost references).
Gotchas: ASM history topology has no face sense or coedge sense, so orientation rules cannot be computed in the decoder; plane identity (not orientation) is the portable way to name a face. Run cargo tests as `../cargo-locked.sh test -q --manifest-path cadmpeg/Cargo.toml -p cadmpeg-codec-f3d --lib` from the worktree root.
