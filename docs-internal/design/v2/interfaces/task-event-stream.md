# Task event stream

Status: Target

This page owns V2 append-only task chronology, bounded event payloads, cursor backfill, Server-Sent Events delivery, and replay/reset behavior. Source-row reads and operator mutations belong to the [Control API](control-api.md).

## Core rule

Task events describe committed controller facts in order. They are authoritative for chronology and audit-chain verification, never for currentness, operation legality, provider-start scheduling, deadlines, process ownership, or continuation.

Replaying an event never starts a provider, launches a command, opens a dispatch, fires a deadline, or reapplies a mutation.

## Event envelope

```yaml
TaskEvent:
  event_id: string
  event_seq: integer
  task_id: string
  event_type: string
  event_source: controller | control_api | operator_mcp | node
  occurred_at: timestamp
  flow_revision_id: string | null
  dispatch_id: string | null
  attempt_id: string | null
  node_key: string | null
  actor_ref: string | null
  payload: object
  prev_event_hash: string | null
  event_hash: string
```

`event_seq` is strictly increasing within one task. Payloads are bounded summaries, not source-row replacements. Provider, adapter, MCP transport, and runtime signal are not event sources.

Where practical, a source mutation and its event commit in the same database transaction. A later projection event may describe a committed source revision but cannot create it.

## Backfill and SSE

`GET /control/tasks/{task_id}/events` accepts an exclusive cursor, limit `1..500`, and optional inclusive `through_event_id` high-water mark for deterministic paging. Results are ascending by `event_seq`; cursor tokens are opaque and task-bound.

`GET /control/tasks/{task_id}/events/stream` emits standard SSE with event ID, type, and the complete event JSON. `cursor` or `Last-Event-ID` resumes exclusively; if both are present, they must identify the same event. No cursor tails from the head observed during setup.

Transport polling/notification choice and reconnects never change task state.

## Cursor reset

An invalid, cross-task, unknown, or expired cursor returns `410 Gone` with `cursor_reset_required` and a fresh snapshot route.

The client then:

1. rereads the task runtime source row;
2. rereads the snapshot;
3. rereads selected source detail when needed; and
4. reconnects after `stream_head_event_id`.

It never rebuilds current state by folding retained events.

## Minimum event catalog

```text
task_started
dispatch_opened
dispatch_start_updated
work_plan_set
work_plan_cleared
checkpoint_recorded
boundary_accepted

child_assignment_staged
child_assignment_committed
structural_revision_adopted

human_request_opened
human_request_resolved
human_request_timed_out
human_request_cancelled

command_run_opened
command_run_started
command_run_progressed
command_run_cancel_requested
command_run_succeeded
command_run_failed
command_run_timed_out
command_run_cancelled
command_run_abandoned

task_paused
task_resumed
task_cancelled
```

There is no provider-output, provider-terminal, provider-tool, provider-session, generic MCP-call, timer-signal, support-projection, or per-invocation event family.

## Task and dispatch events

`task_started` describes committed task/flow/manifest bootstrap. It does not prove provider readiness or root dispatch creation.

`dispatch_opened` is emitted with the same final transaction that creates D2 in `starting` plus its refs-only request row:

```yaml
dispatch_opened:
  dispatch_id: string
  predecessor_dispatch_id: string | null
  assignment_id: string
  attempt_id: string
  node_key: string
  status: starting
  opened_reason: root | boundary | child_return | human_result | command_result | watchdog_recovery | semantic_retry | operator_continue
  requested_provider: codex | claude | openclaw
  resolved_provider: codex | claude | openclaw
  selection_basis: explicit | default
  instructions_ref: ref
  input_ref: ref
```

This event proves neither provider acceptance nor Node activity.

`dispatch_start_updated` describes only durable start-row changes:

```yaml
dispatch_start_updated:
  dispatch_id: string
  state: retry_scheduled | accepted
  attempt_count: integer
  provider_start_revision: integer
  next_attempt_at: timestamp | null
  retry_kind: initial | definite_failure | uncertain_acceptance | null
  last_error_code: string | null
```

There is no `max_attempts`, terminal start-failure state, or generic stop operation event. Replaying retry chronology never schedules a retry. Provider-native completion or failure emits nothing.

