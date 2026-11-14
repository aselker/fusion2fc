# comparator handoff
- tools/exact_compare.py: exact-surface fallback (A: Fusion verts exact dist <=1.25d; tri interiors get allowance=min(measured vs fine tessellation x1.25, L*theta/4 from Fusion mesh dihedral<30deg); B: our exact points vs Fusion tris minus allowance).
- tools/corpus_compare.py: geometry_check(), COMPARATOR_VERSION, tolerances.json labels (max 2.5).
- tools/negative_controls.py (freecadcmd) -> all as expected required.
- Fusion centroids do NOT lie within d of true surface on twisted/lofted faces (0.04-0.07mm, 0.25mm on loft_offset) so centroids can't be held to d.
- TODO: full corpus by tier, tolerances.json, report.
