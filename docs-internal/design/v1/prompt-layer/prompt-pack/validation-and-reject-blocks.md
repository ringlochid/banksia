# Validation and reject blocks

Status: Target

This page contains the canonical prompt-layer wording for validation failures, reject responses, stale guards, and boundary-precondition failures in the live frozen v1 model.

These blocks are wording and examples for prompts, generated examples, and human-facing reject surfaces. They are not controller pseudocode.

## Search-First Routing

- Exact runtime truth, boundary, retry, and read-order wording: [Runtime Rule Blocks](runtime-rule-blocks.md)
- Exact shared system/provider top blocks: [System And Provider Block](system-and-provider-block.md)
- Exact boundary-precondition and validation basis: [Runtime Boundary And Controller Loop Contract](../../architecture/runtime-boundary-and-controller-loop-contract.md)
- Exact `operation_failure` carrier fields: [API Schema Appendix](../../interfaces/api-schema-appendix.md)

## Prompt-Layer Compact Failure Rendering

Use this compact wording shape for prompt-layer reject and failure examples:

```text
operation_failure
- code: <machine_code>
- summary: <plain statement of why current committed truth rejects the request>
- suggested_next_step: <what to reread, republish, or change next>
```

Rules:

- This page owns the exact prompt-layer compact human-facing rendering used in prompt examples, operator-facing examples, and search-first routing.
- This page owns the message substance for prompt-layer rejects and failure examples.
- `docs-internal/design/v1/interfaces/api-schema-appendix.md` is the API/status carrier reference for `operation_failure`. It does not replace the runtime legality rules or the prompt-layer message substance.
- Keep `code` exactly aligned to the live machine enum.
- `summary` explains the current failure. It must not add contradictory semantics.
- `suggested_next_step` should tell the caller what to reread, republish, or change next. Avoid vague advice such as "try again later."
- When `field_path` or `retryable` is available in a richer envelope, it may be shown separately, but the wording below remains the canonical message substance.

## Code Inventory

The live prompt-layer reject families are:

- `invalid_request_shape`
- `illegal_caller`
- `illegal_target_relation`
- `illegal_state`
- `stale_dispatch`
- `stale_flow_revision`
- `stale_assignment`
- `stale_checkpoint`
- `missing_resource`
- `missing_required_publication`
- `conflicting_continuation`
- `boundary_precondition_failed`
- `removed_surface`
- `budget_exhausted`
- `internal_error`

## Shape And Authority Rejects

### `invalid_request_shape_reject_v1`

```text
operation_failure
- code: invalid_request_shape
- summary: The request is missing one or more required fields or uses fields that are not part of the live v1 surface.
- suggested_next_step: Reread the canonical tool or boundary payload shape, then resend the request with only the live required fields.
```

Use this when the request contains stale field families such as:

- `instruction_text` instead of `instruction`
- `url` or `uri` instead of path-only surfaced refs
- callback-era wrapper fields
- missing `assignment_intent.summary` in `AssignChildPayload`
- materialized durable refs passed into parent-side assignment staging
- missing `handoff.summary` or `handoff.next_step` in checkpoint write

### `illegal_caller_reject_v1`

```text
operation_failure
- code: illegal_caller
- summary: This control or boundary action is not legal from the current caller.
- suggested_next_step: Reread the current dispatch context and use only the tools or boundaries legal for this node and this open dispatch.
```

Use this when:

- a worker tries to use parent/root control tools
- a non-root caller tries to use `release_blocked`
- a closed or different caller tries to act as the current dispatched node

### `illegal_target_relation_reject_v1`

```text
operation_failure
- code: illegal_target_relation
- summary: The targeted node is not inside this parent/root node's owned subtree, or the selected tool requires a direct child.
- suggested_next_step: Reread the current workflow manifest and owned subtree, then target only a node this caller may edit or choose a different legal action.
```

### `illegal_state_reject_v1`

```text
operation_failure
- code: illegal_state
- summary: The request conflicts with current committed truth even after reread.
- suggested_next_step: Reread the current manifest, assignment, checkpoint, and surfaced refs, then choose a tool or boundary that matches the current state.
```

Use this when the request is structurally well-formed but still conflicts with live truth, for example:

- `remove_child` would silently destroy open current work
- `release_green` is being used like a worker result
- the caller tries to rewrite open child work in place

## Stale-Guard Rejects

### `stale_dispatch_reject_v1`

```text
operation_failure
- code: stale_dispatch
- summary: The request relied on a dispatch that is no longer current or is already closed.
- suggested_next_step: Reread the current dispatch context and retry only if this node is still the current caller for an open dispatch.
```

Do not tell callers to inspect callback/session binding details here. Those remain transport-private and operator-only.

