# Runtime boundary and controller loop contract

Status: Target

> **V2 supersession notice:** This page remains the frozen V1 boundary baseline. For V2 dispatch lifecycle, external waits, recovery, and continuation, use [Runtime lifecycle and watchdog](../../v2/architecture/runtime-lifecycle-and-watchdog.md) and [Controller contract and resumable execution](../../v2/architecture/controller-contract-and-resumable-execution.md).

This page defines the canonical v1 controller loop, public runtime boundaries, parent/root control tools, and the exact split between checkpoints, tool success, and boundary returns.

## Core rule

The controller is the only owner of runtime truth.

It owns:

- current node selection
- assignment and attempt lineage
- structural currentness
- checkpoint recording
- artifact currentness
- dispatch delivery, continuity, and watchdog state
- the dispatch-to-Gateway session/run binding used for controlled execution
- any private callback-write binding used for the current dispatch

Nodes advance runtime truth only through the explicit controller-facing lanes documented here.

## Public boundary model

The only canonical public runtime boundaries in v1 are:

- ingress: `dispatch`
- egress: `yield | green | retry | blocked`

Rules:

- `dispatch` is controller -> node ingress only.
- `dispatch` is a public cross-system boundary, not an internal waiting, staged, continuity, watchdog, or delivery state.
- `yield` is the non-terminal end of a current parent/root dispatch.
- `green | retry | blocked` are terminal attempt outcomes and terminal egress boundaries.
- worker nodes do not use `yield`.
- parent/root do not close with `retry` in v1.

## Exact boundary meanings

