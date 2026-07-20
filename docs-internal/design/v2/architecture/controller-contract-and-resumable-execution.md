# Controller contract and resumable execution

Status: Target

This page owns the semantic controller meaning of assignments, attempts, dispatches, boundaries, waits, continuation, pause, cancel, retry, and recovery. Runtime scheduling mechanics belong to [Runtime lifecycle and watchdog](runtime-lifecycle-and-watchdog.md).

## Controller authority

The controller database is the only authority for current task structure, assignment ownership, attempt identity, dispatch currentness, boundaries, waits, pause/cancel state, and legal continuation.

Providers may request controller changes only through admitted Node MCP operations. Provider output, provider terminal success, transcript continuity, task files, support projections, and process state cannot assert controller transitions.

## Execution hierarchy

```text
task
  -> flow/revision
       -> assignment tree
            -> assignment
                 -> semantic attempts
                      -> dispatch lineage
```

An assignment states one owned outcome. An attempt is one semantic try at that assignment. A dispatch is one provider invocation/controller turn within the current assignment and attempt.

Provider-start retry, human/command continuation, watchdog replacement, operator continue, and process restart are infrastructure continuity on the same attempt. Only an accepted semantic `retry` boundary creates a new attempt.

## Dispatch authority

At most one dispatch per flow is `starting` or `open`.

- `starting` means the request and controller authority committed but provider start has not been positively accepted;
- `open` means provider start was accepted and current Node MCP calls may act; and
- `closed` means the dispatch can never regain authority.

Managed Node MCP admission may allow a current `starting` dispatch during the start handoff race. A later start-acceptance write may move only that still-current dispatch to `open`; it cannot reopen a dispatch closed by an early legal boundary, wait, pause, or cancel.

## Boundary acceptance

`return_boundary(yield | green | retry | blocked)` is the explicit egress operation.

The owning transaction:

1. authenticates and admits exact current dispatch authority;
2. validates outcome, assignment/attempt state, criteria, checkpoint/evidence, and role policy;
3. persists the accepted boundary against D1;
4. performs the owned assignment/attempt/graph transition; and
5. closes D1 before returning success.

After success, the caller must stop the current outer provider response. Correctness does not wait for provider output or termination.

The after-commit `BoundaryAccepted(source_dispatch_id)` handler may create one successor only from that committed source. Boundary response and successor/provider start are independent.

## Boundary outcomes

### Yield

`yield` returns control according to the authored graph without declaring the assignment terminal. It remains a controller boundary and may require resumable evidence according to policy.

### Green

`green` declares the assignment's criteria satisfied with the required checkpoint/evidence. A worker child return becomes consumable by its parent only after this boundary commits.

### Retry

`retry` is semantic failure followed by another semantic attempt. It requires its owned terminal evidence, closes the current attempt according to the boundary contract, and creates or authorizes a new attempt. It is not provider-start retry or watchdog recovery.

### Blocked

`blocked` declares that the assignment cannot proceed under current authority/inputs. It preserves bounded evidence and routes according to parent/root or policy rules. It is not an infrastructure pause reason.

## Root and child progression

Task/flow start commits a durable root source before any root dispatch exists. `FlowStartCommitted(flow_id)` asynchronously materializes and conditionally creates the one root dispatch.

A parent/root assignment owns child creation, review, and integration. Child return is an exact committed source binding child assignment, attempt, source dispatch, accepted boundary, and matching checkpoint. Parent continuation never selects a child result by timestamp or provider output.

One source may produce at most one successor. Graph routing is derived from controller-owned authored/compiled definitions and accepted boundaries, not plan steps or provider prose.

## Human request

Opening a human request is not a boundary outcome. In one transaction it creates the typed source, sets `waiting_cause = human_request` with the request ID, and closes D1 with `human_request_wait`.

The tool returns after that commit and instructs the provider turn to stop. It does not create D2, call provider stop, or wait for an async handler.

Answer, timeout, and cancellation compete on the exact request. A terminal request clears only its matching wait and remains bound to D1. `HumanRequestTerminal(request_id)` may later create one same-attempt successor if the flow is runnable. If paused, the terminal result is retained until legal continue.

## Command run

Starting a command run is likewise not a boundary outcome. One transaction creates the run, sets `waiting_cause = command_run` with the run ID, and closes D1 with `command_run_wait`.

The command owner launches and supervises the exact run asynchronously. `cancellation_requested` is nonterminal until termination/reap rules commit a terminal result.

If restart cannot prove ownership after a process may have launched, it never blindly relaunches or terminates that process. It commits terminal `abandoned` with `command_ownership_lost`, clears only the matching wait, and retains the exact source for ordinary same-attempt continuation.

Terminal command state clears the matching wait and emits `CommandRunTerminal(run_id)`. A runnable flow may receive one same-attempt successor; a paused or cancelled flow does not.

## Watchdog semantics

Watchdog detects inactivity of one current `open` dispatch from admitted Node MCP activity only. It never treats provider terminal status, output, or lack of output as progress or completion.

A dispatch that owns any human-request or command-run source is watchdog-ineligible, including a terminal source awaiting continuation. This rule prevents watchdog from reinterpreting a deliberate external wait as agent inactivity.

