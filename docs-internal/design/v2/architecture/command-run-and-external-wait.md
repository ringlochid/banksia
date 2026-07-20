# Command run and external wait

Status: Target

This page owns the controller-managed command-run source, its atomic external wait, OS-process supervision, timeout/cancellation semantics, logs, terminal result, and same-attempt continuation.

## Core rule

A node uses `start_command_run` for shell work that must continue independently of the provider turn, especially long-running work, bounded background execution, timeout, logs, or cancellation.

Starting a command run commits the source, matching wait, and D1 closure atomically. It is not a workflow boundary, provider-native shell tool, task cancel, or terminal assignment result.

The MCP response returns after commit and instructs the current provider turn to stop. It does not wait for process launch, provider stop, command completion, successor opening, or an async acknowledgement.

## State machine

The exact states are:

```text
pending_start -> running -> succeeded
                         -> failed
                         -> timed_out
                         -> cancellation_requested -> cancelled
                                                   -> abandoned
                         -> abandoned

pending_start -> cancellation_requested -> cancelled
              -> abandoned
```

`succeeded`, `failed`, `timed_out`, `cancelled`, and `abandoned` are terminal. `abandoned` records restart-time loss of exact ownership over a possibly launched command; it is not a relaunch instruction. `cancellation_requested` is nonterminal until the owner proves that the process terminated and was reaped.

Process state is evidence used to commit controller state; it is not a second runtime truth lane.

## Node operation

Conceptually:

```text
start_command_run(request) -> CommandRunOpenResult
```

Managed schemas contain semantic fields only. The compatibility projection adds required full `task_id` and `dispatch_id` selectors.

The request contains:

```yaml
command: non-empty argv or strict command form
cwd: task-relative workspace path | null
environment: bounded approved references | null
timeout_seconds: positive integer | null
summary: bounded purpose
expected_outputs: optional bounded logical refs/description
```

The command contract must distinguish argv from any shell-string form and apply the owning policy explicitly. It never interpolates provider prose into a privileged shell implicitly.

## Source record

```yaml
command_run:
  run_id: string
  task_id: string
  flow_id: string
  assignment_id: string
  attempt_id: string
  source_dispatch_id: string
  request: typed command request
  state: pending_start | running | cancellation_requested | succeeded | failed | timed_out | cancelled | abandoned
  ownership_revision: integer
  due_at: timestamp | null
  started_at: timestamp | null
  ended_at: timestamp | null
  cancellation_requested_at: timestamp | null
  cancellation_requested_by_actor_ref: string | null
  terminal_result: typed result | null
  stdout_log_ref: logical path | null
  stderr_log_ref: logical path | null
  successor_dispatch_id: string | null
```

The source binds to its exact D1. Historical runs remain readable but cannot own a current wait or authorize continuation.

Live process handles and operating-system process IDs remain process-owner support state. They are not portable controller authority and are never exposed as provider or Node credentials.

## Start legality

Before mutation, the operation proves:

- exact managed binding or compatibility scope resolves current D1;
- task, flow, assignment, attempt, and node are current/runnable;
- effective `command_run` capability permits the requested command, cwd, environment, timeout, and resource bounds;
- no human request or command run already owns the current wait;
- D1 has no accepted boundary or successor; and
- logical paths and environment references are safe.

A rejected call creates no run, wait, dispatch closure, process, or standalone task event. A call rejected after common admission still refreshes Node activity once according to the common contract.

## Atomic external-wait transition

One transaction:

1. inserts the `pending_start` command source bound to D1;
2. sets `waiting_cause = command_run` and `waiting_source_id = run_id`;
3. closes D1 with `closed_reason = command_run_wait`;
4. clears current dispatch authority; and
5. emits the bounded open event.

It does not create D2, record a terminal checkpoint, call `return_boundary`, call provider stop, pause the flow, or keep D1 open.

After commit, `CommandRunPending(run_id)` wakes the command owner. Lost publication is recovered by the bounded startup source audit.

A new `pending_start` source stores `due_at = null` even when its request has `timeout_seconds`. The command timeout begins only after successful operating-system process creation. That transition stores one immutable `started_at` and, when a timeout applies, immutable `due_at = started_at + timeout_seconds`.

## Command-process ownership

The lifespan-owned `CommandProcessOwner` handles one exact run at a time by ownership revision. It owns:

- conditional claim of `pending_start`;
- process creation with resolved cwd/environment policy;
- stdout/stderr pipe consumption;
- bounded log persistence;
- timeout registration;
- exit classification;
- cancellation/termination escalation; and
- final process reap before cancellation terminalization.

Each controller write matches `run_id + ownership_revision + expected state`. Stale callbacks cannot mutate a newer owner or terminal run.

There is no global provider semaphore or broad runtime task lock. An optional command-specific resource limit belongs to command policy/process ownership, not provider dispatch orchestration.

## Launch

The command owner opens a fresh database session, conditionally claims a current `pending_start` run, then launches the process outside the claim transaction. It records `running`, the immutable start/deadline pair, log refs, process support metadata, and incremented ownership revision through its owned recovery-safe sequence.

If process creation definitely fails, it commits terminal `failed` with a sanitized result. If restart makes ownership ambiguous, it does not blindly launch or terminate another process; it follows the recovery classification below.

## Logs and updates

The process owner continuously consumes stdout/stderr to prevent child-process pipe blockage. This is command-resource supervision, not provider output drain.

Raw logs live behind authorized bounded log routes/refs. Generic events, checkpoints, prompts, and snapshots contain bounded summaries and refs only.

