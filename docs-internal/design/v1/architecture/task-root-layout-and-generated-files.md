# Task root layout and generated files

Status: Target

> **V2 supersession notice:** This page remains the frozen V1 task-root baseline. V2 removes `context/`, `context/wiki/`, and the four dispatch monitoring files; use [Task root and file access](../../v2/architecture/task-root-and-file-access.md).

This page defines the canonical v1 task-root layout and the generated runtime surfaces that live inside it.

## Core rule

Task directories are owned by the task, not by the provider adapter.

The controller owns runtime truth and deterministically materializes generated read surfaces under `_runtime/`. Those generated files are useful shared projections, navigation aids, and operator/debug surfaces, but controller/DB state remains the final authority.

Trusted OpenClaw session-binding proof lives outside ordinary worker-readable task-root context and is not part of surfaced semantic runtime files.

## Canonical task root tree

```text
<task-root>/
  workspace/
  context/
    wiki/
    ...
  outputs/
    artifacts/
      <owner_node_key>/
        <slot>/
          <slot>.vNN.<ext>
          current.json
  tmp/
    transfers/
      localized/
  _runtime/
    criteria/
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
    dispatch/
      <dispatch_id>/
        prompt.md
        prompt-request.json
        delivery-state.json
        continuity-state.json
        watchdog-state.json
        provider-events.ndjson
```

## Root roles

| Root                 | Exact meaning                                                                  |
| -------------------- | ------------------------------------------------------------------------------ |
| `workspace/`         | mutable work in progress for the current assignment                            |
| `context/`           | durable supporting material and curated source/reference material for the task |
| `context/wiki/`      | curated reference pages and synthesized reusable notes                         |
| `outputs/artifacts/` | durable published outputs and evidence                                         |
| `tmp/transfers/`     | optional transient carryover                                                   |
| `_runtime/`          | controller-generated runtime projections and monitoring                        |
| `_runtime/criteria/` | controller-generated explicit criteria projections                             |

## Generated runtime surfaces

### Criteria generated surfaces

```text
_runtime/
  criteria/
    <slot>.vNN.md
    <slot>.md
```

Rules:

- `_runtime/criteria/` holds controller-generated explicit criteria projections.
- `<slot>.vNN.md` is the stable versioned criteria projection path.
- `<slot>.md` is the compatibility alias for callers that read the current slot without a version suffix.
- These files are generated runtime read surfaces, not authored `context/` material.

### Whole-task generated surfaces

```text
_runtime/
  workflow-manifest.json
  workflow-manifest.md
```

Rules:

- `_runtime/workflow-manifest.*` is the one stable whole-workflow manifest family.
- It is regenerated in place after adopted runtime structural truth changes.
- It is the shared workflow picture agents read; it is not authored workflow YAML and not a scope-local brief family.
- its payload includes `manifest_version`, filesystem path bindings, `current_context.latest_relevant_checkpoint_path`, the top-level `structural_edit_palette`, and per-node `policy` when present
- the markdown mirror may omit an empty rendered `Structural Edit Palette` section even when the machine payload keeps an empty palette object
- the stable manifest, attempt, and dispatch task-root projections are written by synchronous post-commit helpers so the controller can refresh the read surfaces immediately after commit

Concrete regeneration example:

1. parent/root successfully commits `add_child`
2. controller adopts the new structural revision in DB truth
3. materializer rewrites `_runtime/workflow-manifest.json`
4. materializer rewrites `_runtime/workflow-manifest.md`
5. the still-open parent/root dispatch may reread the regenerated manifest before `yield`

### Attempt-local generated surfaces

