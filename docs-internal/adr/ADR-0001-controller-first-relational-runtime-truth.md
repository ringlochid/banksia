# ADR-0001: controller-first relational runtime truth

Status: Accepted

## Decision summary

Runtime truth lives in controller/DB state first. Generated files, prompts, and surfaced refs are deterministic projections of that truth, not competing authorities.

## Superseded in part

[ADR-0007](ADR-0007-mcp-anchored-local-runtime-and-minimal-provider-control.md) narrows the persisted dispatch record set: delivery, continuity, watchdog, and provider-event rows are no longer separate correctness families. Controller-first relational runtime truth remains unchanged.

## Context

The live v1 runtime model depends on one authoritative source of currentness and legality.

Generated manifests, assignments, checkpoints, artifact pointers, and monitoring files are useful shared surfaces, but they must not compete with the controller's own truth model.

## Decision

Controller/DB state is the only authoritative runtime truth.

Persist explicit typed records for:

- structural revisions and current node ownership
- assignments and attempts
- checkpoints
- durable artifact publications and current pointers
- dispatch, delivery, continuity, and watchdog state
- launch-time compile provenance

Generated files under `_runtime/` and `outputs/artifacts/` are deterministic projections or published bodies derived from that truth.

V1 surfaced refs are path-only. Runtime must localize any external resource into the task root before surfacing it to agents.

Watchdog and recovery logic read controller/DB state directly. Generated monitoring files are observability projections only.

## Historical contrast

This ADR rejects the older idea that current truth can be reconstructed from:

- the latest generated file alone
- a callback/boundary summary alone
- the highest-looking artifact filename
- session memory or transport logs

Generated files remain important, but they are read models over controller truth.

## Consequences

- currentness, legality, retry, release, and recovery decisions are queryable and auditable
- generated projections can lag or be regenerated without changing runtime truth
- prompts and agents consume compact surfaced refs and shared projections without treating them as the source of truth
- DB/controller state wins whenever it disagrees with generated monitoring or manifest files

## Search keywords

- controller-owned truth
- DB-first runtime model
- generated projections
- watchdog DB ground truth
- path-only surfaced refs
- manifest is not the source of truth

Canonical references:

- `../design/v1/architecture/runtime-database-and-object-contract.md`
- `../design/v1/architecture/runtime-records-and-lifecycle.md`
- `../design/v1/architecture/runtime-boundary-and-controller-loop-contract.md`
- `../design/v1/architecture/runtime-observability-and-boundary-log.md`
