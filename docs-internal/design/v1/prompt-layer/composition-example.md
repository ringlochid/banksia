# Prompt Composition Example

Status: Reference

This page shows how the live v1 prompt layer is assembled into the persisted transport request and how prompt-layer validation should fail when generated examples drift from the live owner docs.

Use this page when you want:

- exact persisted request keys for `prompt-request.json`
- the live `instructions_text` versus `input_text` split
- current-node-anchor, checkpoint, and `consumed_durable_refs` examples that match the landed renderer shape
- prompt-layer validation messages for stale or malformed generated prompts

For the fully rendered prompt body examples, use [Rendered Examples](generated/rendered-examples.md).

## Search-first routing

- exact rendered prompt body examples: [Rendered Examples](generated/rendered-examples.md)
- exact section order and section owners: [Source And Sections](source-and-sections.md)
- exact compact ref rendering: [Field Renderers](field-renderers.md)
- exact persistence and send-mode rules: [Render And Persistence](render-and-persistence.md)
- exact reusable system/provider wording: [System And Provider Block](prompt-pack/system-and-provider-block.md)
- exact reusable legality wording: [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md)

## Stable composition stack

The live v1 composition stack is:

1. AutoClaw-owned `instructions_text` on `full_prompt`, starting at `## Instructions`
2. regenerated dynamic `input_text` body, starting at `## Dispatch Input`
3. persisted combined readback at `_runtime/dispatch/<dispatch_id>/prompt.md`, headed `# AutoClaw Dispatch Prompt`
4. persisted request artifact at `_runtime/dispatch/<dispatch_id>/prompt-request.json`

Rules:

- `instructions_text` is present only for `full_prompt`
- `instructions_text` carries AutoClaw-generated dispatch instructions and exact prompt assets, not opaque provider/platform prompt text outside controller truth
- `input_text` is always present and carries the node-facing dispatch input body for the current send mode
- reusable prompt asset blocks render as `###` fragments under `## Instructions`
- dynamic dispatch-input sections render as `###` fragments under `## Dispatch Input`
- persisted `prompt.md` always keeps the readable combined prompt readback
- design canon does not preserve a live optional wrapper layer in the composition stack

## Exact `full_prompt` request shape: `worker_dispatch_prompt`

The persisted request keys below are exact. The long prompt strings are excerpted here; use [Rendered Examples](generated/rendered-examples.md) plus the prompt-pack owner docs when you need every rendered line or reusable block byte.

```yaml
prompt_request_json:
    dispatch_id: dispatch.implement_fix.01
    node_key: implement_fix
    attempt_id: attempt.implement_fix.01
    assignment_key: implement_fix.assign-01
    prompt_name: worker_dispatch_prompt
    send_mode: full_prompt
    instructions_text: |
        ## Instructions

        ### AutoClaw Runtime Identity

        You are AutoClaw, a delegated node inside a controller-first runtime.
        ...

        ### Current Node Guidance

        - node kind: worker
        - node key: implement_fix
        - node description: Repair the bounded auth-refresh defect.
        - node instruction: Change only the scoped auth-refresh code path.
        - role: engineer
        - role description: Worker for one bounded engineering assignment.
        - role instruction: Complete only the current assignment.
        - policy: standard-worker
        - policy description: Guardrails for bounded worker assignments without human waits or command runs.
    input_text: |
        ## Dispatch Input

        ### Workflow Manifest
        - path: C:/tasks/task_2026_0042/_runtime/workflow-manifest.md
        - description: whole-workflow visible contract for the current task
        - current node anchor: implement_fix
        - surfaced path: C:/tasks/task_2026_0042/context/wiki/auth-refresh-history.md

        ### Current Assignment
        - path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.implement_fix.01/assignment.md
        - summary: Repair the auth-refresh defect and publish the required evidence.
        - instruction: Change only the bounded auth-refresh logic and rerun scoped verification.
        - criteria:
          - kind: criteria
            slot: fix_acceptance
            description: Bounded fix acceptance criteria.
        - consumes:
          - kind: artifact
            slot: findings_report
            description: Current findings for the scoped fix.
        - produces:
          - slot: change_patch
            description: Bounded code change artifact.
        - transient_refs:
          - path: C:/tasks/task_2026_0042/tmp/transfers/implement_fix/repro-commands.txt
            description: Optional repro commands from the prior attempt.

        ### Latest Checkpoint Context
        - path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.implement_fix.01/latest-checkpoint.md
        - checkpoint_kind: terminal
        - outcome: retry
        - summary: Prior attempt fixed the primary path but missed one recovery branch.
        - next_step: Keep the same assignment and repair the missed branch.

        ### Consumed Durable Refs
        - kind: criteria
          slot: fix_acceptance
          path: C:/tasks/task_2026_0042/_runtime/criteria/fix_acceptance.v01.md
          description: Bounded fix acceptance criteria.
        - kind: artifact
          slot: findings_report
          version: 2
          path: C:/tasks/task_2026_0042/outputs/artifacts/investigate_issue/findings_report/findings_report.v02.md
          description: Current findings for the scoped fix.
    content_hash: sha256:...
    transport_request_hash: sha256:...
    rendered_at: 2026-05-05T12:40:11+00:00
```

