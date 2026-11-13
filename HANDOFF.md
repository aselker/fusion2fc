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
