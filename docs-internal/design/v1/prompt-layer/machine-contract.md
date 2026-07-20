# Prompt Machine Contract

Status: Target

This page defines the simplified machine-readable prompt contract for the frozen v1 prompt layer.

## Owner Docs And Machine Artifacts

Canonical owner docs:

- `contract.md`
- `source-and-sections.md`
- `machine-contract.md`
- `prompt-pack/runtime-rule-blocks.md`

Secondary machine artifacts:

- `prompt-catalog.yaml`
- `generated/rendered-examples.md`
- `apps/api/src/autoclaw/runtime/prompt/assets/catalog.json`

If any generated or catalog artifact still teaches flow/scope manifests, callback legality, final durable ref metadata inside semantic assignment handoff, or checkpoint `control_effects`, it is stale and must not overrule the canonical owner docs.

## Top-Level Catalog Shape

The catalog must expose:

- `version`
- `owner_docs`
- `section_order`
- `static_sections`
- `send_modes`
- `prompt_families`
- `exact_blocks`
- `generated_artifacts`
- `generated_examples`
- `validation_references`
- `rules`
- `validator_checks`

Rules:

- `version` is fixed to `1`
- `section_order` is exactly the canonical section order from [Contract](contract.md)
- `static_sections` is exactly:
    - `operating_model`
    - `task_identity`
    - `node_purpose`
- live canonical `send_modes` owner docs freeze only `full_prompt`
- `prompt_families` freezes exactly two canonical dispatch prompt families
- `exact_blocks` registers reusable exact wording blocks, not extra prompt families
- shipped exact block bytes come from `apps/api/src/autoclaw/runtime/prompt/assets/**`, while the prompt-pack docs mirror those bytes for human review
- each `exact_blocks` entry must declare whether it is a live `live_instruction_block` consumed by runtime instruction assembly or a `reference_only` exact block
- `section_order` includes `capabilities_now` and `boundary_followup_guidance` in the live renderer order

## Prompt Family Registry

The live v1 family registry contains exactly:

- `worker_dispatch_prompt`
- `parent_root_dispatch_prompt`

All adapter/provider variants are wrappers or generated examples over these two families, not separate canonical prompt families.

## Semantic Assignment And Checkpoint Rules

Machine artifacts must keep these splits explicit:

- `current_assignment` is the runtime-projected assignment surface derived from child-definition durable contract plus parent semantic staging handoff surface
- `current_assignment.summary` plus optional `instruction` are handoff prose
- parent/root `assignment_intent.instruction` should remain acquisition-order guidance rather than vague assignment prose
- `current_assignment.criteria` and `current_assignment.consumes` are reduced durable claims only
- `current_assignment.produces` are `assignment_produce_requirement` values, not published refs
- `consumed_durable_refs` carries the exact current durable refs the runtime resolved for this turn
- `latest_checkpoint_context` mirrors durable handoff written through `record_checkpoint`
- `latest_checkpoint_context` must not teach or surface `control_effects`

## Live Exact Block Registry

The live catalog must register these exact reusable prompt blocks:

- `autoclaw_system_block_v1`
- `autoclaw_provider_continuity_block_v1`
- `worker_dispatch_opening_v1`
- `parent_root_dispatch_opening_v1`
- `runtime_concept_glossary_v1`
- `worker_assignment_doctrine_v1`
- `parent_root_orchestration_doctrine_v1`
- `parent_root_current_assignment_doctrine_v1`
- `parent_root_child_assignment_writing_guide_v1`
- `human_request_use_guide_v1`
- `command_run_use_guide_v1`
- `checkpoint_authoring_guide_v1`
- `runtime_legality_block_worker_v1`
- `runtime_legality_block_parent_v1`
- `runtime_boundary_rule_block_v1`
- `retry_handover_rule_v1`
- `runtime_read_order_rule_v1`
- `current_task_state_frame_v1`
- `artifact_render_rule_v1`
- `monitoring_not_task_truth_v1`
- `worker_runtime_opening_example_v1`
- `parent_root_runtime_opening_example_v1`

