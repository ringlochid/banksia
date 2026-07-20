# Checkpoint Contract

Status: Target

> **V2 supersession notice:** This page remains the frozen V1 checkpoint baseline. V2 narrows checkpoint purpose and separates durable evidence from optional assignment planning in [Work plan and checkpoint contract](../../v2/architecture/work-plan-and-checkpoint-contract.md).

This page defines the canonical checkpoint write/read contract for the frozen v1 runtime.

It owns:

- the `record_checkpoint` write contract
- the `handoff` semantic payload
- the split between child-authored handoff facts and controller-owned durable publication truth
- the canonical `latest-checkpoint.*` projection role

It does not own:

- assignment requirements, which belong to the assignment contract
- durable artifact currentness, which belongs to controller rows plus `current.json`
- dispatch delivery, continuity, or watchdog observability surfaces

## Core rule

A checkpoint is the durable attempt handoff surface.

Nodes publish checkpoints only through `record_checkpoint`.

The node authors:

- checkpoint intent: `checkpoint_kind` and `outcome`
- handoff prose
- reduced durable claims about which produce slots matter
- explicit transient surfaces

The runtime then:

- validates the authored handoff against current assignment and attempt truth
- resolves durable publication truth from controller-owned rows
- writes checkpoint rows
- regenerates `latest-checkpoint.*`

Do not collapse authored handoff claims into final durable publication truth.

## `record_checkpoint` write contract

Recommended request shape:

```yaml
record_checkpoint:
  checkpoint_kind: progress | terminal
  outcome: green | retry | blocked | null
  handoff:
    summary: string
    next_step: string
    blockers: [string, ...] | optional
    risks: [string, ...] | optional
  produced_artifacts:
    - kind: artifact
      slot: string
      path: string
  transient_surfaces:
    - path: string
      description: string
```

Rules:

- `record_checkpoint` is the only checkpoint write lane
- `handoff.summary` and `handoff.next_step` are required authored prose
- `produced_artifacts` is a reduced durable claim keyed by artifact slot plus produced file path only
- `produced_artifacts.path` is the existing source file to publish, not the controller-owned final artifact path
- child-authored `produced_artifacts` must not include final `version`, `description`, `owner_node_key`, `assignment_key`, `attempt_id`, or currentness claims
- `transient_surfaces` is a JSON array/YAML sequence of `{ path, description }` objects for explicit surfaced carryover only
- `transient_surfaces` does not create any transient current-pointer family
- `control_effects` is not part of the live checkpoint contract

Outcome rules:

- progress checkpoints use `outcome: null`
- terminal checkpoints use `green | retry | blocked`
- `yield` is boundary-only and never a checkpoint outcome
- terminal `green` checkpoints must pass the same non-pointer preflight required for the matching `green` boundary before they are accepted
- before the boundary closes an attempt, a later terminal checkpoint may supersede an earlier terminal checkpoint; the older row remains audit history and the attempt's latest-checkpoint pointer moves to the newer terminal checkpoint

## `handoff` meaning

`handoff` is the child-authored attempt summary for later readers.

It answers:

- what happened
- what should happen next
- what blockers or risks remain
- which durable claims and transient surfaces this checkpoint accompanies

It does not answer:

- which durable version is current for a slot
- whether publication currentness advanced
- whether release is legal
- whether dispatch recovery or structural control changed

Those remain controller-validated truth facts.

## Validation and commit order

Freeze this order:

1. semantic facts arrive through `record_checkpoint`, `handoff`, `produced_artifacts`, and `transient_surfaces`
2. the controller rereads current assignment, attempt, and artifact truth
3. the controller validates checkpoint legality and any required durable evidence basis
4. the controller resolves exact durable publication refs for any claimed `produced_artifacts`
5. the controller writes checkpoint rows plus authoritative artifact/currentness rows and advances `attempts.latest_checkpoint_id`
6. after commit, the runtime materializes any required durable or transient filesystem copies
7. after those post-commit durable writes, the runtime regenerates `_runtime/attempts/<attempt_id>/latest-checkpoint.*` before route success when that checkpoint surface is taught or returned as current

