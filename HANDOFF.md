# profiles agent handoff

Done (cadmpeg `f2fc-agent/profiles`): unselected extrude profiles + per-selection arrangement cap (529b2a99f1), construction flag from curve-tail flag block (b0ccd3aded), native sketch-profile operands whose stored curve selection names the sketch now resolve like unselected extrudes (fdd6206dc3; adafruit_2831 4->10/10 steps). Corpus: 42/102 models, 395/1073 steps; generated 28/29; run_cases 28/29; f3d crate tests pass.

Findings:
- "Overlapping/nested loops give wrong areas" (SG90 Extrude4): Whole loops [c1,c2] overlap, Fusion's 3 regions (lens, c1-lens, c2-lens) sum to the union area, so the decoded loops area (sum of loops) differs only because the lens is double counted. Volume is the same when the rebuild unions the loops. I tried gating whole-loop readings on an overlap test (reverted, no corpus change): area_check mismatches there are mostly a metric artifact. SG90's real failure is upstream (0 rebuilt bodies at Extrude4).
- Real area mismatches left (area_check 257/337 match): Controller_Cooler Extrude2/9, WilkoV_03 Extrude1 (8x), bitbank2 badger2040_case/co2 box/rack_mount_foot, Saurabh Crusher_Shaft (2x). Not investigated.
- Stale stored regions (Hook): Hook has no measurable case (Extrude3 is native, no truth); not done. Coincident circles (Pencil Extrude7): not done.
Gotchas: foreground commands are backgrounded after 180 s; area_check takes ~2 min with cached dumps.