## Generated Artifact Registry

The catalog should register these secondary prompt-layer artifacts:

- `generated/rendered-examples.md`

## Generated Example Registry

The generated example registry should currently identify:

- `parent_root_dispatch_prompt_full_prompt`
- `worker_dispatch_prompt_full_prompt`
- `worker_dispatch_prompt_blocked_ending_sketch`

## Prompt Family Coverage

### `worker_dispatch_prompt`

Required sections:

- `operating_model`
- `task_identity`
- `node_purpose`
- `current_dispatch`
- `capabilities_now`
- `workflow_manifest`
- `current_assignment`
- `boundary_followup_guidance`
- `consumed_durable_refs`
- `allowed_actions_now`
- `publication_rule`

Conditionally required sections:

- `latest_checkpoint_context` when a prior relevant checkpoint is part of the current execution or retry handover
- `transient_refs` when explicit transient carryover is surfaced

### `parent_root_dispatch_prompt`

Required sections:

- `operating_model`
- `task_identity`
- `node_purpose`
- `current_dispatch`
- `capabilities_now`
- `workflow_manifest`
- `current_assignment`
- `boundary_followup_guidance`
- `allowed_actions_now`
- `publication_rule`

Conditionally required sections:

- `latest_checkpoint_context` when the current decision depends on surfaced checkpoint evidence
- `consumed_durable_refs` when surfaced durable evidence is part of the current decision
- `transient_refs` when explicit transient carryover is surfaced

## Validator Rules

Catalog, renderer, and generated examples must agree on:

- prompt family ids
- section order
- static sections
- purpose/mode concept guidance
- boundary follow-up guidance
- send modes
- semantic `current_assignment`
- runtime-resolved `consumed_durable_refs`
- `record_checkpoint` durable handoff semantics
- `produces` as requirements
- no checkpoint `control_effects`
- `yield` after exactly one staged child assignment only

Machine validation should reject live catalog/examples that:

- render exact durable `path` or `version` metadata inside `current_assignment.criteria` or `current_assignment.consumes`
- render published artifact refs inside `current_assignment.produces`
- omit `consumed_durable_refs` from worker prompts
- register parent/root terminal closure modes outside `yield | green | blocked`
- teach `yield` after `release_green` or root `release_blocked`
- teach `release_blocked` as a non-root parent path
- omit terminal `blocked` as a non-root parent path
- surface checkpoint `control_effects`
- route live prompt-layer owner or generated surfaces to legacy source packs instead of current owner docs
- register a third canonical dispatch prompt family
- keep non-canonical send modes in live prompt-family registries or live generated-example registries
- omit `capabilities_now` or `boundary_followup_guidance` from live section-order owner artifacts

Concrete validator failures:

```text
Reject:
- a worker example that omits `consumed_durable_refs`
- a current-assignment render that includes `path` for `findings_report`
- a current-assignment render that turns `patch` into a published artifact path
- a parent/root catalog family that still includes `retry` as a closure mode
- a checkpoint render that includes `control_effects`
- a root example that teaches `yield` after `release_green` or root `release_blocked`
- a non-root parent example that surfaces `release_blocked` as an allowed non-root action or omits terminal `blocked`
- a live prompt catalog that registers any non-`full_prompt` send mode or generated example
```

## Completeness Rule

The prompt layer is complete when:

- every dispatchable runtime phase maps to one of the two prompt families
- semantic assignment handoff and runtime-resolved durable refs are rendered as separate prompt surfaces
- reusable `record_checkpoint` and boundary wording stays registered through the exact blocks
- generated examples derive from the same section order and the live `full_prompt` delivery rules

## Related Contracts

- [Prompt contract](contract.md)
- [Prompt source and sections](source-and-sections.md)
- [Rendered examples](generated/rendered-examples.md)