| Boundary   | Exact meaning                                                                                                                                                        |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dispatch` | The controller has given one current node a turn now.                                                                                                                |
| `yield`    | A current parent/root dispatch has ended non-terminally and the controller may now consume the one already-committed staged child assignment for that open dispatch. |
| `green`    | The current node attempt completed its current assignment and the required terminal checkpoint and release/publication basis already exist.                          |
| `retry`    | The current node requests another attempt on the same assignment after publishing a terminal retry checkpoint.                                                       |
| `blocked`  | The current node cannot complete the current assignment as assigned and has already published a terminal blocked checkpoint.                                         |

## Parent/root control tool model

During an open parent/root `dispatch`, the only canonical public control tools are:

- `assign_child`
- `add_child`
- `update_child`
- `remove_child`
- `release_green`
- `release_blocked`

Rules:

- tool success mutates controller-owned runtime truth but does not close the current dispatch
- `assign_child` stages a fresh child assignment, commits the child `assignment_key` and first `attempt_id`, and may materialize child `assignment.*`; while the parent/root dispatch is live and no downstream artifact consumer has current work, the same operation may supersede terminal work for that direct child without rewriting its history
- the child definition owns the baseline durable assignment contract
- parent/root may add only assignment-local wording, supplemental durable artifact/criteria slot selectors, and explicit transient surfacing
- runtime resolves `consumes` and projects `produces` as requirements only
- successful `assign_child` does not create a child `dispatch_id` and does not create child dispatch-local monitoring projections yet
- `release_green` and root-only `release_blocked` are terminal-close preconditions only; they are not boundaries and not continuation outcomes
- parent/root must later emit `yield` for non-terminal closure
- parent/root must later emit `green` or `blocked` for terminal closure
- retry is node-self only; parent/root do not issue a separate public child retry, reassignment, or replacement verb because fresh same-child work uses `assign_child`
- for v1 static `node MCP`, caller supplies `session_key` + `task_id`; the controller resolves the current bound dispatch context from runtime truth rather than from manifest or ack fields

## Checkpoint, tool, and boundary split

The controller-facing lanes are distinct and must not be collapsed:

- `record_checkpoint` durable handoff publication of what happened, what should happen next, which produce slots matter, and which transient files are surfaced
- parent/root control tools dispatch-local runtime mutations
- `yield | green | retry | blocked` public dispatch-closure facts

Rules:

- a checkpoint is not a boundary
- tool success is not a boundary
- a boundary return is not a tool success body
- parent -> child context comes from assignment
- child -> parent and same-node retry context comes from checkpoint plus surfaced refs
- `record_checkpoint` uses `handoff` plus optional reduced durable artifact claims and explicit transient surfaces; `control_effects` is not part of the live checkpoint contract

## One-continuation rule

One open parent/root dispatch may own at most one post-`yield` continuation outcome.

That continuation outcome is exactly:

- one staged child assignment from `assign_child`

Rules:

- checkpoint publication is not a continuation outcome
- tool success is not a continuation outcome
- `release_green` and `release_blocked` are terminal preconditions, not continuation outcomes
- zero staged child assignments makes `yield` illegal
- more than one staged child assignment makes `yield` illegal
- once one staged child assignment exists, no second child assignment may be committed on that same open dispatch
- parent/root may still publish a progress checkpoint if it does not replace or mutate the already-committed staged child assignment

## Boundary matrix

| Caller kind | Legal non-terminal close                                      | Legal terminal close                                                                                                                                                       |
| ----------- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `root`      | `yield` only after exactly one staged child assignment exists | `green` after committed `release_green`; `blocked` after a terminal blocked checkpoint plus committed root `release_blocked` for whole-flow blocked closure                |
| `parent`    | `yield` only after exactly one staged child assignment exists | `green` after committed `release_green`; `blocked` after a terminal blocked checkpoint when the current parent assignment cannot complete, returning control to its parent |
| `worker`    | none                                                          | `green / retry / blocked` after the matching terminal checkpoint and any required publication basis                                                                        |

Parent/root later turns on the same assignment happen by ordinary `redispatch_same_attempt`, not by a parent/root `retry` boundary.

## Boundary precondition and reject split

Use `boundary_precondition_failed` for:

- `yield` without exactly one staged child assignment
- `green` without the required terminal checkpoint or required `release_green` basis
- terminal `green` checkpoint writes that would immediately fail the matching `green` boundary's non-pointer preconditions
- `retry` without the required terminal retry checkpoint basis
- `blocked` without the required terminal blocked checkpoint basis
- root `blocked` without already committed `release_blocked` when required

Use ordinary legality/currentness failure, not `boundary_precondition_failed`, for:

- attempted parent/root `retry`
- attempting to commit a second child assignment on one open dispatch
- stale dispatch or stale structural/currentness guards

## Controller loop and post-boundary advance

Every mutating controller step uses this exact loop:

1. parse the request or trigger through canonical schema objects
2. reread controller-owned current truth
3. derive a candidate next state without mutating truth in place
4. validate authority, currentness, dependency legality, and evidence basis
5. atomically commit authoritative rows only
6. reread committed truth
7. regenerate required projections from committed truth
8. stop at an owed boundary, emit `dispatch` for the one eligible current node, or wait on recomputed controller state

Short form:

- semantic facts
- controller validates
- runtime truth rows commit
- projections regenerate

Core controller advance actions are:

- `redispatch_same_attempt`
- semantic `create_new_attempt`
- `escalate`

Rules:

- parent/root `yield` with one staged child assignment consumes that staged child assignment and prepares the child's first dispatch
- worker `retry` always maps to semantic `create_new_attempt`
- a later parent/root turn on the same assignment after child work or review progress is ordinary `redispatch_same_attempt`
- transport send mode never renames the controller action family
- v1 keeps at most one open dispatch turn per flow at a time
- many tasks may execute concurrently in v1, but each task flow lineage still keeps one live execution slot at a time
- before a recovery or redispatch opens a new dispatch, the older dispatch must already be closed or superseded in controller truth
- a truthfully recorded `provider_failed`, `transport_failed`, force-fenced `transport_ambiguous`, or launch-ambiguous dispatch row is tolerable; a second live dispatch for the same current execution slot is not
- parent/root same-attempt later turns reuse the same durable Gateway `sessionKey` when continuity reuse remains lawful and otherwise fall back to a fresh `sessionKey`, while always opening a fresh live Gateway run
- worker retry and new-attempt recovery open a fresh Gateway `sessionKey` and a fresh live Gateway run
- accepted `yield`, `green`, `retry`, or `blocked` is not by itself enough to open the next live run
- once the prior run is proven inactive and the flow is not paused, ordinary post-boundary progression is internal controller work; it must not be externalized to operator `continue`
- the controller must also prove the prior run is inactive:
    - natural terminal completion already confirmed, or
    - explicit abort completed and the prior dispatch is `fenced`, or
    - the abort/stop deadline expired and the prior dispatch was force-fenced with `delivery_status = transport_ambiguous`
- if the prior run is still live after boundary acceptance, the controller must wait or abort before dispatching the next run
- node/callback write authority must resolve from the supplied v1 `session_key` + `task_id` against runtime currentness truth and must be rejected once that session is no longer current, live, or legal for write commit

## Normalized runtime model

The target runtime model keeps four concerns separate:

- **semantic currentness**
    - what node, assignment, and attempt should run next
- **live execution slot**
    - what dispatch still occupies the one live execution slot for the flow
- **historical evidence**
    - boundaries, checkpoints, and provider history that explain what happened
- **authority**
    - who may still write against the live slot

Rules:

- semantic currentness may already point to the next target while the old dispatch still occupies the live execution slot
- `accepted_boundary` and `staged_child_assignment_id` are evidence and basis fields, not the primary resume source in the target model
- pause and operator resume consume normalized controller truth rather than reconstructing meaning from boundary history
- ordinary automatic progression and paused resume both read the same semantic currentness model
- support-state and readback projections may explain these states, but they do not replace them as controller truth

## Pause and operator resume

Pause is an external operator control, not part of ordinary boundary progression.

Rules:

- pause hard-stops current dispatch progression for controller truth
- pause returns after controller truth commits the paused state plus write revocation and abort-owned dispatch state; final fencing may complete asynchronously in the lifecycle manager
- pause revokes further session-rooted node/callback write authority for that dispatch lineage
- pause must not leave the workflow advancing through ordinary node boundaries while the flow is paused
- if a live run still exists at pause time, controller truth must treat that run as aborting or fenced before replacement dispatch becomes legal
- operator `continue`, when present on external surfaces, is legal only for a paused flow
- operator `continue` resumes from paused controller truth by reopening the appropriate dispatch; it is not the ordinary path for yielded child handoff, worker-to-parent wake, or retry advancement
- paused resume target precedence is:
    - after paused `yield`, reopen the child dispatch
    - after paused `retry`, reopen the retry-attempt dispatch
    - after paused ordinary live work with no accepted boundary, reopen the same-attempt dispatch

## Worked parent -> child sequence

```mermaid
sequenceDiagram
    participant C as Controller
    participant P as Parent/root node
    participant W as Child worker node

    C->>P: dispatch
    P->>C: assign_child(implement_fix, summary + selectors + transient surfacing)
    C->>C: commit child assignment + first attempt
    C->>C: regenerate child assignment.* (no child dispatch_id yet)
    P->>C: optional progress checkpoint
    P->>C: yield
    C->>C: accept boundary, but do not dispatch child yet
    C->>C: prove parent run terminal or fenced
    C->>C: consume staged child assignment
    C->>W: dispatch
    W->>C: record_checkpoint(terminal, handoff + produced_artifacts + transient_surfaces)
    W->>C: green
    C->>C: accept boundary, but do not redispatch parent yet
    C->>C: prove worker run terminal or fenced
    C->>C: wake the next relevant parent/root by ordinary dispatch
