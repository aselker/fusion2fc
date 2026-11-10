"""Fusion-side: dump occurrences (with transform) and every body's mass properties
at the end of the timeline. __OUT__ = output JSON path. Units cm / cm^2 / cm^3."""
import adsk.core, adsk.fusion, json


def run(_context: str):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    occs = []
    for o in root.allOccurrences:
        m = o.transform2.asArray()
        ident = all(abs(m[i] - (1.0 if i in (0, 5, 10, 15) else 0.0)) < 1e-9 for i in range(16))
        occs.append({"path": o.fullPathName, "component": o.component.name, "identity": ident,
                     "transform": list(m), "visible": o.isLightBulbOn})
    bodies = []
    for comp in design.allComponents:
        for b in comp.bRepBodies:
            pp = b.physicalProperties
            bb = b.boundingBox
            bodies.append({"component": comp.name, "name": b.name, "solid": b.isSolid,
                           "visible": b.isLightBulbOn, "volume": pp.volume, "area": pp.area,
                           "centroid": [pp.centerOfMass.x, pp.centerOfMass.y, pp.centerOfMass.z],
                           "bbox": [[bb.minPoint.x, bb.minPoint.y, bb.minPoint.z],
                                    [bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z]],
                           "faces": b.faces.count, "edges": b.edges.count})
    with open(r"__OUT__", "w", encoding="utf-8") as f:
        json.dump({"occurrences": occs, "bodies": bodies}, f, indent=1, ensure_ascii=False)
    print("occurrences", len(occs), "non-identity", sum(not o["identity"] for o in occs),
          "| bodies", len(bodies))
