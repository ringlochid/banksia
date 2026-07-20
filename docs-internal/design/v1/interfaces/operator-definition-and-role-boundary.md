# Operator definition and role boundary

Status: Target

This page is the canonical target definition of `operator`.

Operator is defined by authority and allowed actions, not by embodiment. The canonical design operator is external to the AutoClaw runtime boundary.

## `OperatorDefinitionContract`

An `operator` is a trusted external principal allowed to inspect or steer task runtime state through operator surfaces.

An operator may be:

- a human using the frozen root CLI and API surfaces
- a trusted external automation client authenticated into operator surfaces
- a trusted external automation client using `operator MCP` directly or through one OpenClaw package or parity wrapper

An operator is not:

- the controller
- a delegated worker
- a runtime parent
- a provider transport

## `UserVsOperatorContract`

- `user` owns or initiates business work
- `operator` steers runtime behavior after work exists

The same human may act as both at different moments, but the roles stay distinct because the allowed actions differ.

Concrete example:

- the same engineer may start a task as a user in the morning
- later inspect and pause that running flow as an operator
- but that same engineer still does not gain node-scoped `assign_child` authority unless acting through the internal controller/node lane

## `RoleBoundaryMatrix`

| Role         | Defined by                                   | Owns                                                                                                                                             | Must not own                                                                      |
| ------------ | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| `user`       | business or task authority                   | task summary, bound-root content, launch intent                                                                                                  | runtime steering by default                                                       |
| `operator`   | trusted external query and control authority | snapshot, trace, task-scoped pause/continue/cancel, guarded definition writes when authorized                                                    | delegated execution, controller truth, node-scoped steering as a normal primitive |
| `worker`     | bounded delegated execution                  | one assignment, checkpoint publication, boundary return, scoped outputs                                                                          | operator control, guarded registry writes by default                              |
| `controller` | runtime truth authority                      | durable state transitions, manifests, attempts, boundaries                                                                                       | delegated execution content                                                       |
| `parent`     | in-tree bounded decision authority           | `assign_child`, `add_child`, `update_child`, `remove_child`, `release_green`, and dispatch-local `yield`/terminal closure for its own assignment | external operator control role                                                    |
| `root`       | top-level in-tree bounded decision authority | all parent powers plus root-only `release_blocked` and whole-flow terminal closure when legal                                                    | external operator control role                                                    |
| `provider`   | execution transport                          | provider session and transport delivery                                                                                                          | runtime truth or controller decisions                                             |

## `TrustedAutomationRule`

A trusted external automation client may act as operator only when authenticated into operator surfaces.

That does not make it:

- a worker
- the controller
- a provider
- the internal node-scoped runtime adapter

## `OperatorMcpParityRule`

`operator MCP` is the canonical external automation surface over the operator-safe lanes. One OpenClaw package or parity wrapper may expose that surface without becoming a second truth owner.

It is not:

- the internal controller/node lane
- a separate operator authority model
- the primary human-facing operator UX
- a license to expose node-scoped parent/root tool calls as ordinary operator actions

## `ParentAndRootAreNotOperators`

`parent` and `root` are bounded runtime decision actors inside the workflow tree.

During an open dispatch they may use exactly these canonical control tools:

- `assign_child`
- `add_child`
- `update_child`
- `remove_child`
- `release_green`
- root-only `release_blocked`

They may also close their own current dispatch through:

- `yield`
- `green`
- `retry`
- `blocked` for the current node when its assignment cannot proceed; root whole-flow blocked closure also requires committed `release_blocked`

These are runtime node powers, not operator powers.

Concrete contrast:

- operator may pause `task_2026_0042`
- current parent node may `assign_child(investigate_logs, assignment)`
- current root node may `release_blocked` when whole-flow blocked state is already justified

Those three actions belong to three different authority shapes even if one human can observe them all.

## `WorkerIsNotOperatorRule`

A delegated worker remains a worker. Internal adapter, support, or debug helpers do not turn the worker into operator authority.

Workers do not own:

- parent/root control tools
- guarded definition writes by default
- task-scoped operator pause/continue/cancel

## `OperatorControlScopeRule`

Canonical operator control is task-scoped externally.

That means operator surfaces may:

- inspect task runtime snapshot and trace
- pause the whole task runtime
- continue the whole task runtime
- cancel the whole task runtime
- use guarded definition upload surfaces when explicitly authorized

They do not expose:

- dispatch-local `assign_child`
- dispatch-local structural CRUD
- `release_green`
- `release_blocked`
- callback checkpoint publication
- callback boundary return

Operator-safe routes therefore look like:

- `GET /runtime/tasks/{task_id}`
- `GET /operator/tasks/{task_id}/snapshot`
- `GET /operator/tasks/{task_id}/trace`
- `POST /runtime/tasks/{task_id}/pause`
- `POST /runtime/tasks/{task_id}/continue`
- `POST /runtime/tasks/{task_id}/cancel`

Operator-facing observability reads may also expose derived monitoring through `/observability/tasks/{task_id}/...` routes when an operator tool intentionally asks for them. Those reads remain operator/observability-only and do not grant callback mutation authority.

They do not look like:

- `POST /callback/tasks/{task_id}/tools/assign_child`
- `POST /callback/tasks/{task_id}/checkpoint`
- `POST /callback/tasks/{task_id}/boundary`

## Related contracts

- [MCP, plugin, and CLI boundary](mcp-plugin-and-cli-boundary.md)
- [Human and operator control surface](human-and-operator-control-surface.md)
- [MCP tool reference](plugin-tool-reference.md)
- [API surface and trust-lane map](api-surface-and-trust-lane-map.md)
- [Runtime boundary and controller loop contract](../architecture/runtime-boundary-and-controller-loop-contract.md)