Progress summaries may update command source support fields without affecting a closed D1 watchdog clock. Human/command waits are monitored by their own deadlines/resources, not dispatch inactivity.

## Timeout

`CommandRunDue(run_id, due_at)` reloads the exact source and matches stored due time/state/ownership revision. If still nonterminal, it requests process termination under timeout ownership.

`timed_out` becomes terminal only after the owner has performed the process termination/reap rules required by platform policy, then commits a typed terminal result.

Process exit and timeout compete through conditional state and ownership revision. Exactly one terminal classification wins.

## Dedicated cancellation

Dedicated command cancel targets one exact current nonterminal run and does not cancel the task.

If termination cannot complete synchronously, the controller commits:

```yaml
state: cancellation_requested
cancellation_requested_at: <timestamp>
cancellation_requested_by_actor_ref: <actor or null>
```

This state remains waiting and does not authorize D2. The process owner sends the bounded interrupt/terminate/kill sequence, waits for termination, reaps the process, then conditionally commits `cancelled`.

After the cancellation-request transaction commits, `CommandRunCancellationRequested(run_id, ownership_revision)` wakes that exact process owner. The control response does not wait for the signal handler.

Repeated cancel is idempotent. A process exit may win before cancellation; its legal terminal result remains authoritative.

## Task cancellation

Task cancel is separate. It makes the task terminal and clears its matching flow wait, but a possibly live run moves only to `cancellation_requested`. The run becomes `cancelled` after the process owner proves no process exists or completes termination and reap. Task cancel publishes the exact cleanup signal and never opens a successor.

Later exit/timeout/cancel callbacks fail terminal/task-currentness predicates and cannot continue the cancelled task.

## Terminal result

```yaml
command_run_terminal_result:
  state: succeeded | failed | timed_out | cancelled | abandoned
  exit_code: integer | null
  summary: bounded continuation-first explanation
  started_at: timestamp | null
  ended_at: timestamp
  stdout_log_ref: logical path | null
  stderr_log_ref: logical path | null
  failure_code: sanitized string | null
  terminal_event_source: controller | control_api | operator_mcp | process_owner
  terminal_actor_ref: string | null
```

Command exit code plus policy determines succeeded/failed. Timeout/cancel may have no useful exit code. Raw output is never copied into this result.

`abandoned` requires `failure_code = command_ownership_lost`. It is a terminal controller classification for lost process ownership, not proof that the operating-system process exited.

Terminal state, result, and matching wait clear commit atomically. The source event is emitted from that commit.

## Continuation

Terminal command state, including `abandoned`, is terminal only for the run. After commit, `CommandRunTerminal(run_id)` may create one successor.

The handler proves the terminal run still belongs to the exact lineage, its matching wait is cleared, the flow is runnable, D1 has no successor, and the terminal source is unconsumed. It then publishes the D2 request pair and conditionally creates D2 on the same assignment, attempt, and plan.

The trigger contains the command purpose, terminal state, exit code/failure code, bounded summary, timing, and logical log/output refs. It does not inline raw logs or rely on provider conversation memory.

If paused, the terminal result remains retained with no successor. If cancelled/terminal, no successor is permitted.

## Watchdog interaction

D1 is watchdog-ineligible whenever it owns this command source, from `pending_start` through terminal-but-unconsumed state.

If command opening wins against watchdog, source + wait + D1 closure make watchdog stale/excluded. If watchdog wins, the stale Node MCP transaction cannot create the command row or process.

The command timeout is not the dispatch watchdog. It is owned by `run_id + due_at + ownership_revision`.

## Restart recovery

Startup audits exact command states:

- `pending_start`: emit a launch signal only when no prior launch ownership can be inferred;
- `running`: recover local process ownership when it is exactly provable;
- `cancellation_requested`: resume bounded termination/reap only when ownership is exactly provable;
- terminal without successor: emit terminal continuation if the flow is runnable; and
- terminal on paused/cancelled flow: retain result or clean resources only.

When prior launch ownership is possible but the process cannot be safely reattached, the owner conditionally terminalizes the source as `abandoned`, records `failure_code = command_ownership_lost`, clears only its matching wait, emits `command_run_abandoned`, and publishes the ordinary terminal-continuation signal. The runtime does not blindly relaunch or terminate the process merely to make progress.

## Read and event surfaces

Authorized control surfaces own run list/detail, bounded log reads, and cancel. Generic task events include:

- `command_run_opened`;
- `command_run_started`;
- `command_run_cancel_requested`;
- `command_run_succeeded`;
- `command_run_failed`;
- `command_run_timed_out`;
- `command_run_cancelled`; and
- `command_run_abandoned`.

Events are chronology only. They do not drive process ownership or continuation.

## Required invariants

- start commits source + wait + D1 close atomically;
- successful open leaves no current D1 binding authority;
- command launch happens only after commit;
- nonterminal state keeps the flow waiting and creates no D2;
- cancel is nonterminal until termination and reap;
- exit/timeout/cancel produce one terminal winner;
- restart ownership loss produces one audited `abandoned` winner and never a blind relaunch;
- only the exact terminal source may create one successor;
- terminal result is retained while paused;
- restart never blindly duplicates an ambiguously owned process;
- watchdog skips all command-source states until consumption; and
- provider stop/output/completion and `return_boundary` are absent.

## Related

- [Runtime lifecycle and watchdog](runtime-lifecycle-and-watchdog.md)
- [Controller contract and resumable execution](controller-contract-and-resumable-execution.md)
- [Human request and approval contract](../interfaces/human-request-and-approval-contract.md)
- [Capability, security, and audit](../interfaces/capability-security-and-audit.md)
