# fusion2fc progress notes

Status as of 2026-11-13 (evening). Read this first when resuming. It is written for a fresh session or a
different agent, and assumes no memory of earlier conversations.

## Goal

Convert Autodesk Fusion `.f3d` designs to parametric FreeCAD documents that keep the feature
timeline. The user's target is a converter that passes every corpus test, or failing that, one
whose remaining gaps "won't bite during normal hobby-scale usage". Fillets are mandatory,
because nearly every design uses them. When a design can't be rebuilt fully, the converter must
still give the right shape and say what was lost, never quietly give wrong geometry.

## Rules from the user (still in force)

- Never edit any existing `.f3d`/`.f3z` file. The user has work in some of them. Copy a file
  before modifying it.
- Never push to cadmpeg's repository, and make no AI-generated pull requests upstream. Nothing
  in this repo has been pushed yet: `main` and cadmpeg's `fusion2fc` branch are local only. Ask
  before pushing anything anywhere.
- Never save documents in Fusion. Export archives to local files and close documents with
  `doc.close(False)`.
- Ask before using the Fusion VM. It was allowed for generating test cases on 2026-11-12/13.
- Keep the user's email and personal details out of anything sent to outside services.
- Builds must not exhaust memory. Run cargo only through `.worktrees/cargo-locked.sh`: two
  concurrent runs, 6 jobs and a 14 GB cap each. The VM uses about 17 GB while it runs. Run
  corpus jobs under `nice` with `-j 2` per agent.
- Usage: the user is on Claude Pro. Short Sonnet agents with tightly scoped prompts work well.
  Sonnet limits reset every 5 hours and weekly, and the user wants that capacity used. Keep the
  coordinating session lean, and compact it or start fresh from these notes.
- Don't loosen the corpus comparator or its tolerances. Report suspected comparator problems to
  the user (see "Comparator questions" below).

## Pipeline

1. `cadmpeg/` is a private fork, branch `fusion2fc`, written in Rust. It decodes the `.f3d`
   into CADIR JSON. The codec is in `crates/cadmpeg-codec-f3d`, the format notes in
   `docs/formats/f3d.md`, and the fork changes in `FORK.md`. Read `cadmpeg/AGENTS.md` before
   editing Rust.
2. `tools/slim_cadir.py` slims the CADIR.
3. `fusion2fc/rebuild.py` runs under `freecadcmd` (FreeCAD 1.1, Python 3.14) and rebuilds the
   design feature by feature.
4. `tools/convert.py DESIGN.f3d [OUT.FCStd] [--no-fallback]` is the user entry point. It prints
   a conversion report covering what was built, skipped and failed, and whether the result
   matches Fusion's final shape. If anything is incomplete, it adds Fusion's stored final
   bodies as "Fusion final shape (not parametric)". It also warns when the file has
   format/ASM/record versions outside `fusion2fc/known_versions.json`; regenerate that with
   `python3.14 tools/survey_versions.py --write`.

## How progress is measured

- **Corpus:** `tests/corpus` (see its README) holds 233 models and 1,560 timeline steps. Fusion
  truth for every step is in `truth/<id>/`: `steps.json`, Fusion meshes, and `features.json`,
  which is a Fusion API dump in cm, used as an oracle only.
  - A step matches when the solid body counts agree, the sorted volumes agree to within 1e-6
    relative, and the two-sided mesh distance is within 1.25 × 2 × the deviation.
  - Tiers:
    - `generated` (160): small Fusion-made cases from `vm/scripts/make_cases.py`, each
      isolating one feature;
    - `supported` (28);
    - `extended` (45), real public models.
  - `nice python3 tools/run_corpus.py [IDS] [--tier T] -j 2 [--cadmpeg PATH] [--out DIR]`
    writes `tests/out/corpus/<id>/{result.json, report.json, rebuild.log, ...}`. The CADIR dump
    is cached per binary, and step comparisons are cached per rebuilt geometry. A full run takes
    about 40 minutes at `-j 4`.
  - The baseline is `tests/corpus/baseline.json`, which is per model `{match, steps}`.
- **`tools/run_cases.py`:** an older volume-only suite over `tests/cases`.
- **Generated cases:** these are the best measure of whether normal hobby use works. In real
  models one early failure makes every later step fail too.

## Numbers

