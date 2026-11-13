# Step-by-step geometry corpus

Each model here is checked after **every timeline step**. At each step, the bodies
fusion2fc rebuilds in FreeCAD must match the bodies Fusion has at that step, up to
tessellation and numerical error.

## What a step match means

For each Fusion timeline item, `vm/scripts/step_meshes.py` rolls the timeline to just after
the item. It then records every body as placed in the root (one copy per occurrence),
with:

- exact volume, area and centroid (Fusion high-accuracy physical properties), and
- a triangle mesh from Fusion's own tessellator, at surface deviation `d` (in mm, world
  coordinates).

`d` is 2e-4 of the model's final bounding-box diagonal, clamped to 0.002–0.05 mm.

`tools/run_corpus.py` decodes the `.f3d` with cadmpeg, then rebuilds it with
`fusion2fc/rebuild.py`, saving the bodies after every feature. It aligns the Fusion
timeline with the rebuilt features by name, so each Fusion step is compared with the
rebuild state at that point in history. A step **matches** when all three of these
hold:

1. the solid body counts are equal;
2. the sorted solid volumes agree to 1e-6 relative (Fusion's against OpenCASCADE's);
3. the two meshes are within `1.25 × 2d` of each other in both directions. The FreeCAD
   side is tessellated at the same `d`. The distance is the two-sided Hausdorff distance
   from each mesh's vertices and subdivided triangle centroids to the other mesh, using
   exact point-to-triangle distances (`tools/mesh_compare.py`).

Both meshes approximate the same exact surface within `d`, so identical geometry
always lands within `2d`. Re-tessellating one shape at two deviations measures about
0.75 × (d1 + d2). Any real geometric difference larger than about `2.5d` is reported,
along with the point where it was found. The default `d` puts that floor at 0.005–0.125 mm.

A model **passes** when every step matches.

## Tiers

| Tier | Models | What |
|---|---|---|
| `generated` | 66 | `tests/cases/*.f3d`, minimal designs built by `vm/scripts/make_cases.py`, plus the GPL-3.0 `replica_*` cases (see `tests/cases/README.md`) |
| `supported` | 28 | downloaded models whose decoded features are all kinds the rebuilder handles (sketch, extrude, fillet, chamfer, datum plane) |
| `extended` | 45 | downloaded models that also use patterns, holes, revolves, sweeps, lofts, shells, drafts, combines, moves, splits, surfaces or multi-component assemblies |

The tier is a snapshot of what cadmpeg decoded when the corpus was assembled
(`decoded_features` in the manifest). It is not a promise about what currently passes.

## Running

    tools/run_corpus.py                  # everything with ground truth, in parallel
    tools/run_corpus.py --tier supported
    tools/run_corpus.py ID [ID ...]      # selected models
    tools/run_corpus.py --save-baseline  # record per-model match counts in baseline.json

Each run prints one line per model: matched steps, plus the first mismatching step with
its reason and the rebuild status of the feature. It ends with per-tier totals and
IMPROVED/REGRESSED lines against `baseline.json`. Per-step detail is written to
`tests/out/corpus/<id>/result.json`, next to the decode and rebuild logs.

Recording ground truth needs Fusion in the VM, with its MCP server, as described in the
top-level README:

    tools/corpus_truth.py                # models without truth yet
    tools/corpus_truth.py ID --force     # re-record one

Each model is opened in a new, unsaved Fusion document and closed without saving.

## Layout

The `.f3d` models and `.stl.gz` meshes are stored with Git LFS (see `/.gitattributes`).
Install git-lfs before cloning, or run `git lfs pull` after. The JSON and text files are
ordinary git files.

| Path | Contents |
|---|---|
| `manifest.json` | one entry per model: id, tier, file, sha256, and source (repo, commit, path, license) |
| `models/` | the downloaded `.f3d` files, unmodified |
| `truth/<id>/steps.json` | Fusion: per-step timeline item, health, bodies (volume, area, centroid, bbox, triangle range), mesh file |
| `truth/<id>/mesh_NNNN.stl.gz` | Fusion's mesh after step NNNN: binary STL, mm, world coordinates. A step whose bodies did not change reuses the previous step's file. |
| `truth/<id>/features.json` | Fusion feature definitions (`vm/scripts/dump_features.py`), for diagnosis |
| `licenses/` | the license text of every source repository |
| `baseline.json` | matched-step counts from the last `--save-baseline` |

