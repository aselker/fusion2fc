p='/home/neophile/Documents/Programming/Vibes/fusion/.worktrees/profiles/cadmpeg/crates/cadmpeg-codec-f3d/src/design/profile_select.rs'
s=open(p).read()
old='''                            if let Some(selection) = resolve_profile_curve_arrangement_regions(
                                group,
                                &curve_resolution.path_resolution(),
                                scoped_resolution,
                            )? {
                                *profile = selection;
                                break 'feature_edit;
                            }
                        }
'''
new='''                            if let Some(selection) = resolve_profile_curve_arrangement_regions(
                                group,
                                &curve_resolution.path_resolution(),
                                scoped_resolution,
                            )? {
                                *profile = selection;
                                break 'feature_edit;
                            }
                            if let Some(sketch) = profile_curve_selection_sketch(
                                group,
                                &curve_resolution.path_resolution(),
                            ) {
                                let states = scope
                                    .history_state_id()
                                    .zip(effective_previous_history_state_id);
                                let compact = compact_profile_loop_selection(
                                    group,
                                    &curve_resolution.path_resolution(),
                                );
                                if let Some(selection) = unselected_extrude_profile(
                                    scope,
                                    sketch,
                                    compact,
                                    states,
                                    curve_resolution,
                                    scoped_resolution,
                                )? {
                                    *profile = selection;
                                    if let (true, Some((state_id, prev_state_id))) =
                                        (is_to_termination, states)
                                    {
                                        to_distance_info = historical_extrude_to_distance(
                                            sketch,
                                            0.0,
                                            scoped_histories,
                                            state_id,
                                            prev_state_id,
                                        );
                                    }
                                    break 'feature_edit;
                                }
                            }
                        }
'''
assert s.count(old)==1
s=s.replace(old,new)
helper='''/// The neutral Sketch that every stored curve selection of `group` names
/// through its Sketch scope and owner text.
fn profile_curve_selection_sketch<'a>(
    group: &DesignConstructionOperandGroup,
    resolution: &EntitySelectionPathResolution<'a>,
) -> Option<&'a cadmpeg_ir::sketches::Sketch> {
    let stream = native_stream(&group.id)?;
    let mut selections = resolution.profile_curves.iter().filter(|selection| {
        native_stream(&selection.id) == Some(stream)
            && selection.scope_record_index == group.scope_record_index
            && selection.group_record_index == group.record_index
    });
    let first = selections.next()?;
    if selections.any(|selection| {
        selection.sketch_scope_record_index != first.sketch_scope_record_index
            || selection.owner_text != first.owner_text
    }) {
        return None;
    }
    let mut placements = resolution.placements.iter().filter(|placement| {
        native_stream(&placement.id) == Some(stream)
            && placement.scope_record_index == Some(first.sketch_scope_record_index)
    });
    let placement = placements.next()?;
    if placements.next().is_some() || placement.entity_id.suffix().to_string() != first.owner_text {
        return None;
    }
    let sketch = crate::ids::neutral_sketch_id(placement);
    resolution.sketches.iter().find(|candidate| candidate.id == sketch)
}

'''
anchor='fn profile_curve_selection_curves('
i=s.index(anchor)
s=s[:i]+helper+s[i:]
open(p,'w').write(s)
print("patched")
