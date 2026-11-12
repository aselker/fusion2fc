# geometry agent handoff

Done, verified (merged as 6d8d854): from-face start offset; rational sketch NURBS; join touch tolerance 1e-5 mm (Bracket_Finished); redundant sketch constraints removed (SCD41 Extrude7 sketch had 0 edges); unresolved sketch binding skipped.

In progress, cadmpeg WIP commit (check passes; unit tests, release build, corpus NOT run):
1. Construction flags: decoder found 1 of ~350 construction curves. Layout depends on base type 9FF71F46 version 7/8/9. Construction lines then join profile loops: root cause of Co2SensorEnclosure Extrude4 (13 construction curves) and Lego sketches without profiles; likely many "profile kind sketch(_selection)" skips.
2. Lock_B_Side sketches 1-4 (+5 native extrudes): head records of 24/152 bytes (null closing reference) were rejected.

Next: (1) run `cargo test -p cadmpeg-codec-f3d --lib -- curve_tail member_run placement sketch_project`, release build, full corpus; (2) regenerate layout docs (`UPDATE_LAYOUT_DOCS=1 cargo test --release -p cadmpeg --test layout_tables`); goldens may change; (3) SCD41 Extrude3: OCC keeps edge-touching solids separate, Fusion makes one non-manifold lump (report, comparator counts solids).

Gotchas: rebuild-only work can use the baseline binary with `--cadmpeg`. Python tools in the scratchpad are gone; record offsets come from the CADIR native_ref.
