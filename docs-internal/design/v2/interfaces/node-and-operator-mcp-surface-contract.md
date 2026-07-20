# Node and Operator MCP surface contract

Status: Target

This page defines the V2 provider-neutral Node operation catalog, its managed and compatibility projections, and the separate Operator MCP trust surface. Exact model-visible schemas live in the [Node MCP schema appendix](node-mcp-schema-appendix.md).

## Core rule

AutoClaw owns one logical Node operation catalog and exposes it through two transport projections:

- the managed projection for dynamically attached Codex and Claude executions; and
- the compatibility projection for the explicitly experimental, user-configured OpenClaw lane.

Both projections invoke the same controller operations, currentness rules, transactions, failures, and audit behavior. They differ only in how task and dispatch scope is established and which schemas are model-visible.

Operator MCP is a separate external principal. It is never attached to a managed provider execution and never supplies Node authority.

Operator MCP is a local operator surface in this phase. It relies on the loopback or OS-owned process boundary rather than a global operator API key, and every operation still validates task scope and controller legality.

## Lowest-common-denominator profile

The shared contract depends only on:

- MCP tools;
- explicit JSON-schema inputs;
- structured JSON results with a text fallback;
- stateless Streamable HTTP; and
- provider-neutral logical tool names.

Correctness does not depend on MCP prompts, resources, ping, progress notifications, transport-session continuity, provider tool events, provider output, or dynamic tool refresh after provider start.

## One catalog, two projections

Each catalog descriptor owns:

- one logical operation name;
- its semantic input and output schemas;
- allowed role families;
- any required controller capability;
- whether it reads or mutates controller truth; and
- bounded teaching metadata.

The managed projection removes controller selectors from the model-visible schema because a private `DispatchMcpBinding` already supplies the exact task and dispatch. The compatibility projection prepends required full `task_id` and `dispatch_id` selectors to the same semantic schema.

Transport code registers and adapts descriptors. It does not duplicate domain operations, authorization, transaction boundaries, or failure logic.

## Logical operation families

The common current-context and task-read family is:

```text
get_current_context()
list_files(directory=".")
read_file(path, start_line=1, max_lines=400)
```

The common plan, evidence, boundary, and external-wait family is:

```text
set_work_plan(explanation?, steps)
record_checkpoint(...)
return_boundary(...)
open_human_request(...)
start_command_run(...)
```

Parent/root orchestration may additionally expose the catalog operations owned by structural orchestration, including definition lookup, child assignment and revision, and child-release handling. The current names include:

```text
search_definitions(...)
get_definition(...)
assign_child(...)
add_child(...)
update_child(...)
remove_child(...)
release_green(...)
release_blocked(...)
```

This list is an exposure ceiling, not permission to make every operation legal in every state. The descriptor's role rule, fresh capability read, and operation-specific controller predicate remain authoritative at call time.

## Role-scoped discovery

Managed `tools/list` authenticates the binding, freshly requires its dispatch to remain exact current `starting` or `open` authority, and returns only the stable operation ceiling selected for that dispatch. A worker binding never lists parent/root-only operations. Parent and root bindings receive only the additional structural operations required by their role contract. Tool discovery does not refresh Node activity.

Provider-side tool allowlists mirror that managed ceiling. They improve discovery and reduce accidental calls but do not replace controller admission.

The compatibility endpoint has no dispatch scope at discovery time, so it may list the complete compatibility catalog. Every call must include the full selectors and pass the same role, capability, exposure, and currentness checks before admission.

## Managed projection

The managed projection is mounted privately at `/_internal/node/mcp`. AutoClaw creates one process-local `DispatchMcpBinding` for each provider-start invocation and dynamically gives that invocation:

- the private endpoint;
- one opaque bearer credential; and
- its exact provider-side tool allowlist.

The model never supplies the credential, task ID, or dispatch ID as tool arguments. Multiple concurrent tasks share one MCP application without sharing credentials, role ceilings, or controller scope.

Binding construction, transport security, retry replacement, and revocation are owned by [Managed Node MCP binding](../architecture/managed-node-mcp-binding.md).

## Compatibility projection

The compatibility projection remains at `/node/mcp` for OpenClaw. AutoClaw does not inject or maintain it in `openclaw.json`; the user configures the endpoint and OpenClaw tool policy.

Every compatibility call includes:

```text
task_id
dispatch_id
```

These values are full controller IDs and scope selectors, not credentials. They must match an exact current `starting` or `open` dispatch and the operation's lawful role and capability. A stale dispatch never falls through to the task's newer dispatch.

Because this projection has no per-dispatch AutoClaw credential, it is weaker and remains experimental. Deployment must keep its reachability operator-controlled and apply the Host and Origin policy defined by the security owner.

## Current-context and file behavior

`get_current_context` returns one coherent current read of assignment, attempt, a typed compact trigger, optional work plan, direct-child workflow neighborhood, effective capabilities, allowed actions, logical consume/produce refs, the exact dispatch-request readbacks, and the support-only workflow-manifest readback. The trigger normalizes the opening reason and predecessor identity without duplicating the complete immutable trigger payload. `checkpoint_to_resume_from` is populated only from an exact accepted-boundary successor with a selected checkpoint; `continuation` remains reserved and `null`. A caller must handle either field being `null` and may read the immutable `input` ref for complete dispatch-start trigger or resume detail.

