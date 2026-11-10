# Test cases

Each `<case>.f3d` has a `<case>.truth.json` with Fusion API ground truth (feature
definitions, final bodies, body volumes after every timeline item).

- Generated cases (everything except `replica_*`) are built from scratch by
  `vm/scripts/make_cases.py`.
- `replica_*` cases are rebuilt by `vm/scripts/replicate.py` from components of the
  Burninator toolhead (https://github.com/The-Duke-96/Burninator, v3.0
  `Burninator_v3.0.f3d`), which is licensed under GPL-3.0. These files are derived
  works of that design and are covered by GPL-3.0.