### `stale_flow_revision_reject_v1`

```text
operation_failure
- code: stale_flow_revision
- summary: Structural truth moved on and this request no longer matches the current workflow revision.
- suggested_next_step: Reread the regenerated workflow manifest and current structural revision, then rebuild the request against that newer structure.
```

### `stale_assignment_reject_v1`

```text
operation_failure
- code: stale_assignment
- summary: The assignment basis used by this request is no longer current.
- suggested_next_step: Reread the current assignment projection and resend the request only if the same assignment is still current.
```

### `stale_checkpoint_reject_v1`

```text
operation_failure
- code: stale_checkpoint
- summary: The checkpoint basis used by this request is no longer current.
- suggested_next_step: Reread the latest relevant checkpoint and current surfaced refs, then decide again from that newer handover.
```

## Resource And Publication Rejects

### `missing_resource_reject_v1`

```text
operation_failure
- code: missing_resource
- summary: A required file, surfaced ref, or published runtime surface is missing.
- suggested_next_step: Verify the surfaced path and regenerate or republish the missing resource before retrying this action.
```

### `missing_required_publication_reject_v1`

```text
operation_failure
- code: missing_required_publication
- summary: A required durable artifact or other release-time publication is missing for this control action.
- suggested_next_step: Publish or republish the missing durable basis first, then retry the control action or reread the surfaced release inputs.
```

Use this when:

- release validation detects that the required durable basis is still missing before `release_green` or `release_blocked` can commit
- a parent/root tries to commit release upward without the required durable basis
- a tool-time read/write action expects a published artifact or checkpoint surface and it has not been published yet

Do not use this code for `yield | green | retry | blocked` boundary failures. Those closure attempts still use `boundary_precondition_failed` even when the missing prerequisite is a checkpoint or artifact.

## Continuation And Boundary Rejects

### `conflicting_continuation_reject_v1`

```text
operation_failure
- code: conflicting_continuation
- summary: This open parent/root dispatch already has a committed continuation outcome.
- suggested_next_step: Publish a progress checkpoint if later readers need the reasoning, then close with the matching boundary instead of staging another outcome.
```

Use this when a caller tries to:

- `assign_child` twice on one open parent/root dispatch
- stage another structural or release outcome after one continuation outcome already exists

### `boundary_precondition_failed_shared_v1`

```text
operation_failure
- code: boundary_precondition_failed
- summary: The requested boundary is valid in general, but current committed truth does not justify it yet.
- suggested_next_step: Reread the current checkpoint, release basis, and staged continuation state, then publish or commit the missing prerequisite before retrying the boundary.
```

This code is specific and must not be collapsed into generic `illegal_state`.

### `boundary_precondition_failed_yield_v1`

```text
operation_failure
- code: boundary_precondition_failed
- summary: `yield` is not legal yet because this open parent/root dispatch does not have exactly one committed continuation outcome.
- suggested_next_step: If this dispatch should stay non-terminal, stage exactly one child assignment first, publish a progress checkpoint if later readers need the reasoning, then emit `yield`. Structural CRUD alone does not justify `yield`. If the committed basis is `release_green` or root `release_blocked`, close with the matching terminal boundary instead.
```

### `boundary_precondition_failed_green_v1`

```text
operation_failure
- code: boundary_precondition_failed
- summary: `green` is not legal yet because the required terminal green checkpoint or required publication/release basis is still missing.
- suggested_next_step: Publish the terminal green checkpoint and any required durable outputs or release basis first, then emit `green`.
```

### `boundary_precondition_failed_retry_v1`

```text
operation_failure
- code: boundary_precondition_failed
- summary: `retry` is not legal yet because the current attempt does not have a terminal retry checkpoint basis.
- suggested_next_step: Publish a terminal checkpoint with `checkpoint_kind: terminal` and `outcome: retry`, then emit `retry`.
```

### `boundary_precondition_failed_blocked_v1`

```text
operation_failure
- code: boundary_precondition_failed
- summary: `blocked` is not legal yet because the current blocked basis is incomplete.
- suggested_next_step: Publish a terminal blocked checkpoint first, and if this is whole-flow root blocked closure, commit `release_blocked` before emitting `blocked`.
```

## Removed-Surface And Budget Rejects

### `removed_surface_reject_v1`

```text
operation_failure
- code: removed_surface
- summary: This request uses a public surface that was removed from the live v1 model.
- suggested_next_step: Reread the current control-tool and boundary docs, then resend the request using only the live v1 tools, fields, and boundaries.
```

Searchable examples of removed public requests:

- `retry_child`
- `reassign_child`
- `run_child`
- gate-era decision envelopes
- callback-era child-dispatch verbs

### `budget_exhausted_reject_v1`

