# Guarded Registry And Runtime Writes

Status: Target

This page summarizes the frozen v1 currentness-guard model for definition writes, public flow control, and callback dispatch-local runtime mutation.

## Guard classes

Use these guarded-write classes:

- DB-serialized append-only definition upload
- public task-scoped operator control
- callback current-context checkpoint, boundary, and parent/root tool writes

## Canonical guards

- DB serialization plus append-only revision history for definition upload
- `expected_active_flow_revision_id` for public task pause, continue, and cancel
- current bound execution/session binding for callback checkpoint, boundary, and parent/root tool routes
- optional current structural currentness echo fields when a runtime route needs additional stale protection

These same concurrency meanings apply across the canonical API, CLI, and plugin front doors. Adapters may translate transport, but they may not invent parallel stale-write semantics.

Controller echo facts remain runtime-minted. Definition upload does not use a caller-supplied compare token in the public contract.

## Concrete guard examples

### Guarded definition upload

- route: `POST /definitions`
- concurrency rule: DB serializes the upload and records each accepted write as a new immutable revision
- result rule: if two uploads race, both may succeed as distinct revisions and the current revision pointer advances in commit order

### Public task-scoped operator control

- route: `POST /runtime/tasks/{task_id}/pause`
- guard: `expected_active_flow_revision_id`
- failure shape: if the active structural revision already moved from `flowrev_0007` to `flowrev_0008`, the pause request must fail and the operator must reread the current flow

### Dispatch-local tool or boundary call

- internal adapter-binding examples: `POST /callback/tasks/{task_id}/checkpoint` `POST /callback/tasks/{task_id}/boundary` `POST /callback/tasks/{task_id}/tools/{tool_name}`
- guard: bound current execution/session identity plus any optional runtime-minted structural currentness echo field
- failure shape: if the bound execution already closed or the structural revision already moved past the echoed currentness basis, the write must fail as stale rather than mutating the wrong turn

If legacy `/internal/runtime/...` aliases remain during migration, they are compatibility-only route names. They do not widen or rename the canonical guard contract.

## Runtime mutation rule

Runtime structural CRUD is not a definition-registry write and not a launch compiler step.

The live runtime write sequence is:

1. parse request shape
2. validate semantic and currentness legality
3. commit/adopt runtime truth
4. regenerate runtime projections through the materializer/projector

## Authority rule

- guarded definition writes belong to the registry lane
- public operator runtime control is task-scoped externally
- callback-lane parent/root tool calls belong to the bound current-execution lane only
- delegated workers do not receive public guarded definition-write authority by default

## Conflict rule

If a guard does not match current truth, the write must fail as a stale-write or currentness conflict rather than silently succeeding.

The canonical next step after a conflict is always reread first, then retry only against the newly surfaced current truth.

## Related contracts

- [Definition Registry And Upload Contract](definition-registry-and-upload-contract.md)
- [API Surface And Trust Lane Map](api-surface-and-trust-lane-map.md)
- [Plugin Tool Reference](plugin-tool-reference.md)