`list_files` is bounded and non-recursive. `read_file` is bounded and text-only. Both use the shared logical resolver owned by [Task root and file access](../architecture/task-root-and-file-access.md).

Node MCP does not expose generic file writes, content search, remote-root selection, or provider-native tool emulation. Provider-native tools remain the workspace editing lane; checkpoint and boundary operations remain the durable publication lane.

## Admission and Node activity

Every call follows this ordering:

```text
establish exact task and dispatch scope
  -> authenticate the managed binding or parse compatibility selectors
  -> validate strict semantic shape
  -> reread current dispatch, flow, assignment, attempt, role, exposure, and capability
  -> reject stale or unauthorized scope
  -> admit the invocation and refresh Node activity once
  -> execute the exact read or conditional mutation
  -> return a structured success or failure
```

An admitted call updates `last_node_activity_at` and increments `node_activity_revision` exactly once. Reads, accepted no-ops, and normalized domain failures after admission all count as activity.

Malformed input, failed transport authentication, wrong task/dispatch selectors, stale currentness, role/exposure denial, and capability denial occur before admission and do not refresh activity. Provider output, MCP ping, transport traffic, and provider-native tool events never refresh it.

An optional bounded `NodeMcpInvocation` audit row may describe the admitted operation and normalized outcome. It is not task-event or watchdog authority; the dispatch activity revision is.

## Operation transactions

Admission owns one short activity transaction. After it commits and publishes the exact activity signal, the operation opens a fresh session and owns its read or short conditional domain transaction. Transport code never wraps unrelated tools in a shared transaction, shares an `AsyncSession` between concurrent calls, or hides after-commit effects in `AsyncSession.commit()`.

Boundary, human-request, and command-run operations commit the exact source and close D1 before returning their MCP result. Their successor or deadline/process work is signalled after commit and proceeds independently of the response.

Currentness is checked again by every conditional mutation. If another operation wins after admission, the loser returns the operation's stable stale/conflict failure and cannot mutate a successor dispatch.

## No callback HTTP projection

V2 has no callback HTTP projection. Agent-origin checkpoint, boundary, structural, human-request-open, and command-run-start operations are available only through their owned Node MCP projections; no callback route, bearer/session-key authority, callback schema, provider-side callback client/configuration, runtime callback handler, or target callback test remains.

This is a target removal assertion, not a deprecated or fallback lane. Shipped-behavior contrast may continue to describe callback HTTP until implementation removes it, but target code must not preserve dual mutation authority.

## Operator surface

Operator MCP remains an external inspection and control surface. It may expose provider-neutral operations for:

- definition registry reads, definition upload, and task start;
- runtime reads and task control;
- human-request inspection and resolution;
- command-run inspection and cancellation; and
- support and observability reads.

Mutating definition-draft authoring remains on the local HTTP `/authoring` workbench API. Operator MCP is admitted through the loopback or OS-owned local process boundary and uses the same task-scoped controller legality as HTTP control surfaces. It may record `local_operator` as surface provenance, but that value is not a verified human identity.

Operator MCP has no global operator API key and never receives a managed binding credential. The managed binding remains a separate per-dispatch Node credential, and Operator MCP availability is not a provider readiness requirement.

## Failure contract

Every operation returns its named success shape or the shared structured `OperationFailure`. Provider adapters must preserve the logical code and fields even if a provider renders a text fallback.

Pre-admission failures reveal no file or state detail beyond the bounded recognition/currentness result. Post-admission domain failures may be audited with their normalized code and count as Node activity, but they do not commit the requested domain mutation.

## Required invariants

- one logical descriptor produces both Node projections;
- managed schemas contain semantic arguments only;
- compatibility schemas require full `task_id` and `dispatch_id`;
- a worker never discovers parent/root-only tools through the managed binding;
- every call rereads current controller authority;
- a stale binding or selector can never mutate a newer dispatch;
- each admitted call refreshes activity exactly once;
- pre-admission rejection never refreshes activity; and
- Operator MCP is never attached to managed provider execution;
- local Operator MCP has no global operator API key and never inherits a managed binding; and
- callback HTTP is absent from the V2 target.

## Related contracts

- [ADR-0010: dispatch-scoped managed Node MCP authority](../../../adr/ADR-0010-dispatch-scoped-managed-node-mcp-authority.md)
- [ADR-0012: loopback control plane without an operator API key](../../../adr/ADR-0012-loopback-control-plane-without-operator-api-key.md)
- [Managed Node MCP binding](../architecture/managed-node-mcp-binding.md)
- [Node MCP schema appendix](node-mcp-schema-appendix.md)
- [Task root and file access](../architecture/task-root-and-file-access.md)
- [Work plan and checkpoint](../architecture/work-plan-and-checkpoint-contract.md)
- [Runtime records and control state](../architecture/runtime-records-and-control-state.md)
- [Runtime lifecycle and watchdog](../architecture/runtime-lifecycle-and-watchdog.md)
- [Capability, security, and audit](capability-security-and-audit.md)
- [Human request and approval](human-request-and-approval-contract.md)
- [Command run and external wait](../architecture/command-run-and-external-wait.md)
