# Runtime Monitoring And Watchdog Automation

Status: Reference

> **V2 supersession notice:** This page remains V1 observability routing. V2 removes provider-shaped monitoring projections from correctness and uses the single MCP-anchored watchdog in [Runtime lifecycle and watchdog](../../v2/architecture/runtime-lifecycle-and-watchdog.md).

## Purpose

This page routes monitoring, watchdog, provider-delivery, and observability questions to the live v1 owner pages.

## Core Rule

Controller/DB state is the watchdog ground truth. Generated files under `_runtime/dispatch/<dispatch_id>/` are controller-written observability projections only.

`dispatch_id` is an internal correlation key for one dispatch path. Nodes and ordinary operator/public callers do not use it as a canonical external handle.

This page is observability routing only. It does not freeze the full watchdog, delivery, or continuity support-state machine as core v1 runtime truth.

## Canonical Observability Surface

```text
_runtime/
  dispatch/
    <dispatch_id>/
      delivery-state.json
      continuity-state.json
      watchdog-state.json
      provider-events.ndjson
```

Shared ref family for those files:

```yaml
support_runtime_file_ref:
    kind: delivery_state | continuity_state | watchdog_state | provider_events
    path: string
    description: string
```

Rules:

- these refs are legal on observability/operator carriers only
- they are not ordinary node-visible manifest, assignment, checkpoint, or prompt context
- watchdog reads controller/DB truth first and never scans these files as its source of truth
- operator/public investigation should enter by `task_id`; runtime/support tooling may resolve any internal dispatch chronology afterward
- observability is inspect-only; watchdog recovery remains internal controller behavior

## Observability Read Order

1. Read controller/DB truth or an operator read model over that truth.
2. Read `delivery-state.json`.
3. Read `continuity-state.json`.
4. Read `watchdog-state.json`.
5. Read `provider-events.ndjson` only when normalized chronology matters.
6. If the incident changes later task understanding, bridge it into checkpoint or surfaced refs rather than making later readers scan `_runtime/dispatch/`.

## Use This Page For

- where the observability lane keeps dispatch monitoring
- which dispatch files are the canonical projections
- why observability refs are not node-visible runtime context
- where watchdog and provider recovery stop and durable checkpoint truth begins
- why watchdog is a periodic controller loop rather than a normal node/runtime action
- why detailed support-state enums belong below the lean core lock

## Go Deeper

- [Watchdog and recovery contract](watchdog-and-recovery-contract.md)
- [Runtime observability and boundary log](runtime-observability-and-boundary-log.md)
- [Watchdog and provider recovery](watchdog-and-provider-recovery.md)
- [OpenClaw continuity and send modes](openclaw-continuity-and-send-modes.md)
- [OpenClaw worker and gateway contract](openclaw-worker-and-gateway-contract.md)
