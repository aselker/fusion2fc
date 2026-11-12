# features-a handoff

**Done, verified:** `rebuild.py` builders for hole, pattern (feature seeds via Draft arrays with seed hidden / `Part::Mirroring`; body seeds), revolve, move_body, combine (merged to main as cce0be5). Dice Hole1–19 volumes match Fusion exactly; Custom_Lattice C-Pattern1 matches (2→3 steps). Generated 28/29, run_cases 28/29.

**In progress, unverified (WIP commits):**
- Python: `locate_body` (historical body by its faces' edge geometry), join Combine over all state bodies.
- cadmpeg: compact/220-byte direction records accept distance type 7|8; inactive-direction records dropped; count-one extent allowed; circular axis from 220-byte frame; Hole with one RefDim; Combine null-reference prologue; IR `FeatureInputTopology::body_faces`. Updated unit tests, spec, layout table, FORK.md. Never compiled after the IR change.

**Gaps:** 11 `unresolved` patterns (NEMA17/Battery distance type 10; administrativetrick both counts 1); face-seed patterns (Dice R-Pattern2); fillet seeds (Encoder); mirror op guessed (touching ⇒ join); most revolves/patterns wait on profiles (`profile kind sketch`).

**Next:** 1) `cargo check --tests -p cadmpeg-ir -p cadmpeg-codec-f3d -p cadmpeg-codec-inventor`, fix, run f3d tests (`pattern combine hole feature_inputs`), `UPDATE_GOLDEN=1 cargo test -p cadmpeg-codec-f3d golden`. 2) Release build (`--no-default-features --features f3d`), corpus on Dice, Lattice, SG90, Bracket_Solid, Lego, k_recik. 3) Generated tier + run_cases.

**Gotchas:** Dice compare is slow (>15 min under load). Scratchpad is shared between agents; mine is `scratchpad/fa/`.