An eligible watchdog replacement atomically closes D1 and creates D2 on the same assignment and attempt after D2 request materialization. The old provider is best-effort stopped before D2 start; stop failure does not block the controller transition or new start.

After the default two same-attempt replacements, another stale deadline closes D1 and pauses with `runtime_recovery_exhausted`.

## Provider start and connection failure

A committed D2 begins in `starting`. Provider start happens after commit and may retry the same dispatch indefinitely.

Provider connection, authentication, availability, timeout, rejection, or uncertain acceptance does not create a new attempt, dispatch, or pause. It remains visible as retry state on D2.

Before uncertain same-D2 retry, the runtime revokes the old managed binding and makes the adapter's bounded stop attempt when supported. A stop failure is an adapter limitation and does not become a controller waiting cause.

Deterministic controller request/ref integrity failure is different: it causes zero provider I/O and may close D2 and pause with `runtime_transition_failed`.

## Pause

Pause is durable flow control and is orthogonal to an external wait.

The pause transaction stores reason/details/actor/time, increments `control_revision`, closes any current starting/open dispatch, and clears current authority. It does not erase an active human request or command run.

Provider/process cleanup occurs after commit and cannot delay or undo pause.

Source completion may commit while paused. It clears its matching wait when owned but does not create a successor. The terminal source remains available for continue.

## Continue

Operator continue is directly awaited because operator intent has no independent durable natural source suitable for a disposable signal.

The service requires:

- paused nonterminal flow;
- caller's exact observed `control_revision`;
- no unresolved active human or command source;
- one exact unconsumed flow-start or terminal continuation source, or one lawful lineage tail without successor; and
- a supported pause reason and provider route.

It materializes the prospective D2 request pair, then one final transaction rechecks those predicates, moves the flow to `running`, and creates D2 plus refs. The call returns after commit without waiting for provider start.

Continuing a retained pre-root `FlowStartSource` creates the first dispatch with no predecessor, keeps the exact flow-start link, and records `opened_reason = operator_continue`. It never invents a placeholder D1.

Concurrent continue/cancel or continue/watchdog attempts converge through flow status, control revision, current dispatch, source consumption, and one-successor constraints.

## Cancel

Task cancel is terminal controller intent. It closes current dispatch authority, terminalizes/cancels owned waits as their contracts require, requests resource cleanup, and never opens a successor.

Dedicated command-run cancel is not task cancel. It moves the exact run to `cancellation_requested` until the process owner proves terminal cancellation.

Provider stop failure after task cancel cannot restore authority or keep the task nonterminal.

## Work plan and checkpoint

The work plan is optional assignment-owned advisory state. Root, parent, and worker may set, replace, clear, or omit it. Plan completion never routes the graph or satisfies a boundary.

Checkpoints are durable resumable/terminal evidence selected by controller identity. A continuation renders the exact selected checkpoint when required; it does not use the latest file or provider memory as a substitute.

## Exact trigger model

Every dispatch request has one discriminated trigger derived from one committed source:

- root start;
- accepted boundary;
- child green/blocked return;
- human answer/timeout/cancel;
- command success/failure/timeout/cancel;
- watchdog recovery;
- semantic retry; or
- operator continue.

The trigger owns source identity and prompt-safe result. Generic timestamps, task status, filenames, support projections, and provider output cannot select it.

## Concept-preserving races

### Watchdog versus wait opening

Both operations compete on exact current D1.

- If the wait-opening transaction wins, it creates the source/wait and closes D1; watchdog fails currentness and source exclusion.
- If watchdog wins, it closes D1 and creates D2; the stale Node MCP wait call cannot admit/commit and creates no source.
- If a source is terminal but unrouted, its row still excludes watchdog; only its exact terminal handler may open a successor.

### Pause versus source completion

Pause and source terminalization may both commit because they own different facts. Pause prevents consumption into a successor. Continue later consumes at most one retained source.

### Node call versus watchdog

An admitted activity call increments the revision and makes the observed due signal stale. A watchdog transaction that wins first changes current dispatch, causing the old Node call's final currentness predicate to fail.

## Removed target concepts

- provider-terminal progression;
- provider reconnect as a task waiting cause;
- internal fencing waiting state;
- open dispatch retained through a human/command wait;
- successor opening inside the boundary tool transaction;
- mandatory plan completion before boundary;
- broad per-task lock across controller and external effects;
- provider-start exhaustion as semantic retry; and
- support files or provider sessions as recovery authority.

## Required proof

- each boundary closes D1 once and produces at most one legal successor;
- human/command open commits source + wait + D1 close atomically;
- terminal external sources continue only when runnable and remain retained while paused;
- watchdog skips every dispatch with a human/command source;
- all contested commit orders converge to one legal lineage;
- provider start retries the same D2 without creating semantic work;
- continue requires exact control revision and consumes at most one source;
- cancel never opens a successor; and
- provider output/terminal state cannot complete an assignment.

## Related

- [Runtime lifecycle and watchdog](runtime-lifecycle-and-watchdog.md)
- [Runtime records and control state](runtime-records-and-control-state.md)
- [Work plan and checkpoint contract](work-plan-and-checkpoint-contract.md)
- [Human request and approval contract](../interfaces/human-request-and-approval-contract.md)
- [Command run and external wait](command-run-and-external-wait.md)
