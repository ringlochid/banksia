# ADR-0008: task-relative MCP reads and reduced task root

Status: Accepted

> **Partial supersession notice:** [ADR-0010](ADR-0010-dispatch-scoped-managed-node-mcp-authority.md) replaces this ADR's model-visible `NodeSession.session_key` recognition, one static Node projection, and progress-only invocation classification. The current [prompt system](../design/v2/prompt-layer/prompt-system.md), [work plan contract](../design/v2/architecture/work-plan-and-checkpoint-contract.md), and [task-root owner](../design/v2/architecture/task-root-and-file-access.md) also replace the historical prompt-file and attempt-plan details below. This page remains the accepted origin of task-relative reads, the reduced logical root, safe path resolution, and provider-native workspace editing.

## Decision summary

AutoClaw V2 keeps one small task-relative file namespace. Provider-native tools edit `workspace/`; the shared node MCP surface reads controller context and task files through `get_current_context`, `list_files`, and `read_file`. Artifact publication continues through checkpoints and controller copying.

V2 removes the unused `context/` family, its retrieval-hint mechanism, and the four dispatch monitoring projections. It does not add MCP file writes, search, resource references, or a remote filesystem abstraction.

## Context

ADR-0005 established task-owned roots and controller-generated projections, but it retained several V1 surfaces that are no longer useful to the current product strategy:

- `context/` and `context/wiki/` were created and modeled without becoming a meaningful worker workflow
- retrieval hints taught agents to search a directory that ordinary work did not use
- dispatch delivery, continuity, watchdog, and provider-event files projected provider-shaped support state that is no longer part of runtime correctness
- agents were told to recover controller context by reading generated files with provider-native filesystem tools

ADR-0007 makes committed semantic node MCP operations the agent-facing runtime truth. The file model should follow that decision without turning MCP into a general filesystem protocol.

## Decision

### Reduced task root

The complete V2 task tree is:

```text
task/
  workspace/
  outputs/
    artifacts/
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
```

The controller database remains authoritative. Files below `outputs/`, `tmp/`, and `_runtime/` are durable bodies or controller-owned projections as defined by their owner contracts; they do not become runtime authority.

`workspace/` is a logical task path backed by the task's persisted workspace binding. The other three logical roots are below the physical task root. Callers never provide physical roots.

### Task-relative node MCP reads

The provider-neutral context and file-read family is exactly:

```text
get_current_context()
list_files(directory=".")
read_file(path, start_line=1, max_lines=400)
```

Every call still carries the current explicit `task_id` and node-session `session_key` as recognition arguments. The shorthand signatures omit that common transport convention only for readability.

`get_current_context` returns the current assignment and attempt, the current plan, effective capabilities and allowed actions, consume and produce slots with logical paths, and optional normalized continuation and `checkpoint_to_resume_from` fields. The prompt owner teaches a worker to read a returned checkpoint before replanning after continuation or watchdog recovery and to use the immutable input readback when the optional current projection is absent.

`list_files` is non-recursive. `read_file` returns bounded text only. A shared resolver accepts only logical task-relative paths, rejects absolute paths and `..`, and rejects any symlink resolution that escapes the selected mapped root.

### File mutation and publication

Provider-native tools remain the workspace editing lane. Node MCP does not provide task-file writes. A worker publishes declared artifacts through the existing checkpoint contract; the controller copies and versions the accepted files under `outputs/artifacts/`.

MCP file search, generic resource references, caller-selected roots, and remote filesystem access are outside this decision.

### Plan mutation

The shared node context family also includes the worker-only semantic tool:

```text
update_plan(explanation?, steps)
```

It replaces the current attempt plan with one to nine meaningful steps using `pending`, `in_progress`, and `completed`. Exactly one step is in progress unless all steps are complete. An identical update is a no-op: it creates no revision, task event, or semantic progress.

Planning policy and checkpoint policy remain owned by the V2 attempt-plan and prompt contracts. Parent and root behavior does not change because of this tool.

### Recognition and progress

V2 retains the existing node recognition model: `task_id` plus the current `NodeSession` `session_key`. Provider identity, provider session ids, execution generations, and new MCP credentials do not enter the logical tool schemas.

Changed plan updates and other meaningful accepted controller mutations may advance `last_progress_at`. Reads, rejected calls, failed calls, and no-op plan updates do not. The minimal `NodeMcpInvocation` record captures invocation status and whether progress advanced; it is audit/support state, not a public task-timeline event.

MCP transport state, ping, protocol progress notifications, provider streams, and provider events are not semantic runtime truth.

## Partial supersession of ADR-0005

This ADR supersedes ADR-0005's decisions to retain:

- `context/` and `context/wiki/`
- retrieval hints tied to those directories
- `_runtime/dispatch/<dispatch_id>/delivery-state.json`
- `_runtime/dispatch/<dispatch_id>/continuity-state.json`
- `_runtime/dispatch/<dispatch_id>/watchdog-state.json`
- `_runtime/dispatch/<dispatch_id>/provider-events.ndjson`

It preserves ADR-0005's task-owned root, controller-first generated projections, localized transient material, artifact publication, and `tool` terminology. Generated files still never outrank controller truth.

## Consequences

- managed agents receive the same logical node context and read tools across OpenClaw, Codex, and Claude
- provider adapters no longer need to teach provider-specific reads of controller projections
- the visible task tree becomes smaller and easier to explain
- file access remains local-first and same-host while preserving a resolver seam for safe logical paths
- artifact writes retain one publication path instead of gaining a second MCP mutation lane
- stale databases and stale task-root layouts require a reset rather than a compatibility bridge

## Migration and reset

This is a reset-only V2 change. Schema and reset owners remove the obsolete context and dispatch-monitor record families and fail stale local databases with guidance to run `autoclaw db reset`.

Reset must never recursively delete a formerly configured external context binding. Such a path may be user-owned even though the V2 controller no longer models or surfaces it.

## Alternatives rejected

### Keep the V1 context tree

Rejected because it adds schema, prompt, projection, and support complexity without a demonstrated worker workflow.

### Keep provider-native reads for controller projections

Rejected because provider filesystem behavior then becomes part of runtime context recovery. One node MCP read contract is more portable and easier to validate.

### Add a general MCP filesystem

Rejected for this phase. File writes would duplicate provider-native workspace editing and artifact publication; search and resource-reference abstractions would add surface without current product value.

### Design remote file access now

Rejected because V2 remains local-first and same-host. Remote workspaces, remote shells, synchronization, and object-store task roots require a separate future decision.

## Non-goals

- replacing provider-native workspace editing
- adding task-file writes or search to node MCP
- defining remote workspace or remote filesystem transport
- making generated files authoritative
- changing provider selection or provider adapter control
- changing operator MCP authentication or tool families

## Canonical references

- [Task root and file access](../design/v2/architecture/task-root-and-file-access.md)
- [Node and Operator MCP surface](../design/v2/interfaces/node-and-operator-mcp-surface-contract.md)
- [Node MCP schema appendix](../design/v2/interfaces/node-mcp-schema-appendix.md)
- [ADR-0001: controller-first relational runtime truth](ADR-0001-controller-first-relational-runtime-truth.md)
- [ADR-0005: task-root surfaces and runtime-generated projections](ADR-0005-task-owned-roots-and-runtime-generated-projections.md)
- [ADR-0007: MCP-anchored local runtime and minimal provider control](ADR-0007-mcp-anchored-local-runtime-and-minimal-provider-control.md)
