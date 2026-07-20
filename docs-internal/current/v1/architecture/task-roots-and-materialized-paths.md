# Current task roots and materialized paths

Status: Current

Last verified: 2026-07-19

A task root holds provider inputs, user files, outputs, and derived readbacks. It is not the runtime database.

## Layout

The maintained shape is:

```text
<task-root>/
  workspace/
  outputs/
    artifacts/
  tmp/
    transfers/
      localized/
  _runtime/
    workflow-manifest.json
    workflow-manifest.md
    criteria/
    attempts/
    dispatch/
      <dispatch-id>/
        instructions.md
        input.md
```

The exact contents depend on the workflow and completed work. Missing support projections do not erase controller truth.

## Dispatch request pair

Each dispatch has two immutable provider inputs:

- `instructions.md` teaches the role, runtime rules, available tools, and completion contract
- `input.md` carries the assignment and current dispatch context

The pair is written before the successor dispatch becomes current. A dispatch is not opened if the required pair cannot be published. Providers receive these files; there is no separate prompt file that can become another source of truth.

The rendered input and `get_current_context` both name the pair's task-relative paths for bounded readback. They also name `_runtime/workflow-manifest.md`, but that manifest remains a support projection. Current context reads the direct-child neighborhood from controller rows instead of treating the manifest as live authority.

## Projections

Workflow manifests, criteria, attempt readbacks, and artifact indexes are derived from committed database rows. A dedicated asynchronous projection owner writes them after commit.

Projection signals name the exact source to materialize. Replays are safe because each projection rereads current controller truth and writes the same derived result.

## Workspace and file access

A task may bind an external workspace. Multiple tasks may use the same workspace; AutoClaw does not lease it or block another task from using it.

Node tools accept task-relative paths. The controller checks containment and symbolic-link traversal before reading or writing. Capability and role policy decide which file tools a dispatch receives.

Workers receive only the tools they need. Parent assignment and release tools are not exposed to ordinary worker dispatches.

## Artifacts and cleanup

Published artifacts live under `outputs/artifacts/` and are represented by controller records. Temporary localized inputs live under `tmp/transfers/localized/`.

Transient cleanup and dispatch cleanup are asynchronous support effects. They may remove controller-owned temporary files and revoke a managed MCP binding, but they do not delete an external workspace.

A database reset deletes controller task roots only when they are inside the configured data boundary. It never deletes an external workspace.

## Evidence

- `apps/api/src/autoclaw/runtime/task_root/`
- `apps/api/src/autoclaw/runtime/dispatch/request_pair.py`
- `apps/api/src/autoclaw/runtime/projection/`
- `apps/api/src/autoclaw/runtime/node_operations/`
- `apps/api/src/autoclaw/persistence/models/runtime/assignment/artifacts.py`
- `apps/api/tests/integration/runtime/`
