# Field Renderers

Status: Target

This page defines renderer authority for the frozen v1 prompt sections.

## Canonical Sections

- `operating_model`
- `task_identity`
- `node_purpose`
- `current_dispatch`
- `workflow_manifest`
- `current_assignment`
- `latest_checkpoint_context`
- `consumed_durable_refs`
- `transient_refs`
- `allowed_actions_now`
- `publication_rule`

## Global Renderer Rules

All sections must render with:

- stable headings
- scan-first bullets or short tables
- omission of absent optional data rather than placeholder prose
- path-only surfaced refs
- compact artifact refs only
- meaningful descriptions rather than inferred filename semantics

Do not render:

- flow/scope manifest splits
- `writable_roots`
- callback legality payloads
- gate-era boundary terms
- full current-pointer internals
- raw monitoring files as normal work context

## Exact Rendered Prompt Routes

Use these routes when you need to see the rendered prompt body instead of the section rules only:

- exact `worker_dispatch_prompt` example: [Rendered Examples](generated/rendered-examples.md)
- exact `parent_root_dispatch_prompt` example: [Rendered Examples](generated/rendered-examples.md)
- exact reusable wording blocks that the render must stay compatible with: [Runtime Rule Blocks](prompt-pack/runtime-rule-blocks.md) and [System And Provider Block](prompt-pack/system-and-provider-block.md)
- shipped exact wording lives under `apps/api/src/autoclaw/runtime/prompt/assets/`; the prompt-pack docs mirror those assets for review and validation

## Compact Ref Rule

Ordinary prompt rendering should surface refs in these compact shapes only.

### Artifact ref

- `slot`
- `version`
- `path`
- `description`

### Durable non-artifact ref

- `kind`
- `slot` when relevant
- `path`
- `description`

### Transient ref

- `path`
- `description`

Concrete examples:

```text
Artifact ref
- slot: verification_report
- version: 2
- path: C:/tasks/task_2026_0042/outputs/artifacts/implement_fix/verification_report/verification_report.v02.md
- description: scoped verification evidence for the current fix assignment

Durable non-artifact ref
- kind: criteria
- slot: fix_acceptance
- path: C:/tasks/task_2026_0042/_runtime/criteria/fix_acceptance.md
- description: bounded fix acceptance criteria

Transient ref
- path: C:/tasks/task_2026_0042/tmp/transfers/implement_fix/repro-commands.txt
- description: optional repro commands from the prior attempt
```

Avoid rendering vague refs such as:

```text
- findings_report.v02.md
- latest checkpoint
- see transfer file
```

Those force the reader to infer meaning from filenames instead of from explicit slot, kind, and description.

## Section Rendering Rules

### `operating_model`

Render:

- controller/DB truth ownership
- generated files as projections
- public boundary model
- retry summary
- durable versus transient summary
- monitoring-not-task-truth reminder

### `task_identity`

Render:

- task key/id
- title when present
- short summary
- optional task instruction

### `node_purpose`

Render:

- node key
- node kind
- role
- short node description
- optional node instruction

### `current_dispatch`

Render:

- current bound turn
- send mode
- closure expectation:
    - parent/root: tools now, later `yield` or terminal boundary
    - worker/leaf: later `green | retry | blocked`

The closure line should name the exact legal boundary words, not synonyms such as "continue," "complete," or "resume."

Do not render internal route ids such as `dispatch_id` in the canonical node-facing section.

### `workflow_manifest`

Render:

- stable manifest path
- short description
- current node anchor
- parent/root structural-edit palette entries when the current node may legally edit children
- optional current relevant paths only when they sharpen orientation

Do not restate the entire manifest inline.

### `current_assignment`

Render the assignment fields in this order:

1. `path`
2. `summary`
3. `instruction`
4. `criteria`
5. `consumes`
6. `produces`
7. `transient_refs` when present

Good render:

```text
### Current Assignment
- path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.implement_fix.11/assignment.md
- summary: repair the auth-refresh defect and publish the required evidence
- instruction: change only the bounded auth-refresh logic and rerun the scoped verification
- criteria:
  - kind: criteria
    slot: fix_acceptance
    description: bounded fix acceptance criteria
- consumes:
  - kind: artifact
    slot: findings_report
    description: upstream findings for the scoped fix
- produces:
  - slot: patch
    description: bounded code change artifact
```

