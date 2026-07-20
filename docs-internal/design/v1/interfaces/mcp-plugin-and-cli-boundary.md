# MCP, Plugin, and CLI Boundary

Status: Target

This page is the front-door owner for how AutoClaw exposes tools in v1 and how `MCP`, `plugin`, `bundle`, and `CLI` terminology split.

## Core rules

- AutoClaw has exactly two canonical MCP tool surfaces:
    - `operator MCP`
    - `node MCP`
- `operator MCP` is the standard external parity surface.
- `node MCP` is the static explicit-arg v1 node-tool surface.
- `tool` is the canonical runtime term.
- `plugin` and `bundle` are packaging or parity-wrapper terms only.
- no canonical shared MCP catalog or session may mix operator-safe tools and node-tool write authority
- operator identity is an external caller fact, not canonical runtime DB truth
- `operator MCP` is canonically external `streamable-http`
- `node MCP` is canonically `streamable-http` on a stable MCP server entry in v1
- `node MCP` v1 authority comes from explicit `session_key` + `task_id` tool arguments validated against controller truth
- detailed CLI lifecycle and style rules live on [CLI surface and operator workflows](cli-surface-and-operator-workflows.md)
- `operator MCP` includes runtime reads and control, operator snapshot and trace, any explicitly allowed task-scoped observability reads, definition discovery, guarded upload, and task start

## Surface map

| Surface        | Caller                                                                            | Scope                                                            | Canonical use                                                                                                                                                                                      | Not allowed                                                                                                                                    |
| -------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `operator MCP` | external operator or trusted external automation                                  | task-scoped external authority                                   | runtime reads and control, operator snapshot and trace, any explicitly allowed task-scoped observability reads, definition discovery, guarded upload, and task start                               | parent/root node tools, checkpoint publication, boundary return                                                                                |
| `node MCP`     | any worker/parent/root run that was given the current dispatch-local tool context | one static v1 MCP surface with explicit node-tool authority args | `record_checkpoint`, `return_boundary`, legal parent/root tool calls during the open dispatch, and current-only `role` / `policy` lookup when the dispatch surfaces that read-only escalation lane | operator pause/continue/cancel, shared operator catalogs, generic external automation use, revision-history/upload/start definition operations |
| `CLI`          | local human or local trusted automation                                           | local machine bootstrap                                          | install, doctor, DB flows, local file import, local task start, OpenClaw checks                                                                                                                    | becoming a third tool-runtime authority model                                                                                                  |

When task-scoped observability reads are exposed on `operator MCP`, the frozen support-state family is `delivery-state.json`, `continuity-state.json`, `watchdog-state.json`, and `provider-events.ndjson`. Those readbacks stay support-only and do not create an additional MCP surface. Freezing that file family does not protect retained non-behavioral legacy fields inside those files from removal.

## Teaching rule

- for the inspected OpenClaw bundle-MCP path, tool descriptions are the canonical model-facing teaching contract; server `instructions` are direct-client summary metadata only
- `operator MCP` must teach an observe-before-mutate workflow: `get_runtime_task -> get_operator_snapshot -> get_operator_trace -> get_delivery_state_ref/get_continuity_state_ref/get_watchdog_state_ref/get_provider_events_ref` when deeper support inspection is needed
- `continue_task` is a mutating control action and must not be taught or used as a status-check or polling tool
- `continue_task` is pause-resume only and must not be taught as the ordinary path for yielded child handoff, parent wake, or retry advancement
- `get_delivery_state_ref`, `get_continuity_state_ref`, `get_watchdog_state_ref`, and `get_provider_events_ref` return task-scoped support file refs/paths, not parsed task-state answers
- support-state rereads are support-only; if they disagree with controller/runtime truth, controller/runtime truth wins
- `node MCP` must teach lookup separately from mutation: `search_definitions` / `get_definition` are read-only current-only lookup tools, while `record_checkpoint`, `return_boundary`, `assign_child`, `add_child`, `update_child`, `remove_child`, `release_green`, and `release_blocked` mutate live runtime state
- node lookup tools must say they are only for the live structural-edit lane when surfaced prompt or manifest context is insufficient, not for broad browsing or provenance
- `return_boundary` must teach that `yield` is non-terminal workflow progress while `green`, `retry`, and `blocked` are terminal for the current dispatch turn
- each structural node-mutation tool must teach that it is legal only when the current dispatch allows parent/root mutation for that turn
- static `node MCP` wrappers must preserve the strict runtime request and response schemas; they must not widen structural-mutation payloads into generic object maps or flatten typed node-operation results into untyped wrapper contracts
- `upload_definition` and `start_task` must teach that they load local files on the AutoClaw host and mutate controller-owned state

