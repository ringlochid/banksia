# MCP Tool Reference

Status: Target

Path note: this file path is retained for older plugin-routing links. The live surface model is MCP-based.

The canonical runtime term is `tool`. AutoClaw has exactly two canonical MCP tool surfaces:

1. `operator MCP`
2. `node MCP`

`plugin` and `bundle` remain packaging or parity-wrapper terminology only.

For the front-door boundary and CLI split, start with [MCP, plugin, and CLI boundary](mcp-plugin-and-cli-boundary.md).

One shared controller-owned internal definition service backs the operator-facing definition and task-start tools on `operator MCP` and the separate current-only role/policy lookup path behind explicit v1 structural edits on `node MCP`.

## Product shape

The canonical MCP split is:

1. `operator MCP`
2. `node MCP`

Rules:

- `operator MCP` is the standard external parity surface
- `node MCP` is private, internal, and explicit-arg in v1
- no canonical shared MCP catalog or session may mix those two surfaces
- operator identity is not canonical runtime DB truth
- if task-scoped observability reads are exposed as tools, they belong to `operator MCP`, not to a third canonical MCP surface
- `operator MCP` exposes runtime reads and control, operator snapshot and trace, any explicitly allowed task-scoped observability reads, definition-registry reads and guarded writes, and task start

## Quick boundary examples

- Need to start a task from one local file: `operator MCP`.
- Need to read a task runtime snapshot or trace: `operator MCP`.
- Need to call `assign_child` for a currently dispatched parent or root node: `node MCP` only.
- Need definition revision history for audit or provenance: `operator MCP` only.
- Need task-scoped watchdog inspection after a stalled runtime: `operator MCP` only when the wrapper intentionally exposes the observability read.
- Need a definition upload: `operator MCP`, not `node MCP`.

When OpenClaw is the worker transport:

- canonical controlled execution should use Gateway WS RPC machine surfaces such as `agent`, `agent.wait`, and `sessions.abort`
- HTTP `POST /v1/responses` remains compatibility/fallback transport only

## Operator-safe external lane

This lane is the canonical `operator MCP` surface.

## Operator MCP runtime and control tools

`operator MCP` uses external `streamable-http`. It mirrors the operator-safe runtime, operator, and optional observability lanes on one external surface.

| MCP tool                                                              | Contract                                                                                                                                                                                   | Result                           |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------- |
| `list_runtime_tasks(query?, limit?, cursor?, sort?, status?)`         | `Read-only:` list task runtime summaries and choose a task for deeper inspection                                                                                                           | `RuntimeFlowSummaryListResponse` |
| `get_runtime_task(task_id)`                                           | `Read-only:` inspect current task status and active flow revision; use this first for status checks and before mutating controls                                                           | `RuntimeFlowRead`                |
| `get_operator_snapshot(task_id)`                                      | `Read-only:` inspect current operator-facing support/readback state and `current_paths`; these refs do not define semantic currentness                                                     | `OperatorFlowSnapshotResponse`   |
| `get_operator_trace(task_id, scope?, query?, limit?, cursor?, sort?)` | `Read-only:` inspect dispatch and checkpoint chronology plus support/readback `current_paths`; these refs do not define semantic currentness                                               | `OperatorFlowTraceResponse`      |
| `pause_task(task_id, expected_active_flow_revision_id)`               | `Mutating:` pause a task intentionally; use only with a fresh revision id from a current runtime read                                                                                      | `RuntimeFlowPauseResponse`       |
| `continue_task(task_id, expected_active_flow_revision_id)`            | `Mutating:` resume a paused flow by reopening the appropriate dispatch from paused controller truth; do not use for status checks, polling, or ordinary post-boundary workflow advancement | `RuntimeFlowRead`                |
| `cancel_task(task_id, expected_active_flow_revision_id)`              | `Mutating:` cancel a task intentionally; use only with a fresh revision id from a current runtime read                                                                                     | `RuntimeFlowRead`                |

