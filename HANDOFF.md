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
