# ADR-0005: task-root surfaces and runtime-generated projections

Status: Accepted

## Decision summary

The task root is the shared local runtime workspace, but controller/DB state still owns truth. Generated files under `_runtime/`, durable outputs under `outputs/artifacts/`, and optional transient files under `tmp/transfers/` are deterministic projections and bodies, not primary authority.

## Superseded in part

[ADR-0008](ADR-0008-task-relative-mcp-reads-and-reduced-task-root.md) supersedes `context/`, `context/wiki/`, and the dispatch delivery, continuity, watchdog, and provider-event projection families. The task-owned root, controller-first authority, and generated-projection rules remain accepted.

## Context

The live v1 model is filesystem-first and path-first, but it no longer uses execution slices, packets, reports, or session bindings as canonical shared runtime authority.

Instead, agents and operators rely on:

- one stable whole-workflow manifest
- deterministic attempt-local assignment and latest-checkpoint projections
- durable artifact publications and current pointers
- optional transient carryover under `tmp/transfers/`
- dispatch-local monitoring projections

Those generated files must stay separate from controller/DB truth while still remaining deterministic, readable shared surfaces.

## Decision

The canonical task-root surfaces are:

- `workspace/`
- `context/`
- `outputs/`
- `tmp/`
- `_runtime/`

Within that task root:

- `workspace/` is mutable current-assignment work
- `_runtime/criteria/` is the explicit generated criteria root
- `context/wiki/` is curated reusable reference material
- other curated files under `context/` are source/reference material
- `outputs/artifacts/` holds durable published outputs plus `current.json` pointers
- `tmp/transfers/` is the optional transient carryover lane
- `_runtime/` holds deterministic controller-generated projections

The canonical generated runtime projections are:

- `_runtime/workflow-manifest.json`
- `_runtime/workflow-manifest.md`
- `_runtime/attempts/<attempt_id>/assignment.*`
- `_runtime/attempts/<attempt_id>/latest-checkpoint.*`
- `_runtime/attempts/<attempt_id>/artifact-index.json`
- `_runtime/attempts/<attempt_id>/transient-index.json`
- `_runtime/dispatch/<dispatch_id>/delivery-state.json`
- `_runtime/dispatch/<dispatch_id>/continuity-state.json`
- `_runtime/dispatch/<dispatch_id>/watchdog-state.json`
- `_runtime/dispatch/<dispatch_id>/provider-events.ndjson`

These are deterministic projections of controller/DB truth. They are not the canonical authority themselves.

V1 surfaced refs are path-only. If an external resource is needed, runtime must first localize or mirror it into the task root and then surface the localized `path`.

## Historical contrast

This ADR removes execution-slice, packet, report, brief, and session-binding families from the live shared-surface model.

The canonical runtime file families are now:

- manifest
- assignment
- latest checkpoint
- artifact current pointers and artifact indexes
- transient indexes
- dispatch-level monitoring projections

## Consequences

- retries and adopted structural revisions preserve the shared task-root model while minting new attempt or dispatch projections as needed
- manifest, assignment, checkpoint, artifact, transient, and monitoring files can be regenerated without changing runtime truth
- durable outputs and explicit current pointers replace packet/report-era completion surfaces
- execution-slice, packet, report, and session-binding language is removed as live authority
- controller/DB state remains the final authority whenever it disagrees with a generated file

## Search keywords

- task root
- runtime-generated projections
- path-only refs
- watchdog-state.json
- transient-index.json
- artifact current pointer
- context wiki versus context criteria

Canonical references:

- `../design/v1/architecture/filesystem-layout-and-roots.md`
- `../design/v1/architecture/task-root-layout-and-generated-files.md`
- `../design/v1/architecture/manifest-contract.md`
- `../design/v1/architecture/worker-context-contract.md`
- `../design/v1/architecture/artifact-ref-and-storage-contract.md`
- `../design/v1/architecture/runtime-database-and-object-contract.md`
