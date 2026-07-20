# Human and operator control surface

Status: Target

This page defines the frozen v1 human and operator control surface.

The core trust split is:

- human/operator surfaces are external
- AutoClaw has exactly two canonical MCP tool surfaces: `operator MCP` and `node MCP`
- `operator MCP` is external, operator-safe, and task-scoped
- `node MCP` is private, internal, and explicit-arg in v1
- `operator MCP` is canonically external `streamable-http`
- `node MCP` is canonically private internal HTTP/`streamable-http`
- bound node/runtime surfaces use callback semantics over private internal HTTP/`streamable-http`
- task-scoped observability reads stay operator-safe and, if surfaced as tools, attach to `operator MCP`
- no canonical shared MCP catalog or session may mix operator-safe tools and node-scoped runtime tools
- operator identity is external authority only; it is not canonical runtime DB truth
- `operator MCP` exposes runtime/operator/support reads, task-scoped control, definition-registry reads and guarded writes, and task start

## Standard external surfaces

The frozen v1 external control surface has three layers:

1. root CLI for local install, onboarding, DB work, local checks, local definition import, and local task-start wrappers
2. public operator API for snapshot, trace, task-scoped control, and guarded registry writes
3. trusted external operator MCP for automation

Browser or UI console is not part of the frozen v1 contract.

## Quick trust-boundary examples

Use these concrete examples to keep the lanes separate:

- An operator wants to pause a running task runtime: use the public operator API or `operator MCP`.
- A parent node wants to stage `assign_child` during an open dispatch: use `node MCP` only.
- A worker wants to publish a terminal checkpoint and then close with `retry`: use `node MCP` only.
- A support engineer wants raw provider delivery traces for incident review: use the task-scoped observability lane through operator-safe reads, not `node MCP`.

## Surface responsibilities

### Root CLI

The root CLI owns:

- local install and onboarding flows
- local DB migration flows
- local health and configuration checks

[CLI surface and operator workflows](cli-surface-and-operator-workflows.md) owns the detailed lifecycle and style contract and keeps the CLI aligned with OpenClaw's CLI posture.

Session-bound runtime mutation is not a first-class root CLI family. Definition-import and task-compose wrappers remain local authoring front doors over the guarded registry lifecycle rather than second runtime-truth authorities.

Concrete examples:

- `POST /definitions` is the canonical public guarded upload front door.
- `upload_definition(...)` is the operator MCP parity write lane.
- `POST /tasks/start` is the canonical public task-start surface.
- root CLI `definitions import` and `task-compose start` wrappers are local front doors over the same canonical backend services.

### Public operator API

The public operator API owns:

- definition list and revision-history reads
- task start
- task runtime reads
- task pause, continue, and cancel
- operator snapshot and trace
- guarded definition uploads

Public operator routes are task-scoped externally. Internal flow lineage remains controller-owned.

When OpenClaw is the worker transport, the canonical machine control path for dispatch lifecycle is Gateway WS RPC (`agent`, `agent.wait`, `sessions.abort`), not HTTP OpenResponses.

Concrete examples:

- legal operator action: `POST /runtime/tasks/{task_id}/pause?expected_active_flow_revision_id=...`
- legal operator read: `GET /operator/tasks/{task_id}/snapshot`
- illegal operator shortcut: calling `assign_child` for one current parent node through a public flow route

Authenticated operator identity gates caller authority on these surfaces. It does not become canonical runtime DB truth.

### Trusted external operator MCP

`operator MCP` mirrors the operator-safe external lanes only.

`operator MCP` exposes these runtime/operator/support tools:

- task runtime reads
- task pause, continue, and cancel
- operator snapshot and trace

If task-scoped observability reads are exposed as tools, they also stay on `operator MCP`.

The same `operator MCP` surface also exposes:

- definition registry reads and guarded writes
- task start

`operator MCP` is:

- an automation-facing parity adapter
- external to the runtime controller/node trust lane
- not a second truth owner
- required to stay separate from `node MCP` in runtime-effective tool inventories such as `tools.effective`

`operator MCP` is not:

- `node MCP`
- a controller/node bridge
- a license to expose parent/root tool calls as ordinary operator actions

Operator teaching rule:

- inspect first with `get_runtime_task`
- then use `get_operator_snapshot` and `get_operator_trace`
- use `get_delivery_state_ref`, `get_continuity_state_ref`, `get_watchdog_state_ref`, and `get_provider_events_ref` only when deeper support-file inspection is needed
- `get_operator_snapshot` and `get_operator_trace` expose `current_paths` as support/readback refs only; those refs do not define semantic currentness, resume targets, or flow-control truth
- support-state rereads are support-only; if they disagree with controller/runtime truth, controller/runtime truth wins
- `pause_task`, `continue_task`, and `cancel_task` are mutating controls
- `continue_task` must not be used as a status-check or polling command and should use a fresh `expected_active_flow_revision_id` from a current runtime read
- `continue_task` is pause-resume only; it resumes the graph by reopening the appropriate dispatch from paused controller truth
- ordinary post-boundary progression after accepted `yield | green | retry | blocked` remains internal controller behavior rather than operator work

