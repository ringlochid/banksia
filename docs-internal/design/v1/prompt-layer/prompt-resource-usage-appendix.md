# Prompt resource and usage appendix

Status: Target

This appendix is the exhaustive prompt-layer detail owner for the live v1 prompt section order, read order, filesystem guidance, and render detail.

Use [Contract](contract.md) for the core semantic prompt contract. Use this appendix when exact section ordering, read ordering, filesystem guidance, or render detail matters.

The core owner pages that this appendix extends are:

- [Contract](contract.md)
- [Source And Sections](source-and-sections.md)
- [Field Renderers](field-renderers.md)
- [Render And Persistence](render-and-persistence.md)
- [System And Provider Block](prompt-pack/system-and-provider-block.md)
- [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md)

Shipped exact block bytes live under `apps/api/src/autoclaw/runtime/prompt/assets/`. Prompt-pack markdown stays as the human-readable mirror surface.

## Section inventory

The live section order is:

1. `operating_model`
2. `task_identity`
3. `node_purpose`
4. `current_dispatch`
5. `workflow_manifest`
6. `current_assignment`
7. `latest_checkpoint_context`
8. `consumed_durable_refs`
9. `transient_refs`
10. `allowed_actions_now`
11. `publication_rule`

## Current read order

The prompt should teach this read order:

1. `_runtime/workflow-manifest.*`
2. `_runtime/attempts/<attempt_id>/assignment.*`
3. `latest_relevant_checkpoint_path` when present, otherwise the current attempt-local `_runtime/attempts/<attempt_id>/latest-checkpoint.*`
4. surfaced `consumed_durable_refs`, built from the current assignment durable claims plus surfaced current-relevant durable refs
5. optional `transient_refs`

## Filesystem guidance

The prompt layer should consistently teach:

- `workspace/` = mutable current-assignment work
- `_runtime/criteria/` = explicit criteria projections
- `outputs/artifacts/` = durable published outputs and evidence
- `tmp/transfers/` = optional transient carryover
- `_runtime/` = controller-generated projections and monitoring

## Render reminders

### Workflow manifest

Render:

- stable manifest path
- short description
- current node anchor
- optional surfaced current-relevant paths when they sharpen orientation

### Assignment

Render:

- `path`
- `summary`
- `instruction`
- `criteria`
- `consumes`
- `produces`
- optional `transient_refs`

### Checkpoint

Render:

- `path`
- `checkpoint_kind`
- `outcome`
- `summary`
- `next_step`
- optional `blockers`
- optional `risks`
- optional `produced_artifacts`
- optional `transient_refs`

### Consumed durable refs

Render:

- the de-duplicated union of assignment `criteria`, assignment `consumes`, and surfaced current-relevant durable refs
- `kind`
- optional `slot`
- optional `version`
- `path`
- `description`

Do not repeat the checkpoint path already rendered in `Latest Checkpoint Context`. If no durable refs are surfaced, worker prompts still render `- no current durable refs are surfaced for this turn`; parent/root prompts may omit the section.

### Compact refs

Artifact refs surface only:

- `slot`
- `version`
- `path`
- `description`

Non-artifact durable refs surface only:

- `kind`
- optional `slot`
- `path`
- `description`

Transient refs surface only:

- `path`
- `description`

## Prompt artifact expectations

The prompt layer maintains these secondary implementation artifacts:

- [prompt-catalog.yaml](prompt-catalog.yaml)
- [Inventory](generated/inventory.md)
- [Rendered Examples](generated/rendered-examples.md)

They are useful for generation and validation, but if they drift from the live owner docs, the owner docs win and the artifacts must be regenerated.

For the v1 static `node MCP` bridge, dispatch-local prompt state may surface `task_id` and `session_key` for tool calls. That bridge belongs to the live owner pages in this folder and must not be inferred from support-state files or header-based transport examples.

`delivery-state.json` remains observability-only in this appendix. It is a raw delivery rollup for debug/readback, not a prompt-layer carrier for controller control-state meaning.

## Exact Prompt Lookup Table

Use this quick table when you need the exact live page for one prompt-layer question.

| Need                                                           | Exact page                                                                                                        |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| exact shared system block                                      | [System And Provider Block](prompt-pack/system-and-provider-block.md)                                             |
| exact provider continuity block                                | [System And Provider Block](prompt-pack/system-and-provider-block.md)                                             |
| exact worker legality block                                    | [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md)                                                         |
| exact parent/root legality block                               | [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md)                                                         |
| exact worker full prompt example                               | [Rendered Examples](generated/rendered-examples.md)                                                               |
| exact parent/root full prompt example                          | [Rendered Examples](generated/rendered-examples.md)                                                               |
| exact `full_prompt` request composition                        | [Composition Example](composition-example.md)                                                                     |
| exact authored task title / summary / instruction launch shape | [Task Compose Schema](../workflows/task-compose-schema.md)                                                        |
| exact generated section order                                  | [Inventory](generated/inventory.md)                                                                               |
| exact prompt-layer validation/reject wording                   | [Validation And Reject Blocks](prompt-pack/validation-and-reject-blocks.md)                                       |
| exact API reject carrier fields                                | [API Schema Appendix](../interfaces/api-schema-appendix.md)                                                       |
| exact boundary-precondition rule                               | [Runtime Boundary And Controller Loop Contract](../architecture/runtime-boundary-and-controller-loop-contract.md) |

## Searchability note

Live exact-query intents should route as live prompt-layer questions:

- `exact system prompt` [System And Provider Block](prompt-pack/system-and-provider-block.md)
- `exact validation message` [Validation And Reject Blocks](prompt-pack/validation-and-reject-blocks.md)
- `exact reject payload` [Validation And Reject Blocks](prompt-pack/validation-and-reject-blocks.md) and [API Schema Appendix](../interfaces/api-schema-appendix.md)
- `current/debt same-session wrapper scheduled for deletion` [System And Provider Block](prompt-pack/system-and-provider-block.md) and [Rendered Examples](generated/rendered-examples.md)
- `exact request composition` [Composition Example](composition-example.md)

Historical search terms remain:

- old dispatch families
- packet or bundle prose
- flow/scope manifest prompt inputs
- `WorkerContext`
- `instruction_text`

Those historical terms should route to compatibility pages only. The live exact-query intents above are part of the current prompt contract.
