"""Fusion-side: for each timeline item of component __COMP__, roll to just after it and
record the volumes of that component's bodies. Restores the marker. __OUT__ = JSON path."""
import adsk.core, adsk.fusion, json

COMP = r"__COMP__"


def run(_context: str):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    tl = design.timeline
    collapsed = [g for g in tl.timelineGroups if g.isCollapsed]
    for g in collapsed:
        g.isCollapsed = False
    comp = [c for c in design.allComponents if c.name == COMP][0]
    steps = []
    for i in range(tl.count):
        it = tl.item(i)
        if it.isGroup:
            continue
        ent = it.entity
        try:
            owner = ent.parentComponent.name
        except Exception:
            continue
        if owner != COMP:
            continue
        it.rollTo(False)
        vols = sorted((b.physicalProperties.volume * 1000.0 for b in comp.bRepBodies), reverse=True)
        steps.append({"index": i, "name": it.name, "type": ent.objectType.split("::")[-1], "volumes_mm3": vols})
    tl.moveToEnd()
    for g in collapsed:
        g.isCollapsed = True
    with open(r"__OUT__", "w") as f:
        json.dump(steps, f, indent=1)
    for s in steps:
        print(s["index"], s["name"], s["type"], [round(v, 4) for v in s["volumes_mm3"]])
