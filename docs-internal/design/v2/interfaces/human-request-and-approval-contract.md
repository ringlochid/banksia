# Human request and approval contract

Status: Target

This page owns the typed human-request source, the atomic external-wait transition, deadline behavior, terminal resolution, and same-attempt continuation. Human requests are controller concepts, not provider-native permission prompts or conversational questions.

## Core rule

A managed agent intentionally opens a human request through Node MCP when its effective capability allows the requested kind. Opening succeeds only when the source row, matching wait, and D1 closure commit atomically.

The MCP response returns after that commit and instructs the current provider turn to stop. It does not wait for deadline registration, a human response, successor opening, provider stop, provider completion, or an async acknowledgement.

## Request kinds

The target kinds are:

- `input` for typed information required to proceed;
- `direction` for a bounded decision among described paths;
- `approval` for explicit authorization of a controller-described action; and
- `review` for a bounded human assessment of supplied evidence.

Kinds do not inherit provider-native approval UI, permission modes, or hidden interactive prompts. Provider-native interaction is configured noninteractively by provider policy.

## Node operation

Conceptually:

```text
open_human_request(request) -> HumanRequestOpenResult
```

Managed schemas contain only the semantic request. The compatibility projection adds required full `task_id` and `dispatch_id` selectors.

The request contains:

```yaml
kind: input | direction | approval | review
summary: bounded operator-facing purpose
items:
  - id: stable item id
    prompt: bounded question or review request
    response_schema: typed schema or bounded option set
context_refs: optional bounded logical refs
timeout:
  due_at: timestamp | null
  default_behavior: bounded policy | null
suggested_human_instruction: optional bounded text
```

Every field is strict and bounded. Context uses logical refs instead of copying large artifacts, raw command logs, or provider output.

## Source record

The authoritative source binds:

```yaml
human_request:
  request_id: string
  task_id: string
  flow_id: string
  assignment_id: string
  attempt_id: string
  source_dispatch_id: string
  kind: input | direction | approval | review
  request: typed body
  due_at: timestamp | null
  default_behavior: bounded policy | null
  status: open | resolved | timed_out | cancelled
  opened_at: timestamp
  terminal_resolution: typed resolution | null
  successor_dispatch_id: string | null
```

The request is bound to its source dispatch, not merely to a task or provider session. Historical requests remain readable but cannot own current wait or continuation.

## Open legality

Before mutation, the operation proves:

- managed binding or compatibility selectors resolve exact current D1;
- flow, assignment, attempt, and node are current and runnable;
- effective policy allows the request kind;
- no human request or command run already owns the current wait;
- D1 has no accepted boundary or successor; and
- request shape and timeout/default policy are valid.

A rejected call creates no source, wait, dispatch closure, or standalone task event. If the call passed admission before its normalized domain rejection, it still refreshes Node activity once according to the common admission contract.

## Atomic open transition

One transaction:

1. inserts the open human-request source bound to D1;
2. sets `waiting_cause = human_request` and `waiting_source_id = request_id`;
3. closes D1 with `closed_reason = human_request_wait`;
4. clears current dispatch authority; and
5. emits the bounded committed open event.

It does not create D2, create a terminal checkpoint, call `return_boundary`, pause the flow, call provider stop, or retain D1 open.

After commit, `HumanRequestOpened(request_id)` registers the immutable due time if one exists. Registration failure cannot undo the open transition; startup recovery rediscovers the exact open request.

## Resolution

The terminal resolution shape is:

```yaml
human_request_resolution:
  kind: answered | timed_out | cancelled
  item_responses: typed map | null
  policy_basis: bounded value | null
  summary: bounded continuation guidance
  resolved_at: timestamp
  resolved_by_actor_ref: string | null
  resolved_by_surface: control_api | control_ui | operator_mcp | controller
```

The ordinary answer route may submit only `answered`. Timeout and cancellation are controller-owned terminal transitions.

Answers are validated against the original item schemas/options. Resolution provenance is immutable audit truth. Generic events carry bounded summaries, not complete sensitive answers.

## Deadline

`HumanRequestDue(request_id, due_at)` reloads the exact source. It terminalizes only when status remains `open`, the stored due time equals the signal, and the controller clock reached it.

Answer and timeout use conditional source-state writes. Exactly one terminal result wins; the loser rereads and returns an idempotent/stale result.

Timeout records the configured default behavior/policy basis and a bounded summary. It does not fail the task automatically.

## Terminal transaction

Answer, timeout, and cancellation atomically:

- change the exact source to its terminal status;
- persist the typed resolution and provenance;
- clear only matching `waiting_cause = human_request` and `waiting_source_id = request_id`; and
- emit the matching bounded event.

They do not open D2 inline. After commit, `HumanRequestTerminal(request_id)` owns possible continuation.

## Continuation

The exact terminal handler loads only the request, its source D1, flow, assignment/attempt, and rows needed to prove continuation.

If the flow is runnable and the terminal source is unconsumed, it publishes the prospective D2 request pair and conditionally creates one same-assignment/same-attempt successor plus refs.

The new prompt trigger includes the original request and typed resolution once, with timeout/default behavior when relevant. Provider conversation memory is optional and never required.

If the flow is paused, the terminal source remains retained with no successor. A later legal continue may consume it. If the flow is cancelled/terminal, no successor is permitted.

Duplicate terminal signals converge through source consumption, one-successor, and current-dispatch constraints.

## Watchdog interaction

D1 remains watchdog-ineligible because it owns a human-request source, even after the source terminalizes and before continuation consumes it.

In the opening race:

- if human open wins, the source/wait and D1 close make a watchdog due signal stale and excluded;
- if watchdog wins, D1 is no longer current and the whole stale Node MCP open transaction creates no request; and
- no per-task lock is required beyond exact predicates and constraints.

## Pause and cancel

Operator pause does not cancel an open request. The human may still answer or the deadline may still fire; the result is retained without continuation.

Task cancel terminalizes/cancels the owned request as part of task cancellation policy, clears the wait, and never opens a successor.

An operator may use a dedicated request-cancel surface when authorized. That cancellation competes with answer/timeout on source status.

## Read and audit surfaces

Authorized source routes return the complete typed request and resolution. Generic task snapshot/trace/event surfaces return only bounded kind, status, summary, due/provenance, and canonical IDs.

Events include:

- `human_request_opened`;
- `human_request_resolved`;
- `human_request_timed_out`; and
- `human_request_cancelled`.

Events are chronology over committed source changes. They do not schedule deadlines or continuation.

## Required invariants

- a successful open commits source + wait + D1 close atomically;
- success leaves no current D1 binding authority;
- nonterminal open never creates D2;
- answer and timeout have one terminal winner;
- only the exact terminal source can authorize one successor;
- terminal results are retained while paused;
- watchdog skips open and terminal-unconsumed human sources;
- provider stop/output/completion and `return_boundary` are absent; and
- managed/compatibility projections preserve the same semantic contract.

## Related

- [Runtime lifecycle and watchdog](../architecture/runtime-lifecycle-and-watchdog.md)
- [Controller contract and resumable execution](../architecture/controller-contract-and-resumable-execution.md)
- [Command run and external wait](../architecture/command-run-and-external-wait.md)
- [Node MCP schema appendix](node-mcp-schema-appendix.md)
