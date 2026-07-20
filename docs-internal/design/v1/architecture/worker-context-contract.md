# Worker context contract

Status: Target

This page defines the canonical worker-facing read contract for the frozen v1 runtime.

V1 does not use a giant `WorkerContext` callback object that tries to inline the whole runtime database, prompt, planning state, boundary state, provider transport state, and writable-root policy in one payload.

V1 also does not use a canonical `GET /callback/current/context` reread route.

What survives is a smaller current-node read surface:

- one stable whole-workflow manifest
- one current assignment
- one current-attempt checkpoint path when one exists
- one surfaced relevant checkpoint path when parent/root redispatch needs a different durable handoff
- the exact consumed durable refs that matter now
- optional explicit transient refs

Assignment field ownership lives in [Assignment contract](assignment-contract.md). Checkpoint field ownership lives in [Checkpoint contract](checkpoint-contract.md).

Controller/DB state remains authoritative. The surfaced files below are deterministic controller-generated projections of that truth. Those projections are written by synchronous post-commit helpers so the controller can expose the stable task-root read surfaces immediately after commit.

## Core rule

The current worker reads:

1. `_runtime/workflow-manifest.md`
2. current `_runtime/attempts/<attempt_id>/assignment.md`
3. `latest_relevant_checkpoint_path` when present, otherwise the current attempt-local `_runtime/attempts/<attempt_id>/latest-checkpoint.md`
4. consumed durable refs surfaced in assignment
5. optional `transient_refs`

The worker does not recover its context from:

- authored workflow-definition YAML
- flow/scope manifest splits
- `scope_key`
- provider continuity state
- dispatch-family callback enums
- callback read helpers
- callback credentials, env var names, or auth-file locations
- writable-root callback fields
- giant inline role/policy/system blocks

Concrete reading sequence:

1. open `_runtime/workflow-manifest.md` to understand where this node sits in the workflow
2. open the current `assignment.md` to see the exact `summary`, `instruction`, `criteria`, `consumes`, and `produces`
3. open `latest_relevant_checkpoint_path` when present, otherwise the current attempt-local `latest-checkpoint.md`, only to understand what already happened and what should happen next
4. open each consumed durable ref by its surfaced `path`
5. inspect optional transient refs only if they help this assignment

## Current worker read surface

There is no separately locked `worker_read_contract` API payload in v1.

The canonical worker context is the combination of:

- the stable manifest files under `_runtime/workflow-manifest.*`
- the current attempt-local `assignment.*`
- the current attempt-local `latest-checkpoint.*`
- the surfaced relevant checkpoint path when parent/root redispatch needs a different durable handoff
- surfaced durable refs from assignment or manifest
- optional surfaced `transient_refs`

The prompt should surface the exact file paths and descriptions needed for that reread. Callback remains a write-only semantic lane.

If an implementation emits a convenience envelope around those already materialized files, treat it as a helper projection only, not as a second canonical runtime contract.

The stable manifest path above still owns the whole-workflow payload details such as:

- `manifest_version`
- top-level `structural_edit_palette`
- per-node `policy` when present
- `current_context.latest_relevant_checkpoint_path`

Illustrative convenience envelope only:

```yaml
worker_read_surface:
  current_node_key: string
  current_node_kind: root | parent | worker
  workflow_manifest_path: string
  assignment_path: string
  latest_checkpoint_path: string | null
  latest_relevant_checkpoint_path: string | null
  consumed_refs: [worker_consumed_ref, ...]
  transient_refs: [worker_transient_ref, ...] | optional
```

Supporting shape:

```yaml
worker_checkpoint_ref:
  kind: checkpoint
  path: string
  description: string

worker_evidence_ref:
  kind: artifact | criteria | doc | wiki
  slot: string | null
  version: integer | null for `kind: artifact`, otherwise omitted
  path: string
  description: string

worker_consumed_ref:
  one_of:
    - worker_checkpoint_ref
    - worker_evidence_ref

worker_transient_ref:
  kind: transient
  slot: null
  path: string
  description: string
```

Rules:

- V1 surfaced refs are path-only.
- Runtime must localize any external resource into the task root before it is surfaced to the worker.
- any callback/session/dispatch binding identity stays internal to the runtime/gateway and is not part of the canonical worker read surface
- callback write authority is injected privately by the runtime/launcher and is not part of prompt-visible semantic context
- `workflow_manifest_path` points at the stable whole-workflow manifest.
- `assignment_path` points at the current deterministic assignment projection for this attempt.
- `latest_checkpoint_path` points at the current deterministic checkpoint projection when one exists for the current attempt.
- `latest_relevant_checkpoint_path` is optional and points at the surfaced checkpoint chosen for parent/root redispatch handoff when that handoff differs from the current attempt's own checkpoint.
- prompt and worker reread logic consume this field as already-selected controller truth; they do not infer it by scanning surfaced checkpoint list order
- ordinary direct-child checkpoint auto surfacing may still appear in the manifest or `consumed_refs`, but it does not by itself select `latest_relevant_checkpoint_path`
- `worker_checkpoint_ref` is the worker-context alias for the shared `node_runtime_file_ref` family restricted to `kind: checkpoint`.
- `worker_evidence_ref` is the worker-context alias for the shared `evidence_ref` family restricted to `kind: artifact | criteria | doc | wiki`.
- compact worker `kind: criteria` refs keep only `slot`, `path`, and `description`; criteria ownership remains preserved in manifest/compiler truth and does not widen ordinary worker consumed refs with `owner_node_key`
- `consumed_refs` should mirror the current assignment `consumes` set plus any additional surfaced criteria/checkpoint/doc refs that the worker must read now.
- when a parent/root turn depends on current child durable publications, surfaced `consumed_refs` may also include the exact current child artifact refs resolved from controller-owned current-pointer truth
- when a parent/root release reread depends on deeper descendant evidence, surfaced `consumed_refs` may instead come from controller-staged descendant checkpoint and artifact refs for that release turn
- `transient_refs` is optional explicit carryover only. It is not durable truth.

