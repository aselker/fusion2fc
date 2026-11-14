# profiles agent handoff (second pass: plain sketch -> extrude failures)

Triage of the 25 models whose first failing step is a built Extrude with wrong volume/bodies.
Fusion volume vs rebuilt volume; "stored loops" = the sketch `profiles` loops the decoder emits.
Causes: R = wrong profile region (Fusion's selected regions are arrangement pieces; stored
loops/indices are whole loops, stale after later sketch edits, or incomplete), X = overlapping or
crossing loops built wrongly by the rebuilder (fixed), D = through-all direction, T = tiny volume
diff, N = no oracle profile.

- AdamLaskoi_SG90@Extrude4: X (two overlapping circles, face maker failed -> empty join). FIXED 8->15 steps.
- digitalsputnik_Apollo_Yoke_Int_Corner@Extrude1: X (hole circles cross the outer rect). FIXED 1->3; next Extrude4 is T (48994.7 vs 48994.2).
- PacktPublishing_3_1@Extrude3: D (through-all cut met no body; flipped now, cut hits the right body but also a second body Fusion left alone). Still fails.
- WilkoV_03@Extrude1: R (stored loop 4 = r10 circle, Fusion extrudes 2 sectors of circle/line arrangement).
- adafruit_1739_Pizero@Extrude2: R (stored 1 loop = circle; Fusion also selected the 0.37 cm2 piece of the keyhole outside it).
- adafruit_2278@Extrude2: R (stored two 113 cm2 loops; Fusion also has two 2.4 cm2 pieces).
- administrativetrick@Extrude1: R/N (stored 3x3 square 9 cm2; Fusion volume is 2.88 cm2; oracle profile is an error).
- bitbank2_badger2040_case@Extrude3: R (stored index 0 = outer 41.6 cm2 loop; Fusion extrudes 3 small pieces, 2.97 cm2).
- bitbank2_co2_01space_box@Extrude18: R (outer 6 minus 9 holes; Fusion extrudes 3 small pieces).
- bitbank2_oled_cover@Extrude2: R (outer 1 minus hole 0 = 7.2 cm2; Fusion four small pieces, 1.17 cm2).
- bowenchristopher@Extrude1: R/X (outer minus 12 hole loops built from trimmed-derived curves, areas 0 in the face builder; 8% too much volume).
- busraakgun24_kol@Extrude4: R (trimmed region 1.4 cm2 only; Fusion cuts 1.4 + 1.8).
- digitalsputnik_16mm_Claw@Extrude1: R (loops 0,3; Fusion has 6 pieces, 3.72 vs 3.33 cm2).
- Apollo_Yoke_Lamp_Mount@Extrude1: R (stored 24.2 cm2 loop; Fusion's 5 pieces total 17.2, one 7.0 cm2 inner piece is not selected).
- Apollo_Yoke_Lock_B_Side@Extrude2: R (loops 0,1,2; Fusion 4 pieces, less area).
- Apollo_Yoke_Lock_P3@Extrude1: R (28-profile arrangement; outer loop minus 2 circles vs Fusion 4 pieces 3.5 cm2).
- Controller_Cooler@Extrude2: R (loops 5,7,9,3 give 5 bodies; Fusion 1 body from 6+ pieces).
- digitalsputnik_Nupud_T1 / Nupud_T_v2@Extrude1: T (356.238 vs 356.239, 805.296 vs 805.277; not chased, likely Fusion's volume tolerance/spline approximation).
- digitalsputnik_T_bel_T2@Extrude2: N (oracle profile is an error); stored outer 5 is a hexagon inside hole circle 0, nonsense nesting.
- digitalsputnik_Tihend_v4@Extrude1: R (stored one 0.905 cm2 loop; Fusion selects 6 pieces, 1.2055 cm2, four 0.075 pieces missing).
- gtgkartik_Industrial_Tool_2@Extrude1: R, stale loops (stored outer rect + hole = 69.12 cm2; a later slot splits it; Fusion = piece A 36 + piece B 54.86).
- homebrew_pinball_Seven_LED@Extrude1: R (selection [4,5,1]; Fusion 6 pieces from overlapping loops, one body).
- intuibase_SCD41Chamber@Extrude3: R (trimmed regions leave two sliver bodies Fusion does not have).
- ravengraves_NEMA17@Extrude1: R, stale loops (stored square; four chamfer lines added later; Fusion = octagon piece).

Counts (initial triage): R 19, X 2 (+1 R/X), D 1, T 2 (+1 after fix), N 2 (overlapping R).

## Done (this pass)
- cadmpeg `unselected_extrude_profile`: the recorded curve selection now outranks the history
  transition (which can only name whole stored loops). Fixed the first extrude of WilkoV_03
  (4->7), badger2040 (2->6), oled_cover (3->6, passes), Lamp_Mount (1->2), NEMA17 (1->2),
  gtgkartik (2->3), and with the rebuild fixes below SG90 (8->18) and Int_Corner (1->3).
- rebuild.py: `overlapping_profile_union` (partly overlapping whole loops build a union face),
  `crossing_loops` (a hole loop crossing its outer loop builds by boolean cut), circle pieces
  merged back to one closed edge when nothing else meets the split point (keeps later fillets
  working: Disc_P2, adafruit_2831 regressed without it), through-all cut that meets no body is
  flipped.
- Corpus: 43/102 models, 420/1073 steps (baseline 42/395); generated 28/29; run_cases 28/29;
  cargo test -p cadmpeg-codec-f3d passes. No model lost matched steps.

## Third pass (why recorded_curve_selection_profile returned None)
Root causes found with temporary eprintln builds (removed), fixed in cadmpeg 929e4ccf7c:
1. Shared arrangement budget (Tihend, Lock_P3, Claw, 2278): each region of a multi-region
   selection rebuilt the whole sketch arrangement and charged the 1M per-selection cap again.
   Faces are now cached per selection (`ProfileGeometryWork::curve_faces`).
2. Stored loop lists a split curve's pieces out of walk order (Tihend 16-curve face): the
   unique face with the same curve multiset is taken (`arrangement_region_matching_curve_set`,
   reports FeatureProfileLoopFlagsAssumed).
3. Lines with an in-plane stored normal were dropped from the sketch (Tihend 209/230).
4. Curves with no constraint had no owner: the curve record ends with a typed container
   reference (flag, u64, GUID string, 2 zero bytes) that was not read (Pizero circle 104).
Results: Tihend 1->2/2 (passes), Lock_P3 1->13/14, Claw 1->4/12, 2278 2->4/5. Corpus 43/102
models, 432/1073 steps (generated 28/29, run_cases 28/29, cargo test passes, no regressions).

## Still failing at an Extrude, by DBG exit (before fixes; counts are models)
- L4363 `!single_exterior` multi-loop region with no ring match (bowenchristopher, Controller_Cooler,
  Seven_LED): a region with holes whose rings do not match faces; same order issue likely applies
  to `arrangement_regions_matching_member_rings` (try multiset matching there).
- L4280 curve selection does not resolve (co2_box, Lock_B_Side, Controller_Cooler, Seven_LED): a
  program curve is missing/point (Lock_B_Side: curve 1231 has no identity record).
- Pizero: selection names derived piece ids (106, 123, 126, 128, 130) that exist as no stored
  curve (second-generation split pieces); needs wildcard ring matching on the known parents.
- administrativetrick: no counted group (oracle profile is an error).
- busra_kol, SCD41, WilkoV later steps (Fillet) not traced.

## Left (ranked by models blocked at an Extrude)
1. R, 14 models still: Pizero, 2278, administrativetrick, co2_box, busra_kol, Claw, Lock_B_Side,
   Lock_P3, Controller_Cooler, Tihend, Seven_LED, SCD41, bowenchristopher, WilkoV later steps.
   For these the recorded selection either does not resolve (Tihend, Pizero still take the
   transition result) or resolves to the wrong pieces; next step is tracing why
   `recorded_curve_selection_profile` returns None for them (needs a debug eprintln build).
2. T: Nupud_T1/T_v2 (1e-5 relative), Int_Corner Extrude4 (48994.7 vs 48994.2), SG90 Extrude9.
3. PacktPublishing_3_1 Extrude3: flipped through-all cut now hits, but also cuts a second
   body Fusion left alone (participant bodies not decoded).
4. T_bel_T2 Extrude2: oracle has no profile; stored outer loop (hexagon) lies inside its "hole".

## Gotchas
- Foreground commands are backgrounded after ~120 s here; poll with short timeouts.
- handoff-tools/area_check.py is stale against the current rebuild.
- No Rust unit test was added for the ordering change (needs a fixture with both a recorded
  selection and a history transition); the corpus gain is the evidence.

# Fourth pass (profiles agent, Sonnet): root causes by decoder exit

Method: temporary eprintln builds (reverted) at every exit of the extrude profile binder
(`profile_select.rs`), `resolve_profile_curve_arrangement_regions`, and the arrangement builder.
Findings, in order of models affected:

- `profile kind sketch` skips (rack_mount_foot, B10P/B2PS_VH, Crusher_Shaft): the extrude scope has no
  counted selection group and the recorded curve selection did not resolve, so the decoder left the bare
  sketch reference. Crusher_Shaft selects every region of its sketch (nested circles) -> rebuild now
  extrudes all loop regions for a bare `sketch` (`bare_sketch_regions`). B10P/B2PS: the sketch decodes with no
  closed loops at all (curves "not part of any closed profile loop"), still open.
- rack_mount_foot: Fusion keeps a 0.19 um line between two arcs (and a 0.1 um arc piece). With the 1e-5 mm
  tolerance the exact arrangement refuses the sketch (edges "meet other than at nodes"/not separated), so no
  region resolved. Fixed in cadmpeg: `curve_arrangement_faces` retries at 100x tolerance (drops lines under
  that, merges nodes), same-circle arc test tolerant to float noise, programs also matched without slivers.
  1 -> 16/16 steps.
- Exit counts seen on the remaining models (line numbers of the pre-edit tree): arrangement budget exhausted
  (`arrangement.exhausted()`; co2_box, Lego_20x20, Cooler), `certified_pieces_separated` false for edges with
  no shared node (busra_kol, SCD41, co2_box, Lock_B_Side), member-ring match finds no face (Seven_LED, Claw,
  Tihend, 2278), `!single_exterior` multi-loop region (bowenchristopher, Cooler, Seven_LED), no counted group
  and no curve selection (administrativetrick, Lego_2x4).

## Fourth pass result (final binary)
Corpus 76/139 models, 592/1209 steps (baseline 75/575); generated 60/66; run_cases 60/66. No model lost steps.
Gains: bitbank2_rack_mount_foot 1->16/16 (micrometre-sliver arrangement retry), Saurabh_Mudgal_Crusher_Shaft 3->5
(bare sketch profile extrudes every loop region; next failure is a Base Feature, not profiles).
Also added (no corpus change measured): `sketch_arrangement_faces` retries with crossing nodes for stored loops whose
whole curves cross (busra_kol/SCD41 showed `certified_pieces_separated` failing on a line crossing a line without node).

## Left / next (profiles)
1. busra_kol Extrude4: the nested region operand resolves 1 of its 2 regions (exit 791/896 of the extrude binder).
2. B10P/B2PS_VH: sketch decodes with no closed loops (many projected/construction lines) -> no profile at all.
3. Arrangement work budget exhausted (co2_box, Lego_20x20, Controller_Cooler): `arrangement.exhausted()`.
4. `!single_exterior` regions with no ring match (bowenchristopher, Cooler, Seven_LED); derived piece ids (Pizero).
5. sketch_selection skips (2BC, Cake_v2, hook_sogou, TimingPulleyBase): `unresolved_region_operand` exit 977.
6. Sweep/Revolve `profile kind sketch` (S_Hook, Metal_Post, k_recik): the rebuilder's sweep/revolve do not take
   the bare-sketch path added for extrudes (`bare_sketch_regions`); not attempted.
## Gotchas
- The scratchpad dir and `../edges/tests/out` are shared/live: compare against `tests/corpus/baseline.json`.
- Debugging recipe: sed `eprintln!("DBGX {}", line!())` before each `break 'feature_edit` and in the arrangement
  builder's `return Ok(None)`/`geometric!`; ~4 min build via ../build-decoder.sh.

# Fifth pass (profiles agent, Sonnet): revolve/sweep/ellipse/text
Done:
- rebuild.py `bare_sketch_profile`: a `sketch` profile (no selection) now serves revolve (`profile_base`) and sweep sections (`profile_loops`) through `bare_sketch_regions`. Sweep: a closed-loop binder (Compound of edges) becomes a face for the centre/at-start test; path-start tolerance 1e-4 mm (Fusion paths start 1.5e-5 mm off the profile plane). All 7 case_rev_* and case_sweep_{line,arc_path,line_arc_path,spline_path} pass; corpus busraakgun24_k_recik 1->4, Metal_Post 2->4.
- cadmpeg `SketchCurveGeometry::Ellipse` (see FORK.md) + rebuild.py `full_ellipse`: case_sk_ellipse, case_sk_ellipse_rotated_cut pass.
- case_sk_text_extrude: rebuilder now says "profile selects sketch text: glyph outlines come from the font and are not stored" (no outline data in file).
Left:
- case_sweep_cut_groove: Sweep path decodes as `historical_edges` (id suffix = the path sketch curve 115, resolves to a block edge) instead of `sketch_curves`; also the profile is off the path (Fusion sweeps along the path direction/length from the profile). features-b lane.
- S_Hook: "profile sweep along a path with corners" (profile sections only mitred for generated pipes).
- Metal_Post Extrude1, k_recik Hole1, kantoku BaseFeature: other areas/not traced.
- sketch_selection `unresolved_region_operand` models (2BC, Cake_v2, hook_sogou, TimingPulleyBase) not touched this pass; bounded ellipses and ellipses in arrangements not handled.
Gotchas: zipfile cannot read the .f3d (zstd); use `unzip -p`. Ellipse vs circle: 13th f64 of the payload.
Result (final binary, cadmpeg 73d0578f2b / fusion d82e133+): corpus 141/233 models, 948/1560 steps (baseline 128/930); generated 123/160; supported 12/28; extended 6/45; run_cases 127/160; no model lost steps; cargo test -p cadmpeg-codec-f3d passes.

# Sixth pass (profiles): unresolved region operands
Done (cadmpeg 583bb921c1): a counted region operand whose members name curves a later sketch edit replaced (member primary id has no stored curve) made the history-transition candidate fail `planar_selection_agrees_with_region_operand`. Now agrees when >= half of the members survive and exactly one stored loop holds them all (same member count, or a >= loop when members were replaced). PacktPublishing_2BC 3->6 steps (next fail: Mirror body selection), onlinelei_hook_sogou_v1 1->4 (next: Fillet 715.09 vs 713.79).
Diagnosis of the rest:
- ravengraves_TimingPulleyBase Extrude2: operand has 11 members, ~6 replaced; stored loops are 3 single circles; transition candidate is a Loops region with a hole, which the agreement check never accepts (only hole-free Loops). Needs ring matching against the arrangement with wildcard members.
- andyeske_Cake_v2 Extrude8: `transition_profile_selection` returns None; `curve_arrangement_faces` exit (geometry.rs `geometric!` at the arrangement call) also fires. Not traced further.
- ulikoehler B10P/B2PS: not touched.
Final binary numbers: corpus 154/233 models, 968/1560 steps (generated 136/160 steps 562/593; supported 12/28 steps 126/220; extended 6/45 steps 280/747); run_cases 140/160. No model lost steps vs tests/corpus/baseline.json (old baseline; main already had other agents' gains).

# Seventh pass (profiles): diagnosis only, no code change
- ulikoehler_B10P_VH / B2PS_VH Extrusion3 (`profile kind sketch`): the sketch (842) holds many overlapping/duplicate collinear lines and construction copies, so no closed stored loop exists, the extrude has no counted group and no curve selection, and `transition_profile_selection_step` ends at the `unique_multi_face_deleted_carrier_family` exit (its cap-face path needs `sketch.profiles`). Fusion extruded one profile (area 11.96 mm2). Fix needs cap-face matching against arrangement regions (not loops) for sketches without loops.
- andyeske_Cake_v2 Extrude8: `transition_profile_selection` exits at the chain walk (`chain.last() != previous_state_id`); raising the 8-step cap to 24 changed nothing (tried, reverted), so the previous state is not on the end state's transition chain (branching history).
- TimingPulleyBase: needs wildcard ring matching against the arrangement (candidate has a hole region, agreement check accepts only hole-free loops).
- sogou Fillet1 (715.09 vs 713.79 mm3): extrude passes, so not a profile problem; not traced.

# Eighth pass (profiles): extrudes that build with the wrong shape
Classification of first failures (Fusion volume vs rebuilt), from main's result.json:
| model / step | class | note |
|---|---|---|
| bitbank2_co2_01space_box Extrude18 | wrong region | new body: Fusion extrudes 3 small pieces (0.085+0.086+1.94 cm2), rebuilt the big outer region |
| busraakgun24_kol Extrude4 | wrong region | cut: Fusion 1.4+1.8 cm2 pieces, rebuilt only 1.4 (nested region operand resolves 1 of 2) |
| 16mm_Claw Extrude1 | wrong region | Fusion 6 pieces (3.72 cm2), rebuilt 3.33 |
| Controller_Cooler_P2 Extrude2 | wrong region / body count | join: Fusion fuses 4 small discs + 5.33 cm2 piece into 1 body; rebuilt leaves 4 loose discs |
| Seven_LED_Insert Extrude1 | wrong region / body count | 6 pieces from overlapping loops, rebuilt 3 bodies |
| gtgkartik_Industrial_Tool_2 Extrude2 | wrong region (stale loops) | cut volume differs 205548 vs 194232 |
| Int_Corner_P2 Extrude4 | tolerance | 48994.7 vs 48994.2 (1e-5 relative), geometry equal |
| Lock_B_Side Extrude2 | wrong region/participants | cut removed the whole body (0 vs 8256): now REFUSED |
| Metal_Post Extrude1 | tool misses body | cut met no body (sketch at pipe end, reversed direction, profile 1 of two circles): now REFUSED; cause not traced |
| T_bel_T2_v3 Extrude2 | tool adds nothing | join of a ring region (outer 5, hole 0) added no volume (Fusion +937 mm3): now REFUSED |
Not looked at: administrativetrick, Tihend, bowenchristopher, 2278, Pizero (known region causes in earlier passes).
Done: rebuild.py `apply_op` refuses (ValueError, bodies left as they were) a cut/intersect whose tool meets no body, a cut that removes a whole body, and a join that adds no volume, for extrude/revolve/sweep features only (patterns excluded). No matched step lost; it turns three silently wrong builds into reasoned refusals.
Left: the wrong-region class needs the decoder to resolve the selection uniquely (see earlier passes); the rebuilder cannot tell a wrong region from a right one without the Fusion volume.

# Ninth pass (profiles): wrong-region class, one attempt
- co2_box Extrude18: root cause `transition_inserted_profile_selection` (profile_select.rs) built the region (outer 6 + all 9 holes) from outer-loop support alone, logging `FeatureProfileRegionHoleInferred`. Of the 9 models carrying that loss, 5 fail at an extrude (co2_box, kol, bowenchristopher, SCD41, Seven_LED). Now every hole must bound a selected face, else None -> profile stays `sketch` -> rebuilder refuses ("skipped profile kind sketch"). The two passing models with the loss (NeoPixel_Jewel, case_sk_offset_curves_ring) still pass. Unit test updated (outer-only support now refuses).
- kol Extrude4 and Claw Extrude1 NOT fixed: kol's trimmed region (1 of the 2 selected pieces) and Claw's loops [0,3] do not come from that path (kol has the loss but its fault is the 1-of-2 region resolution; Claw does not carry it). A generic idea not tried: compare the recorded region count with the resolved one and refuse on mismatch.
- Numbers (final binary): corpus 156/233 models, 970/1560 steps (generated 138/160 564/593, supported 12/28 126/220, extended 6/45 280/747); run_cases 142/160; f3d lib tests 4225 passed. No change in matched steps; co2_box now a refusal rather than a wrong build.