## OpenClaw attachment rule

When OpenClaw carries one of these MCP surfaces, the attachment belongs to the OpenClaw package or wrapper bootstrap, not to controller runtime truth.

Rules:

- an OpenClaw package or parity wrapper may attach one MCP surface to an OpenClaw agent/profile pair
- if one package ships both MCP surfaces, they still remain separate surfaces with separate trust boundaries
- do not teach one shared mixed MCP catalog or one shared mixed MCP session as the canonical model
- prefer fail-closed OpenClaw agent config for each surface: `tools.profile="minimal"` plus explicit `tools.allow` for the intended surface inventory
- do not rely on broad `coding` or `messaging` profiles to keep the surfaces separated
- on any OpenClaw profile or session that must not see MCP tools, deny `bundle-mcp` explicitly
- config writes alone are not proof of correct attachment
- runtime proof must show that operator-facing profiles or sessions expose only `operator MCP` and that `node MCP` is reachable through the static v1 tool surface without a mixed operator inventory
- OpenClaw agent or profile attachment does not become task, flow, assignment, attempt, or operator truth in the runtime DB
- operator identity remains an external authority fact on CLI, API, and MCP boundaries rather than a canonical runtime object family

## Recommended transports

- OpenClaw-backed dispatch lifecycle uses Gateway WS RPC `agent`, `agent.wait`, and `sessions.abort` as the canonical machine control path.
- HTTP `POST /v1/responses` is compatibility or fallback transport only.
- `operator MCP` uses external `streamable-http` as the canonical MCP transport.
- `operator MCP` mirrors the operator-safe route families under `/runtime`, `/operator`, any explicitly allowed task-scoped `/observability` reads, `/definitions`, and `/tasks/start`.
- `node MCP` uses a static MCP server in v1.
- the tool call itself carries `session_key` and `task_id`.
- `session_key` is the primary authority input.
- `task_id` is also required and must match controller truth for that session.
- `x-session-key` and `x-task-id` are not the canonical v1 node-MCP interface.
- operator API auth belongs to `operator MCP`, not to `node MCP`.
- shipped `node MCP` exposes current-only `search_definitions` / `get_definition` for `role` and `policy`, and prompt surfaces especially teach that lane when parent/root structural edits need it
- `node MCP` must not expose `list_definition_versions`, `upload_definition`, or `start_task`
- plugin/harness session injection may remain current or experimental integration, but it is not the v1 canonical contract.
- do not require `gateway.auth.mode="none"` or broad public ingress as part of the canonical AutoClaw v1 setup; loopback or otherwise private trusted ingress is the default expectation

## Vocabulary rule

Use these terms exactly:

- `tool`: a canonical runtime action or read surface
- `MCP surface`: one exposed tool inventory with one trust boundary
- `plugin` or `bundle`: OpenClaw packaging, parity-wrapper, or bootstrap terminology only
- `operator`: an external authority shape, not a runtime DB identity family

## Related contracts

- [API surface and trust-lane map](api-surface-and-trust-lane-map.md)
- [MCP tool reference](plugin-tool-reference.md)
- [Human and operator control surface](human-and-operator-control-surface.md)
- [CLI surface and operator workflows](cli-surface-and-operator-workflows.md)
- [CLI, API, and package shape](cli-api-and-package-shape.md)
- [OpenClaw Gateway RPC subset](../architecture/openclaw-gateway-rpc-subset.md)
- [OpenClaw worker and gateway contract](../architecture/openclaw-worker-and-gateway-contract.md)