```

No external operator `continue` action participates in this ordinary parent-to-child or child-to-parent progression path.

Terminal checkpoint repair rule:

- before a parent/root commits a release decision, or before a worker closes its boundary, a later terminal checkpoint may supersede an earlier terminal checkpoint
- the controller keeps the earlier checkpoint rows as audit history
- the attempt's latest-checkpoint pointer moves to the newer terminal checkpoint
- after a staged-child decision, only an optional progress checkpoint may precede `yield`
- after `release_green` or `release_blocked`, checkpoint evidence is frozen and the node must return the matching terminal boundary

Concrete file effects in that sequence:

- parent/root may reread `_runtime/workflow-manifest.md`
- the committed child attempt may already expose `_runtime/attempts/<attempt_id>/assignment.md` before `yield`
- no child `latest-checkpoint.*` exists until the child records a real checkpoint
- no child dispatch monitoring files exist until the child `dispatch_id` exists

The key high-level safety rule is unchanged: neither the child dispatch nor the later parent/root redispatch may open until the prior live run is naturally terminal or fenced.

## Dispatch preparation rule

The controller prepares a dispatch only when:

- exactly one current node is eligible to run now
- no higher-precedence public boundary must be returned first
- the current assignment and attempt for that node are current and legal
- no pause, stale-currentness, or recovery rule forbids dispatch now

Sibling nodes do not dispatch concurrently in v1.

Parallel-task note:

- sibling nodes inside one task flow do not dispatch concurrently in v1
- different tasks may still dispatch and execute concurrently because each task has separate flow/assignment/attempt/dispatch lineage

## Retry rule

Retry is node-self only.

Rules:

- retry keeps the same assignment
- retry always mints a new attempt
- retry always uses `full_prompt`
- the retrying node rereads the same assignment, the prior terminal checkpoint, and the current surfaced durable and transient refs for that assignment
- retry opens a fresh Gateway session and a fresh live Gateway run

## Structural mutation rule

`add_child`, `update_child`, and `remove_child` act on already-running runtime truth.

Rules:

- runtime CRUD does not invoke the launch compiler
- the runtime validator still owns semantic graph validation, role/policy compatibility, dependency legality, runtime currentness, and evidence/release legality
- candidate-graph dependency legality must be checked before commit
- after successful commit, the runtime materializer/projector regenerates stable projections such as `_runtime/workflow-manifest.*`

## Removed from the live v1 model

This page no longer teaches or owns:

- `parent_gate`
- gate-era boundary subtype families
- `BoundaryAction`
- parent-facing callback decision envelopes
- public child retry control
- a separate public reassignment control verb
- child replacement control
- manifest/session/ack-field callback naming in the target contract

## Related contracts

- [Glossary and boundaries](glossary-and-boundaries.md)
- [Runtime records and lifecycle](runtime-records-and-lifecycle.md)
- [Runtime database and object contract](runtime-database-and-object-contract.md)
- [Assignment contract](assignment-contract.md)
- [Checkpoint contract](checkpoint-contract.md)
- [Runtime observability and boundary log](runtime-observability-and-boundary-log.md)
- [Worker context contract](worker-context-contract.md)
