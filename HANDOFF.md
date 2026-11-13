# geometry agent handoff (fail-safety)

Done: tools/convert.py (end-to-end driver + report), final-shape check and fallback group in rebuild.py
(`finish()`, `compare_final`, `summary_text`, enabled by F2FC_FINAL/F2FC_FACTS), stored_bodies.export(ids)
+ final_body_ids, fusion2fc/versions.py + known_versions.json, tools/survey_versions.py. No Rust changes.

Left: fallback decision treats any skipped/failed feature as incomplete even if the shapes match
(deliberate). Final compare uses product_definitions[].bodies for placement; bodies without a
component are taken as root. Surfaces/sheet bodies are not compared (solids only). Known-version table
should be regenerated (`python3.14 tools/survey_versions.py --write`) when the corpus grows.

Gotchas: system python3 is 3.12 without zstd zip support, survey needs python3.14. Fusion has no app
version string in the file; ASM version and save date are the proxy. Earlier handoff items (construction
flags, Lock_B_Side heads) were merged before this task.