The generated checkpoint files are projections after accepted runtime truth, not the source of truth.

## Read projection

Projected checkpoint files live at:

- `_runtime/attempts/<attempt_id>/latest-checkpoint.json`
- `_runtime/attempts/<attempt_id>/latest-checkpoint.md`

Recommended projection shape:

```yaml
latest_checkpoint:
  checkpoint_kind: progress | terminal
  outcome: green | retry | blocked | null
  handoff:
    summary: string
    next_step: string
    blockers: [string, ...] | optional
    risks: [string, ...] | optional
  produced_artifacts:
    - kind: artifact
      slot: string
      version: integer
      path: string
      description: string
  transient_refs:
    - kind: transient
      slot: null
      version: null
      path: string
      description: string
```

Rules:

- the node authors the semantic claim that a slot matters
- the runtime writes the exact surfaced durable artifact refs in the projection
- produced artifact descriptions come from the authored produce-slot meaning
- `transient_refs` remain transient even when checkpoint projections surface them
- the checkpoint projection does not own durable artifact currentness; it only cites the exact published versions that mattered to this checkpoint

## Durable versus transient split

Freeze this split:

- `produced_artifacts` cites durable outputs or durable evidence bodies
- `transient_refs` cites explicit temporary carryover only

Rules:

- transient entries never replace durable artifact publication truth
- transient entries never get a `current.json`-style pointer family
- if transient surfacing is omitted, later readers must not scan `tmp/` or `tmp/transfers/` guessing what was intended

## Example

Authored checkpoint write:

```yaml
record_checkpoint:
    checkpoint_kind: terminal
    outcome: green
    handoff:
        summary: Implemented the retry-safe auth refresh patch and validated the
            failure path locally.
        next_step: Parent should review the patch and rerun the auth smoke tests.
        risks:
            - Token-expiry coverage still depends on the shared staging environment.
    produced_artifacts:
        - kind: artifact
          slot: code_patch
          path: <task_root>/workspace/out/code_patch.diff
        - kind: artifact
          slot: verification_note
          path: <task_root>/workspace/out/verification_note.md
    transient_surfaces:
        - path: <task_root>/tmp/transfers/auth-refresh-local-notes.md
          description: Optional transient local notes for follow-up validation.
        - path: <task_root>/tmp/transfers/auth-refresh-proof-caveat.md
          description: Temporary caveat about staging-only token-expiry proof.
```

Projected checkpoint readback after controller validation:

```yaml
latest_checkpoint:
    checkpoint_kind: terminal
    outcome: green
    handoff:
        summary: Implemented the retry-safe auth refresh patch and validated the
            failure path locally.
        next_step: Parent should review the patch and rerun the auth smoke tests.
        risks:
            - Token-expiry coverage still depends on the shared staging environment.
    produced_artifacts:
        - kind: artifact
          slot: code_patch
          version: 3
          path: <task_root>/outputs/artifacts/implement_fix/code_patch/code_patch.v03.diff
          description: Code patch implementing the approved fix.
        - kind: artifact
          slot: verification_note
          version: 1
          path: <task_root>/outputs/artifacts/implement_fix/verification_note/verification_note.v01.md
          description: Verification note for the implement-fix node.
    transient_refs:
        - kind: transient
          slot: null
          version: null
          path: <task_root>/tmp/transfers/auth-refresh-local-notes.md
          description: Optional transient local notes for follow-up validation.
        - kind: transient
          slot: null
          version: null
          path: <task_root>/tmp/transfers/auth-refresh-proof-caveat.md
          description: Temporary caveat about staging-only token-expiry proof.
```

## Related contracts

- [Assignment contract](assignment-contract.md)
- [Worker context contract](worker-context-contract.md)
- [Runtime boundary and controller loop contract](runtime-boundary-and-controller-loop-contract.md)
- [Runtime database and object contract](runtime-database-and-object-contract.md)
- [Artifact ref and storage contract](artifact-ref-and-storage-contract.md)