### `latest_checkpoint_context`

Render in this order when a checkpoint exists:

1. `path`
2. `checkpoint_kind`
3. `outcome`
4. `summary`
5. `next_step`
6. `blockers` when present
7. `risks` when present
8. `produced_artifacts` when present
9. `transient_refs` when present

Good render:

```text
### Latest Checkpoint Context
- path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.implement_fix.11/latest-checkpoint.md
- checkpoint_kind: terminal
- outcome: blocked
- summary: browser refresh path still fails the current criteria
- next_step: parent should decide whether to assign a narrower repro child or end blocked
- risks:
  - current repro is still flaky on one browser family
- produced_artifacts:
  - kind: artifact
    slot: verification_report
    version: 2
    path: C:/tasks/task_2026_0042/outputs/artifacts/implement_fix/verification_report/verification_report.v02.md
    description: scoped verification evidence for the current blocked decision
```

If no checkpoint is surfaced, render the explicit empty state:

```text
### Latest Checkpoint Context
- path: null
- no current relevant checkpoint is surfaced
```

### `consumed_durable_refs`

Render the de-duplicated union of assignment `criteria`, assignment `consumes`, and surfaced current-relevant durable refs as:

- kind
- slot when relevant
- version when relevant
- path
- description

Do not repeat the checkpoint path already rendered in `Latest Checkpoint Context`.

If the union is empty, worker prompts still render:

```text
## Consumed Durable Refs
- no current durable refs are surfaced for this turn
```

Parent/root prompts may omit the section when no durable refs are surfaced.

### `transient_refs`

Render each transient ref as:

- path
- description

and explicitly say transient refs are optional carryover only and not durable truth.

### `allowed_actions_now`

Render only the bounded action surface that is legal now:

- parent/root tools when current node is parent/root
- `yield` when exactly one staged child assignment already exists
- `green | blocked` when parent/root terminal closure is relevant, with root-only `release_blocked` required only for whole-flow blocked closure
- `green | retry | blocked` when worker/leaf terminal closure is relevant

Good parent/root render:

```text
## Allowed Actions Now
- tools:
  - assign_child
  - add_child
  - update_child
  - remove_child
  - release_green
  - release_blocked (root only)
- do bounded research to sharpen delegation, then turn that into a tighter child brief plus the right surfaced refs
- emit `yield` only after exactly one staged child assignment already exists
- for structural edits, reread the current manifest first, use the surfaced structural edit palette in the current prompt or manifest, and if that is still insufficient, use the current-only `search_definitions` / `get_definition` read-only lookup lane before guessing; then reread the regenerated manifest after the edit
- do not use definition revision history, upload proof, or registry provenance as dispatched planning input
- emit `green` only when this parent/root node itself is closing its own assignment; emit `blocked` only after this node cannot complete its current assignment and has published a terminal blocked checkpoint; root whole-flow blocked closure also requires committed `release_blocked`
```

Good worker render:

```text
## Allowed Actions Now
- continue the current assignment
- publish progress checkpoint if later readers need the reasoning
- close terminally with `green`, `retry`, or `blocked`
```

### `publication_rule`

Render:

- required `produces` gate `green`
- durable artifacts publish as immutable versioned files
- later agents reread checkpoint plus compact surfaced refs
- do not rely on transcript memory

## Validation Mirror

Renderer output must stay consistent with:

- [Runtime Boundary And Controller Loop Contract](../architecture/runtime-boundary-and-controller-loop-contract.md) for boundary names and closure preconditions
- [Worker Context Contract](../architecture/worker-context-contract.md) for manifest, assignment, checkpoint, and surfaced-ref read rules
- [API Schema Appendix](../interfaces/api-schema-appendix.md) for assignment/checkpoint field shapes and surfaced ref carriers

If a rendered example, section renderer, and validation carrier disagree, the runtime should not invent a third phrasing. Fix the drift so prompt wording, schema shape, and boundary legality stay identical.

## Related Contracts

- [Prompt contract](contract.md)
- [Prompt source and sections](source-and-sections.md)
- [Artifact ref and storage contract](../architecture/artifact-ref-and-storage-contract.md)
