# Runtime lifecycle and watchdog

Status: Target

This page owns V2 asynchronous runtime effects, exact-source routing, dispatch start retry, admitted-call activity, watchdog recovery, and process-lifetime ownership. Source transactions and relational fields are owned by [Runtime records and control state](runtime-records-and-control-state.md).

## Core rule

Controller truth changes synchronously in the operation that owns the concept. The asynchronous runtime handles only work that must occur after that commit or depends on elapsed time or an owned OS resource.

The runtime never waits for provider output, final response, drain, or termination to decide whether a controller operation succeeded.

## Sync and async ownership

| Cause | Synchronous authoritative transaction | Asynchronous exact-source work |
| --- | --- | --- |
| task/flow start | persist runnable flow and root source | materialize and conditionally create root dispatch |
| accepted boundary | persist boundary and close D1 | materialize and conditionally create D2 |
| admitted Node MCP call | refresh exact dispatch activity revision once | register the new exact watchdog deadline |
| open human request | persist request + wait and close D1 | register exact request deadline only |
| terminal human request | terminalize request and clear matching wait | materialize and conditionally create D2 when runnable |
| start command run | persist run + wait and close D1 | launch and supervise exact run |
| terminal command run | terminalize run and clear matching wait | materialize and conditionally create D2 when runnable |
| watchdog due | none before due handler | materialize, then atomically close D1 + create D2 or pause on cap |
| operator pause | persist pause intent and close current dispatch authority | exact dispatch cleanup only; active external source survives |
| task cancel | persist terminal intent, close current authority, and terminalize sources as owned | exact dispatch, live-process, and already-expired transient cleanup signals |
| operator continue | directly await validation, materialization, and run+D2 commit | provider start only |
| D2 committed `starting` | none | validate refs, create binding, invoke provider, retry if needed |

The source call returns after its own transaction. It does not wait for the listed asynchronous work or an acknowledgement.

## Lifespan-owned components

The main FastAPI lifespan owns one instance of each runtime resource:

```text
FastAPI lifespan
  RuntimeEffectRouter
  DeadlineScheduler
  CommandProcessOwner
  provider adapter resources
  managed and compatibility Node MCP applications
  SupportProjectionOwner
```

`RuntimeEffectRouter` centralizes typed dispatch but does not centralize domain decisions. Each route calls a small handler owned by the exact source concept.

`DeadlineScheduler` stores in-memory generations for sleeping efficiently and emits typed due signals. Durable UTC due values remain in source records. It is not a task scanner.

`CommandProcessOwner` owns command OS resources, pipe consumption, cancellation, termination, and reap. Provider output consumption is not part of this owner.

`SupportProjectionOwner` materializes operator/readback projections after commits. Its work cannot make a controller transition eligible and is not the request-file materialization required before D2.

Support projections may reuse the same lifespan, queue, logging, and exact-source utility patterns, but they keep their own exact source/generation signal family and process-local health domain. They add no projection authority or status table. They are not `RuntimeEffectRouter` control routes and cannot open/close a dispatch, clear a wait, start a provider, or refresh watchdog activity.

Mounted MCP application lifespan contexts are explicitly entered by the main lifespan. Callers do not manually pair application-level `start()` and `close()` calls.

## Typed signal model

The complete runtime-control signal family is:

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

Every signal carries one natural source ID and only the generation/due value needed for staleness. Handlers derive task, flow, assignment, attempt, node, provider, policy, and file truth from fresh database reads.

Signals are disposable scheduling hints. They are not durable requests, acknowledgements, idempotency keys, event-stream rows, or controller authority.

An in-process enqueue either succeeds promptly or fails runtime health visibly; callers never wait for the signal's handler result. A process crash after source commit but before enqueue is the one accepted loss window and is repaired by the bounded startup audit. The runtime does not silently drop a rejected enqueue while remaining healthy.

## Handler paradigm

Every handler follows the same small pattern:

```text
receive exact signal
  -> open a fresh AsyncSession
  -> load exact source and minimum linked rows
  -> reject consumed, stale, paused, terminal, or otherwise ineligible state
  -> perform preparatory file/process work outside the final transaction
  -> repeat every authoritative predicate in one short conditional write
  -> commit one legal winner or observe zero affected rows
  -> publish only the next exact signal after commit
```

No `AsyncSession` is shared across asyncio tasks. No handler hydrates a complete task projection merely to answer its source-specific question.

The runtime does not hide effects in an `AsyncSession.commit()` override. The owning service commits explicitly and then explicitly publishes its typed signal.

### Minimum reads by route

Handlers do not begin from a task aggregate. They load the exact source first and join only facts required for that route:

| Signal/route | Required durable reads before its conditional action |
| --- | --- |
| flow start | exact flow/root source, root assignment/attempt basis, current-dispatch existence, render/provider-route inputs |
| accepted boundary | accepted boundary, source D1 and successor field, flow status/current pointer, routed assignment/attempt, exact checkpoint/trigger/render inputs |
| human opened/due | exact request status, immutable due/default policy, matching flow wait only when terminalizing |
| human terminal | exact terminal request, source D1/successor field, flow/wait/current status, same assignment/attempt and render inputs |
| command pending/due/cancel/exit | exact run request/state/due/ownership revision plus the minimum workspace/process-policy facts; flow/wait only for terminalization |
| command terminal | exact terminal run, source D1/successor field, flow/wait/current status, same assignment/attempt and render inputs |
| dispatch cleanup | exact closed dispatch/provider route plus process-local binding/adapter handle keyed by dispatch ID |
| transient cleanup | exact expired localization ID and expiry generation, task root, localized logical path, and existence of any active reference to that path |
| watchdog deadline change | no task aggregate; monotonic in-memory replacement by exact dispatch/revision/due key |
| watchdog due | exact D1, activity revision/deadline, flow current/runnable state, existence of D1-owned human/command source, recovery lineage, and render inputs |
| dispatch start | exact current D2, provider-start revision/due, committed request refs, resolved provider route, workspace, capability/tool exposure |
| support projection | exact committed source ID and projection revision plus only the read-model rows that projection owns |

The support variants and generations are frozen by the task-root owner. Startup pages their durable source rows and idempotently republishes every desired projection, including already-present files. It does not scan the filesystem to decide what controller truth ought to exist and does not start a periodic reconcile loop.

Renderer input may require several controller rows, but it is a purpose-built prompt snapshot query, not the broad runtime/task read model used by API or console. Preparatory reads are repeated as exact predicates in the final write whenever they affect legality.

The single router owns queue dispatch, lifecycle, error isolation, and health. Each route function owns one concept question; it does not automatically open unrelated dispatches except where that exact source's contract says continuation is its next effect.

### Source ownership direction

The target source layout keeps the cross-domain mechanism thin and the decisions domain-owned:

```text
runtime/post_commit/
  router.py          # typed queue dispatch and health only
  deadlines.py       # exact-key timer registration and due publication

runtime/dispatch/
  materialize.py     # immutable request-pair preparation
  start.py           # one starting-dispatch provider question

runtime/boundary/
  continuation.py

runtime/human_request/
  deadline.py
  continuation.py

runtime/command_run/
  process_owner.py
  continuation.py

runtime/watchdog/
  recovery.py

runtime/projection/  # separate support/readback effects
```

The filenames are steady-state ownership guidance, not permission to keep a second broad worker beside them. Transport modules call owning domain services; they do not contain these transitions.

## Ordinary successor opening

Boundary, human terminal, command terminal, root, and directly awaited continue handlers first mint a prospective `dispatch_id`, render/publish its canonical request pair, and then perform one final transaction that:

1. rereads or conditionally matches the exact committed source;
2. proves the flow is runnable and the source has no successor;
3. proves the expected predecessor/current pointer has not changed;
4. inserts D2 in `starting` plus its refs-only request row;
5. records the source consumption/successor identity; and
6. replaces current dispatch authority.

