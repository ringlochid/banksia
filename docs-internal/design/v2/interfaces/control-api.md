# Control API

Status: Target

This page owns V2 task runtime reads, operator controls, human-request and command-run routes, snapshots, and traces. Event listing and streaming belong to the [task event stream](task-event-stream.md).

## Core rule

The Control API reads controller source rows and commits explicit controller intent. It never reconstructs currentness from provider output, task events, support files, provider/MCP sessions, or in-memory runtime signals.

The V2 Control API is a loopback-only, operating-system-trusted local surface. It has no global operator API key, `X-AutoClaw-API-Key` header, or browser credential bootstrap. Exact Host and unsafe-request Origin admission belong to the security owner; every admitted request still enforces task scope, currentness, and operation legality.

Local mutations record stable `local_operator` surface provenance. That value identifies the trusted local control surface; it does not claim an authenticated human identity.

## Route families

```text
GET  /control/tasks/{task_id}
GET  /control/tasks/{task_id}/snapshot
GET  /control/tasks/{task_id}/trace
GET  /control/tasks/{task_id}/events
GET  /control/tasks/{task_id}/events/stream

GET  /control/tasks/{task_id}/human-requests
POST /control/tasks/{task_id}/human-requests/{request_id}/resolve

GET  /control/tasks/{task_id}/command-runs
GET  /control/tasks/{task_id}/command-runs/{run_id}
GET  /control/tasks/{task_id}/command-runs/{run_id}/log
POST /control/tasks/{task_id}/command-runs/{run_id}/cancel

POST /control/tasks/{task_id}/pause
POST /control/tasks/{task_id}/continue
POST /control/tasks/{task_id}/cancel
```

Provider login/configuration mutation is not part of this browser-facing route family. No route exposes provider credentials, managed MCP binding material, raw provider payloads, or adapter-private continuity.

Callback HTTP is absent from the V2 target. Node operations use the managed or explicit-ID compatibility MCP projections rather than callback routes or session-key authority.

## Task runtime read

`GET /control/tasks/{task_id}` returns:

```yaml
RuntimeFlowRead:
  task_id: string
  task_title: string
  task_summary: string
  workflow_key: string | null
  status: pending | running | paused | completed | cancelled
  active_flow_revision_id: string
  control_revision: integer
  workflow_manifest_ref: ref
  current_node_key: string | null
  active_assignment_id: string | null
  active_attempt_id: string | null
  waiting_cause: human_request | command_run | null
  pause_reason: paused_by_operator | runtime_recovery_exhausted | runtime_transition_failed | null
  current_dispatch: DispatchRuntimeRead | null
  latest_dispatch_id: string | null
  current_plan: WorkPlanRead | null
  watchdog_recovery_count: integer | null
  current_human_request: HumanRequestSummary | null
  current_command_run: CommandRunSummary | null
  updated_at: timestamp
```

`current_dispatch` is non-null only for current `starting` or `open` authority:

```yaml
DispatchRuntimeRead:
  dispatch_id: string
  predecessor_dispatch_id: string | null
  assignment_id: string
  attempt_id: string
  status: starting | open
  opened_reason: root | boundary | child_return | human_result | command_result | watchdog_recovery | semantic_retry | operator_continue
  requested_provider: codex | claude | openclaw
  resolved_provider: codex | claude | openclaw
  selection_basis: explicit | default
  adapter_started_at: timestamp | null
  last_node_activity_at: timestamp | null
  node_activity_revision: integer
  watchdog_due_at: timestamp | null
  provider_start: ProviderStartReadback | null
  effective_capabilities: EffectiveCapabilityReadback
```

Closed dispatches are history and appear in trace. The API never invents a `closing` state or keeps a closed row current while waiting for provider cleanup.

The provider-start readback is:

```yaml
ProviderStartReadback:
  revision: integer
  attempt_count: integer
  next_attempt_at: timestamp | null
  retry_kind: initial | definite_failure | uncertain_acceptance | null
  last_error_code: string | null
```

There is no maximum-attempt field. `last_error_code` is bounded/sanitized controller readback, not a raw provider exception.