```text
_runtime/
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

- `assignment.*` is the deterministic controller-generated projection of the current assignment for that attempt.
- `latest-checkpoint.*` is the deterministic controller-generated projection of the current published checkpoint for that attempt.
- `artifact-index.json` is the attempt-local durable artifact ledger.
- `transient-index.json` is the attempt-local surfaced transient-ref ledger.
- These files are navigation and handoff surfaces for later agents.
- Agents do not invent the runtime metadata in these files.

Concrete example:

- child node `implement_fix` receives `_runtime/attempts/attempt.implement_fix.01/assignment.md`
- later parent review reads `_runtime/attempts/attempt.implement_fix.01/latest-checkpoint.md`
- if that attempt published a durable artifact, the same directory's `artifact-index.json` tells later readers which exact versioned path was published during that attempt

### Dispatch-local generated monitoring surfaces

```text
_runtime/
  dispatch/
    <dispatch_id>/
      prompt.md
      prompt-request.json
      delivery-state.json
      continuity-state.json
      watchdog-state.json
      provider-events.ndjson
```

Rules:

- `prompt.md` is the persisted full canonical prompt for that dispatch.
- `prompt-request.json` is the persisted transport request envelope for that dispatch, including send-mode-specific request fields.
- These are controller-generated observability projections only.
- `delivery-state.json` is the transport/delivery rollup.
- `continuity-state.json` is the session continuity and reuse/reset projection.
- `watchdog-state.json` is the watchdog classification and recovery projection.
- `provider-events.ndjson` is the append-only normalized provider/adapter event log.
- Watchdog reads controller/DB state as ground truth; it does not rely on file scans as its authoritative source.
- If generated files and controller/DB state disagree, controller/DB state wins.

## Durable artifact layout

Durable published outputs live under `outputs/artifacts/`.

```text
outputs/
  artifacts/
    <owner_node_key>/
      <slot>/
        <slot>.v01.<ext>
        <slot>.v02.<ext>
        current.json
```

Rules:

- Versioned artifact files are immutable durable publications.
- `current.json` is the controller-generated current pointer for that `(owner_node_key, slot)` pair.
- Do not publish mutable artifact aliases such as `<slot>.latest.md`.
- Later readers should use surfaced refs, assignment/checkpoint files, and current pointers rather than guessing currentness from filename ordering.

## Path-only surfaced refs

V1 surfaced refs are path-only.

That means:

- assignment refs use `path`
- checkpoint refs use `path`
- manifest surfaced refs use `path`
- artifact refs use `path`
- transient refs use `path`

Runtime must localize any external resource into the task root before surfacing it to agents. Do not make agents reason about local-versus-remote locator precedence inside the live v1 generated-surface model. Imported external resources should be mirrored under `tmp/transfers/localized/` so surfaced paths stay task-root-owned even when authored `context/` is host-bound.

## Read and write rule

Normal work should follow this split:

- read broader durable task support material from `context/`
- use `context/wiki/` for curated reusable reference pages
- read explicit criteria from `_runtime/criteria/`
- perform mutable in-progress work in `workspace/`
- use `tmp/transfers/` only for optional explicit transient carryover
- use `tmp/transfers/localized/` for controller-owned mirrors of external surfaced files
- publish durable outputs under `outputs/artifacts/` through the controller's publication flow
- treat `_runtime/` as controller-generated read surfaces and monitoring, not as an ordinary direct-write work area

Practical consequence:

- if a node wants to explain what happened, it writes checkpoint content through the checkpoint publication lane
- if a node wants to publish durable evidence, it uses the durable artifact publication lane
- it should not hand-edit `_runtime/workflow-manifest.md` or `_runtime/dispatch/<dispatch_id>/watchdog-state.json`

## Removed from the live generated-surface model

The following are not canonical generated surfaces in the live v1 model:

- `_runtime/views/`
- `flow-manifest.json` / `flow-manifest.md`
- `scope-manifest` families
- `flow-brief.md`
- scope briefs
- `scopes/<scope_key>/...`
- handoffs as the canonical generated output surface
- old views/scopes read models as required agent context

The live generated-surface model is stable manifest + attempt-local files + dispatch-local monitoring.

## Related contracts

- [Filesystem layout and roots](filesystem-layout-and-roots.md)
- [Manifest contract](manifest-contract.md)
- [Artifact ref and storage contract](artifact-ref-and-storage-contract.md)
- [Worker context contract](worker-context-contract.md)
