#!/usr/bin/env python3
"""Write a replication spec for vm/scripts/replicate.py from a dump_features.py dump.

  make_replica_spec.py DUMP.json COMPONENT NAME OUT.json [--upto FEATURE_NAME]

Takes the timeline records of COMPONENT (in order, up to and including --upto) and the
design's user parameters.
"""
import json
import sys


def main(argv):
    dump, comp, name, out = argv[1:5]
    upto = argv[argv.index("--upto") + 1] if "--upto" in argv else None
    d = json.load(open(dump))
    recs = []
    for r in d["timeline"]:
        if r.get("component") != comp or r["type"] == "Occurrence":
            continue
        recs.append(r)
        if upto and r["name"] == upto:
            break
    spec = {"name": name, "userParameters": d.get("userParameters", []), "records": recs}
    json.dump(spec, open(out, "w"), ensure_ascii=False)
    print("%s: %d records (%s)" % (name, len(recs), ", ".join(r["name"] for r in recs)))


if __name__ == "__main__":
    main(sys.argv)