The exact capability readback is:

```yaml
EffectiveCapabilityReadback:
  provider_native_access:
    effective: full | restricted | denied
    source: default | policy_definition | task_policy | controller
  network_access:
    effective: allow | deny
    source: default | policy_definition | task_policy | controller
```

The two axes resolve independently. Their `source` identifies the ceiling that produced the effective value, using `controller > task_policy > policy_definition > default` when equally restrictive ceilings tie. Adapter or local hard ceilings report `controller`. Provider selection provenance remains separate.

`WorkPlanRead` is assignment-owned and optional:

```yaml
WorkPlanRead:
  assignment_id: string
  revision: integer
  explanation: string | null
  steps:
    - step: string
      status: pending | in_progress | completed
  authored_by_dispatch_id: string
  updated_at: timestamp
```

`current_plan: null` is a legal stable state for root, parent, or worker work. A plan is advisory and never interpreted as assignment completion.

`last_node_activity_at` is admitted current Node MCP activity, including reads, no-ops, and post-admission domain failures. It is not semantic progress, percent complete, provider liveness, or plan progress.

Provider provenance is exact selection provenance. An explicit route has matching requested/resolved values. An omitted preference resolves through the configured default. The API never labels a different provider as fallback because target selection has no fallback chain.

## Snapshot

`GET /control/tasks/{task_id}/snapshot` returns the runtime flow read plus a bounded operator summary:

```yaml
OperatorFlowSnapshotResponse:
  flow: RuntimeFlowRead
  top_actionable_items:
    - summary: string
      node_key: string | null
      current_paths: ref[]
      suggested_action: string | null
  current_paths: ref[]
  stream_head_event_id: string | null
```

The event anchor bootstraps chronology only. Current state still comes from source rows. Actionable items may identify a current work-plan item, open external wait, provider-start retry, pause, or exhausted watchdog recovery, but never infer action from provider output.

## Trace

`GET /control/tasks/{task_id}/trace` accepts:

```yaml
OperatorFlowTraceQuery:
  scope: current | whole
  q: string | null
  cursor: string | null
  limit: 1..200
  sort: occurred_at_desc | occurred_at_asc
```

The response contains graph nodes/dependencies, checkpoint and boundary history, current logical paths, and:

```yaml
dispatch_history:
  - dispatch_id: string
    predecessor_dispatch_id: string | null
    assignment_id: string
    attempt_id: string
    node_key: string
    status: starting | open | closed
    opened_reason: string
    closed_reason: string | null
    requested_provider: codex | claude | openclaw
    resolved_provider: codex | claude | openclaw
    selection_basis: explicit | default
    adapter_started_at: timestamp | null
    last_node_activity_at: timestamp | null
    node_activity_revision: integer
    effective_capabilities: EffectiveCapabilityReadback
    created_at: timestamp
    closed_at: timestamp | null
```

Trace contains no delivery state, provider terminal result, provider run/session identity, managed binding, or reopen-after-inactivity field. Work-plan chronology comes from bounded task events; individual Node invocation audit rows stay internal.

## Operator task controls

Pause, continue, and cancel require the caller's observed structural/control guard:

```yaml
RuntimeFlowControlRequest:
  expected_active_flow_revision_id: string
  expected_control_revision: integer
```

### Pause

Pause atomically records operator intent, increments `control_revision`, and closes current `starting` or `open` dispatch authority. The response reports that committed state immediately.

Binding currentness ends at commit. `DispatchCleanupRequested(dispatch_id)` performs registry removal and one bounded provider cleanup attempt afterward. Pause never waits for provider stop and never creates a `closing` state.

An active human request or command run remains source-owned. It may become terminal while the flow is paused, but no successor opens until a legal continue consumes the exact source.

### Continue

Continue is legal for an operator pause, watchdog exhaustion, or deterministic transition failure after repair. It does not answer a human request, complete/cancel a command, reconnect a provider response, or bypass an unresolved source.

The request directly awaits fresh legality validation, request-file materialization, and the final flow-running plus D2+refs commit. Only provider start is asynchronous after the response. If another transition wins, continue returns a stable conflict and causes no provider effect.

