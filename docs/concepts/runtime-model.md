# Runtime model

The runtime model records one launched task. It answers what is current, what happened, what evidence exists, and which transition is legal next.

## Main records

| Record | Meaning |
| --- | --- |
| Task | one launched unit of work |
| Compiled plan | pinned workflow, role, policy, and dependency revisions |
| Flow | active runtime graph |
| Assignment | bounded mission for one node |
| Attempt | one try at an assignment |
| Dispatch | one provider turn for the current attempt |
| Checkpoint | recorded progress or handoff |
| Artifact | durable output in a declared slot |
| Boundary | node return such as `yield`, `green`, `retry`, or `blocked` |
| Wait | active human request or command run |

## Commit first, continue after

The transaction that accepts a node action commits the authoritative concept change. It can close the current dispatch, open a wait, record a boundary, or stage the exact source for continuation.

After that commit returns, a thin asynchronous handler processes the signal. It rereads only the source rows needed for that signal, rejects stale work, publishes the next dispatch request pair, and commits a successor with those refs when legal. Provider start runs independently after the successor commit. The original MCP or HTTP response does not wait for this work.

## Dispatch states

A dispatch commits in `starting` only after its immutable request pair is published. It is then eligible for provider start. Provider acceptance moves it to `open`. Closed dispatches remain history and cannot become current again. Support projections never gate dispatch eligibility.

## Human and command waits

Opening a human request or command run moves the flow into an explicit wait. Its own deadline and terminal signal drive continuation. A task waiting on one of these sources is not an idle provider dispatch, so the watchdog must not recover it as one.

## Watchdog

The watchdog watches an open dispatch for admitted node activity. The default inactivity deadline is 15 minutes. Provider stdout, final output, and provider terminal status do not refresh the deadline.

When the exact dispatch is still current and inactive, recovery closes it and opens a replacement in one short controller transaction, or pauses the task after the same-attempt replacement limit is exhausted. Stale watchdog signals lose harmlessly.

## Projections and events

Materialized files and console read models follow authoritative commits. Task events form an ordered chronology. Neither is a substitute for current source rows.

See [inspect and control a task](../guides/inspect-and-control-a-task.md) for the operator workflow.
