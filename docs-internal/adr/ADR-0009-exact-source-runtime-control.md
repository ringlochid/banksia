# ADR-0009: exact-source runtime control

Status: Accepted

## Decision summary

AutoClaw V2 uses one lifespan-owned, signal-driven runtime effect router whose handlers answer small questions about exact committed sources. Boundary, wait, pause, cancel, and other controller mutations commit synchronously in their owning transaction. Work that must happen after that commit—successor opening, deadlines, command-process supervision, watchdog recovery, provider start, and support projection—is asynchronous and source-specific.

The controller selects transition winners through fresh reads, short conditional writes, and database constraints. It does not take a broad per-task execution lock, poll all runnable tasks, or wait for provider output, drain, or termination before accepting a controller boundary.

## Context

ADR-0007 correctly made committed Node MCP operations controller truth and rejected provider output as completion truth, but it centralized runtime behavior in a large supervisor with a generic provider-control state machine, semantic-only progress, mandatory worker plans, stop fencing, and finite six-call provider retry. The shipped post-commit worker likewise discovers broad task state and reconciles several concepts at once.

That shape is larger than the target local runtime requires. Each durable cause already has a natural exact identity: a source dispatch, human request, command run, watchdog activity generation, or starting dispatch. The target can route those identities directly and let each concept owner prove its own legality from fresh database truth.

## Decision

### Synchronous controller truth

The transaction that accepts a Node MCP or operator boundary owns every authoritative row change needed to make that boundary true.

- an accepted boundary persists its result and closes D1 before the MCP response returns;
- opening a human request or command run persists the exact source and wait and closes D1 before the MCP response returns;
- human-request and command-run terminalization persists the exact source result and clears only its matching wait;
- pause and cancel persist controller intent and revoke current dispatch authority immediately; and
- task or flow start persists the durable source that may later authorize the root dispatch.

Those calls return after their transaction commits. They do not wait for an async handler, successor dispatch, request materialization, provider start, provider completion, or acknowledgement.

### Typed after-commit signals

After commit, the owner publishes a disposable typed scheduling hint. The target signal family is:

```text
FlowStartCommitted(flow_id)
BoundaryAccepted(source_dispatch_id)
HumanRequestOpened(request_id)
HumanRequestDue(request_id, due_at)
HumanRequestTerminal(request_id)
CommandRunPending(run_id)
CommandRunDue(run_id, due_at)
CommandRunCancellationRequested(run_id, ownership_revision)
CommandRunTerminal(run_id)
CommandProcessExited(run_id, ownership_revision)
DispatchCleanupRequested(dispatch_id)
TransientCleanupRequested(transient_localization_id, expires_at)
WatchdogDeadlineChanged(dispatch_id, activity_revision, due_at)
WatchdogDue(dispatch_id, activity_revision, due_at)
DispatchStartDue(dispatch_id, provider_start_revision, due_at)
```

Signals contain the exact natural source plus only the generation or due value needed to reject a stale timer. They do not copy task, flow, assignment, attempt, node, provider, projection, or capability truth. There is no generic open-dispatch request, durable ACK, outbox, or runtime idempotency table.

### Runtime components

One main FastAPI lifespan owns:

- the `RuntimeEffectRouter` and its typed in-memory queue;
- a small deadline scheduler for human, command, watchdog, and provider-start due keys;
- the command-process owner for launch, pipe consumption, cancellation, termination, and reap;
- provider adapter resources and the managed Node MCP application; and
- the support-projection owner as a separate failure domain from controller transitions.

Callers do not manually pair public `start()` and `close()` calls. Unexpected death of an authoritative owner fails runtime health visibly instead of being logged and swallowed.

Each concurrent handler owns a fresh SQLAlchemy `AsyncSession`. It loads the exact source and minimum linked rows, performs any preparatory file work outside the final transaction, then uses a short conditional write. A session is never shared across concurrent tasks.

### Winner and loser model

Contested operations recheck exact currentness and concept-specific predicates at their authoritative write. Zero affected rows means another operation won. The loser returns a no-op or a stable conflict after the minimum reread needed by its caller.

Database constraints backstop the model:

- one root dispatch per flow;
- one successor per predecessor;
- at most one `starting` or `open` dispatch per flow;
- immutable predecessor and successor identity after commit; and
- natural-source uniqueness for accepted boundaries, human requests, command runs, and other owned source rows.

This prevents duplicate controller successors. It does not promise exactly-once provider effects. An old provider execution may overlap physically with a retry or successor, but stale bindings and fresh Node MCP admission prevent it from changing current controller truth.

### Request materialization and successor opening

Before committing a candidate D2, the exact-source handler publishes:

```text
_runtime/dispatch/<dispatch_id>/instructions.md
_runtime/dispatch/<dispatch_id>/input.md
```

The final conditional transaction creates D2 in `starting`, creates its refs-only request record, consumes the exact source when applicable, and replaces current authority. It never commits D2 before both files are published and readable. A losing candidate may leave unreferenced cleanup files but causes no provider I/O.

Ordinary boundary, terminal human-request, terminal command-run, root-start, and operator-continue paths use this materialize-then-conditionally-open sequence. Watchdog recovery is the deliberate exception: it materializes first and then atomically closes D1 and creates D2 in one final transaction.

Support and observability projections are different. They are post-commit readbacks and never block D2 or become provider-request authority.

### Provider start and retry

`DispatchStartDue` rereads one current `starting` dispatch and its committed request refs. Missing, unreadable, escaped, or otherwise invalid refs cause zero provider I/O; the handler conditionally closes that still-current dispatch and pauses the flow with `runtime_transition_failed`.

