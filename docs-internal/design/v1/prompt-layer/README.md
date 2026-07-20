# Prompt Layer

Status: Target

> **V2 supersession notice:** This directory remains the frozen V1 prompt baseline. V2 current-context reads, optional assignment work plans, narrowed checkpoints, and the two-file provider-neutral request are owned by [Prompt system](../../v2/prompt-layer/prompt-system.md) and [Work plan and checkpoint contract](../../v2/architecture/work-plan-and-checkpoint-contract.md).

This folder owns the canonical frozen v1 prompt contract for the current runtime model.

Read this folder with this mental model first:

- controller/DB state owns runtime truth
- prompts are derived execution briefs over manifest, assignment, checkpoint, and surfaced refs
- the manifest is the whole-workflow picture, the assignment is the current mission, and the checkpoint is the durable "what happened / what next" handoff
- semantic assignment handoff stays separate from exact runtime-resolved durable refs in `consumed_durable_refs`
- files under `_runtime/dispatch/` are observability projections, not ordinary assignment truth
- structural edits start from surfaced role/policy names in the compact `structural_edit_palette`, may use the current-only `search_definitions` / `get_definition` lookup lane when that palette is insufficient, and runtime revalidates committed names on commit
- if surfaced context is insufficient or conflicting, reread current truth, search hinted curated files, and use a legal checkpoint or current-node boundary instead of guessing
- `tool` is the canonical runtime term
- `plugin` is adapter-specific only
- v1 surfaced refs are path-only
- shipped exact prompt blocks are app-owned packaged Markdown assets under `apps/api/src/autoclaw/runtime/prompt/assets/`
- prompt-pack markdown pages are audited mirrors of those shipped assets

A retained secondary search router exists for legacy entry points. This `README.md` is the canonical prompt-layer front door.

Use the [secondary prompt-layer index](INDEX.md) only when arriving from a legacy search term.

## Start Here

Read in this order:

1. [Contract](contract.md)
2. [Source And Sections](source-and-sections.md)
3. [Field Renderers](field-renderers.md)
4. [Render And Persistence](render-and-persistence.md)
5. [Machine Contract](machine-contract.md)
6. [Prompt Resource Usage Appendix](prompt-resource-usage-appendix.md)
7. [Prompt-pack front door](prompt-pack/README.md)
8. [Generated prompt-layer artifacts front door](generated/README.md)

## Canonical Live Owners

- [Contract](contract.md) overall prompt contract, section order, prompt families, and the live `full_prompt` redispatch model
- [Source And Sections](source-and-sections.md) source provenance and section ownership
- [Field Renderers](field-renderers.md) exact compact render rules for assignments, checkpoints, and surfaced refs
- [Render And Persistence](render-and-persistence.md) persisted prompt artifacts and transport wrapper rules
- [Machine Contract](machine-contract.md) machine-readable catalog and validation expectations
- [Prompt Resource Usage Appendix](prompt-resource-usage-appendix.md) exhaustive prompt section order, read order, filesystem guidance, and render-detail appendix owner
- [System And Provider Block](prompt-pack/system-and-provider-block.md) exact shared system, provider, and family-specific opening blocks
- [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md) exact worker/parent legality blocks plus shared runtime wording fragments
- [Validation And Reject Blocks](prompt-pack/validation-and-reject-blocks.md) exact prompt-layer reject wording and boundary-precondition examples

## Secondary Live References

These pages are live supporting references and readback aids. They must not override the canonical owners above, but they are not historical migration stubs:

- [Composition Example](composition-example.md) exact `full_prompt` composition
- [Rendered Examples](generated/rendered-examples.md) generated or canonicalized rendered prompt body readback for worker and parent/root
- [Generated prompt-layer artifacts front door](generated/README.md) generated artifact routing and authority rule
- [Legality And Coverage](legality-and-coverage.md) coverage summary and cross-check reference

## Exact Text And Validation Routes

Use these routes when the question is "what exact text do I send or expect?"