### Cancel

Cancel atomically records terminal task intent, closes current dispatch authority, and updates exact owned external sources according to their contracts. A possibly live command remains `cancellation_requested` until termination/reap even though the task is already terminal. Later provider output, process callbacks, or stale signals cannot reopen the task.

Binding currentness ends at commit. Exact `DispatchCleanupRequested` and command-process cleanup signals perform bounded post-commit work and cannot fail the cancellation transaction.

## Human-request routes

`GET /control/tasks/{task_id}/human-requests` returns chronological typed source records with terminal resolution/provenance when present.

`POST /control/tasks/{task_id}/human-requests/{request_id}/resolve` accepts typed item responses for the exact open request. Answer and timeout compete on request status; one terminal transition wins.

The synchronous transaction terminalizes the request and clears only its matching wait. The response returns that committed resolution without waiting for successor materialization, D2 commit, provider start, or any acknowledgement. A typed `HumanRequestTerminal(request_id)` signal independently routes legal continuation after commit.

Timeout and cancellation are controller-owned terminal paths, not caller-selected answer kinds. Historical/stale requests cannot resolve or redirect current work.

## Command-run routes

List/detail/log routes expose the command source state owned by the command contract:

```text
pending_start | running | cancellation_requested | succeeded | failed | timed_out | cancelled | abandoned
```

Detail identifies the exact `run_id`, task/source dispatch, assignment/attempt, command policy, timing, ownership revision, normalized terminal result/provenance, and bounded log refs. Raw logs remain behind the authorized log route.

`abandoned` is terminal and carries sanitized `failure_code = command_ownership_lost`. It means restart lost exact ownership after a possible launch; it neither proves process exit nor permits blind relaunch or termination.

`POST .../{run_id}/cancel` records intent only for an exact current nonterminal run. `cancellation_requested` remains nonterminal until the process owner proves termination and reap. `CommandRunCancellationRequested(run_id, ownership_revision)` wakes that owner after commit; the HTTP response does not wait for it, a successor dispatch, or provider start.

Run ID identifies the source; its stored source dispatch/lineage is reread before any terminal or continuation transition. A stale callback cannot continue a newer lineage.

## Failure contract

Mutations use a shared structured failure:

```yaml
OperationFailure:
  code: string
  summary: string
  retryable: boolean
  suggested_next_step: string | null
```

Currentness, stale source, conflict, invalid transition, capability, task scope, local transport admission, path, and shape errors have distinct normalized codes. Responses exclude raw provider exceptions, credentials, process environment, binding material, and stack traces.

## Required invariants

- current reads expose only `starting`/`open` current authority and `starting|open|closed` history;
- current and trace reads expose both independent capability effective/source objects without provider configuration or credentials;
- provider-start retries show attempt count without a fake maximum;
- Node activity is not labeled semantic progress;
- optional assignment work plans do not gate execution;
- exact explicit provider selection never appears as fallback;
- pause/cancel return after controller commit and never wait for provider stop;
- continue awaits D2+refs commit but not provider start;
- human resolution returns independently of successor opening;
- command cancellation remains nonterminal until process termination/reap;
- events, signals, sessions, and support projections never replace source-row currentness;
- local operator writes use `local_operator` provenance without asserting human authentication; and
- no global operator API key, browser credential bootstrap, or callback HTTP authority exists in the V2 API.

## Related contracts

- [Task event stream](task-event-stream.md)
- [Controller contract and resumable execution](../architecture/controller-contract-and-resumable-execution.md)
- [Runtime records and control state](../architecture/runtime-records-and-control-state.md)
- [Runtime lifecycle and watchdog](../architecture/runtime-lifecycle-and-watchdog.md)
- [Work plan and checkpoint contract](../architecture/work-plan-and-checkpoint-contract.md)
- [Human request and approval contract](human-request-and-approval-contract.md)
- [Command run and external wait](../architecture/command-run-and-external-wait.md)
- [Capability, security, and audit](capability-security-and-audit.md)
