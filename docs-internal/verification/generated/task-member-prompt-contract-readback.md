# Banksia Task-member prompt contract readback

Status: Reference

This page is generated from the shipped Banksia prompt contracts and controller-owned instruction assets. It is a deterministic implementation readback, not an independent source of product truth. The versionless [Task-member system-prompt contract](../../architecture/system-prompts.md) is normative. Run `make docs-prompt-generate` after changing an input, then run `make docs-prompt-check`.

## Instruction assets

- shared/core.txt
- shared/workspace-and-files.txt
- shared/checkpoint.txt
- positions/task-lead.txt
- behaviors/manager.txt
- behaviors/contributor.txt
- actions/human-request.txt
- actions/command-run.txt
- situations/continuation.txt

## Stable composition order

1. `shared/core.txt`
2. `shared/workspace-and-files.txt`
3. `shared/checkpoint.txt`
4. `positions/task-lead.txt` when the current Member is the Task lead
5. exactly one behavior asset: `behaviors/manager.txt` or `behaviors/contributor.txt`
6. `actions/human-request.txt` when an allowed Human Request action is exposed
7. `actions/command-run.txt` when Command Run is allowed and exposed
8. `situations/continuation.txt` when a Continuation exists
9. the nonblank authored Member instruction
10. the nonblank authored Workflow note

## Dynamic input

`task | dispatch | current_member | assignment | continuation | direct_team | work_plan | available_actions | workspace`

## Trigger kinds

`delegation_wave_settled | human_result | command_result | watchdog_recovery | semantic_retry | operator_continue | structural_replan`

## Rendering invariants

- one `<banksia_system>` instruction root and one `<banksia_dispatch_request>` input root
- controller-owned fixed element names with escaped values as element text
- stable field order and omission of absent optional sections
- UTF-8-compatible Unicode, LF line endings, and exactly one final newline
- a Checkpoint exists only after the exposed controller action is accepted; provider prose cannot complete an Assignment or become the Task Result

## Definition-backed behavior evaluation

Every scenario loads the named packaged Starter through the shipped Workflow parser and initial-team planner. The rendered system and dynamic inputs must contain that exact current Member, its authored instruction, the Workflow note, and every direct-team instruction before a provider run is admitted.

| Scenario | Starter Workflow | Current Member | Behavior under evaluation |
| --- | --- | --- | --- |
| `anti-relay` | `reviewed-code-change` | `change-lead` | A Manager must add interpretation, scope, inspection, and integration. |
| `child-says-done` | `reviewed-code-change` | `implementation-manager` | A green child claim requires evidence inspection before acceptance. |
| `review-and-rework` | `reviewed-code-change` | `change-lead` | Review findings become a fresh, feedback-bearing repair Assignment. |
| `debug-before-repair` | `debug-and-verify` | `debug-lead` | Reproduction and cause evidence precede a cause-based repair. |
| `sequential-dependency` | `reviewed-code-change` | `change-lead` | A dependent review receives a fresh Assignment shaped by the first return. |
| `unsettled-contract` | `cross-layer-feature` | `feature-lead` | Settle shared assumptions before parallel disjoint implementation. |
| `item-specific-batch` | `bounded-maintenance-batch` | `batch-lead` | A finite inventory becomes item-specific work plus integrated verification. |
| `lead-synthesis` | `evidence-synthesis` | `research-lead` | The lead reconciles provenance and conflict instead of concatenating summaries. |
| `evidence-based-decision` | `technical-decision` | `decision-lead` | The lead resolves disagreement from common evidence, not a vote. |
| `failed-replication` | `reproducible-study` | `study-lead` | Failed replication narrows the reported claim and exposes uncertainty. |
| `nested-wave` | `technical-decision` | `decision-lead` | A Manager consumes ordered direct returns only after nested local joins. |
| `stop-after-transfer` | `reviewed-code-change` | `change-lead` | A successful transfer closes the current provider response. |
