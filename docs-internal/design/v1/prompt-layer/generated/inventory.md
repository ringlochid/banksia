# Generated Prompt Inventory

Status: Reference

This page inventories the current generated prompt contract surfaces. Static exact blocks are shipped from app-owned assets under `apps/api/src/autoclaw/runtime/prompt/assets/`, while the prompt-pack docs remain human-readable mirrors.

## Canonical Section Order

1. `operating_model`
2. `task_identity`
3. `node_purpose`
4. `current_dispatch`
5. `capabilities_now`
6. `workflow_manifest`
7. `current_assignment`
8. `latest_checkpoint_context`
9. `boundary_followup_guidance`
10. `consumed_durable_refs`
11. `transient_refs`
12. `allowed_actions_now`
13. `publication_rule`

## Static Continuation Sections

- `operating_model`
- `task_identity`
- `node_purpose`

## Canonical Prompt Families

- `worker_dispatch_prompt`
- `parent_root_dispatch_prompt`

## Canonical Send Modes

- `full_prompt`

## Exact Block Registry

- `autoclaw_system_block_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/autoclaw_system_block_v1.md`
  - mirror doc: `prompt-pack/system-and-provider-block.md`
  - role: `exact_system_block`
  - consumption: `live_instruction_block`
- `autoclaw_provider_continuity_block_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/autoclaw_provider_continuity_block_v1.md`
  - mirror doc: `prompt-pack/system-and-provider-block.md`
  - role: `provider_transport_rule`
  - consumption: `live_instruction_block`
- `worker_dispatch_opening_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/worker_dispatch_opening_v1.md`
  - mirror doc: `prompt-pack/system-and-provider-block.md`
  - role: `worker_dispatch_opening_block`
  - consumption: `live_instruction_block`
- `parent_root_dispatch_opening_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/parent_root_dispatch_opening_v1.md`
  - mirror doc: `prompt-pack/system-and-provider-block.md`
  - role: `parent_root_dispatch_opening_block`
  - consumption: `live_instruction_block`
- `parent_root_current_assignment_doctrine_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/parent_root_current_assignment_doctrine_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `parent_root_current_assignment_doctrine`
  - consumption: `live_instruction_block`
- `parent_root_child_assignment_writing_guide_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/parent_root_child_assignment_writing_guide_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `parent_root_child_assignment_writing_guide`
  - consumption: `live_instruction_block`
- `human_request_use_guide_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/human_request_use_guide_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `human_request_use_guide`
  - consumption: `live_instruction_block`
- `command_run_use_guide_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/command_run_use_guide_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `command_run_use_guide`
  - consumption: `live_instruction_block`
- `runtime_concept_glossary_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/runtime_concept_glossary_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `runtime_concept_glossary`
  - consumption: `live_instruction_block`
- `worker_assignment_doctrine_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/worker_assignment_doctrine_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `worker_assignment_doctrine`
  - consumption: `live_instruction_block`
- `parent_root_orchestration_doctrine_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/parent_root_orchestration_doctrine_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `parent_root_orchestration_doctrine`
  - consumption: `live_instruction_block`
- `checkpoint_authoring_guide_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/checkpoint_authoring_guide_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `checkpoint_authoring_guide`
  - consumption: `live_instruction_block`
- `runtime_legality_block_worker_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/runtime_legality_block_worker_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `worker_legality_rule`
  - consumption: `live_instruction_block`
- `runtime_legality_block_parent_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/runtime_legality_block_parent_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `parent_root_legality_rule`
  - consumption: `live_instruction_block`
- `runtime_boundary_rule_block_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/runtime_boundary_rule_block_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `boundary_rule`
  - consumption: `live_instruction_block`
- `retry_handover_rule_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/retry_handover_rule_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `retry_rule`
  - consumption: `reference_only`
- `runtime_read_order_rule_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/runtime_read_order_rule_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `read_order_rule`
  - consumption: `live_instruction_block`
- `current_task_state_frame_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/current_task_state_frame_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `section_coverage_rule`
  - consumption: `reference_only`
- `artifact_render_rule_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/artifact_render_rule_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `artifact_render_rule`
  - consumption: `live_instruction_block`
- `monitoring_not_task_truth_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/monitoring_not_task_truth_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `monitoring_rule`
  - consumption: `live_instruction_block`
- `worker_runtime_opening_example_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/worker_runtime_opening_example_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `runtime_opening_example`
  - consumption: `reference_only`
- `parent_root_runtime_opening_example_v1`
  - asset: `apps/api/src/autoclaw/runtime/prompt/assets/blocks/parent_root_runtime_opening_example_v1.md`
  - mirror doc: `prompt-pack/runtime-rule-blocks.md`
  - role: `runtime_opening_example`
  - consumption: `reference_only`

## Generated Artifact Registry

- `rendered_examples`
  - file: `generated/rendered-examples.md`

## Generated Example Registry

- `parent_root_dispatch_prompt_full_prompt`
  - rendered heading: `parent_root_dispatch_prompt`
  - family: `parent_root_dispatch_prompt`
  - send mode: `full_prompt`
- `parent_root_dispatch_prompt_non_root_blocked_full_prompt`
  - rendered heading: `parent_root_dispatch_prompt non-root blocked closure`
  - family: `parent_root_dispatch_prompt`
  - send mode: `full_prompt`
- `worker_dispatch_prompt_full_prompt`
  - rendered heading: `worker_dispatch_prompt`
  - family: `worker_dispatch_prompt`
  - send mode: `full_prompt`
- `worker_dispatch_prompt_blocked_ending_sketch`
  - rendered heading: `worker_dispatch_prompt blocked-ending sketch`
  - family: `worker_dispatch_prompt`
  - send mode: `full_prompt`
