#!/usr/bin/env python3
"""Reduce a cadmpeg CADIR dump to what fusion2fc/rebuild.py reads.

  slim_cadir.py MODEL.cadir.json SLIM.json TOPO.json

slim: features, sketches, sketch entities/constraints, parameters, spatial sketches,
bodies, and `face_planes` (resolved face id -> plane of its surface).
topo: feature input topologies (history edge geometry).
"""
import json
import sys


def slim(cadir):
    m = cadir["model"]
    keep = ("features", "sketches", "sketch_entities", "sketch_constraints", "parameters", "spatial_sketches")
    s = {k: m.get(k, []) for k in keep}
    s["bodies"] = [{"id": b.get("id"), "name": b.get("name")} for b in m.get("bodies", [])]
    planes = {sf["id"]: sf["geometry"] for sf in m.get("surfaces", [])
              if (sf.get("geometry") or {}).get("kind") == "plane"}
    s["face_planes"] = {}
    for f in m.get("faces", []):
        g = planes.get(f.get("surface"))
        if g:
            s["face_planes"][f["id"]] = {"origin": g["origin"], "normal": g["normal"], "sense": f.get("sense")}
    topo = [{"id": t["id"], "input_of": t.get("input_of"), "edge_geometry": t.get("edge_geometry")}
            for t in m.get("feature_input_topologies", [])]
    return s, topo


def main(argv):
    s, topo = slim(json.load(open(argv[1])))
    json.dump(s, open(argv[2], "w"))
    json.dump(topo, open(argv[3], "w"))


if __name__ == "__main__":
    main(sys.argv)