| Point | Models | Steps | Notes |
|---|---|---|---|
| Start (2026-11-11) | 32/102 | 257/1073 | |
| After profile + geometry decoder work | 40/102 | 364/1073 | |
| After WIP integration, early extrudes, regions, shell | 43/102 | 439/1073 | |
| + 37 fillet/chamfer cases | 69/139 | 564/1209 | |
| After fillet rounds 1–2, loft | 76/139 | 585/1209 | |
| +94 everyday cases, profiles/patterns round 3 | 128/233 | 930/1560 | generated 110/160 (535/593 steps), supported 12/28, extended 6/45; run_cases 114/160 |
| round 4/5: scale, split, offset face, draft, shell, sweep taper/twist, tapped holes, copy body, whole-sketch revolve/sweep, ellipses) | 154/233 | 962/1560 | generated 136/160 (562/593 steps), supported 12/28, extended 6/45; run_cases 140/160 |
| + split by tool body, off-path sweep, region operands with replaced curves, rosbot Move, honest cut/join refusals, 4 participant-cut cases) | 157/237 | 1025/1601 | generated 138/164 (601/634 steps), supported 12/28 (126/220), extended 7/45 (298/747); run_cases 143/164 |
| + participant cuts, symmetric/extent patterns, co2_box region refusal) | 164/237 | 1032/1601 | generated 144/164 (607/634 steps), supported 13/28 (127/220), extended 7/45 (298/747); run_cases 146/164; f3d 4225, IR 1938, creo 2646 lib tests pass |
| + NEMA17 type-10 pattern directions) | 164/237 | 1052/1601 | extended 7/45 (318/747); others unchanged |
| **Current main** (+ thicken face, cornered sweeps, exact-surface comparator fallback, 3 more participant cases) | **169/240** | **1085/1631** | generated 148/167 (639/664), supported 13/28 (127/220), extended 8/45 (319/747); 3 steps matched by the exact-surface check, 0 by labels |

## What works now (merged on main)

- **Sketch profiles:**
  - region arrangement, unselected profiles, stored selections ahead of history loops;
  - nested and overlapping loops, construction flags, native operands;
  - micrometre sliver curves, bare whole-sketch extrudes.
- **Extrude:** blind, symmetric, two-sided, taper, offset start, to-face, through-all,
  join/cut/intersect, touching joins.
- **Fillets:**
  - constant radius on single edges, all edges, tangent chains, holes, concave edges,
    three-edge corners, multiple edge groups, sequences, after patterns, G2, chord length;
  - a shrink-retry for sizes that exactly use up a face.
- **Chamfers:** equal distance, two distances, distance + angle. The decoder measures the
  reference face (DR-341).
- **Holes:** simple, counterbore, countersink, through-all.
- **Other features:**
  - patterns and mirrors, most forms; revolve; move; combine; sweep/pipe; primitives (box,
    cylinder);
  - shell, via a face matcher that finds faces from their recorded boundary edges;
  - loft through whole-sketch sections;
  - Base Feature stored bodies.
- **Fail-safe:** conversion report, final-shape fallback, version warnings (`tools/convert.py`).

## Agent state (stopped 2026-11-13 ~21:00 PT at 80% session usage)

Everything the agents committed is merged into main. Each worktree's `HANDOFF.md` has its
diagnoses and next steps (see "Findings from round 6" below).