`operator MCP` rules:

- for the inspected OpenClaw bundle-MCP path, tool descriptions are the canonical model-facing teaching contract; server `instructions` are direct-client summary metadata only
- recommended inspection order is `get_runtime_task -> get_operator_snapshot -> get_operator_trace -> get_delivery_state_ref/get_continuity_state_ref/get_watchdog_state_ref/get_provider_events_ref` when deeper support inspection is needed
- `get_operator_snapshot` and `get_operator_trace` expose `current_paths` as support/readback refs only; those refs do not define semantic currentness, resume targets, or flow-control truth
- `continue_task` is a mutating control action and must not be used as a polling or diagnostic command
- `continue_task` is pause-resume only; it must not be used as the ordinary child handoff, parent wake, or retry-advance path
- external control remains task-scoped
- there is no standard public node-level steering tool
- `operator MCP` must not widen into dispatch-bound runtime mutation
- when one OpenClaw package carries both MCP surfaces, operator-facing profiles or sessions must show only this inventory through `tools.effective` or an equivalent runtime inventory read
- prefer `tools.profile="minimal"` plus exact `tools.allow` entries for this inventory instead of broad profile inheritance

Worked example:

```text
pause_task("task_2026_0042", "flowrev_0007")
-> RuntimeFlowPauseResponse { flow: ... }
```

## Operator MCP definition and task tools

The same `operator MCP` surface also exposes the public ingest/start parity tools:

| MCP tool                                                                                    | Contract                                                                                                                                                                                       | Result                              |
| ------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| `search_definitions(kind, query?, limit?, cursor?, sort?, allowed_node_kind?, applies_to?)` | `Read-only:` discover candidate `role`, `policy`, or `workflow` definitions before choosing or mutating                                                                                        | `DefinitionSummaryListResponse`     |
| `get_definition(kind, key)`                                                                 | `Read-only:` inspect one current definition revision                                                                                                                                           | `DefinitionRevisionDetailResponse`  |
| `list_definition_versions(kind, key, limit?, cursor?, sort?)`                               | `Read-only:` inspect definition revision history for audit or provenance only, not normal planning                                                                                             | `DefinitionRevisionHistoryResponse` |
| `upload_definition(definition_path)`                                                        | `Mutating:` load one canonical definition file from a local file path on the AutoClaw host and create or update controller-owned definition truth; inspect current definitions first if unsure | `DefinitionRevisionDetailResponse`  |
| `start_task(task_compose_path)`                                                             | `Mutating:` load one `TaskStartRequest` from a local file path on the AutoClaw host, create task root, and start real runtime effects; not a dry run                                           | `TaskStartResponse`                 |

Definition and task tool rules:

- file-path tools load one local file and submit the exact canonical body
- `upload_definition` and `start_task` are mutating tools, not dry-run inspection commands
- these tools are the operator/public search/get/history/upload/start surface over the shared internal definition service
- they reuse the same service as the HTTP and CLI surfaces rather than inventing plugin-owned registry logic
- `list_definition_versions(...)` remains operator/audit/provenance read only and is not part of the normal live parent/root node surface
- guarded definition writes use DB-serialized append-only revision semantics
- exact parameter names, defaults, enum values, HTTP query-name mapping, and machine-readable MCP result carriers live in [api-machine-catalog.yaml](api-machine-catalog.yaml)

### Optional task-scoped observability reads

If task-scoped observability reads are surfaced as tools, they stay on `operator MCP`.

They remain operator/support reads and do not create a third canonical MCP surface.

The frozen support-state readback family is `delivery-state.json`, `continuity-state.json`, `watchdog-state.json`, and `provider-events.ndjson`, surfaced through `get_delivery_state_ref(task_id)`, `get_continuity_state_ref(task_id)`, `get_watchdog_state_ref(task_id)`, and `get_provider_events_ref(task_id)` only. These tools return task-scoped support file refs/paths, not parsed task-state answers.

