# Prompt Pack

Status: Target

This folder holds mirror docs for reusable wording blocks plus compatibility pages for the prompt layer.

The shipped exact wording blocks live under `apps/api/src/autoclaw/runtime/prompt/assets/`. The exact-block sections in this folder must stay byte-for-byte aligned with those assets, including trailing newline preservation. The prompt catalog classifies each exact block as either a live `live_instruction_block` consumed by runtime instruction assembly or a `reference_only` exact block kept for search, validation, or example routing.

## Canonical Live Prompt-Pack Pages

Read these first:

1. [Runtime Rule Blocks](runtime-rule-blocks.md)
2. [System And Provider Block](system-and-provider-block.md)
3. [Validation And Reject Blocks](validation-and-reject-blocks.md)

These are the live reusable wording owners for:

- controller/DB truth versus generated projections
- public boundary model
- tool usage and closure rules
- retry wording
- filesystem and surfaced-ref wording
- provider transport wording
- reject wording and worked `boundary_precondition_failed` examples

## Exact Block Ownership

Use these exact block ids when you need copy-ready shared wording. Load the shipped bytes from `apps/api/src/autoclaw/runtime/prompt/assets/`; use these docs as the human-readable mirror and routing surface:

| Need                                          | Exact owner block                                                                                    |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| shared system/runtime block                   | [System And Provider Block](system-and-provider-block.md) -> `autoclaw_system_block_v1`              |
| provider continuity / transport block         | [System And Provider Block](system-and-provider-block.md) -> `autoclaw_provider_continuity_block_v1` |
| worker dispatch opening block                 | [System And Provider Block](system-and-provider-block.md) -> `worker_dispatch_opening_v1`            |
| parent/root dispatch opening block            | [System And Provider Block](system-and-provider-block.md) -> `parent_root_dispatch_opening_v1`       |
| runtime concept glossary                      | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `runtime_concept_glossary_v1`                       |
| worker assignment doctrine                    | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `worker_assignment_doctrine_v1`                     |
| parent/root orchestration doctrine            | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `parent_root_orchestration_doctrine_v1`             |
| parent/root current assignment doctrine       | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `parent_root_current_assignment_doctrine_v1`        |
| parent/root child assignment writing guide    | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `parent_root_child_assignment_writing_guide_v1`     |
| conditional human-request use guide           | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `human_request_use_guide_v1`                        |
| conditional command-run use guide             | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `command_run_use_guide_v1`                          |
| checkpoint authoring guide                    | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `checkpoint_authoring_guide_v1`                     |
| reusable boundary stanza                      | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `runtime_boundary_rule_block_v1`                    |
| worker legality block                         | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `runtime_legality_block_worker_v1`                  |
| parent/root legality block                    | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `runtime_legality_block_parent_v1`                  |
| current-task-state framing block              | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `current_task_state_frame_v1`                       |
| artifact compact-render reminder              | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `artifact_render_rule_v1`                           |
| monitoring-is-not-task-truth reminder         | [Runtime Rule Blocks](runtime-rule-blocks.md) -> `monitoring_not_task_truth_v1`                      |
| exact reject wording and stale-guard examples | [Validation And Reject Blocks](validation-and-reject-blocks.md)                                      |

Pair these exact blocks with:

- [Rendered Examples](../generated/rendered-examples.md) for secondary rendered prompt body readback
- [Field Renderers](../field-renderers.md) for section-level render rules
- [Source And Sections](../source-and-sections.md) for section provenance

This folder owns reusable prompt wording blocks. It does not own machine reject envelopes or generated rendered prompt body readback.

## Historical Compatibility Pages

These pages remain searchable for migration/background only and must not overrule the live owner docs:

- [Dispatch Family Packs](dispatch-family-packs.md)
- [State And Boundary Overlays](state-and-boundary-overlays.md)
- [Historical Packet Prose Examples](historical-packet-prose-examples.md)

## Search-First Routing

- "Where is the canonical runtime wording?" [Runtime Rule Blocks](runtime-rule-blocks.md)
- "Where is the canonical system/provider wording?" [System And Provider Block](system-and-provider-block.md)
- "Where is the exact worker or parent/root legality text?" [Runtime Rule Blocks](runtime-rule-blocks.md)
- "Where is the exact system block to paste into a runtime prompt?" [System And Provider Block](system-and-provider-block.md)
- "Where is the exact rendered prompt body example that uses these blocks?" [Rendered Examples](../generated/rendered-examples.md)
- "Where is the exact prompt-layer reject wording page?" [Validation And Reject Blocks](validation-and-reject-blocks.md)
- "Where are the exact prompt-layer reject wording and the current API reject carrier fields?" [Validation And Reject Blocks](validation-and-reject-blocks.md) and [API Schema Appendix](../../interfaces/api-schema-appendix.md)
- "Where is the exact boundary-precondition rule the wording must match?" [Runtime Boundary And Controller Loop Contract](../../architecture/runtime-boundary-and-controller-loop-contract.md)
- "Where did old dispatch-family prompt packs go?" [Dispatch Family Packs](dispatch-family-packs.md)
- "Where did packet or bundle prose examples go?" [Historical Packet Prose Examples](historical-packet-prose-examples.md)