## Sources and licenses

The downloaded models come from public GitHub repositories whose license is permissive:
MIT (36 models), BSD-3-Clause (17), Apache-2.0 (11), CC0-1.0 (7) and Unlicense (2).
Each repository's license file is copied to `licenses/<owner>__<repo>.txt`, and the files
are unmodified. The license here is the repository license that GitHub reports. Each
license file was read to confirm it, but the provenance of individual files was not
checked. Models were found with `gh search repos` (topics like fusion360, with license
filters) and a scan of each repository's tree for `.f3d` files. They are pinned to the
commit listed below.

| Model | Tier | Source | License |
|---|---|---|---|
| `andyeske_N2_Pencil_v1` | supported | [andyeske/How-to-CAD-Fusion-360](https://github.com/andyeske/How-to-CAD-Fusion-360/blob/482b7bae438c/Session%20Files/Session%201/N2%20Pencil%20v1.f3d) | mit |
| `bitbank2_badger2040_case` | supported | [bitbank2/Fusion_360_Projects](https://github.com/bitbank2/Fusion_360_Projects/blob/d6230f583f43/badger2040_case/badger2040_case.f3d) | apache-2.0 |
| `bitbank2_co2_01space_box` | supported | [bitbank2/Fusion_360_Projects](https://github.com/bitbank2/Fusion_360_Projects/blob/d6230f583f43/co2_01space_box/co2_01space_box.f3d) | apache-2.0 |
| `bitbank2_diagonal_cutter_cover` | supported | [bitbank2/Fusion_360_Projects](https://github.com/bitbank2/Fusion_360_Projects/blob/d6230f583f43/diagonal_cutter_cover/diagonal_cutter_cover.f3d) | apache-2.0 |
| `bitbank2_oled_cover` | supported | [bitbank2/Fusion_360_Projects](https://github.com/bitbank2/Fusion_360_Projects/blob/d6230f583f43/oled_cover/oled_cover.f3d) | apache-2.0 |
| `bitbank2_rack_mount_foot` | supported | [bitbank2/Fusion_360_Projects](https://github.com/bitbank2/Fusion_360_Projects/blob/d6230f583f43/rack_mount_foot/rack_mount_foot.f3d) | apache-2.0 |
| `bowenchristopher_Untitled_v1` | supported | [bowenchristopher/Fusion360_API](https://github.com/bowenchristopher/Fusion360_API/blob/ef94a4dd276a/Test%20Files/Untitled%20v1.f3d) | mit |
| `gtgkartik_Industrial_Tool_2` | supported | [gtgkartik/3D-Printing-Fusion-360](https://github.com/gtgkartik/3D-Printing-Fusion-360/blob/28fd4001ea59/Fusion%20360%20Project%20Files/Industrial%20Tool%202.f3d) | apache-2.0 |
| `digitalsputnik_Al_Pipe_16x200mm_M_SPPS000000046_v1` | supported | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/metal/Al%20Pipe%2016x200mm%20[(M)SPPS000000046]%20v1.f3d) | bsd-3-clause |
| `digitalsputnik_Al_Pipe_16x170mm_M_SPPS000000007_v1` | supported | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/metal/Al.%20Pipe%2016x170mm%20%20[(M)SPPS000000007]%20v1.f3d) | bsd-3-clause |
| `digitalsputnik_Al_Pipe_16x22mm_M_SPPS000000057_v2` | supported | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/metal/Al.%20Pipe%2016x22mm%20[(M)SPPS000000057]%20v2.f3d) | bsd-3-clause |
| `digitalsputnik_Al_Pipe_16x75mm_M_SPPS000000043_v1` | supported | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/metal/Al.%20Pipe%2016x75mm%20[(M)SPPS000000043]%20v1.f3d) | bsd-3-clause |
| `digitalsputnik_Controller_Cooler_P2_M_SPPS000000003_2_v2` | supported | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/metal/Controller%20Cooler%20(P2)%20[(M)SPPS000000003.2]%20v2.f3d) | bsd-3-clause |
| `digitalsputnik_Apollo_Yoke_Lock_P3_P_MPLA000000158_v2` | supported | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/plastic/Apollo%20Yoke%20Lock%20P3%20[(P)MPLA000000158]%20v2.f3d) | bsd-3-clause |
| `digitalsputnik_Front_Transparent_T1_v5` | supported | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/plastic/Front%20Transparent-T1%20v5.f3d) | bsd-3-clause |
| `digitalsputnik_Nupud_T_v2` | supported | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/plastic/Nupud-T%20v2.f3d) | bsd-3-clause |
| `digitalsputnik_Nupud_T1_v1` | supported | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/plastic/Nupud-T1%20v1.f3d) | bsd-3-clause |
| `digitalsputnik_Tihend_v4` | supported | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/plastic/Tihend%20v4.f3d) | bsd-3-clause |
| `homebrew_pinball_Fast_Light_Board` | supported | [homebrew-pinball/fusion360-models](https://github.com/homebrew-pinball/fusion360-models/blob/5a0f50bd0e74/lights/Fast%20Light%20Board.f3d) | mit |
| `homebrew_pinball_NeoPixel_Jewel_7_LED` | supported | [homebrew-pinball/fusion360-models](https://github.com/homebrew-pinball/fusion360-models/blob/5a0f50bd0e74/lights/NeoPixel%20Jewel%207%20LED.f3d) | mit |
| `intuibase_SCD41Chamber` | supported | [intuibase/esp32_co2_monitor](https://github.com/intuibase/esp32_co2_monitor/blob/0db87bfa69f0/enclosure/f3d/SCD41Chamber.f3d) | mit |
| `PacktPublishing_L_Brackets` | supported | [PacktPublishing/3D-Printing-with-Fusion-360](https://github.com/PacktPublishing/3D-Printing-with-Fusion-360/blob/4c80cda6d17d/Chapter13/L%20Brackets.f3d) | mit |
| `onlinelei_hook_sogou_v1` | supported | [onlinelei/Autodesk-Fusion-360](https://github.com/onlinelei/Autodesk-Fusion-360/blob/a38000ecea3c/small/hook-sogou-v1.f3d) | apache-2.0 |
| `PacktPublishing_3_1_Example` | supported | [PacktPublishing/Improving-CAD-Designs-with-Autodesk-Fusion-360](https://github.com/PacktPublishing/Improving-CAD-Designs-with-Autodesk-Fusion-360/blob/04ccbf639ed7/Ch03/3.1_Example.f3d) | mit |
| `uwearzt_DINRailMount` | supported | [uwearzt/fusion360](https://github.com/uwearzt/fusion360/blob/72b08c3b8e36/parts/Lab/RaspberryPi/DINRailMount.f3d) | apache-2.0 |
| `adafruit_4320_PermaProto_Gizmo` | supported | [adafruit/Adafruit_CAD_Parts](https://github.com/adafruit/Adafruit_CAD_Parts/blob/9f2a89f3d5c3/4320%20PermaProto%20Gizmo/4320%20PermaProto%20Gizmo.f3d) | mit |
| `adafruit_67_9V_battery_holder` | supported | [adafruit/Adafruit_CAD_Parts](https://github.com/adafruit/Adafruit_CAD_Parts/blob/9f2a89f3d5c3/67%209V%20Battery%20Holder/67%209V%20battery%20holder.f3d) | mit |
| `adafruit_2278_RGB_matrix_4mm` | supported | [adafruit/Adafruit_CAD_Parts](https://github.com/adafruit/Adafruit_CAD_Parts/blob/9f2a89f3d5c3/2278%20RGB%20Matrix%204mm/2278%20RGB%20matrix%204mm.f3d) | mit |
| `administrativetrick_Parametric_A_s_v1` | extended | [administrativetrick/Parametric_3D_Models_Alphabet](https://github.com/administrativetrick/Parametric_3D_Models_Alphabet/blob/0532628e6f67/fusion%20360%20files/Parametric%20A's%20v1.f3d) | apache-2.0 |
| `adafruit_1739_Pizero_Large` | extended | [adafruit/Adafruit_CAD_Parts](https://github.com/adafruit/Adafruit_CAD_Parts/blob/9f2a89f3d5c3/1739%20Pizero%20Large/1739%20Pizero%20Large.f3d) | mit |
| `ulikoehler_B10P_VH` | extended | [ulikoehler/JST-3D](https://github.com/ulikoehler/JST-3D/blob/7a64d02069d3/models/VH/B10P-VH/B10P-VH.f3d) | cc0-1.0 |
| `ulikoehler_B2PS_VH` | extended | [ulikoehler/JST-3D](https://github.com/ulikoehler/JST-3D/blob/7a64d02069d3/models/VH/B2PS-VH/B2PS-VH.f3d) | cc0-1.0 |
| `digitalsputnik_Encoder_Button_P_MPLA000000109_v2` | extended | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/plastic/Encoder%20Button%20[(P)MPLA000000109]%20v2.f3d) | bsd-3-clause |
| `andyeske_Cake_v2` | extended | [andyeske/How-to-CAD-Fusion-360](https://github.com/andyeske/How-to-CAD-Fusion-360/blob/482b7bae438c/Session%20Files/Session%201/Cake%20v2.f3d) | mit |
| `nick0451_Parametric_Battery_Case_v2` | extended | [nick0451/fusion-360-parametric-battery-case-generator](https://github.com/nick0451/fusion-360-parametric-battery-case-generator/blob/041eac5d58eb/Parametric%20Battery%20Case%20v2.f3d) | cc0-1.0 |
| `PacktPublishing_Custom_Lattice` | extended | [PacktPublishing/3D-Printing-with-Fusion-360](https://github.com/PacktPublishing/3D-Printing-with-Fusion-360/blob/4c80cda6d17d/Chapter04/Custom%20Lattice.f3d) | mit |
| `digitalsputnik_Apollo_Yoke_Disc_P2_M_SPPS000000053_v1` | extended | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/metal/Apollo%20Yoke%20Disc%20P2%20[(M)SPPS000000053]%20v1.f3d) | bsd-3-clause |
| `digitalsputnik_Apollo_Yoke_Lamp_Mount_Body_M_SPPS000000036_v2` | extended | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/metal/Apollo%20Yoke%20Lamp%20Mount%20Body%20[(M)SPPS000000036]%20v2.f3d) | bsd-3-clause |
| `digitalsputnik_Apollo_Yoke_Int_Corner_P2_P_MPLA000000157_v1` | extended | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/plastic/Apollo%20Yoke%20Int.%20Corner%20P2%20[(P)MPLA000000157]%20v1.f3d) | bsd-3-clause |
| `PacktPublishing_Bracket_Finished` | extended | [PacktPublishing/3D-Printing-with-Fusion-360](https://github.com/PacktPublishing/3D-Printing-with-Fusion-360/blob/4c80cda6d17d/Chapter10/Bracket-Finished.f3d) | mit |
| `gtgkartik_Dice` | extended | [gtgkartik/3D-Printing-Fusion-360](https://github.com/gtgkartik/3D-Printing-Fusion-360/blob/28fd4001ea59/Fusion%20360%20Project%20Files/Dice.f3d) | apache-2.0 |
| `ravengraves_NEMA17StepperMotor` | extended | [ravengraves/Fusion360NEMA17StepperMotor](https://github.com/ravengraves/Fusion360NEMA17StepperMotor/blob/56d341f807bb/NEMA17StepperMotor.f3d) | unlicense |
| `WilkoV_03_Refinements` | extended | [WilkoV/Fusion360_ExportIt](https://github.com/WilkoV/Fusion360_ExportIt/blob/e7b12a2deeaf/tests/cases/03-Refinements.f3d) | mit |
| `ravengraves_TimingPulleyBase` | extended | [ravengraves/Fusion360GTTimingPulley](https://github.com/ravengraves/Fusion360GTTimingPulley/blob/6bf077836a1a/TimingPulleyBase.f3d) | unlicense |
| `busraakgun24_k_recik` | extended | [busraakgun24/Fusion360-Projects](https://github.com/busraakgun24/Fusion360-Projects/blob/867caaed0dab/kürecik.f3d) | cc0-1.0 |
| `kantoku_code_n_5_ryoji_jp` | extended | [kantoku-code/Fusion360-CSSPP](https://github.com/kantoku-code/Fusion360-CSSPP/blob/ee97f8069014/answer/n=5_ryoji.jp.f3d) | mit |
| `PacktPublishing_4_2_S_Hook_Sweep_Final` | extended | [PacktPublishing/Improving-CAD-Designs-with-Autodesk-Fusion-360](https://github.com/PacktPublishing/Improving-CAD-Designs-with-Autodesk-Fusion-360/blob/04ccbf639ed7/Ch04/4.2_S-Hook_Sweep_Final.f3d) | mit |
| `busraakgun24_suborusu` | extended | [busraakgun24/Fusion360-Projects](https://github.com/busraakgun24/Fusion360-Projects/blob/867caaed0dab/suborusu.f3d) | cc0-1.0 |
| `homebrew_pinball_Metal_Post_1_Inch_02_4434` | extended | [homebrew-pinball/fusion360-models](https://github.com/homebrew-pinball/fusion360-models/blob/5a0f50bd0e74/posts/Metal%20Post%201%20Inch%2002-4434.f3d) | mit |
| `homebrew_pinball_Seven_LED_Insert` | extended | [homebrew-pinball/fusion360-models](https://github.com/homebrew-pinball/fusion360-models/blob/5a0f50bd0e74/lights/Seven%20LED%20Insert.f3d) | mit |
| `rsheldiii_Doom_Keycap_Prototype_Enclosure_v22` | extended | [rsheldiii/doom-keycap-hardware](https://github.com/rsheldiii/doom-keycap-hardware/blob/95f0ed07d233/Doom%20Keycap%20Case/Doom%20Keycap%20Prototype%20Enclosure%20v22.f3d) | mit |
| `PacktPublishing_Bicycle_Handlebars_final` | extended | [PacktPublishing/Improving-CAD-Designs-with-Autodesk-Fusion-360](https://github.com/PacktPublishing/Improving-CAD-Designs-with-Autodesk-Fusion-360/blob/04ccbf639ed7/Ch07/Bicycle%20Handlebars_final.f3d) | mit |
| `onlinelei_appleScreen_v9` | extended | [onlinelei/Autodesk-Fusion-360](https://github.com/onlinelei/Autodesk-Fusion-360/blob/a38000ecea3c/appleScreen/appleScreen%20v9.f3d) | apache-2.0 |
| `andyeske_Lego_20x20_plate_v8` | extended | [andyeske/How-to-CAD-Fusion-360](https://github.com/andyeske/How-to-CAD-Fusion-360/blob/482b7bae438c/Session%20Files/Session%205/Lego%2020x20%20plate%20v8.f3d) | mit |
| `andyeske_Lego_2x4_brick_v1` | extended | [andyeske/How-to-CAD-Fusion-360](https://github.com/andyeske/How-to-CAD-Fusion-360/blob/482b7bae438c/Session%20Files/Session%205/Lego%202x4%20brick%20v1.f3d) | mit |
| `digitalsputnik_16mm_Claw_P_MPLA000000141_v1` | extended | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/plastic/16mm%20Claw%20[(P)MPLA000000141]%20v1.f3d) | bsd-3-clause |
| `digitalsputnik_T_bel_T2_v3` | extended | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/plastic/Tüübel-T2%20v3.f3d) | bsd-3-clause |
| `PacktPublishing_Hook` | extended | [PacktPublishing/3D-Printing-with-Fusion-360](https://github.com/PacktPublishing/3D-Printing-with-Fusion-360/blob/4c80cda6d17d/Chapter04/Hook.f3d) | mit |
| `PacktPublishing_2BC` | extended | [PacktPublishing/3D-Printing-with-Fusion-360](https://github.com/PacktPublishing/3D-Printing-with-Fusion-360/blob/4c80cda6d17d/Chapter09/2BC.f3d) | mit |
| `PacktPublishing_Bracket_Solid` | extended | [PacktPublishing/3D-Printing-with-Fusion-360](https://github.com/PacktPublishing/3D-Printing-with-Fusion-360/blob/4c80cda6d17d/Chapter05/Bracket-Solid.f3d) | mit |
| `PacktPublishing_Clip_Fixed` | extended | [PacktPublishing/3D-Printing-with-Fusion-360](https://github.com/PacktPublishing/3D-Printing-with-Fusion-360/blob/4c80cda6d17d/Chapter01/Clip_Fixed.f3d) | mit |
| `PacktPublishing_Example_B` | extended | [PacktPublishing/3D-Printing-with-Fusion-360](https://github.com/PacktPublishing/3D-Printing-with-Fusion-360/blob/4c80cda6d17d/Chapter06/Example%20B.f3d) | mit |
| `homebrew_pinball_Gate_Bracket_535_5742_00` | extended | [homebrew-pinball/fusion360-models](https://github.com/homebrew-pinball/fusion360-models/blob/5a0f50bd0e74/gates/Gate%20Bracket%20535-5742-00.f3d) | mit |
| `digitalsputnik_Apollo_Yoke_Lock_B_Side_P_MPLA000000177_v2` | extended | [digitalsputnik/ApolloHardware](https://github.com/digitalsputnik/ApolloHardware/blob/cde6e59bb1ee/hw/custom/plastic/Apollo%20Yoke%20Lock%20B%20Side%20[(P)MPLA000000177]%20v2.f3d) | bsd-3-clause |
| `AdamLaskoi_SG90_Micro_Servo_9g_v1` | extended | [AdamLaskoi/my_3Dmodels](https://github.com/AdamLaskoi/my_3Dmodels/blob/2984c0ff7a6c/SG90_Micro%20Servo%209g%20v1.f3d) | cc0-1.0 |
| `PacktPublishing_Connector_Bracket` | extended | [PacktPublishing/3D-Printing-with-Fusion-360](https://github.com/PacktPublishing/3D-Printing-with-Fusion-360/blob/4c80cda6d17d/Chapter08/Connector%20Bracket.f3d) | mit |
| `intuibase_Co2SensorEnclosure` | extended | [intuibase/esp32_co2_monitor](https://github.com/intuibase/esp32_co2_monitor/blob/0db87bfa69f0/enclosure/f3d/Co2SensorEnclosure.f3d) | mit |
| `runtimerobotics_rosbot` | extended | [runtimerobotics/fusion360-urdf-ros2](https://github.com/runtimerobotics/fusion360-urdf-ros2/blob/e317c5e00e10/demos/rosbot/rosbot.f3d) | mit |
| `adafruit_727_3xAAA_JST_Battery_Holder` | extended | [adafruit/Adafruit_CAD_Parts](https://github.com/adafruit/Adafruit_CAD_Parts/blob/9f2a89f3d5c3/727%203x%20AAA%20Battery%20Holder/727%203xAAA%20JST%20Battery%20Holder.f3d) | mit |
| `busraakgun24_kol` | extended | [busraakgun24/Fusion360-Projects](https://github.com/busraakgun24/Fusion360-Projects/blob/867caaed0dab/kol.f3d) | cc0-1.0 |
| `Saurabh_Mudgal_Crusher_Shaft` | extended | [Saurabh-Mudgal/Fusion360_SugarCane-Machine](https://github.com/Saurabh-Mudgal/Fusion360_SugarCane-Machine/blob/a8f51a9ae8e9/Crusher%20Shaft%20.f3d) | mit |
| `PacktPublishing_Ch12_tealight_ghost_final` | extended | [PacktPublishing/Improving-CAD-Designs-with-Autodesk-Fusion-360](https://github.com/PacktPublishing/Improving-CAD-Designs-with-Autodesk-Fusion-360/blob/04ccbf639ed7/Ch12/Ch12_tealight%20ghost_final.f3d) | mit |
| `adafruit_2831_Photo_Transistor_Light_Sensor` | extended | [adafruit/Adafruit_CAD_Parts](https://github.com/adafruit/Adafruit_CAD_Parts/blob/9f2a89f3d5c3/2831%20Photo%20Transistor%20Light%20Sensor/2831%20Photo%20Transistor%20Light%20Sensor.f3d) | mit |
