"""Fusion-side script (run via fusion_mcp_execute): dump timeline, parameters and
component tree of the active design to JSON. OUT is substituted by the caller."""
import adsk.core, adsk.fusion, json, collections

OUT = r"__OUT__"


def entity_info(ent):
    if ent is None:
        return None
    d = {"type": ent.objectType.split("::")[-1]}
    for attr in ("name", "isSuppressed"):
        try:
            d[attr] = getattr(ent, attr)
        except Exception:
            pass
    try:
        pc = ent.parentComponent
        d["component"] = pc.name if pc else None
    except Exception:
        pass
    return d


def run(_context: str):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    tl = design.timeline
    items = []

    def add(it, group):
        rec = {"index": len(items), "name": it.name, "group": group,
               "isSuppressed": it.isSuppressed, "health": it.healthState}
        try:
            rec["entity"] = entity_info(it.entity)
        except Exception as e:
            rec["entity_error"] = str(e)
        items.append(rec)

    for i in range(tl.count):
        it = tl.item(i)
        if it.isGroup:
            g = adsk.fusion.TimelineGroup.cast(it)
            for j in range(g.count):
                add(g.item(j), g.name)
        else:
            add(it, None)
    groups = []
    for g in tl.timelineGroups:
        try:
            start = g.item(0).index if g.count else None
        except Exception:
            start = None
        groups.append({"name": g.name, "start": start, "count": g.count})
    user_params = [{"name": p.name, "expression": p.expression, "value": p.value,
                    "unit": p.unit, "comment": p.comment} for p in design.userParameters]
    comps = []
    for c in design.allComponents:
        comps.append({"name": c.name, "bodies": c.bRepBodies.count, "sketches": c.sketches.count,
                      "occurrences": c.occurrences.count, "features": c.features.count})
    occs = []
    for o in design.rootComponent.allOccurrences:
        occs.append({"path": o.fullPathName, "component": o.component.name,
                     "isReferenced": o.isReferencedComponent})
    out = {"design": design.rootComponent.name, "designType": design.designType,
           "timeline": items, "groups": groups, "userParameters": user_params,
           "allParametersCount": design.allParameters.count,
           "components": comps, "occurrences": occs}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    types = collections.Counter((r.get("entity") or {}).get("type", "?") for r in items)
    print("timeline items", tl.count, "| groups", len(groups), "| user params", len(user_params),
          "| all params", design.allParameters.count, "| components", len(comps), "| occurrences", len(occs))
    print(dict(types.most_common()))
