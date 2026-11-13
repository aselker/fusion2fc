#!/bin/sh
# usage: burn_check.sh OUTDIR [CADMPEG]
set -e
OUT=$1
BIN=${2:-/home/neophile/Documents/Programming/Vibes/fusion/.worktrees/profiles/cadmpeg/target/release/cadmpeg}
WT=/home/neophile/Documents/Programming/Vibes/fusion/.worktrees/profiles
SP=/tmp/claude-1000/-home-neophile-Documents-Programming-Vibes-fusion/718e78be-211f-4304-a3b2-40271bf91e41/scratchpad
mkdir -p $OUT
nice timeout 1800 $BIN dump "/home/neophile/Tech/VirtualBox VMs/Shared/Burninator/v3.0/CAD/Burninator_v3.0.f3d" -o $OUT/v3.cadir.json --force > $OUT/v3.dump.log 2>&1
nice python3 $WT/tools/slim_cadir.py $OUT/v3.cadir.json $OUT/v3.slim.json $OUT/v3.topo.json
rm -f $OUT/v3.cadir.json $OUT/v3.cadir.fidelity.json
cp $SP/cad9/v3.align.json $OUT/
F2FC_SLIM=$OUT/v3.slim.json F2FC_AREAS=$OUT/areas.json nice freecadcmd $WT/tools/profile_areas.py > $OUT/areas.log 2>&1
python3 $SP/area_compare.py $(dirname $OUT) "/home/neophile/Tech/VirtualBox VMs/Shared/fusion-work/out" $(basename $OUT)
