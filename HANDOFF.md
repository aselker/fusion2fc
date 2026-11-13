# HANDOFF: fillet/chamfer cases

37 generated cases (`fillet_*`, `chamfer_*`) added to `vm/scripts/make_cases.py`, exported to
`tests/cases/`, registered as `case_<name>` in `tests/corpus/manifest.json` (generated tier, 66
models now) with per-step truth meshes in `tests/corpus/truth/`.

Regenerate (Fusion VM; never saves documents):

    python3 vm/mcp_call.py script vm/scripts/make_cases.py --include vm/scripts/dump_features.py \
        'OUTDIR=\\VBOXSVR\Shared\fusion-work\cases_new' ONLY=fillet_single_edge,chamfer_single_edge,...
    python3 tools/corpus_truth.py case_fillet_single_edge ...

Not exposed by the API (so not generated): "rule" fillets (all edges of a feature) and setback
distances per vertex; `isRollingBallCorner=False` gives Fusion's default setback corner.
`addTwoDistances/DistanceAndAngle` chamfer sets take a 5th bool (flip) after isTangentChain.

Results (main cadmpeg binary, no rebuilder changes): run_corpus 26/37 models, 125/136 steps;
run_cases 54/66 (old 28/29 unchanged; the 26 passing new cases add to it).

| Cause | Cases | First failing step |
|---|---|---|
| chamfer two-distances / distance+angle not built | chamfer_two_distances(_swapped,_flipped), chamfer_distance_angle(_flipped) | rebuild skipped chamfer spec two_distances / distance_angle (volume rebuilt = unchamfered) |
| fillet variable / chord / asymmetric not built | fillet_variable_radius, fillet_chord_length, fillet_asymmetric | skipped fillet radius variable / chordal / asymmetric |
| tangent chain off ignored | fillet_tangent_chain_off | Fusion 953.424 vs rebuilt 935.904 (whole loop rounded) |
| mixed radii at a vertex | fillet_corner_mixed_radii | Fusion 985.63 vs 987.064 |
| setback corner | fillet_corner_setback | Fusion 967.963 vs 971.295 (rolling ball built) |

# Round 2: hobby-feature cases (agent `cases`)

94 new generated cases in `vm/scripts/make_cases.py` (section "round 2"), registered as
`case_<name>` (generated tier now 160). Groups: `sk_*` (slots, polygons, sketch fillet/chamfer,
offset, fit/control splines, 3-point/tangent/sweep arcs, ellipses, construction geometry,
projection, intersect, sketch mirror/copy, dimensions driving user parameters, sketch on
face/angled/offset plane, text), `rev_*`, `sweep_*`, `loft_*`, `hole_*`, `pat_*`, `mirror_*`,
`comb_*`, `split_*`, `shell_*`, `draft_*`, `thicken_face`, `offset_face_*`, `move_*`,
`copy_body`, `scale_*`, `comp_*`/`two_components`/multi-body cut with participants.

Chamfer fix: the `chamfer_two`/`chamfer_angle` helpers passed `(True, flip)` to
`(edges, d1, d2, isFlipped, isTangentChain)`, so every round-1 case was actually flipped and
the `_flipped` ones only toggled tangent chain. Now `flip` is `isFlipped` and tangent chain is
True; the five chamfer two-distance/angle cases were regenerated (their volumes are equal
either way; the mesh differs) and truth re-recorded with `--force`.

API gaps: no tangent-arc call (`tangent_arc` helper = 3-point arc + tangent constraint); no
pattern-in-sketch (`sketch.copy` used); `isModeled` for threads is a hole-input property;
sketches on a face also yield the face outline as a profile, so those cases pick the
smallest profile. Text works (`sk_text_extrude` extrudes the SketchText).

Regenerate: same command as round 1 with `ONLY=<names>`, then copy `.f3d/.truth.json` to
`tests/cases/`, update manifest sha/bytes, `tools/corpus_truth.py <ids>` (`--force` if re-recorded).

Results (main cadmpeg binary, no rebuilder changes): run_corpus on the 94 new + 5 chamfer
cases: 53/99 models, 316/366 steps. All 5 chamfer cases pass. Failures (46) by cause:

| Cause | Cases |
|---|---|
| revolve/sweep profile kind `sketch` skipped | rev_full_axis, rev_partial_angle, rev_about_sketch_line, rev_about_profile_edge, rev_symmetric, rev_cut_groove, rev_join_flange, sweep_line, sweep_arc_path, sweep_line_arc_path, sweep_spline_path, sweep_cut_groove |
| sweep twist / taper | sweep_twist, sweep_taper |
| loft rails; loft mesh/volume tolerance | loft_with_rail; loft_two_rect_circle, loft_offset_centers, loft_three_profiles |
| split body not built | split_body_plane, split_body_plane_yz, split_body_by_tool_body |
| scale not built | scale_body_uniform, scale_body_about_corner |
| offset faces (move_face) | offset_face_press_pull, offset_face_side_inward |
| draft face selection native | draft_side_faces, draft_single_face |
| shell whole body (face selection) | shell_whole_body |
| ellipse / text profile selection | sk_ellipse, sk_ellipse_rotated_cut, sk_text_extrude |
| holes: through-all and tapped | hole_simple_through_all, hole_tapped_through (volume = unholed), hole_tapped_cosmetic/modeled (thread volume) |
| patterns | pat_path, pat_rect_faces, pat_rect_one_dir_extent (extent distance), pat_rect_symmetric, pat_circ_symmetric, mirror_feature_mid_plane |
| copy/paste body | copy_body |
| components | comp_extrude_in_component, two_components (volume off ~1%) |
| cut participants (native) | cut_across_bodies_participants |
| surface extrude | thicken_face |
