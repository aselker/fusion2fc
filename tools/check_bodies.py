#!/usr/bin/env python3
"""Compare rebuilt FreeCAD bodies (rebuild report) with Fusion bodies (dump_bodies.py).
  check_bodies.py REPORT.json FUSION_BODIES.json COMPONENT"""
import json, sys
rep = json.load(open(sys.argv[1])); fus = json.load(open(sys.argv[2])); comp = sys.argv[3]
want = sorted((b for b in fus["bodies"] if b["component"] == comp), key=lambda b: -b["volume"])
got = sorted(rep["bodies"], key=lambda b: -b["volume"])
bad = [f"{r['name']}: {r['status']} ({r.get('reason', '')})" for r in rep["features"] if r["status"] != "built"]
print(f"{comp}: fusion {len(want)} bodies, rebuilt {len(got)}" + (f"; not built: {bad}" if bad else ""))
for i in range(max(len(want), len(got))):
    w = want[i] if i < len(want) else None
    g = got[i] if i < len(got) else None
    wv = w["volume"] * 1000 if w else None  # cm^3 -> mm^3
    gv = g["volume"] if g else None
    rel = abs(gv - wv) / wv if (wv and gv is not None) else None
    print(f"   {w['name'] if w else '-':20s} fusion {wv if wv is not None else float('nan'):12.4f} mm3 | rebuilt {gv if gv is not None else float('nan'):12.4f} mm3"
          + (f" | rel.err {rel:.2e} {'OK' if rel < 1e-6 else 'MISMATCH'}" if rel is not None else ""))