Only a committed D2 emits `DispatchStartDue`. A losing opener may leave an unreferenced file pair but never invokes a provider.

Nonterminal human-request and command-run opening never creates D2. Only their later terminal source can authorize continuation.

## Transition-preparation failure

Known deterministic failure before D2—unsupported/disabled route, invalid controller relationship, unsafe request path, or request materialization failure—performs zero provider I/O.

For an automatic exact-source route, one short conditional transaction proves the source is still current/runnable, pauses the flow with `runtime_transition_failed`, and leaves the source without a successor so operator continue can consume it after repair. For watchdog, that transaction also closes the still-current stale D1 with `control_failed`; it never leaves a paused flow with active dispatch authority. Direct operator continue returns the structured failure and preserves the existing paused state instead of committing a second pause.

Unexpected infrastructure exceptions that cannot be classified safely fail runtime health and leave source truth recoverable; they do not guess a controller transition.

## Watchdog recovery

Watchdog uses `WatchdogDue(dispatch_id, activity_revision, due_at)`. The handler first proves a plausible candidate, publishes the prospective D2 request pair, then enters one final transaction that repeats all checks and atomically:

- proves D1 is the current `open` dispatch;
- proves the flow is runnable;
- matches the exact activity revision and due time;
- proves the stale deadline is reached;
- proves D1 owns no human-request or command-run source, including a terminal but unrouted source;
- proves the same-attempt recovery cap is not exhausted;
- closes D1 as watchdog-superseded; and
- creates D2 in `starting` with refs and the same assignment/attempt.

If another operation wins during materialization, the final write affects zero rows and the handler performs no provider work.

If the configured same-attempt watchdog cap is exhausted, the final transaction closes D1 with `control_failed`, pauses the flow with `runtime_recovery_exhausted`, and creates no D2. The default cap is two replacements.

The target runtime settings are `watchdog_inactivity_timeout_seconds`, default `900` (15 minutes), and `watchdog_same_attempt_replacement_limit`, default `2`. There is no watchdog poll interval, bootstrap-only timeout, per-tick work limit, auto-recover toggle, or separate execution-stale threshold.

Before a winning watchdog D2 starts, the dispatch starter makes one bounded adapter stop attempt for D1. A successful return proves stopped/not-running. Unsupported, failed, or timed-out stop does not block D2 start.

## Node activity clock

Each current dispatch stores:

- `adapter_started_at` when provider start is positively accepted;
- `last_node_activity_at`; and
- monotonic `node_activity_revision`, initially zero.

Every authenticated and admitted exact-current Node MCP invocation sets the timestamp from the controller clock and increments the revision once. This includes reads, accepted no-ops, and normalized domain failures after admission.

Malformed transport, failed binding authentication, wrong task/dispatch, stale authority, role/capability denial, or other pre-admission rejection does not refresh activity. Provider output and provider terminal state never refresh it.

The watchdog deadline is:

```text
max(adapter_started_at, last_node_activity_at ?? adapter_started_at)
  + watchdog_inactivity_timeout_seconds
```

Only `open` dispatches have a watchdog deadline. `starting` dispatches are governed by provider-start retry instead. The maximum prevents an admitted call made during the `starting` handoff from producing a first-open deadline earlier than positive adapter acceptance.

After activity commits, `WatchdogDeadlineChanged(dispatch_id, activity_revision, due_at)` asks the scheduler to replace the in-memory due generation. The scheduler never lets an older revision overwrite a newer one. A due signal carrying the old revision or due time loses at the final conditional write.

## Provider start

`DispatchStartDue` answers one question for one current `starting` dispatch. It:

1. matches `provider_start_revision` and due time;
2. loads the committed request refs;
3. validates logical paths, containment, file type, and readability;
4. reads the exact instruction and input bytes;
5. resolves the committed provider route and effective tool exposure;
6. creates a fresh `DispatchMcpBinding` for managed routes, or selects the compatibility connection for OpenClaw;
7. invokes the adapter; and
8. conditionally records acceptance or the next retry on the same D2.