- **`features-a`:** next are `pat_rect_faces` (decoder face slot for the R-Pattern face group;
  the rebuilder's `face_pattern` exists), `pat_path` (path pattern settings not parsed),
  even-count symmetric patterns, nick0451 R-Pattern6 and NEMA17 R-Pattern1.
- **`features-b`:** next is the participant-extrude prologue ordinal for
  `case_cut_across_bodies_participants` and `case_cut_participants_all`. Two readings fit the
  data. A case with a different number of references before the 0x5 group would settle it.
- **`profiles`:** next are kol Extrude4 (1 of 2 regions), Claw Extrude1, and refusing when the
  recorded region count differs from the resolved count.

To resume, either send each agent a "continue" message (if the same session is still around),
or start a new agent with that worktree and its `HANDOFF.md`. Tell it to finish, commit, run
its affected ids plus the full corpus by tier, and report.

**Merge procedure** (the coordinator does this, never the agents):
1. In `cadmpeg/`, fast-forward or merge `f2fc-agent/<name>` into `fusion2fc`.
2. `git merge --no-ff --no-commit agent/<name>` into `main`. Then `git rm` its
   `HANDOFF.md`/`handoff-tools`, which stay off main.
3. Build the main binary with `.worktrees/build-decoder.sh` from the repo root. The full LTO
   release build runs out of memory while the VM runs.
4. Commit the cadmpeg pointer.
5. Run `cargo test -q -p cadmpeg-codec-f3d --lib` through the wrapper, then `run_cases.py`.
6. Update the baseline from per-model `result.json` files. Never lower a model's count: keep a
   regressed model's old number so it stays flagged.
7. After merging two branches that weren't tested together, run the full corpus on main.
8. When syncing main back into an agent branch, restore its `HANDOFF.md` from the old tip,
   because main's merge deleted it.

**Check agents' reported numbers against the `result.json` files.** One agent once claimed
gains that did not reproduce.

## Open gaps, ranked by how much they block

Failing generated cases (ids `case_<name>`) are listed per area. Corpus first-failure triage is
in the agents' `HANDOFF.md` files.

1. **Profiles** (largest corpus gap; 21 real models first fail at an extrude with the wrong
   shape):
   - revolve and sweep from a whole sketch: 12 cases (work paused, above);
   - ellipse profiles (`spatial_sketch_selection`) and text;
   - region resolution that fails: the arrangement work budget runs out, ring matching fails,
     curve ids come from derived split pieces, or program curves are missing;
   - `sketch_selection` exits at `unresolved_region_operand` (2BC, Cake_v2, hook_sogou,
     TimingPulleyBase);
   - the `ulikoehler` sketches decode with no closed loops at all.
2. **Patterns/holes:**
   - pattern of faces, path pattern, one-direction extent, symmetric patterns;
   - nick0451 R-Pattern6 (direction two; 39 steps);
   - Apollo countersink depth;
   - NEMA17 R-Pattern1.
3. **Move/copy/components:**
   - copy body ("move with N copies");
   - Move "body selection native" (rosbot, 18 steps; a decoder body-slot gap);
   - extrude in a component, and two components about 1% off;
   - cut participant bodies.
4. **Faces:** draft and shell face selections are "native" in the decoder (draft_side_faces,
   draft_single_face).
5. **Base Feature derived from snapshots** (Connector_Bracket 19 steps, Example_B 12): this needs
   historical per-state body geometry from the decoder.
6. **Fillets:**
   - about 12 corpus steps have edge selections the decoder can't read: 8 in nick0451, where
     Fusion lost the references, plus spline blends in N2_Pencil and tealight;
   - badger2040 has a radius larger than its face;
   - out of reach for OCC, and refused with a clear reason: tangent chain off, setback corner,
     mixed-radius corners, asymmetric, variable radius, and the WilkoV hemisphere cap.
7. **Surface modelling** (tealight, 32 steps: patch, trim, stitch) and sheet metal (flange in
   Gate_Bracket): low priority for hobby use.
8. **Rule fillets:** none appear in the corpus or in 850 permissively licensed public `.f3d`
   files, and the Fusion API can't create them. Low priority unless the user makes a sample.

## Findings from round 6 (2026-11-13 evening), not yet fixed

- **Wrong-region extrudes** (silent wrong geometry): co2_box Extrude18, kol Extrude4, Claw
  Extrude1, Industrial_Tool_2 Extrude2, Controller_Cooler_P2 Extrude2, Seven_LED_Insert
  Extrude1. The decoder has to resolve the selection uniquely, or downgrade it to unresolved.
  The classification table is in `.worktrees/profiles/HANDOFF.md`.
- **Participant cuts:**
  - The Extrude prologue with a `reference:N` participant list is rejected at the DR-117
    refusal.
  - Variants `case_cut_participants_{one,all,blind,reverse}` were generated for decoding it.
  - The rebuilder plan: `affected_bodies` plus recorded `body_centers`.
  - See `.worktrees/features-b/HANDOFF.md`.
- **Derived Base Feature** (Connector_Bracket, Example_B): needs historical-state BREP from
  replaying the ASM delta states. This is a decoder project of its own.
- **appleScreen Shell3:** no history holds the 212/211 state pair.
- **thicken_face:** Fusion's `faces.item(0)` of the sheet is the y=20 mm face (checked in the
  VM). The decoder reads active face slot 22 as the y=0 face, so it misreads which face is
  selected.
- **Region gaps left:**
  - B10P/B2PS: cap-face matching against arrangement regions;
  - Cake_v2: a branching transition chain;
  - TimingPulleyBase: ring matching with replaced members.
- Quick triage of the first failure per real model, reading `tests/out/corpus/*/result.json`:
  each file's `summary.first_mismatch` has `name`, `type`, `rebuild.status`/`reason` and
  `problems`. Sort by `steps - index`.

## Comparator questions for the user

These have not been changed; they are for the user to decide.

- Pipe volume has a 4.6e-6 relative error from the spline approximation (suborusu).
- Fusion merges edge-touching slivers that OCC keeps as separate solids (SCD41 Extrude3).
- Surface-only steps never match (tealight, kantoku).
- Localised datum-plane names (作業平面1) break alignment.
- The Nupud models are about 1e-5 relative off in volume.
- Warped faces: resolved by the exact-surface fallback (`tools/exact_compare.py`, user-approved 2026-11-14). The user also allowed per-test labels in `tests/corpus/tolerances.json` (up to 2.5 x, a written reason required); none are used yet. `freecadcmd tools/negative_controls.py` must keep reporting ALL AS EXPECTED.

## Gotchas

- `.f3d` zips use zstd compression (method 93). Use `python3.14` (`compression.zstd`); system
  `unzip` silently skips those entries.
- `git` has an external diff tool configured, so use `git diff --no-ext-diff`.
- **Fusion VM:**
  - The Fusion MCP server is at host `127.0.0.1:27182`. Run `python3 vm/mcp_call.py script FILE`;
    the script must define `run(context)`.
  - Fusion is 2706.1.17.
  - The shared folder is `~/Tech/VirtualBox VMs/Shared/fusion-work`.
- In `make_cases.py`, the chamfer helper's 5th argument is `isTangentChain`. The flip argument
  is `isFlipped`. This is fixed now.
- Two `run_corpus.py` runs on the same model in the same output directory clobber each other.
- Coordinator scratch notes are in `.worktrees/COORDINATOR.md` and `.worktrees/BRIEF.md`, the
  shared agent rules. `.worktrees/` is git-excluded.