## Exact `full_prompt` request shape: `parent_root_dispatch_prompt`

The surfaced checkpoint path appears once in `Latest Checkpoint Context`. `Consumed Durable Refs` keeps the other exact current durable refs for the turn and does not repeat that same checkpoint path.

```yaml
prompt_request_json:
    dispatch_id: dispatch.root.07
    node_key: root
    attempt_id: attempt.root.07
    assignment_key: root.assign-07
    prompt_name: parent_root_dispatch_prompt
    send_mode: full_prompt
    instructions_text: |
        ## Instructions

        ### AutoClaw Runtime Identity

        You are AutoClaw, a delegated node inside a controller-first runtime.
        ...

        ### Current Node Guidance

        - node kind: root
        - node key: root
        - node description: Coordinate the whole flow and decide the next bounded child step.
        - node instruction: Keep the root decision tied to surfaced evidence.
        - role: root_planning_lead
        - role description: Root coordinator for the whole task.
        - role instruction: Choose the next bounded child step and close only when release is legal.
        - policy: standard-root
        - policy description: Guardrails for root orchestration and final closure.
    input_text: |
        ## Dispatch Input

        ### Workflow Manifest
        - path: C:/tasks/task_2026_0042/_runtime/workflow-manifest.md
        - description: whole-workflow visible contract for the current task
        - current node anchor: root
        - surfaced runtime file: C:/tasks/task_2026_0042/_runtime/attempts/attempt.investigate_issue.02/latest-checkpoint.md
        - surfaced path: C:/tasks/task_2026_0042/context/wiki/cookie-rotation-note.md

        ### Current Assignment
        - path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.root.07/assignment.md
        - summary: Decide the next bounded child step after the current investigation result.
        - instruction: Stay inside the current owned subtree and preserve reasoning durably when needed.
        - criteria:
          - kind: criteria
            slot: root_release_rule
            description: Root completion and release criteria.
        - consumes:
          - kind: checkpoint
            description: Latest investigation handoff for this root decision.
          - kind: artifact
            slot: findings_report
            description: Current investigation findings for the auth-refresh regression.
        - produces:
          - slot: root_decision_note
            description: Durable decision note required when root reasoning must survive redispatch.
        - transient_refs:
          - path: C:/tasks/task_2026_0042/tmp/transfers/root/investigation-compare-grid.md
            description: Optional transient comparison grid for the current root decision.

        ### Latest Checkpoint Context
        - path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.investigate_issue.02/latest-checkpoint.md
        - checkpoint_kind: progress
        - outcome: null
        - summary: One implementation child assignment is already staged and the current checkpoint explains why this child is next.
        - next_step: If the handoff is sufficient, emit yield.

        ### Consumed Durable Refs
        - kind: criteria
          slot: root_release_rule
          path: C:/tasks/task_2026_0042/_runtime/criteria/root_release_rule.md
          description: Root completion and release criteria.
        - kind: artifact
          slot: findings_report
          version: 2
          path: C:/tasks/task_2026_0042/outputs/artifacts/investigate_issue/findings_report/findings_report.v02.md
          description: Current investigation findings for the auth-refresh regression.
    content_hash: sha256:...
    transport_request_hash: sha256:...
    rendered_at: 2026-05-05T12:41:03+00:00
```

