# fusion2fc

Convert Autodesk Fusion `.f3d` / `.f3z` designs to FreeCAD documents, keeping the
parametric features and timeline rather than only the final geometry.

## Pipeline

1. **Decode** the Fusion file with a fork of [cadmpeg](https://github.com/cadmpeg/cadmpeg)
   (`cadmpeg dump design.f3d -o design.cadir.json`). The fork is the `cadmpeg/` submodule
   (branch `fusion2fc`); see `cadmpeg/FORK.md`. Clone with `git clone --recurse-submodules`
   and build it with `cargo build --release --manifest-path cadmpeg/Cargo.toml -p cadmpeg`.
2. **Rebuild** the decoded design in FreeCAD with `fusion2fc/rebuild.py`, run by
   `freecadcmd` (inputs via `F2FC_*` environment variables, see the module docstring).
   Sketches become Sketcher sketches; extrudes become profile binder → `Part::Extrusion`
   → boolean chains (profile loops that overlap or cross are built as a static boolean face,
   not by the binder's face maker); an extrude whose profile is a bare sketch takes every loop region of it, nested loops as holes; fillets and chamfers find their edges by geometry, and shell, draft and delete-face find their faces from the recorded boundary edges (`Part::Thickness`, `PartDesign::Draft`, OCC defeaturing). Holes become
   primitive solids cut from the bodies; patterns and mirrors re-apply their seed features'
   tools through Draft arrays or `Part::Mirroring` (or copy bodies); revolves, moves and
   combines map to `Part::Revolution`, placed `Part::Compound`s and Part booleans.
   Base Feature bodies (stored, not rebuilt) are exported from the CADIR to STEP by
   `tools/stored_bodies.py` (`F2FC_BODIES`) and imported as the starting solids.
3. **Check** against Fusion ground truth.

## Converting a design

    python3 tools/convert.py DESIGN.f3d [OUT.FCStd] [--no-fallback] [--keep WORKDIR]

`tools/convert.py` runs the whole pipeline (decode, slim, stored bodies, rebuild) and prints a
short **conversion report**, also written to `OUT.report.txt` and `OUT.report.json` and stored in
the document as the text object "Conversion report". It lists features built / skipped / failed
with reasons, whether the rebuilt final bodies match Fusion's, and the decoder's loss codes.

**Final-shape fallback.** Fusion stores its exact final B-rep bodies. After the rebuild they are
compared with the rebuilt bodies (solid count, sorted volumes to 1e-4, bounding box). If any feature
was skipped or failed, or the shapes differ, the stored bodies are added as the group "Fusion final
shape (not parametric)", and the rebuilt bodies are relabelled "(INCOMPLETE rebuild)" and hidden.
`--no-fallback` (or `F2FC_NO_FALLBACK=1`) turns this off. The corpus tools do not set `F2FC_FINAL`,
so per-step comparison is unaffected.

**Version warnings.** Fusion stores no application build number; the evidence is the ASM
(ShapeManager) version and save date in each BREP header, the container manifest version, and the
(type, version) table of the Design stream. `tools/survey_versions.py` (python3.14) surveys the
corpus and writes the known range to `fusion2fc/known_versions.json` (manifest 3-2-0-0, ASM 223-232,
2018-03 to 2026-11, 421 record types). `fusion2fc/versions.py` warns when a file is outside it, or
when the decoder reports record_not_typed or "-native / -unresolved / -incomplete / -uninterpreted"
loss codes (counted by code in the report). No Rust changes were needed: the facts are already in
the CADIR `source.attributes`, `native.f3d.design_types` and the fidelity sidecar.

## Layout

| Path | Purpose |
|---|---|
| `fusion2fc/rebuild.py` | CADIR → FreeCAD rebuilder |
| `tools/convert.py` | one design end to end, with conversion report and final-shape fallback |
| `tools/survey_versions.py` | survey of ASM / manifest / record versions over the corpus |
| `tools/run_cases.py` | decode → rebuild → compare for every case in `tests/cases/` |
| `tools/compare_fusion_cadir.py` | feature-by-feature comparison of a decode with a Fusion dump |
| `tools/check_bodies.py`, `tools/rebuild_component.sh` | helpers for rebuilding one component of a large design |
| `tests/cases/` | minimal test designs (`.f3d`) and Fusion ground truth (`.truth.json`) |
| `tests/corpus/` | permissively licensed real-world models with per-step Fusion meshes; see its README |
| `tools/run_corpus.py`, `tools/corpus_compare.py`, `tools/mesh_compare.py` | step-by-step geometric comparison with Fusion over the corpus |
| `tools/corpus_truth.py`, `vm/scripts/step_meshes.py` | record the corpus ground truth in Fusion |
| `vm/mcp_call.py` | client for Fusion's built-in MCP server (runs Fusion API scripts) |
| `vm/scripts/` | Fusion-side scripts: case generator, timeline/feature/body dumps |

## Fusion ground truth

Fusion runs in a Windows VM with its MCP server enabled (Preferences → General → API),
reachable from the host at `http://127.0.0.1:27182/mcp`. Run a Fusion API script with:

    vm/mcp_call.py script vm/scripts/make_cases.py --include vm/scripts/dump_features.py \
        'OUTDIR=\\VBOXSVR\Shared\fusion-work\cases' ONLY=

## Tests

    tools/run_cases.py            # all cases, needs cadmpeg/target/release/cadmpeg and freecadcmd
    tools/run_cases.py -v NAME    # one case, verbose
    tools/run_corpus.py           # every corpus model, compared with Fusion after every timeline step

`run_cases.py` compares step volumes and names. `run_corpus.py` compares geometry after
each timeline step: body counts, volumes, and Fusion's tessellation against the rebuilt
bodies' tessellation (two-sided distance within tessellation error). See
`tests/corpus/README.md`.
