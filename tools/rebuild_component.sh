#!/bin/sh
# Rebuild one Fusion component's features in FreeCAD (dev helper).
#   rebuild_component.sh WORKDIR DESIGN COMPONENT
# Expects WORKDIR/DESIGN.slim.json, DESIGN.topo.json (tools/slim_cadir.py) and
# DESIGN.align.json (tools/compare_fusion_cadir.py --alignment); writes WORKDIR/out/.
set -e
W=$1; D=$2; C=$3; HERE=$(dirname "$0")
mkdir -p "$W/out"
jq --arg c "$C" '[.[] | select(.component==$c) | .cadir]' "$W/$D.align.json" > "$W/out/$C.ids.json"
F2FC_SLIM="$W/$D.slim.json" F2FC_TOPO="$W/$D.topo.json" F2FC_FEATURES="$W/out/$C.ids.json" \
F2FC_OUT="$W/out/$C.FCStd" F2FC_REPORT="$W/out/$C.report.json" \
  timeout 600 freecadcmd "$HERE/../fusion2fc/rebuild.py" 2>&1 | grep -E 'F2FC|Error|Traceback|line [0-9]' | sed "s/^/$C: /"
