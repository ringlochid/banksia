# Recovery and observability

Status: Reference

This page owns process startup recovery, runtime-health failure domains, support projections, and protected audit readback.

## Commit first, recover by exact source

Controller mutations commit their authoritative rows before asynchronous work starts. Runtime signals are disposable scheduling hints containing one exact natural source and only the generation or deadline needed to reject stale work. Duplicate hints converge through fresh reads, conditional writes, uniqueness constraints, and immutable source relationships.

FastAPI lifespan owns the effect router, deadline scheduler, command-process owner, provider adapters, Dispatch binding registry, Node MCP applications, Operator adapter, and support-projection owner. Each concurrent handler uses a fresh database session. Provider output and filesystem projections do not drive controller transitions.

## Startup recovery

Startup verifies the exact database schema before serving work, repairs stranded Operator turns, reconciles controller-marked Task workspace admission, and exhausts bounded indexed pages for recoverable runtime sources. The audit routes the same exact signals used during ordinary operation for:

- committed Task starts and structural replan continuations;
- Wave-member and Wave settlement;
- terminal Human Requests and their deadlines;
- pending, running, cancellation-requested, and terminal Command Runs;
- current provider starts and watchdog deadlines; and
- Workflow manifest projection.

An audit pagination or publication failure prevents a healthy startup. A lost in-memory signal is therefore recoverable from committed source truth without a broad steady-state Task scan.

Provider-start recovery treats an ambiguous prior start conservatively and retries the same Dispatch with a fresh binding. Command recovery never blindly relaunches a process whose ownership cannot be proved; it records the exact terminal ownership-loss result and lets ordinary continuation handle it.

The watchdog gives each Attempt a bounded number of same-Attempt replacements between successful user Resume boundaries. Exhaustion pauses the whole Task and settles every current runnable Dispatch. Resume preserves immutable Dispatch history, resets the live replacement counter of every retained running Attempt, and then opens exact continuations. The deadline scheduler rechecks the authoritative UTC deadline when a process-local timer fires and rearms the same generation when the event loop invokes it early.

## Command process ownership

Managed Command Run owns one complete process family, not only the direct child. Linux and macOS use a small POSIX guardian with the already admitted working directory descriptor, a new process session/group, controller-liveness pipe, group termination, bounded escalation, and reap. Windows uses a small guardian that creates the command suspended, assigns it to a kill-on-close Job Object before first execution, resumes it, and retains the controller liveness channel. Windows terminal codes are retained as unsigned 32-bit values.

Cancel, timeout, controller shutdown, and controller-process loss terminate the owned family and preserve the existing combined-output drain, byte accounting, flush-before-terminal, and no-blind-relaunch rules. Process-group ownership is lifecycle supervision, not a provider sandbox. A command that deliberately escapes an OS containment primitive is outside the ordinary cooperative Command Run guarantee and must not be advertised as adversarial isolation.

## Runtime health

`GET /healthz` reports process liveness. `GET /readyz` proves database connectivity and returns `503 database_unavailable` when that check fails. Application startup itself also fails if exact schema validation or mandatory recovery cannot complete.

The runtime effect router and support-projection owner keep separate process-local health snapshots with bounded nonsecret source context. Queue rejection, owner death, unregistered signals, or handler failure become visible health failures rather than silently discarded work. Projection failure cannot authorize or block a controller transition, although it can make a support file temporarily stale until replay.

## Product Activity and protected audit

Ordinary product APIs expose semantic Task status, attention, legal actions, Results, referenced files, Human Requests, Command Runs, and bounded Activity. They do not expose Assignment, Attempt, Dispatch, Wave, revision, binding, watchdog, provider-route, or raw event machinery.

The optional `/support` application is the protected diagnostic plane. Its bearer-authenticated, nonbrowser routes expose:

- paged Task search;
- a support snapshot with current manifest path and actionable facts;
- a paged technical trace of Dispatches, including requested/effective Skill/MCP mode provenance and sanitized observed extension inventory, Checkpoints, and accepted boundaries;
- raw immutable Task events; and
- a cursor-resumable event stream.

Support readbacks are derived from database truth. They never mutate runtime state, select a successor, clear a wait, or become a provider request.

## Workspace projections

`manifest.md` and the optional authored Workflow note are provider-visible projections. The controller regenerates the manifest from the current TeamRevision after Task start and accepted replan. `notes/`, `artifacts/`, and Command Run logs are ordinary loose workspace files, not observability records.

The exact ownership and failure behavior are defined by [Runtime](../architecture/runtime.md) and [Workspace, files, and prompt](../architecture/workspace-files-and-prompt.md).