- exact shared system block: [System And Provider Block](prompt-pack/system-and-provider-block.md) -> `autoclaw_system_block_v1`
- exact provider continuity block: [System And Provider Block](prompt-pack/system-and-provider-block.md) -> `autoclaw_provider_continuity_block_v1`
- exact boundary wording reused by every prompt family: [System And Provider Block](prompt-pack/system-and-provider-block.md) and [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md)
- exact worker or parent/root opening block: [System And Provider Block](prompt-pack/system-and-provider-block.md) -> `worker_dispatch_opening_v1` or `parent_root_dispatch_opening_v1`
- exact runtime concept glossary: [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md) -> `runtime_concept_glossary_v1`
- exact worker assignment doctrine: [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md) -> `worker_assignment_doctrine_v1`
- exact parent/root orchestration doctrine: [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md) -> `parent_root_orchestration_doctrine_v1`
- exact parent/root current assignment doctrine: [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md) -> `parent_root_current_assignment_doctrine_v1`
- exact parent/root child assignment writing guide: [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md) -> `parent_root_child_assignment_writing_guide_v1`
- exact conditional human-request and command-run guides: [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md) -> `human_request_use_guide_v1`, `command_run_use_guide_v1`
- exact checkpoint authoring guide: [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md) -> `checkpoint_authoring_guide_v1`
- exact worker or parent/root legality block: [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md)
- exact rendered worker or parent/root prompt: [Rendered Examples](generated/rendered-examples.md)
- exact `full_prompt` request composition: [Composition Example](composition-example.md)
- exact node/role/policy instruction assembly: [System And Provider Block](prompt-pack/system-and-provider-block.md), [Workflow Definition Schema](../workflows/workflow-definition-schema.md), and [Role And Policy Definition Schema](../interfaces/role-and-policy-definition-schema.md)
- exact authored task-intent launch shape: [Task Compose Schema](../workflows/task-compose-schema.md)
- exact generated section order and family inventory: [Inventory](generated/inventory.md), [Machine Contract](machine-contract.md), and [Prompt Resource Usage Appendix](prompt-resource-usage-appendix.md)
- exact prompt-layer reject wording examples: [Validation And Reject Blocks](prompt-pack/validation-and-reject-blocks.md)
- exact API reject carrier fields such as `code`, `field_path`, and `suggested_next_step`: [API Schema Appendix](../interfaces/api-schema-appendix.md)
- exact boundary-precondition meaning for `yield`, `green`, `retry`, and `blocked`: [Runtime Boundary And Controller Loop Contract](../architecture/runtime-boundary-and-controller-loop-contract.md)
- exact route/lane legality for checkpoint, boundary, and tool calls: [API Surface And Trust Lane Map](../interfaces/api-surface-and-trust-lane-map.md)

## Search-First Questions

- "What does the prompt always teach?" [Contract](contract.md)
- "What is the exact system block to paste into the runtime prompt?" [System And Provider Block](prompt-pack/system-and-provider-block.md)
- "What is the exact worker or parent legality block?" [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md)
- "Where does each section come from?" [Source And Sections](source-and-sections.md)
- "How should refs and artifacts render?" [Field Renderers](field-renderers.md)
- "What is persisted versus inline transport?" [Render And Persistence](render-and-persistence.md)
- "What are the machine-readable prompt families and section ids?" [Machine Contract](machine-contract.md)
- "Where is the machine-readable generated catalog?" [prompt-catalog.yaml](prompt-catalog.yaml)
- "Where are the exact worker and parent/root prompt examples?" [Rendered Examples](generated/rendered-examples.md)
- "Where is the exact `full_prompt` request composition?" [Composition Example](composition-example.md)

Compatibility note:

- canonical v1 runtime control keeps same-session continuity only as the preferred parent/root same-attempt redispatch path, still opens a fresh live run, falls back to a fresh `sessionKey` when continuity reuse is unavailable, and still resends the full regenerated prompt package
- canonical v1 static `node MCP` uses explicit `task_id` + `session_key` in dispatch-local prompt state; hidden/plugin/header binding is not part of the v1 contract
- "Where is role/policy description and instruction assembly defined?" [System And Provider Block](prompt-pack/system-and-provider-block.md) and [Role And Policy Definition Schema](../interfaces/role-and-policy-definition-schema.md)
- "Where is the authored task title / summary / instruction launch shape?" [Task Compose Schema](../workflows/task-compose-schema.md)
- "What wording should be reused verbatim?" [Prompt-pack front door](prompt-pack/README.md)
- "Where are the exact validation and reject wording blocks?" [Validation And Reject Blocks](prompt-pack/validation-and-reject-blocks.md)
- "Where are generated examples and inventories?" [Generated prompt-layer artifacts front door](generated/README.md)
- "Where is the exact validation or reject payload shape?" [Validation And Reject Blocks](prompt-pack/validation-and-reject-blocks.md) and [API Schema Appendix](../interfaces/api-schema-appendix.md)
- "Where is the exact boundary-precondition rule that prompt closure text must match?" [Runtime Boundary And Controller Loop Contract](../architecture/runtime-boundary-and-controller-loop-contract.md)

## Historical And Compatibility Material

These pages remain for migration/search compatibility and must not overrule the canonical owners above:

- [Historical Prompt And Artifact Layers](historical-prompt-and-artifact-layers.md)
- historical prompt-pack compatibility pages called out in the [Prompt-pack front door](prompt-pack/README.md)

Treat those pages as:

- `Reference` = secondary explanation, generated readback aid, or migration/search router only

## Generated Material Rule

`prompt-catalog.yaml` and the files under `generated/` are implementation artifacts and secondary references.

The shipped exact block source is the app-owned asset catalog under `apps/api/src/autoclaw/runtime/prompt/assets/`. The prompt-pack docs mirror those assets for human routing and validation.

They are useful for validation and examples, but if they drift from the live owner docs, the live owner docs win and the generated artifacts must be regenerated.

For prompt-driven runtime validation and reject wording, the prompt layer must stay aligned with:

- [Runtime Boundary And Controller Loop Contract](../architecture/runtime-boundary-and-controller-loop-contract.md)
- [API Surface And Trust Lane Map](../interfaces/api-surface-and-trust-lane-map.md)
- [API Schema Appendix](../interfaces/api-schema-appendix.md)