## Checkpoint publication excerpt

When a checkpoint surfaces durable output claims, the rendered field names are `produced_artifacts` and `transient_refs`.

```text
### Latest Checkpoint Context
- path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.implement_fix.02/latest-checkpoint.md
- checkpoint_kind: terminal
- outcome: green
- summary: the bounded fix and verification completed and the current outputs are ready for parent/root review
- next_step: parent/root may consume the published outputs and decide whether release or further review is now legal
- produced_artifacts:
  - kind: artifact
    slot: change_patch
    version: 2
    path: C:/tasks/task_2026_0042/outputs/artifacts/implement_fix/change_patch/change_patch.v02.diff
    description: bounded code change artifact for the current assignment
  - kind: artifact
    slot: verification_report
    version: 3
    path: C:/tasks/task_2026_0042/outputs/artifacts/implement_fix/verification_report/verification_report.v03.md
    description: scoped verification evidence for the current assignment
- transient_refs:
  - path: C:/tasks/task_2026_0042/tmp/transfers/implement_fix/browser-rerun-notes.md
    description: optional transient browser rerun notes that do not become durable truth
```

## Exact prompt-layer validation messages

These are the kinds of exact validation failures the prompt layer should emit when generated examples drift from the live owner docs.

### Reject: progress checkpoint rendered with terminal outcome

```text
Prompt generation reject
- prompt_name: parent_root_dispatch_prompt
- section: latest_checkpoint_context
- summary: `checkpoint_kind: progress` must render with `outcome: null`. A progress checkpoint may not teach `green`, `retry`, or `blocked` as its outcome.
- required fix: Regenerate `latest_checkpoint_context` from the canonical checkpoint projection and keep terminal outcomes only for `checkpoint_kind: terminal`.
```

### Reject: compact artifact ref drifted into current-pointer internals

```text
Prompt generation reject
- prompt_name: worker_dispatch_prompt
- section: consumed_durable_refs
- summary: Ordinary prompt rendering may surface only compact artifact refs: `slot`, `version`, `path`, and `description`. The rendered example leaked controller-only pointer fields such as `assignment_key`, `attempt_id`, or `supersedes_path`.
- required fix: Replace the leaked pointer fields with the compact artifact ref shape.
```

### Reject: worker prompt omitted `consumed_durable_refs`

```text
Prompt generation reject
- prompt_name: worker_dispatch_prompt
- summary: Worker prompts must include `consumed_durable_refs` because the current assignment requires bounded must-read durable refs.
- required fix: Regenerate the prompt with surfaced criteria, artifact, and explicit doc/wiki refs rendered in the `consumed_durable_refs` section, without re-listing the checkpoint already rendered in `latest_checkpoint_context`.
```

### Reject: parent/root prompt reintroduced removed control wording

```text
Prompt generation reject
- prompt_name: parent_root_dispatch_prompt
- section: allowed_actions_now
- summary: The rendered prompt reintroduced removed live-model wording such as `run_child(...)`, child retry control, or reassignment control.
- required fix: Use only the canonical parent/root tools `assign_child`, `add_child`, `update_child`, `remove_child`, and `release_green`; include `release_blocked` only on root prompts.
```

## Exact review checklist for these examples

Before accepting a new rendered prompt example, verify:

1. the persisted request uses `instructions_text` for live `full_prompt` examples
2. the prompt family is `worker_dispatch_prompt` or `parent_root_dispatch_prompt`
3. `workflow_manifest` renders the current node anchor
4. every `Current Assignment` and `Latest Checkpoint Context` example renders a `- path:` line
5. `produced_artifacts` and `transient_refs` use the live checkpoint field names when present
6. `Consumed Durable Refs` de-duplicates the checkpoint already rendered in `Latest Checkpoint Context`
7. `path` and `version` do not leak into current-assignment `criteria`, `consumes`, or `produces`
8. monitoring files are not treated as normal assignment truth

## Related live owners

- [Contract](contract.md)
- [Source And Sections](source-and-sections.md)
- [Field Renderers](field-renderers.md)
- [Render And Persistence](render-and-persistence.md)
- [Machine Contract](machine-contract.md)