The starter never renders, publishes, repairs, substitutes, or hashes request files. A same-D2 retry rereads the same bytes.

Deterministic missing, escaped, unreadable, or wrong-dispatch refs cause zero provider I/O. A short conditional transaction closes the still-current `starting` D2 with `control_failed`, clears current authority, and pauses the flow with `runtime_transition_failed`.

## Provider-start retry

Provider connection, authentication, availability, timeout, explicit start failure, and uncertain acceptance are retriable. The dispatch remains `starting` indefinitely until accepted or a separate controller action closes it.

Retry delay is exponential from `dispatch_launch_retry_initial_backoff_seconds` (default one second) and capped by `dispatch_launch_retry_max_backoff_seconds` (default 30 seconds). There is no maximum attempt count and no provider-start exhaustion pause.

The persisted retry facts are:

- monotonic `provider_start_revision`;
- `provider_start_attempt_count`;
- `next_provider_start_at`;
- `provider_start_retry_kind = initial | definite_failure | uncertain_acceptance`; and
- sanitized `provider_start_last_error_code`.

An uncertain attempt includes adapter acceptance followed by an unconfirmed controller write, transport ambiguity after invocation, or startup recovery of a `starting` dispatch for which an earlier call may have occurred.

Any nonaccepted managed attempt revokes its just-issued binding before it can be retained for retry. For definite failure, the starter records/schedules the retry directly. For uncertain acceptance, it also makes one bounded `stop(dispatch_id)` call when supported before the next attempt. The next attempt creates a fresh binding and starts the same D2. Stop failure does not create a fence state or prevent retry.

An accepted start conditionally moves a still-current D2 to `open`, sets `adapter_started_at`, clears due/retry metadata, and registers the first watchdog deadline. If the provider already used its managed/compatibility Node authority to close D2 before the acceptance write, the write affects zero rows; the starter performs cleanup only and neither reopens nor retries that dispatch.

## Command deadlines and process ownership

Human due handling changes only the exact open request whose immutable `due_at` still matches. Human answer and timeout compete on source status; one terminal transition wins.

Command launch, exit, timeout, and cancellation compete on the exact run and ownership revision. `cancellation_requested` is nonterminal until the process has terminated and been reaped. A process callback cannot reopen or continue a stale lineage.

Consuming command stdout/stderr prevents child-process pipe blockage and feeds bounded command logs. It is not provider drain.

Restart never blindly relaunches a command process whose ownership is ambiguous. The command owner first classifies the durable run and any locally provable process state according to the command-run contract.

When exact ownership cannot be proved after a possible launch, the command owner terminalizes that source as `abandoned` with `command_ownership_lost`, clears only the matching wait, and publishes the ordinary command-terminal signal. It does not blindly relaunch or terminate the process.

## Pause, cancel, and cleanup

Pause and task cancel commit controller truth first. Current dispatch authority becomes invalid immediately through database currentness, even if a process-local binding has not yet been removed.

Provider stop and process cleanup are post-commit best effort. They cannot delay, reverse, or fail the pause/cancel transaction.

An active human request or command run survives ordinary pause. Its terminal result may commit while paused but cannot open a successor until an explicit legal continue consumes it.

Task cancel terminalizes/cancels matching sources as owned, requests process termination, and never opens a successor.

Transient cleanup never invents retention policy or expires an active row. Task cancel discovers only scalar IDs and expiry generations for rows already committed as `expired`, then publishes one exact `TransientCleanupRequested` per row after the cancel transaction. The handler rereads `transient_localization_id + expires_at`, removes only a regular body under `tmp/transfers/localized/`, conditionally records `removed + removed_at`, and republishes the transient support projection. A duplicate or stale generation is a no-op. A cleanup failure may leave an expired body, but it cannot delete an active body, committed artifact, request file, or external workspace content.

