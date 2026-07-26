# Runtime and results

Banksia separates the reusable team from the work happening now. The controller, not a provider transcript, owns the running state.

## From Workflow to Task

Starting a Task pins a published Workflow revision, selects a workspace, and creates a runtime team revision. Banksia also creates the root Assignment for the Task lead.

The core records have distinct jobs:

- **Task:** the user-visible lifecycle and selected final Result.
- **Team revision:** the exact responsibility tree active at that point in the Task.
- **Assignment:** one immutable, complete work request for one Member, with optional file references.
- **Attempt:** one execution try for an Assignment.
- **Dispatch:** one resolved provider request inside an Attempt.
- **Checkpoint:** a durable teammate-facing report for an exact Assignment execution.
- **Continuation:** the exact successor context created from one committed controller source.

A same-Assignment retry reuses the exact stored prompt. Materially changed work or feedback creates a fresh Assignment.

## Delegation Waves

A Manager delegates one or more complete Assignments to current direct children in a Delegation Wave. The controller creates the entire fan-out atomically and gives every child an independent Attempt lane.

The parent waits locally until every Wave member returns a terminal `green` or `blocked` Checkpoint. Blocked children do not cancel their siblings. After the collect-all join settles, the parent resumes once with every child Assignment and Checkpoint in delegation order.

Nested teams use the same rule. If a child delegates another Wave, that child waits on its local join; only its later terminal result settles its place in the parent's Wave. No global conversation pointer or mutable completion counter is required.

There is no `wait_for_wave` operation. A successful delegation commits the work and wait; the provider turn stops, and the controller opens the continuation when the join is ready.

## Checkpoints and the user Result

A Checkpoint always has a human-readable summary and may have details and file references. It can report progress without an outcome, or finish the current execution with:

- `green` — the Assignment completed;
- `blocked` — the Assignment cannot complete within its current boundary; or
- `retry` — start another Attempt for the exact Assignment when budget remains.

`green` and `blocked` close the Assignment. `retry` closes the current Attempt but does not become a user Result.

The accepted terminal `green` or `blocked` Checkpoint from the Task lead is the exact Result shown to the user. Banksia does not ask another model to paraphrase it.

## External waits

A capable Member can open a typed Human Request or managed Command Run. The controller commits the request and an Attempt-local wait before the external effect. The provider must stop after the operation is accepted; unrelated Task lanes may continue.

Human Requests preserve the original question, stable option identities, answer, actor, and timing. Command Runs preserve process ownership and bounded controller status while streaming the full output to the Task workspace. A later continuation includes the exact terminal source.

## Replanning

A Manager may add, update, or remove members only within its current subtree. Adding a Member can create a nested subtree recursively. Updating can change the selected child's optional fields and listed descendants, but it never changes an existing ID. Removal is explicit; omission never means deletion.

Every accepted structural change creates a new runtime team revision and regenerates the organization manifest. Earlier Assignments, Attempts, Checkpoints, and team revisions remain unchanged for audit and recovery.

See [Run and operate Tasks](../guides/run-and-operate.md) and [Controller tools](../reference/controller-tools.md).
