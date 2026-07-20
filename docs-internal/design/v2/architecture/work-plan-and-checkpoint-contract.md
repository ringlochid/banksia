# Work plan and checkpoint contract

Status: Target

This page owns the distinction between optional current work planning and durable handoff or terminal evidence. Plans help an assignment explain its current approach; checkpoints prove resumable or terminal controller facts. Neither surface replaces graph routing, boundaries, artifacts, or runtime currentness.

## Ownership

The work plan belongs to the assignment, not to a provider session, dispatch, or attempt-local conversation. Root, parent, and worker assignments may all use the same contract.

An assignment may have no plan. The absence of a plan is legal and does not block provider start, Node MCP admission, boundary acceptance, watchdog recovery, or continuation.

The current plan remains visible across:

- replacement dispatches on the same assignment;
- human-request and command-run continuation;
- watchdog same-attempt recovery;
- provider-start retry of the same dispatch; and
- process restart.

A new assignment begins with no plan. A new semantic retry attempt may keep or replace the assignment-owned plan according to the owning retry transition; plan state never determines attempt identity.

## Work plan schema

The managed semantic operation is:

```text
set_work_plan(explanation?, steps)
```

The managed projection supplies no model-visible task or dispatch selectors. The OpenClaw compatibility projection adds the required full `task_id` and `dispatch_id` selectors defined by the Node MCP schema owner.

The request shape is conceptually:

```yaml
explanation: optional short reason for replacing or clearing the plan
steps:
  - step: concise outcome-oriented work item
    status: pending | in_progress | completed
```

Rules:

- zero to nine steps are accepted;
- each normalized step contains one to 512 Unicode characters;
- the optional normalized explanation contains one to 1,024 Unicode characters;
- `steps: []` explicitly clears the current plan;
- at most one step may be `in_progress`;
- all steps may be `completed`;
- steps are ordered and replace the previous snapshot as one revision;
- repeated or vague filler steps fail validation; and
- an identical normalized request is an accepted no-op and creates no new plan revision or plan event.

Normalization trims surrounding whitespace before persistence and equality comparison. For the meaningful-text check only, the controller case-folds the value and removes non-alphanumeric characters. An empty fingerprint or the whole-field fingerprints `todo` and `tbd` fail validation. This rejects whitespace, punctuation-only ellipses, and punctuated placeholder variants without rejecting prose that merely discusses a TODO or TBD.

The assignment stores a monotonic `work_plan_revision`. A present current snapshot stores that revision, the normalized steps, optional explanation, authoring dispatch ID, and commit time. Clearing an existing plan increments the assignment revision and removes the current snapshot; clearing an absent plan is a no-op. This preserves unambiguous event ordering without treating an empty snapshot as a current plan.

Plan state stores no provider transcript, hidden chain of thought, credential, raw tool result, or task-file body.

## Semantics

A work plan is advisory and control-flow inert.

It does not:

- satisfy a workflow boundary or criterion;
- create, complete, or route a child assignment;
- publish an artifact;
- count as a checkpoint;
- create or close a dispatch;
- extend a human or command deadline;
- change watchdog meaning beyond the admitted Node MCP call refreshing activity; or
- make provider output authoritative.

The controller may display plan status to agents and operators, but it never infers assignment success from completed plan steps.

## Current-context readback

`get_current_context()` returns the complete current plan or `null` in the same coherent controller read as assignment, trigger, capabilities, allowed actions, and logical refs.

The plan readback includes:

- assignment ID;
- plan revision;
- optional explanation;
- every ordered step and status; and
- authoring dispatch ID and commit time when useful for audit.

There is no separate `read_plan` tool and no selector for older plan revisions in the bounded current-context contract. Historical plan changes remain available through controller audit or task-event surfaces where those owners expose them.

## Node activity

Every authenticated and admitted `set_work_plan` or `get_current_context` invocation refreshes `last_node_activity_at` and increments `node_activity_revision` once, even when the plan write is an identical no-op or fails with a normalized domain error after admission.

The activity refresh proves only that the current agent interacted with AutoClaw. A changed plan remains a separate semantic domain event; it is not the watchdog's definition of activity.

## Checkpoint purpose

Checkpoints are immutable assignment/attempt evidence for recovery, handoff, review, and terminal boundary proof. They are not a diary of every completed plan step.

Use checkpoints for:

- the exact evidence required by a terminal worker boundary;
- a child return consumed by its parent;
- resumable evidence selected by the controller for a later dispatch;
- artifact and transient publication metadata owned by the checkpoint contract; and
- operator-visible explanation of a blocked or retry outcome.

Routine planning, exploration, and intermediate status stay in the current work plan or ordinary controller records unless an owning concept explicitly requires a checkpoint.

## Checkpoint schema

A checkpoint binds at minimum:

- checkpoint ID;
- task, assignment, attempt, and authoring dispatch IDs;
- checkpoint kind and commit time;
- bounded summary and evidence;
- declared artifact and transient refs;
- criteria or verification results required by the boundary; and
- the exact terminal outcome when the checkpoint supports a terminal boundary.