```text
operation_failure
- code: budget_exhausted
- summary: The bounded retry or controller budget for this path is exhausted.
- suggested_next_step: Surface the latest terminal checkpoint to the relevant parent/root so it can choose a fresh assignment or another legal path.
```

### `internal_error_reject_v1`

```text
operation_failure
- code: internal_error
- summary: The controller hit an unexpected internal failure while validating or committing this request.
- suggested_next_step: Do not invent new runtime truth locally; surface the failure for operator or controller recovery and reread current runtime state before retrying.
```

## Compact Parent/Root Tool Reject Examples

### Parent tries `release_green` without required durable basis

```text
operation_failure
- code: missing_required_publication
- summary: `release_green` is not legal yet because the required durable evidence or published outputs for upward green release are still missing.
- suggested_next_step: Publish or republish the required durable basis, reread the surfaced criteria and artifacts, then retry `release_green`.
```

### Non-root caller tries `release_blocked`

```text
operation_failure
- code: illegal_caller
- summary: `release_blocked` is root-only and is not legal from this current caller.
- suggested_next_step: Reread the current dispatch and node role, then use only root-owned `release_blocked` from the current root dispatch.
```

### Root tries `release_blocked` without current blocked basis

```text
operation_failure
- code: missing_required_publication
- summary: `release_blocked` is not legal yet because the current whole-flow blocked basis has not been published or surfaced completely.
- suggested_next_step: Publish the blocked checkpoint and any required blocked-basis evidence first, then retry `release_blocked`.
```

### Parent tries `yield` before staging any continuation

```text
operation_failure
- code: boundary_precondition_failed
- summary: `yield` is not legal yet because no child assignment or release basis is currently staged for this open parent/root dispatch.
- suggested_next_step: If this dispatch should stay non-terminal, stage exactly one child assignment first, then emit `yield`. Structural CRUD alone does not justify `yield`.
```

### Parent tries a second `assign_child` on the same open dispatch

```text
operation_failure
- code: conflicting_continuation
- summary: This open parent/root dispatch already has a committed continuation outcome, so a second `assign_child` is not legal.
- suggested_next_step: Publish a progress checkpoint if later readers need the reasoning, then close with `yield` instead of staging another child.
```

### Parent targets a non-child node

```text
operation_failure
- code: illegal_target_relation
- summary: `assign_child` may target only a current direct child, and `qa_review` is not a current direct child of this node.
- suggested_next_step: Reread the current workflow manifest and direct-child set, then target only a current direct child.
```

## Compact Boundary Reject Examples

### Parent tries `green` without committed `release_green`

```text
operation_failure
- code: boundary_precondition_failed
- summary: `green` is not legal yet because parent/root upward green closure still lacks the committed `release_green` basis.
- suggested_next_step: Commit `release_green`, publish the required terminal green checkpoint basis, then emit `green`.
```

### Worker tries `green` before publishing required output

```text
operation_failure
- code: boundary_precondition_failed
- summary: `green` is not legal yet because one or more required durable outputs for this assignment are still unpublished, so the green boundary basis is incomplete.
- suggested_next_step: Publish every required `produces` artifact, record the terminal green checkpoint, then emit `green`.
```

### Worker tries `retry` without a terminal retry checkpoint

```text
operation_failure
- code: boundary_precondition_failed
- summary: `retry` is not legal yet because the current attempt has not published a terminal retry checkpoint.
- suggested_next_step: Record a terminal checkpoint with `outcome: retry`, then emit `retry`.
```

### Root tries whole-flow `blocked` without `release_blocked`

```text
operation_failure
- code: boundary_precondition_failed
- summary: Root whole-flow `blocked` closure is not legal yet because `release_blocked` has not been committed.
- suggested_next_step: Commit `release_blocked`, then emit `blocked`.
```

### Root tries `blocked` after missing blocked-basis publication

```text
operation_failure
- code: boundary_precondition_failed
- summary: Root whole-flow `blocked` closure is not legal yet because the required blocked checkpoint or blocked-basis publication is still incomplete.
- suggested_next_step: Publish the terminal blocked checkpoint and missing blocked-basis evidence, commit `release_blocked`, then emit `blocked`.
```

## Prompt-Layer Search Terms Preserved Here

Readers may search here for:

- `operation_failure`
- reject wording
- stale guard
- missing publication
- removed surface
- `boundary_precondition_failed`
- parent/root tool rejection
- boundary rejection
- retry rejection

## Related Contracts

- [Runtime rule blocks](runtime-rule-blocks.md)
- [System and provider block](system-and-provider-block.md)
- [Prompt source and sections](../source-and-sections.md)
- [Prompt machine contract](../machine-contract.md)