## Node MCP

`node MCP` is the static v1 node-tool surface. Server-side runtime truth resolves the current execution context from explicit `session_key` and `task_id`.

| MCP tool                                                                                                          | Canonical runtime operation                                                                                                                                                        | Result                             |
| ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| `search_definitions(session_key, task_id, kind, query?, limit?, cursor?, sort?, allowed_node_kind?, applies_to?)` | `Read-only:` current-only `role` / `policy` discovery for the live structural-edit lane when surfaced prompt or manifest context is insufficient; not broad browsing or provenance | `DefinitionSummaryListResponse`    |
| `get_definition(session_key, task_id, kind, key)`                                                                 | `Read-only:` current-only `role` / `policy` detail for the live structural-edit lane when surfaced prompt or manifest context is insufficient; not broad browsing or provenance    | `DefinitionRevisionDetailResponse` |
| `record_checkpoint(session_key, task_id, checkpoint)`                                                             | `Mutating:` durable semantic-progress publication for the current live node execution; use before a terminal boundary when later readers need the progress state                   | `CheckpointRead`                   |
| `return_boundary(session_key, task_id, boundary)`                                                                 | `Mutating:` close the current dispatch turn; `yield` is non-terminal workflow progress, while `green`, `retry`, and `blocked` are terminal; not a polling action                   | `BoundaryRead`                     |
| `assign_child(session_key, task_id, payload, expected_structural_revision_id?)`                                   | `Mutating:` stage one bounded assignment for a ready or terminal direct child; fresh same-child work requires a live parent/root dispatch and no assigned downstream artifact consumer | `AssignChildSuccess`               |
| `add_child(session_key, task_id, payload, expected_structural_revision_id?)`                                      | `Mutating:` add one structural child node draft to the current flow revision when the current dispatch allows legal parent/root mutation                                           | `AddChildSuccess`                  |
| `update_child(session_key, task_id, payload, expected_structural_revision_id?)`                                   | `Mutating:` update one current-flow child node definition in place when the current dispatch allows legal parent/root mutation                                                     | `UpdateChildSuccess`               |
| `remove_child(session_key, task_id, payload, expected_structural_revision_id?)`                                   | `Mutating:` remove one child node from the current flow revision when the current dispatch allows legal parent/root mutation                                                       | `RemoveChildSuccess`               |
| `release_green(session_key, task_id, expected_structural_revision_id?)`                                           | `Mutating:` mark the current parent/root assignment green-release-ready once current evidence is sufficient                                                                        | `ReleaseGreenSuccess`              |
| `release_blocked(session_key, task_id, expected_structural_revision_id?)`                                         | `Mutating:` mark the current root assignment blocked-release-ready once whole-flow blocked evidence is sufficient                                                                  | `ReleaseBlockedSuccess`            |

Rules:

