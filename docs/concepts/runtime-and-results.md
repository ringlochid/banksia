# Runtime and results

The user-facing runtime story is:

```text
Task prompt
  -> adaptive, accountable team work
  -> bounded replan when responsibility must change
  -> questions or managed actions when needed
  -> teammate Checkpoints
  -> exact lead Result
```

The controller owns this state. Eligible work can pause, wait, replan, retry safely, recover after interruption, and resume without treating provider conversation history as runtime truth. Provider output, a browser connection, and loose workspace files can help perform or inspect the work, but none can declare the Task complete.

## Task and pinned team

A Task is one run of a published Workflow against one exact prompt. Starting one Task:

1. validates the published Workflow, workspace, provider intent, capabilities, and optional file references;
2. pins the selected immutable Workflow revision;
3. materializes the complete Task-local responsibility tree;
4. creates the root work for the lead; and
5. returns an accepted receipt before claiming that provider startup has finished.

All Members exist structurally at start, but only the lead begins execution. Children become runnable through later Manager delegation. A later publication of the reusable Workflow does not change the pinned Task.

## Work Plan

A Work Plan is one Member's current advisory approach and progress for its Assignment. It may contain a short explanation and up to nine distinct steps marked `pending`, `in_progress`, or `completed`, with at most one step in progress.

A Member can replace, revise, or clear the plan as evidence changes. The current plan survives same-Assignment continuation and recovery.

A Work Plan is not:

- authored Workflow steps;
- controller scheduling authority;
- a prerequisite for delegation;
- a Checkpoint or completion proof; or
- a projected file under `.banksia/`.

## Assignment and Attempt

An **Assignment** is one immutable, complete work request for one Task Member. It contains the exact nonblank prompt and optional ordered file references. Materially changed scope, review feedback, or another item in a batch requires a fresh Assignment.

An **Attempt** is one try to execute that Assignment. A semantic `retry` Checkpoint replaces the current Attempt only when its snapshotted retry budget permits. It does not change the Assignment prompt.

Inside an Attempt, a **Dispatch** is one exact provider turn. Continuations create fresh Dispatches with the exact committed source that resumed the work. Restarting the same Dispatch resends its stored request; it does not rerender from current files or a newer Workflow.

An active Member may accept a **steer**: later user direction delivered to its exact current provider session. Confirmed steers appear in Activity with the exact message and are carried into later Dispatches for the same Assignment. They do not replace the Assignment, revise the Workflow, undo completed effects, or grant new authority.

Provider terminal success does not complete any of these records. Only an accepted controller operation can record progress, open a wait, delegate work, or finish an execution.

## Delegation Waves and local joins

A Manager delegates one or more complete Assignments to unique, available direct children in a Wave. The controller commits the complete ordered fan-out and the parent wait atomically, then starts child work after commit.

One child gives sequence through the same durable path. Several children give parallel work when their scopes are credibly independent. The Manager cannot delegate one child, inspect an early response, and add another child to that same Wave.

The parent resumes once after **every** Wave member has returned a terminal `green` or `blocked` Checkpoint:

- blocked members do not cancel siblings;
- results are returned in delegation-request order, not completion order; and
- a child `retry` does not settle its Wave position.

Joins are local and recursive. If a child Manager opens another Wave, that child waits for its own descendants, integrates their work, and returns its own terminal Checkpoint. Only then does its position settle in the parent's Wave.

There is no separate wait-for-Wave action. Successful delegation transfers authority, closes the provider turn, and lets the controller open the exact continuation when the join settles.

## Human Request and Command Run waits

When explicitly granted to the current Member and currently legal:

- a **Human Request** asks one to three typed questions and waits for an exact answer, cancellation, or timeout; and
- a **Command Run** starts one controller-managed command after commit, drains output to the workspace, and waits for its terminal state.

Opening either wait closes the current Dispatch. The provider must stop. Unrelated Task lanes may continue.

The eventual continuation includes the exact terminal source: the original Human Request plus its typed resolution, or the Command Run's terminal result. A Human Request accepts an answer; a Command Run can expose a current cancellation action, but it is not a per-command approval request.

## Checkpoints

A Checkpoint is the durable teammate-facing report for the current execution. It has a required summary and may add details and file references.

When `outcome` is omitted, the Checkpoint records progress and the Dispatch remains current. A present outcome is terminal for that execution:

| Outcome | What closes | Consequence |
| --- | --- | --- |
| `green` | Dispatch, Attempt, and Assignment | The work completed; it may settle a Wave member or the root Task. |
| `blocked` | Dispatch, Attempt, and Assignment | The work cannot complete within its current boundary; it still settles a Wave member or the root Task. |
| `retry` | Dispatch and Attempt | The same Assignment gets a fresh Attempt when budget remains; it does not settle a Wave or become a Result. |

A Manager's `green` Checkpoint is legal only after every current direct child configuration has an accepted green return on its current branch basis. A blocked return can settle a Wave position but does not satisfy participation; retry settles neither. Direct takeover requires removing every child first so the next fresh context is Contributor-shaped.

Ordinary review-driven repair is not retry. It is fresh work with the concrete findings in a new Assignment.

## Recovery and its limits

Banksia commits controller truth before starting provider or command effects. Disposable process signals can therefore be recreated from exact committed sources after a controller restart. Startup reconciles accepted Task admission, provider starts, Waves, terminal waits, Command Runs, retry and replan continuations, and the organization manifest.

Same-Assignment recovery retains the current Work Plan and immutable Assignment. An ambiguous provider start may use a fresh binding for the same stored Dispatch. A Command Run whose process ownership cannot be proved is terminalized honestly rather than launched again blindly.

Recovery does not promise:

- deterministic model output;
- exactly-once external effects;
- replay of arbitrary provider-native shell or network activity;
- reconstruction of changed loose file bytes;
- distributed failover; or
- success without an accepted terminal Checkpoint.

The configured semantic retry budget, provider-start handling, and watchdog replacement limits are bounded. Exhaustion or infrastructure failure remains visible controller state; it is never rewritten into successful work.

## The exact Result

The accepted terminal `green` or `blocked` Checkpoint from the Task lead's root Assignment is the exact user-visible Result:

```text
root Assignment
  -> accepted terminal lead Checkpoint
  -> Result
```

The Result preserves the outcome, summary, optional details, file references, and completion time. Banksia does not ask another model to paraphrase it or fall back to ordinary provider prose.

A `retry` Checkpoint produces no Result. Cancellation, provider failure, and other infrastructure failures also produce no fabricated Result unless the lead has already committed an accepted root `green` or `blocked` Checkpoint.

See [Run and operate Tasks](../guides/run-and-operate.md) for user actions and [Controller tools](../reference/controller-tools.md) for exact operation boundaries.
