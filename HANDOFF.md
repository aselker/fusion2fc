# features-a handoff (pattern, hole, mirror, move)

## Done
- Rectangular-pattern payload distribution block now reads when a 7-byte compact reference follows its zero byte (newer "Active" designs). The block's distance type (0 spacing / 1 extent) overrides the direction record's type; nick0451 patterns have record type 8 yet are adjacent spacing. 3 -> 20 steps on nick0451_Parametric_Battery_Case_v2.
- Direction record distance type 10 accepted (form comes from the payload; unresolved without a readable block).
- Mirror plane: a compact plane selection naming a WorkPlane scope selects that plane (it used to bind a coincidentally numbered face). PacktPublishing_Bracket_Finished 8 -> 15/15.
- Rebuilder: a hole with a single part (simple hole, no counterbore/drill point) used `Part::MultiFuse` with one shape and failed silently; the lone bore is the tool now (ravengraves_NEMA17: Hole1 built).
- Pattern active only in direction two: the one record is direction one's; direction two comes from the payload (zero payload leaves it unresolved; before it silently reused direction one).

## Left (ranked)
1. nick0451 R-Pattern6 (direction two only; payload V direction is zero, record displacement is x but physical layout needs y). Truth removes ~19.7k mm3, matching four seed cuts along y. Where Fusion stores the direction is unknown.
2. Move body selection native (runtimerobotics_rosbot, Ch12 tealight): the Move group's members have no `resolved_body_slot` ("3 affected body slots without a unique active body in its BREP namespace"). `history.rs` Move binding needs a single member.
3. ravengraves_NEMA17 R-Pattern1 "pattern linear unresolved", and other skipped patterns (direction unresolved: administrativetrick, kantoku mirror).
4. Dice R-Pattern2 "pattern of faces" (one pattern, 8 steps); needs face-to-tool-body mapping or face matcher.
5. Apollo Lamp_Mount_Body Hole1 (countersink, angled bottom): Fusion removes 21 mm3 more per hole than ours (about one countersink frustum). Oracle gives no hole data; suspect depth measured from the countersink bottom.

## Gotchas
- `$TMPDIR` is unset in this shell; use the scratchpad for `cadmpeg convert -o ... --force` output.
- `cargo fmt` reformats ~19 files not fmt-clean upstream; run it, then `git checkout` the unrelated ones.
- features.json has no pattern/hole/mirror data for most features (only counts for circular patterns).