- caller supplies `session_key` and `task_id` explicitly on every node tool call
- each structural mutation tool keeps its own exact typed payload contract; node MCP wrappers must not widen those payloads into a generic object shape
- the node teaching order is: use `search_definitions` / `get_definition` for current-only lookup when needed, then `record_checkpoint`, `return_boundary`, or the exact structural mutation tool intentionally
- `session_key` is the primary authority input
- `task_id` is also required and must match controller truth for that `session_key`
- canonical node-facing MCP calls do not require caller-visible `dispatch_id` or `attempt_id`
- `record_checkpoint` writes the semantic handoff body plus any explicit `transient_refs`; runtime-managed checkpoint refs and surfaced durable rereads come back through read projections
- callback request and response payloads do not expose `manifest_id`, `manifest_hash`, `node_session_key`, or `ack_checkpoint_id`
- direct structural mutation success carriers remain typed per tool and are not wrapped into a generic object-map envelope
- `assign_child` success returns committed child assignment/attempt lineage and optional `child_assignment_ref`; it does not expose a child `dispatch_id`
- `BoundaryRead` returns `accepted_boundary`, `flow`, and optional `latest_checkpoint_ref`
- node MCP wrappers preserve these typed result contracts rather than advertising generic object-map success bodies
- a fresh attempt may legitimately reread with `latest_checkpoint_ref: null`
- callback success carriers do not include `suggested_next_step`
- path-only surfaced refs remain canonical in returned read surfaces
- `search_definitions` and `get_definition` on `node MCP` are the only legal definition lookup tools on that surface, and they are current-only `role` / `policy` reads available on the shipped node surface
- `node MCP` must not expose `list_definition_versions`, `upload_definition`, or `start_task`
- when structural tools submit role/policy names, runtime resolves them through the same current-only lookup path and pins exact current revisions at commit time
- live parent/root planning should use surfaced current structural-edit choices first, then the current-only lookup lane when needed, rather than generic registry browsing or revision-history reads
- operator-safe automation must not be given this lane by default
- static node MCP config is stable in v1; the live `session_key` and `task_id` come from dispatch-local prompt state rather than hidden headers or plugin injection
- prefer `tools.profile="minimal"` plus exact `tools.allow` entries for this inventory instead of broad profile inheritance

Worked sequence:

```text
assign_child(session_key, task_id, payload)
-> AssignChildSuccess { target_assignment_key: ..., target_attempt_id: ..., child_assignment_ref: ..., workflow_manifest_ref: ... }

return_boundary(session_key, task_id, "yield")
-> BoundaryRead { accepted_boundary: "yield", flow: ... }
```

This sequence is legal only when `session_key` and `task_id` resolve to the current live node execution context. It is not part of `operator MCP`.

In the filesystem-first v1 model, worker reread comes from surfaced manifest/assignment/checkpoint/ref paths in prompt and generated files rather than from a callback read helper.

## MCP, tool, and packaging rule

Use these terms exactly:

- `tool`: canonical semantic action such as `assign_child` or `record_checkpoint`
- `MCP surface`: one exposed tool inventory with one trust boundary
- `plugin` or `bundle`: one OpenClaw package or parity wrapper that may carry one or both MCP surfaces without collapsing them

Packaging or wrapper language must not rename the core runtime model into a plugin-owned truth model.

It also must not blur these two questions:

- "What may an external operator-safe automation client do?"
- "What may a currently dispatched node do inside one open dispatch?"

Those are different trust boundaries even when one package happens to carry both surfaces.

## Removed from the live tool-surface model

Do not keep these as the live surface model:

- one shared MCP catalog or session that mixes `operator MCP` and `node MCP`
- broad inherited tool profiles standing in for exact MCP-surface allowlists
- config-only bootstrap “success” without live runtime tool-inventory proof
- old `/internal/runtime/...` callback naming
- old `/internal/support/...` or `/support/...` observability naming
- dispatch-keyed callback helper signatures
- `get_worker_context(binding_id)`
- `post_worker_callback(binding_id, node_attempt_id, event)`
- callback-era `progress | result | parent_decision | replan_request` event families
- `retry_child`
- `reissue_child`
- a separate public reassignment control verb; fresh same-child work uses `assign_child`
- `scope_key`
- flow/scope manifest split
- plugin-first truth ownership

## Related contracts

- [MCP, plugin, and CLI boundary](mcp-plugin-and-cli-boundary.md)
- [Human and operator control surface](human-and-operator-control-surface.md)
- [Operator definition and role boundary](operator-definition-and-role-boundary.md)
- [API surface and trust-lane map](api-surface-and-trust-lane-map.md)
- [API schema appendix](api-schema-appendix.md)
- [Guarded registry and runtime writes](guarded-registry-and-runtime-writes.md)
- [OpenClaw Gateway RPC subset](../architecture/openclaw-gateway-rpc-subset.md)
- [Runtime boundary and controller loop contract](../architecture/runtime-boundary-and-controller-loop-contract.md)