Concrete examples:

- legal operator MCP call: `pause_task(task_id, expected_active_flow_revision_id)`
- legal operator MCP call after pause: `continue_task(task_id, expected_active_flow_revision_id)`
- legal operator MCP read: `get_operator_snapshot(task_id)`
- legal operator MCP call: `start_task("C:/tasks/bugfix/task-compose.yaml")`
- not legal as part of `operator MCP`: `assign_child(session_key, task_id, payload, expected_structural_revision_id?)`
- not legal as part of `operator MCP`: using `continue_task(...)` as the normal child handoff, parent wake, or retry-advance path

### Private node MCP and callback lane

`node MCP` is the static v1 node-tool surface for controller or bound node integration.

It may expose:

- current-only `role` / `policy` lookup for the live node-bound structural-edit lane
- semantic checkpoint handoff writes
- dispatch boundary return
- dispatch-local parent/root tool calls

`node MCP` is:

- controller/node-facing only
- not `operator MCP`
- not the canonical human/operator control surface
- not a public trust-lane widening

Node teaching rule:

- `search_definitions` and `get_definition` are read-only current-only lookup tools for the live structural-edit lane when surfaced prompt or manifest context is insufficient, not for broad browsing or provenance
- `record_checkpoint` publishes durable semantic progress for the current live node execution and should be used before a terminal boundary when later readers need that progress state
- `return_boundary` closes the current dispatch turn; `yield` is non-terminal workflow progress, while `green`, `retry`, and `blocked` are terminal for the current dispatch turn
- `assign_child`, `add_child`, `update_child`, `remove_child`, `release_green`, and `release_blocked` perform dispatch-local parent/root mutation only when the current dispatch allows them and are not an operator-control surface

Concrete examples:

- `search_definitions(session_key, task_id, role, query=researcher)`
- `get_definition(session_key, task_id, policy, standard-worker)`
- `record_checkpoint(session_key, task_id, checkpoint)`
- `return_boundary(session_key, task_id, yield)`
- `assign_child(session_key, task_id, payload, expected_structural_revision_id?)`
- `release_green(session_key, task_id, expected_structural_revision_id?)`

This lane is canonically exposed as a static MCP server in v1. The tool call itself carries `session_key` and `task_id`. Canonical node-facing semantics do not require caller-visible `dispatch_id`, and callers must not invent `attempt_id` or callback-binding ids.

In the filesystem-first v1 model, the current node rereads surfaced files directly and does not rely on a canonical callback read helper.

Revision-history, guarded upload, and task-start tools remain operator/public surfaces rather than `node MCP` tools.

## Task-scoped observability reads

Implementation may retain deeper observability or debug helpers only when needed for runtime correctness or incident investigation.

Those reads are not:

- the standard operator role
- `node MCP`
- a reason to weaken the public API boundaries

There is no third canonical observability MCP.

If public or operator observability routes are documented, they should be task-scoped such as `/observability/tasks/{task_id}/...`. If they are surfaced as tools, they attach to `operator MCP`.

If retained, watchdog inspection belongs here, not on `node MCP`. Watchdog recovery itself remains internal controller behavior.

The frozen support-state readback family is `delivery-state.json`, `continuity-state.json`, `watchdog-state.json`, and `provider-events.ndjson`. Those files stay operator/support readbacks only and do not become controller truth.

## Task-compose entry model

The canonical task-compose entry model is split by surface:

- HTTP operators submit `TaskStartRequest` directly to `POST /tasks/start`
- CLI reads one local task-compose file and submits the resulting body
- `operator MCP` reads one local task-compose file and submits the resulting body

Each surface reaches the same task-start contract, but they do not gain the same runtime authority after launch. Task-start parity does not imply dispatch-local steering parity.

## Trust-boundary rule

Use these terms exactly:

- `tool`: canonical runtime action such as `assign_child`, `record_checkpoint`, or `release_green`
- `MCP surface`: one exposed tool inventory with one trust boundary
- `plugin` or `bundle`: OpenClaw packaging or parity-wrapper terminology only

`operator MCP` may mirror operator-safe external routes. It must not silently absorb `node MCP`.

## Related contracts

- [MCP, plugin, and CLI boundary](mcp-plugin-and-cli-boundary.md)
- [Operator definition and role boundary](operator-definition-and-role-boundary.md)
- [MCP tool reference](plugin-tool-reference.md)
- [API surface and trust-lane map](api-surface-and-trust-lane-map.md)
- [CLI surface and operator workflows](cli-surface-and-operator-workflows.md)
- [OpenClaw Gateway RPC subset](../architecture/openclaw-gateway-rpc-subset.md)
- [Runtime boundary and controller loop contract](../architecture/runtime-boundary-and-controller-loop-contract.md)