Closing/superseding dispatch truth is visible through the event owned by its concept: boundary, external wait, watchdog successor, pause, or cancel. The target does not add a `closing` event/state while provider cleanup runs.

## Work-plan and checkpoint events

A changed nonempty assignment plan emits:

```yaml
work_plan_set:
  assignment_id: string
  revision: integer
  explanation: string | null
  steps:
    - step: string
      status: pending | in_progress | completed
  authored_by_dispatch_id: string
  updated_at: timestamp
```

Clearing an existing plan emits:

```yaml
work_plan_cleared:
  assignment_id: string
  revision: integer
  explanation: string | null
  authored_by_dispatch_id: string
  updated_at: timestamp
```

The revision is the assignment's newly incremented work-plan revision. Clearing an absent plan or submitting an identical plan is an accepted no-op and emits nothing.

Plan events are advisory chronology. They never satisfy a boundary, checkpoint, or assignment.

`checkpoint_recorded` carries bounded checkpoint identity, kind, outcome when terminal, summary/evidence refs, produced artifact/transient refs, and authoring lineage. It never copies artifact bodies or provider output.

`boundary_accepted` carries source dispatch, assignment/attempt, explicit boundary outcome, exact checkpoint/evidence ref when required, and resulting controller status. It has no provider-terminal field. D1 is already closed before the Node MCP result returns; any successor `dispatch_opened` occurs later after exact-source routing.

## Human-request events

`human_request_opened` is emitted by the same transaction that creates the request/wait and closes D1. Terminal request events are emitted by the winning answer, timeout, or cancellation transaction.

Payloads carry request ID, typed kind, title/summary, source dispatch, due/terminal timestamps, resolution kind, and bounded actor provenance. They do not inline full answers or arbitrary response payloads.

A later `dispatch_opened` may show legal continuation, but the terminal event itself neither creates nor acknowledges that dispatch.

## Command-run events

Command events carry exact run ID, source dispatch, current state, bounded command/description/workdir/timing, process ownership revision when relevant, terminal result summary, and log ref.

`command_run_cancel_requested` remains nonterminal. A concrete terminal event is emitted only after the process owner satisfies the state-specific termination/reap rules.

`command_run_abandoned` records restart-time loss of exact process ownership. Its bounded payload carries `failure_code = command_ownership_lost`; it is terminal chronology, not proof of process exit or a request to relaunch.

Raw stdout/stderr remains behind the authorized log route. Process pipe consumption does not generate provider-drain or runtime-liveness events.

## Task-control events

`task_paused` carries:

```yaml
task_paused:
  pause_reason: paused_by_operator | runtime_recovery_exhausted | runtime_transition_failed
  control_revision: integer
  actor_ref: string | null
  summary: string
```

`task_resumed` records an accepted operator continue and the new control revision. It does not mean provider reconnect, human answer, or command completion.

`task_cancelled` records terminal controller cancellation. Post-commit cleanup has no success/failure task event because it cannot change cancellation truth.

## Consumer behavior

Consumers combine current source reads, event chronology, and source-specific detail routes. They may render:

```text
Starting Claude - attempt 3
Next retry at 10:42:18
```

They must not render `3/6`, an exhausted provider-start state, a fallback provider, or provider health from these events.

## Required invariants

- order is per task and append-only;
- replay has no runtime side effects;
- every event describes committed controller state;
- provider events and individual MCP invocations are absent;
- accepted plan no-ops emit nothing but still count as admitted Node activity;
- external-wait events never replace source currentness;
- start retry events have no maximum and never own scheduling;
- post-commit provider/process cleanup emits no fake controller transition; and
- cursor reset returns to source rows rather than event folding.

## Related contracts

- [Control API](control-api.md)
- [Runtime records and control state](../architecture/runtime-records-and-control-state.md)
- [Runtime lifecycle and watchdog](../architecture/runtime-lifecycle-and-watchdog.md)
- [Work plan and checkpoint contract](../architecture/work-plan-and-checkpoint-contract.md)
- [Human request and approval contract](human-request-and-approval-contract.md)
- [Command run and external wait](../architecture/command-run-and-external-wait.md)
- [Capability, security, and audit](capability-security-and-audit.md)