Checkpoint bodies remain bounded controller data. Large artifacts and logs are stored behind logical refs rather than copied into the checkpoint row or generic event stream.

The handoff summary contains one to 2,048 normalized Unicode characters and `next_step` contains one to 1,024. `blockers` and `risks` each contain zero to 16 entries, with one to 1,024 normalized Unicode characters per entry. These handoff text fields use the same narrow meaningful-text check as work-plan text.

## Boundary relationship

`return_boundary(yield | green | retry | blocked)` remains the explicit controller transition. The boundary owner validates whether its outcome requires a matching checkpoint and whether that checkpoint belongs to the same task, assignment, attempt, and current source dispatch.

- `green`, `retry`, and `blocked` require the terminal evidence defined by the role/workflow policy and boundary contract;
- `yield` may carry a resumable checkpoint only when the owning policy requires durable handoff evidence;
- a completed plan does not substitute for a checkpoint; and
- a checkpoint never closes a dispatch by itself.

After a successful boundary transaction, D1 is closed and the provider turn has no further controller authority. The agent should stop its outer response, but provider output or termination is not part of boundary correctness.

## Continuation and recovery

When a later dispatch receives `checkpoint_to_resume_from`, the prompt and current-context readback identify one exact controller-selected checkpoint. The agent reads that logical ref before acting when the trigger requires it.

The selection must bind to the same assignment/attempt lineage and exact continuation source. The renderer must not choose a checkpoint by latest timestamp, filename, provider history, or proximity.

Watchdog replacement stays on the same assignment and attempt and preserves the current plan. It may select the latest lawful checkpoint as recovery context, but it does not create a checkpoint merely because the watchdog fired.

Human-request and command-run continuation preserve the plan and render the exact terminal source result. They do not manufacture a checkpoint from the external response or command log.

## Persistence and events

The database owns current plan and checkpoint truth. Every successful checkpoint transaction updates the attempt's exact `latest_checkpoint_id` pointer with the checkpoint, publication, localization, association, and current-artifact-pointer rows in one all-or-none change. Selection never depends on a maximum timestamp or filename. Generated `latest-checkpoint` files are readable projections only.

Correctness-critical artifact and active transient bodies are published completely before that final transaction under the task-root publication protocol. A body-copy failure commits no checkpoint. A version/currentness conflict loses the entire checkpoint transaction rather than committing a partial set of claimed bodies. Unreferenced unique candidates are cleanup inputs, never evidence.

Plan replacement may emit a bounded committed `work_plan_set` or `work_plan_cleared` event. Checkpoint commit emits its owned checkpoint event. Events provide chronology; they do not become current-plan or checkpoint authority.

## Failure behavior

- stale or wrong-dispatch plan writes fail before mutation;
- capability-denied plan writes fail without changing the plan;
- invalid step shape fails validation;
- an identical plan is a successful no-op;
- a terminal `green` checkpoint missing any declared produce claim fails before checkpoint or publication mutation;
- before a parent/root release decision, or before a worker boundary closes, a later terminal checkpoint may replace the attempt's latest-checkpoint pointer while preserving the older row as audit history;
- a staged-child decision permits only an optional progress checkpoint before `yield`, while a release decision freezes checkpoint evidence;
- checkpoint identity mismatch fails the owning boundary or continuation before successor creation; and
- missing checkpoint projection files do not erase the authoritative checkpoint row, though the read path reports the projection problem explicitly.

## Removed target concepts

The target does not include:

- mandatory `AttemptPlan` creation for every worker;
- an `update_plan` tool name;
- plan completion as boundary or assignment completion;
- plan changes as the only watchdog activity;
- checkpoint-per-step journaling;
- provider transcript storage in plans or checkpoints; or
- separate worker-only plan semantics that parent/root cannot use.

## Required proof

- root, parent, and worker assignments can operate with no plan;
- `set_work_plan` replaces, clears, and no-ops deterministically;
- at most one step is in progress and at most nine steps persist;
- current context returns the complete plan or `null` coherently;
- plan state survives same-assignment continuation and watchdog replacement;
- plan completion cannot satisfy a boundary;
- checkpoint and boundary identity cannot be mixed across dispatches or attempts;
- one checkpoint cannot commit only a subset of its artifact or transient claims;
- every committed active body ref resolves to a completely published immutable body; and
- admitted plan reads/writes refresh Node activity once; and
- plan/checkpoint rows and events expose no provider or binding credentials.

## Related

- [Runtime lifecycle and watchdog](runtime-lifecycle-and-watchdog.md)
- [Controller contract and resumable execution](controller-contract-and-resumable-execution.md)
- [Runtime records and control state](runtime-records-and-control-state.md)
- [Task root and file access](task-root-and-file-access.md)
- [Prompt system](../prompt-layer/prompt-system.md)
- [Node MCP schema appendix](../interfaces/node-mcp-schema-appendix.md)