## Startup recovery

Before accepting runtime work, lifespan startup exhausts bounded indexed pages for:

1. runnable flows with no root dispatch;
2. accepted boundaries whose source dispatch has no successor;
3. terminal human requests or command runs whose successor is absent;
4. open human requests with future or overdue deadlines;
5. command runs pending launch, running, or cancellation-requested;
6. current `starting` dispatches, treating any possibly attempted start as uncertain;
7. current eligible `open` dispatches and their watchdog deadlines; and
8. expired transient localizations and other paused or terminal rows needing resource cleanup only.

Each discovered row emits or registers the same exact signal used during normal operation. A recovered `open` managed dispatch receives only its existing watchdog registration; startup does not recreate its lost binding or blindly start another provider. Startup does not run a special whole-task reconciler.

An explicit safety ceiling must be high enough to exhaust each family. Hitting it fails runtime health rather than silently leaving work undiscovered.

## Failure isolation and health

- one handler failure is logged with exact source identity and leaves durable truth recoverable;
- a deterministic domain failure records its owned outcome instead of crashing the router;
- repeated transient provider failures reschedule the same D2;
- support-projection failure cannot change controller currentness;
- unexpected router, scheduler, or command-owner death fails runtime health; and
- shutdown cancels sleepers, revokes bindings, and performs bounded resource cleanup without rewriting committed state.

## Required race outcomes

| Race | Required result |
| --- | --- |
| duplicate boundary signals | one successor; later signals no-op |
| human/command open vs watchdog | the current D1 conditional transition chooses one; loser creates no source/successor |
| terminal wait vs delayed watchdog | source row keeps watchdog ineligible until continuation consumes it |
| human answer vs timeout | one terminal request status wins |
| command exit vs timeout/cancel | one terminal run status wins after process rules |
| activity vs watchdog due | new revision makes old due signal stale |
| pause vs source terminalization | both facts may persist; paused flow prevents successor |
| pause vs watchdog | runnable/current predicates choose one legal result |
| continue vs cancel | flow terminal/control revision predicates choose one |
| Node boundary/wait during provider-start handoff | the admitted operation may close current `starting` D2; late start acceptance cannot reopen or retry it |
| duplicate provider start | in-process coalescing plus revision; uncertain repeat revokes/stops/retries same D2 |
| two terminal continuation signals | one-successor constraint chooses one |

## Removed target machinery

- broad post-commit task discovery and whole-task reconciliation;
- steady-state watchdog or dispatch-open polling;
- `LocalRuntimeSupervisor` and `AgentControlManager` as domain owners;
- provider call semaphore/pool;
- generic ready/open request, ACK, outbox, or idempotency table;
- broad per-task execution-slot lock;
- shared `AsyncSession` across concurrent handlers;
- hidden side effects in `AsyncSession.commit()`;
- `closing` state or wait-for-stop fence;
- provider output/drain/terminal progression;
- finite six-call provider-start exhaustion; and
- provider start rendering or repairing request files.

## Framework basis

These primary references guide implementation without overriding this product contract:

- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) for one application-owned resource lifecycle;
- [SQLAlchemy session concurrency model](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#is-the-session-thread-safe-is-asyncsession-safe-to-share-in-concurrent-tasks) for one `AsyncSession` per concurrent task; and
- [SQLAlchemy asyncio guidance](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks) for explicit concurrent-session ownership.

## Related

- [ADR-0009: exact-source runtime control](../../../adr/ADR-0009-exact-source-runtime-control.md)
- [Runtime records and control state](runtime-records-and-control-state.md)
- [Controller contract and resumable execution](controller-contract-and-resumable-execution.md)
- [Managed Node MCP binding](managed-node-mcp-binding.md)
- [Minimal provider adapter contract](adapter-contract.md)
- [Human request and approval contract](../interfaces/human-request-and-approval-contract.md)
- [Command run and external wait](command-run-and-external-wait.md)
