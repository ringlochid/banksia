# Current runtime control plane

Status: Current

Last verified: 2026-07-19

AutoClaw stores control truth in its database. Providers execute work, but provider output, provider termination, queues, and generated files do not decide runtime state.

## Controller truth

The database records tasks, compiled flows, nodes, assignments, attempts, dispatches, prompt references, capability sets, boundaries, decisions, human requests, command runs, waits, work plans, checkpoints, artifacts, transients, and task events.

An operation changes a task only through these records. Read models and task-root files are derived support surfaces.

## Commit first, continue after

Task start, a returned boundary, a human request, a command run, and an expired deadline each commit an explicit source record. The request returns according to that source operation; it does not wait for a provider to stop or produce a final response.

An in-process signal wakes the matching handler after commit. The signal is only a hint. The handler opens a fresh database session, rereads the exact source, checks that it is still current, and performs one short conditional transition.

Duplicate or stale signals are harmless:

- one handler wins the conditional write
- later handlers see completed or stale truth and do nothing
- database constraints prevent more than one current dispatch for a flow

Startup audits committed exact-source work, so a lost in-memory wakeup does not strand durable work.

## Successor dispatches

The continuation source identifies the dispatch or wait it came from. A handler opens a successor only when that source is still the current eligible source and every concept-specific rule is satisfied.

The handler publishes the immutable dispatch request pair before the final database transaction. It then closes the old dispatch when required and commits the successor dispatch as the current starting dispatch. This keeps the controller transition atomic without holding a long task-wide lock.

Boundary behavior remains concept-specific:

- a parent yield advances to the accepted child assignment
- worker green returns control to the parent or completes the root flow
- worker retry creates the next attempt for the same assignment
- blocked and released outcomes follow their existing release rules
- pause and cancel prevent ordinary successor opening

## Provider start

Only a committed current starting dispatch may call a provider adapter. The starter checks that exact dispatch, creates a process-local dispatch-scoped Node MCP binding, and calls the configured adapter. After provider acceptance, it conditionally commits the still-current dispatch as `open` with its acceptance time. The binding itself is never a database record.

If the acceptance write or commit raises, AutoClaw rereads the exact dispatch and provider-start generation in a fresh session. When that read proves the dispatch already committed as accepted, the process-local binding stays active. Otherwise the starter revokes it and follows the uncertain-start retry path.

Pre-acceptance start failures retry indefinitely with bounded backoff from one second up to thirty seconds. A later retry first checks currentness. There is no provider-result drain, provider-stop wait, or provider-output success path.

Codex and Claude are managed adapters. OpenClaw is an experimental, explicitly selectable adapter that uses user-managed compatibility configuration. OpenClaw may be the default provider; its experimental label does not disable it.

## Human and command waits

Opening a human request or command run commits the source row, its wait, and the closure of the current dispatch together. No successor is eligible while that wait remains active.

A terminal human response or command result clears only its matching wait. Its after-commit handler then applies the same exact-source winner-or-no-op rule before opening the successor.

Command execution has one additional asynchronous owner. It starts the process, captures bounded logs, handles cancellation and timeout, reaps the process, and commits the terminal command result. Process state is not used as controller truth until that commit.

## Watchdog

The default inactivity deadline is fifteen minutes. Admitted Node MCP calls record dispatch activity. A deadline signal carries the exact dispatch and observed activity revision; the handler rereads both before acting.

The watchdog does nothing when:

- the dispatch is no longer current or open
- activity advanced after the signal was scheduled
- the deadline is not due
- the dispatch owns a human-request or command-run source, including a terminal source not yet routed
- the task is paused, cancelled, or otherwise ineligible

When the dispatch is still stale, one transaction closes it and opens a same-attempt replacement. After two same-attempt replacements, the watchdog pauses the flow for recovery instead of opening another dispatch.

The watchdog is deadline-driven. It does not poll provider output and does not wait for provider shutdown.

## Lifespan and support work

FastAPI lifespan owns the effect router, deadline scheduler, command-process owner, support-projection owner, provider adapters, and MCP binding registry. Startup initializes and audits them; shutdown closes them.

Support projections run separately from runtime transitions. A projection failure may leave a readback file missing, but it cannot change dispatch eligibility or controller state.

## Evidence

- `apps/api/src/autoclaw/runtime/post_commit/`
- `apps/api/src/autoclaw/runtime/dispatch/`
- `apps/api/src/autoclaw/runtime/watchdog/`
- `apps/api/src/autoclaw/runtime/human_request/`
- `apps/api/src/autoclaw/runtime/command_run/`
- `apps/api/src/autoclaw/runtime/providers/`
- `apps/api/src/autoclaw/main.py`
- `apps/api/tests/integration/runtime/`
- `apps/api/tests/e2e/`
