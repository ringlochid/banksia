# Prompt legality and coverage

Status: Reference

This page is a secondary coverage summary for the live v1 prompt model.

If this page drifts from the owner docs in this folder, the owner docs win.

Use it to cross-check generated examples, generated inventories, and search routes. Use [Contract](contract.md), [Source And Sections](source-and-sections.md), and [Prompt Resource Usage Appendix](prompt-resource-usage-appendix.md) for owner-level prompt truth.

## Prompt-family cross-check

Cross-check that the owner docs still describe exactly two base prompt families:

- `worker_dispatch_prompt`
- `parent_root_dispatch_prompt`

Provider, adapter, or watchdog-specific variants are wrappers or generated examples over these two families, not separate canonical families.

## Send-mode cross-check

- `full_prompt`

Cross-check that the owner docs still keep these live consequences:

- `full_prompt` is required for first dispatch and retry
- dispatch control emits `full_prompt` for every live dispatch
- same-session continuity must not be described as a live controller prompt path or as part of coverage completeness

## Coverage checklist

Prompt coverage is complete in v1 when the generated examples, inventories, and secondary summaries all still align with the owner docs:

- every current dispatchable node turn maps to one of the two base prompt families
- the generated inventory and rendered examples follow the canonical section order
- prompts teach only the live boundary model:
    - ingress: `dispatch`
    - egress: `yield | green | retry | blocked`
- prompts use path-only surfaced refs
- prompts render `instruction`, not `instruction_text`
- prompts never teach flow/scope manifest split, packet families, or gate-era callback legality as live contract

## Family expectations

### `worker_dispatch_prompt`

Must support:

- current assignment execution
- durable publication
- terminal closure by `green | retry | blocked`

### `parent_root_dispatch_prompt`

Must support:

- explicit parent/root tool use
- structural edit orientation
- surfaced child evidence review
- non-terminal closure through `yield`
- terminal closure through `green | blocked` when the parent/root node itself is closing its own current assignment; root whole-flow `blocked` closure also requires committed `release_blocked`

## Generated-artifact rule

`prompt-catalog.yaml`, [Inventory](generated/inventory.md), and [Rendered Examples](generated/rendered-examples.md) are generated or secondary artifacts and must match the live owner docs.

If they drift, the owner docs win and the generated artifacts are stale.

In particular:

- worker prompts must surface `latest_checkpoint_context` when retry or other prior checkpoint evidence is part of the current execution
- parent/root prompts must surface `latest_checkpoint_context` and `consumed_durable_refs` when the current decision depends on surfaced child or prior-attempt evidence

## Exact Validation And Reject Routes

Use these pages when the question is "what exact reject or legality message does the runtime emit after a prompt-driven action?"

- [Validation And Reject Blocks](prompt-pack/validation-and-reject-blocks.md) for exact prompt-layer reject wording and worked examples
- [Runtime Boundary And Controller Loop Contract](../architecture/runtime-boundary-and-controller-loop-contract.md) for exact `dispatch`, `yield`, `green`, `retry`, `blocked`, and `boundary_precondition_failed` meaning
- [API Surface And Trust Lane Map](../interfaces/api-surface-and-trust-lane-map.md) for exact route/lane legality of checkpoint, boundary, and tool calls
- [API Schema Appendix](../interfaces/api-schema-appendix.md) for exact error payload carriers such as `code`, `field_path`, and `suggested_next_step`

Use this page when the question is "does the prompt family and example set cover the live model completely?"

## Exact Prompt Example Routes

Use these pages when the question is "show me the whole prompt exactly as a reader would see it":

- [Rendered Examples](generated/rendered-examples.md) for exact worker and parent/root examples plus any retained deletion-target compatibility mirrors
- [System And Provider Block](prompt-pack/system-and-provider-block.md) for exact shared top-level blocks
- [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md) for exact legality and support blocks

## Historical search terms

Do not treat any of these as the live v1 prompt-coverage model:

- `parent_gate_resume`
- `worker_retry` as a separate prompt family
- dispatch-family packs
- state/boundary overlay families as first-class prompt authorities
