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
   → boolean chains; fillets and chamfers find their edges by geometry.
3. **Check** against Fusion ground truth.

## Layout

| Path | Purpose |
|---|---|
| `fusion2fc/rebuild.py` | CADIR → FreeCAD rebuilder |
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