Provider connection, authentication, availability, timeout, start rejection, and uncertain acceptance do not pause the flow or create another dispatch. The same D2 remains `starting` and retries indefinitely with exponential delay using the configured one-second initial delay and 30-second maximum delay. The 30 seconds is a retry-delay cap, not a provider drain or stop window.

The dispatch persists only a monotonic provider-start revision, attempt count, next due time, retry kind, and sanitized last error code. There is no finite start-attempt budget or provider-start exhaustion state.

Every nonaccepted managed start attempt revokes its binding before retry. After uncertain acceptance, the runtime additionally makes one bounded `stop(dispatch_id)` call when the adapter supports it, then retries the same D2 with a fresh binding. A successful stop return proves that execution stopped or was already absent. Unsupported, failed, or timed-out stop does not block retry; that residual overlap is an adapter limitation, not a controller state.

A provider may call Node MCP during the start handoff while D2 is still `starting`. If that admitted operation lawfully closes D2 before the adapter acceptance write, the late write loses currentness, performs cleanup only, and never reopens or retries the closed dispatch.

Normal boundaries and legal human or command waits never call provider stop. Provider stdout, final response, EOF, terminal status, drain completion, and continuity identifiers do not advance controller truth, refresh watchdog activity, or delay a source response.

### Activity and watchdog

Each admitted current Node MCP invocation updates `last_node_activity_at` and increments `node_activity_revision` exactly once, including reads, accepted no-ops, and normalized domain failures. Authentication, scope, currentness, and capability rejection do not update it. The after-commit `WatchdogDeadlineChanged` hint replaces only an equal/newer exact scheduler generation; an older hint cannot erase a newer timer.

The watchdog deadline is `max(adapter_started_at, last_node_activity_at ?? adapter_started_at) + watchdog_inactivity_timeout_seconds`. Only `open` dispatches are eligible. The maximum keeps a Node call admitted during the `starting` handoff from creating a first-open deadline earlier than positive adapter acceptance. The due signal contains the observed dispatch ID, activity revision, and due time, so any later admitted call makes it stale.

A watchdog candidate is ineligible whenever D1 owns a human-request or command-run source, including a terminal source that has not yet been routed. The final watchdog transaction repeats that exclusion after request materialization.

For an eligible stale D1, the handler atomically closes D1 and creates D2 on the same assignment and attempt. Before D2 provider start it makes one bounded stop attempt against D1, then starts D2 even if stop is unsupported or fails. The default same-attempt watchdog replacement cap remains two; exhaustion closes D1 and pauses with `runtime_recovery_exhausted` without creating D2.

### Recovery and polling

Startup performs a finite, paged audit of exact indexed source families: missing roots, accepted boundaries without successors, terminal waits without successors, open human deadlines, command ownership, current starting dispatches, eligible open watchdog deadlines, exact already-expired transient generations, and other cleanup-only paused or terminal resources. It exhausts those pages before declaring runtime ready.

If restart cannot prove ownership after a command may have launched, it terminalizes the durable run as `abandoned` with `command_ownership_lost`, clears only the matching wait, and uses ordinary exact-source continuation. It never blindly relaunches or terminates the process.

After startup, runtime control is signal-driven. There is no periodic broad task scan. A process crash between source commit and in-memory publication is repaired by the next startup audit.

## Consequences

- the async runtime owner is small and teachable rather than a whole-task state machine;
- concept-specific source owners retain their behavior while sharing one routing and lifecycle pattern;
- no broad lock is held across file, provider, process, or database I/O;
- provider output and termination are irrelevant to controller correctness;
- a starting dispatch may remain visibly retrying until its provider is repaired; and
- watchdog exhaustion remains the bounded infrastructure escalation path, while provider start itself remains retriable.

## Partial supersession of ADR-0007

This ADR supersedes ADR-0007's `LocalRuntimeSupervisor`, `AgentControlManager`, semantic-only `last_progress_at`, mandatory worker-plan progress, universal provider-control budget, provider-stop fencing, and provider-start exhaustion behavior.

It preserves ADR-0007's local-first scope, controller-owned runtime truth, provider-output irrelevance, provider-neutral adapter boundary, same-attempt watchdog recovery, and separation of semantic retry from infrastructure recovery.

## Alternatives rejected

### Keep the broad reconciliation worker

Rejected because it rediscovers task-wide state for causes that already have exact durable identities.

### Serialize the execution slot with one task lock

Rejected because it couples unrelated concept transitions and can hold a lock across database, filesystem, provider, process, or reconciliation work. Exact predicates and constraints are sufficient for the current one-process target.

### Add durable open/start requests and acknowledgements

Rejected for the local phase. Committed natural sources and the current `starting` dispatch already provide restart authority.

### Pause on ambiguous provider start

Rejected. The adapter owns stop/idempotency quality; the controller revokes the old binding, makes the bounded stop attempt when supported, and retries the same dispatch.

### Wait for provider stop before every successor

Rejected because a controller boundary is complete when its transaction commits. Normal progression never depends on provider shutdown.

## Canonical references

- [Runtime lifecycle and watchdog](../design/v2/architecture/runtime-lifecycle-and-watchdog.md)
- [Runtime records and control state](../design/v2/architecture/runtime-records-and-control-state.md)
- [Controller contract and resumable execution](../design/v2/architecture/controller-contract-and-resumable-execution.md)
- [Minimal provider adapter contract](../design/v2/architecture/adapter-contract.md)
- [Command run and external wait](../design/v2/architecture/command-run-and-external-wait.md)
- [Human request and approval contract](../design/v2/interfaces/human-request-and-approval-contract.md)