## Manifest, assignment, and checkpoint roles

### Manifest

The manifest is the worker's whole-workflow picture.

It tells the worker:

- what workflow it is inside
- what node is current
- how nodes relate
- which structural-edit role/policy names are currently surfaced when the turn is `root` or `parent`
- what each node consumes, produces, and checks
- each node's `policy` when one is part of current workflow truth
- which stable roots and current files exist

The worker should not be told to recover this from authored YAML or from a scope-only digest.

### Assignment

The assignment is the worker's current mission contract.

The worker should expect the canonical assignment shape defined by [Assignment contract](assignment-contract.md).

At minimum, the worker reads:

- `summary`
- `instruction`
- runtime-resolved `criteria`
- runtime-resolved `consumes`
- `produces` requirements
- optional explicit `transient_refs`

The assignment is forward-looking. It is not history.

### Checkpoint

The checkpoint is the worker's durable summary of what happened and what should happen next.

The worker should expect the canonical checkpoint shape defined by [Checkpoint contract](checkpoint-contract.md).

At minimum, the worker reads:

- `checkpoint_kind`
- `outcome`
- `handoff`
- optional runtime-resolved `produced_artifacts` derived from accepted reduced durable artifact claims
- optional explicit `transient_refs`

The checkpoint is backward-looking handoff, not a provider trace log.

## Deterministic generated files

The worker-facing runtime file families should be:

```text
<task-root>/
  _runtime/
    workflow-manifest.json
    workflow-manifest.md
    attempts/
      <attempt_id>/
        assignment.json
        assignment.md
        latest-checkpoint.json
        latest-checkpoint.md
        artifact-index.json
        transient-index.json
```

Rules:

- `_runtime/workflow-manifest.*` is the stable whole-workflow contract.
- `_runtime/attempts/<attempt_id>/assignment.*` is the deterministic current assignment projection.
- `_runtime/attempts/<attempt_id>/latest-checkpoint.*` is the deterministic current checkpoint projection.
- `artifact-index.json` and `transient-index.json` are navigation aids, not replacement truth surfaces.
- `_runtime/dispatch/<dispatch_id>/delivery-state.json`, `continuity-state.json`, `watchdog-state.json`, and `provider-events.ndjson` are observability-only surfaces, not ordinary worker context.
- The worker-facing manifest, assignment, checkpoint, and dispatch write helpers are synchronous post-commit writers.

Short rule of thumb:

- manifest answers "where am I in the workflow?"
- assignment answers "what do I need to do now?"
- checkpoint answers "what happened already and what should happen next?"
- surfaced artifact or criteria paths answer "what exact evidence or rules do I need to inspect?"
- callback answers "how do I publish semantic writes back to the controller?" and not "what should I read?"

## What is not part of the live v1 worker context

Do not keep these as the canonical worker-facing model:

- `binding_id`
- `flow_key`
- `flow_revision_key`
- `flow_node_key`
- `attempt_key`
- flow/scope manifest split
- `scope_key`
- `current_boundary_summary`
- `parent_evidence_bundle_ref`
- `replan_scope_ref`
- dispatch-family callback enums
- callback auth token material
- callback env var names
- callback auth-file paths
- provider-facing retry/continuity fields
- `writable_roots`
- inline role/policy/system prose blocks as a machine callback schema

Those ideas either belong in controller/DB truth, prompt wording, parent/root control docs, registry/tool docs, or monitoring surfaces. They do not belong in the canonical worker read surface.

## Example convenience envelope

```yaml
worker_read_surface:
    current_node_key: implement_change
    current_node_kind: worker
    workflow_manifest_path: C:/tasks/task_2026_0042/_runtime/workflow-manifest.md
    assignment_path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.implement_change.03/assignment.md
    latest_checkpoint_path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.implement_change.03/latest-checkpoint.md
    latest_relevant_checkpoint_path: null
    consumed_refs:
        - kind: criteria
          slot: implement_change_delivery_criteria
          path: C:/tasks/task_2026_0042/_runtime/criteria/implement_change_delivery_criteria.v01.md
          description: Delivery criteria for the implement-change node.
        - kind: artifact
          slot: findings_report
          version: 1
          path: C:/tasks/task_2026_0042/outputs/artifacts/investigate_issue/findings_report/findings_report.v01.md
          description: Findings for downstream implementation.
    transient_refs:
        - kind: transient
          slot: null
          path: C:/tasks/task_2026_0042/tmp/transfers/auth-refresh-repro-steps.md
          description: Optional transient repro notes surfaced for this assignment.
```

## Related contracts

- [Manifest contract](manifest-contract.md)
- [Assignment contract](assignment-contract.md)
- [Checkpoint contract](checkpoint-contract.md)
- [Task root layout and generated files](task-root-layout-and-generated-files.md)
- [Runtime boundary and controller loop contract](runtime-boundary-and-controller-loop-contract.md)
- [Runtime database and object contract](runtime-database-and-object-contract.md)
- [Prompt contract](../prompt-layer/contract.md)
