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
