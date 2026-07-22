# Runtime target

Status: Target

Decision record: accepted 2026-07-22; revised 2026-07-23.

## Runtime grammar

Banksia deliberately keeps authoring simpler than execution. A published Workflow suggests a responsibility tree. The controller records the actual work with this target record family:

```text
Task
  pinned Workflow revision
  current TeamRevision
  root Assignment

TeamRevision -> Member configurations
Assignment -> Attempt -> Dispatch + exact DispatchRequest
                   \-> AttemptWait -> HumanRequest | CommandRun | DelegationWave
DelegationWave -> ordered members -> child Assignments
Checkpoint -> optional internal AcceptedBoundary
WorkPlan
TaskStartRequest -> root Assignment ordered FileReference values
Assignment | Checkpoint | HumanRequest -> ordered FileReference values
Continuation | Result | TaskActivity -> exact readback of owning values
TaskEvent -> semantic product projection
```

Task owns global lifecycle, outcome, workspace binding, pinned Workflow, current team head, control authority, and the exact accepted root result relationship. The final target has no one-to-one Flow record.

The database is controller truth. Signals, provider process state, conversation history, ordinary assistant output, filesystem projections, and UI state cannot authorize or complete work.

## Member responsibility

`Member` is the structural noun. Two labels are derived from current position:

- the top member is the **Task lead**;
- a member with current direct children behaves as a **Manager**;
- a member without current direct children behaves as a **Contributor**.

These labels are never authored member kinds and never persisted as a mutable mode. A structural change can therefore change behavior on the next fresh context without a mode-transition record.

Each Member configuration also pins its requested provider selection and optional requested Human Request/Command Run grants. Capabilities do not inherit through the tree. The effective action set is the intersection of that Member's pinned request, current controller/deployment policy, and current Dispatch legality. Policy may narrow or revoke but never widen an authored grant; every Dispatch stores exact requested/effective provenance and receives only effective tools and prompt teaching.

### Manager contract

A Manager retains the complete parent Assignment and owns:

- orientation and interpretation;
- decomposition and dependency judgment;
- child-specific Assignment prompts;
- sequential, parallel, iterative, batch, and hybrid choices;
- returned Checkpoint and referenced-file inspection;
- acceptance, rejection, and conflict resolution;
- integration decisions and proportionate verification; and
- the complete parent Checkpoint.

It is a quality failure for a Manager to copy its Assignment unchanged to a child and then restate the child Checkpoint as its own result. Banksia evaluates anti-relay behavior rather than creating similarity gates or another runtime approval record.

While children exist, the prompt tells a Manager not to replace their substantive execution. The controller cannot reliably classify every native shell command or file edit as managerial versus contributor work, so it enforces the objective completion rule and leaves semantic accountability to prompting, evaluation, and audit. A Manager that intends to take over direct execution must remove all direct children first and continue under fresh Contributor context.

### Required participation

Before a Manager can finish green, every **current direct child configuration** must have at least one accepted green terminal return whose recorded Assignment-pinned branch basis equals that direct-child branch's basis in the current TeamRevision.

- “At least once” allows repeated implementation, review, repair, and batch Assignments.
- A blocked return settles work but does not satisfy participation.
- A retry does not satisfy participation.
- Adding or execution-relevantly updating a member gives that member and every containing ancestor branch a new basis. Untouched sibling branches retain their basis and accepted participation.
- Removing a child removes its future obligation but never removes historical work.
- Unchanged prior returns remain historical evidence but cannot validate a new configuration basis.
- An irrelevant child should be removed, not given filler work.

Assignment records pin the member configuration and branch basis they execute; an accepted green return records that basis as the participation it satisfies. Terminal green admission derives participation by exact current-basis relationship, never timestamp or broad revision comparison, rather than introducing an authored criteria/evidence model.

## Work Plan and planning patterns

Work Plan remains an optional controller record containing the agent’s current intended approach and progress. It may be revised as evidence arrives. It is not a user-authored Workflow step list, a scheduling engine, or completion proof.

Preserve the current small assignment-owned operation:

```yaml
set_work_plan:
  explanation: Optional short reason for replacing or clearing the plan.
  steps:
    - step: Concise outcome-oriented work item.
      status: pending # pending | in_progress | completed
```

- zero to nine ordered steps of 1–512 normalized characters are accepted; `steps: []` clears the plan;
- at most one step is `in_progress`, while zero or all-completed are legal;
- optional explanation is 1–1,024 normalized characters when present;
- the complete normalized list replaces the previous snapshot atomically;
- repeated or whole-field filler such as `todo`/`tbd` rejects;
- an identical normalized request is an accepted no-op;
- Assignment owns the current snapshot, monotonic private revision, optional explanation, authoring Dispatch, and commit time; and
- a new Assignment starts without a plan, while same-Assignment continuations and recovery keep the current snapshot.

Plan completion never routes work, satisfies child participation, records a Checkpoint, settles a Wave, or completes an Assignment. The product may render the current human-readable steps, but private revisions and authoring Dispatch identity remain support/audit facts. No Work Plan file is projected under `.banksia/`.

The Manager prompt teaches five complementary planning views. Their familiar orchestration names are included for precision, not as additional runtime concepts:

| Banksia pattern | Familiar orchestration term | Use |
| --- | --- | --- |
| Sequence | Sequential orchestration or prompt chaining | A later contribution depends on an earlier result, or shared-state risk requires one-at-a-time work. |
| Parallel | Concurrent orchestration or fan-out/fan-in | Contributions can remain independent until the Manager's join and integration. |
| Iterative | Evaluator-optimizer or feedback loop | Evaluation supplies concrete feedback for a fresh semantic Assignment. |
| Batch | Bounded map over items | A finite set of similar, independently scoped items can use a reusable Member or subtree; sequence or parallelism still determines scheduling. |
| Hybrid | Adaptive composition | The Manager combines the other patterns as evidence and dependencies become known. |

Iteration is not retry. Batch describes repeated scope, while sequence or parallelism describes scheduling. Neither requires an authored mode or separate runtime engine.

## Task start and initial materialization

One atomic start service:

1. validates the strict TaskStartRequest, selected Workflow, provider intent, requested built-in capabilities, workspace, and ordered file references;
2. reads and pins the current published Workflow revision;
3. allocates Task identity `t_<8 lowercase Crockford-base32 characters>`;
4. creates a collision-safe Task directory carrying an unambiguous controller-owned initialization marker, including empty `notes/`, `artifacts/`, and `command-runs/`;
5. calls `materialize_initial_task_team` to create Task-scoped Member identity, immutable MemberConfiguration rows, the first ordered TeamRevision, and the initial branch-participation bases from the pinned Workflow revision;
6. renders `manifest.md` and the optional `workflow-note.md` in that marked directory before any provider Dispatch can start;
7. creates the immutable root Assignment from the exact Task prompt and validated ordered `FileReference` values;
8. creates its first Attempt and exact first Dispatch request, stores the pinned Workflow revision and `Task.current_team_revision_id`, and commits DB truth;
9. clears the initialization marker only for that committed Task and publishes provider-start work afterward; and
10. returns an accepted receipt rather than claiming provider startup finished.

A validation rejection performs no Task, workspace, reference, Dispatch, or provider mutation. A crash or filesystem/DB failure after staging may leave only its controller-marked initialization directory. Startup recovery may remove that directory only when no Task committed; a committed Task with a remaining marker is repaired in place. Reset and generic cleanup never recursively delete an accepted `.banksia/t_<id>/` directory.

Workflow-authored Member IDs become Task-scoped Member identities. They and controller-issued replan IDs are unique and never reused within one Task, not in a global namespace across unrelated Workflows or Tasks. Every immutable MemberConfiguration records its predecessor/basis and the TeamRevision that selects it; Assignments pin the exact MemberConfiguration and branch basis they execute.

## Assignment, Attempt, and Dispatch

### Assignment

Assignment is the semantic mission owned by one member:

```text
Assignment
  id
  task_id
  parent_assignment_id?
  member configuration basis
  prompt
  ordered FileReference values
  creating Dispatch/source
```

Its prompt and inputs are immutable. A fresh meaning creates a new Assignment. Retry retains the same Assignment.

### Attempt

Attempt is one execution attempt at an Assignment. It owns one local lane:

```text
running Attempt
  current Dispatch XOR one AttemptWait

terminal Attempt
  neither current Dispatch nor wait
```

At most one current/first Dispatch exists per Attempt. Same-Attempt Dispatch predecessor lineage never pretends that a child first Dispatch is the parent’s successor. Typed sources own cross-Attempt causality:

- Task start -> root first Dispatch;
- Wave member -> child first Dispatch;
- accepted retry boundary -> replacement Attempt first Dispatch;
- prior same-Attempt Dispatch or terminal wait source -> continuation Dispatch.

### Dispatch and request

Dispatch is the exact current provider turn. It commits with one immutable request:

```text
DispatchRequest
  dispatch_id
  exact resolved instructions
  exact resolved input
  created_at
```

Adapters receive those two strings and exact effective provider configuration. They do not rerender from current Workflow or filesystem state. Restarting the same Dispatch resends byte-identical strings. A successor Dispatch receives a new request containing its exact continuation.

Assignment and continuation lineage remain distinct. Every Dispatch input contains the complete Assignment. An initial Dispatch has no Continuation or trigger. A successor has exactly one typed Continuation whose nested trigger owns:

```text
trigger.kind    why this continuation exists
trigger.source  exact committed controller source
trigger.result  complete typed result needed to act
```

For example, a child-Wave result contains every complete returned child Assignment and terminal Checkpoint; a Human Request or Command Run contains its complete typed response. The trigger is not a compact reason code, a second Assignment, or a lookup for the latest result.

Provider terminal success never implies Assignment success. Only a successful controller action can record a Checkpoint, open a wait, or complete the work.

## One Checkpoint action

A Checkpoint is Banksia's durable, teammate-facing work report for an exact Assignment execution. It is not a saved workflow-state snapshot or provider transcript. Controller state remains in the records that own it; the Checkpoint communicates the result, evidence, limits, and next relevant action.

Agent-facing contract:

```yaml
checkpoint:
  summary: Concise reached state or result.
  details: Optional Markdown expansion.
  files:
    - path: .banksia/t_7m4k2d9x/artifacts/review-report.md
      description: Optional reason the receiver should inspect it.
  outcome: green # optional: green | blocked | retry
```

`summary` is always required and nonblank. `details` and file references are optional.

Outcome has one decisive rule: omission is progress; every present value is a terminal Checkpoint outcome for the exact current Dispatch. The three terminal outcomes differ in scope:

| Outcome | What terminates | What remains |
| --- | --- | --- |
| `green` | Dispatch, Attempt, and Assignment | A parent may integrate the completed contribution. |
| `blocked` | Dispatch, Attempt, and Assignment | A parent or user receives the blocker and decides what follows. |
| `retry` | Dispatch and Attempt | The exact immutable Assignment stays open for a fresh Attempt when budget permits. |

The internal AcceptedBoundary preserves all three terminal outcome variants. Replacing `return_boundary` with `checkpoint` must never collapse or discard retry; only the old delegation-yield transfer moves to `delegate` and its controller-owned wait.

### Progress-only

When `outcome` is omitted, the controller records a progress Checkpoint tied to the exact Assignment, Attempt, authoring Dispatch, and ordered file references. The Dispatch remains current. No AcceptedBoundary is created.

### Green or blocked

One transaction:

1. authenticates exact current Dispatch authority;
2. validates and records declared file references;
3. records the terminal Checkpoint;
4. records the internal accepted `green` or `blocked` Boundary;
5. closes and clears the Dispatch;
6. completes the Attempt and Assignment;
7. settles its Wave member when applicable; and
8. commits before settlement hints.

Green additionally enforces current direct-child participation. Blocked is a real terminal teammate result and does not automatically cancel siblings or decide the parent outcome.

### Retry

Retry is legal only while the snapshotted Assignment retry budget remains. One transaction records a terminal retry Checkpoint plus internal accepted retry Boundary, closes the current Dispatch and Attempt, and creates the next Attempt and exact first Dispatch from that retry source. The Assignment remains open. A retry is therefore terminal for the current execution attempt, not terminal for the semantic work. It never settles participation or a Wave member and never becomes the Task Result.

Provider-start retries and watchdog replacement are infrastructure behavior on the same Dispatch/Attempt semantics; they are not semantic retry.

### Task result

The accepted terminal `green` or `blocked` Checkpoint of the root Task lead's Assignment is the exact Result presented to the user. A terminal `retry` Checkpoint belongs only to its completed Attempt and produces no Result:

```text
accepted root Boundary
  -> its exact Checkpoint
  -> product Result projection
```

There is no TaskResponse table, copied final prose, final-summary model call, latest-by-time query, or provider-output fallback. Completed and blocked Results both expose exact outcome, summary, optional details, file references, and completion time. Cancellation or infrastructure failure without an accepted root green/blocked Checkpoint is status, not a fabricated Result.

## Attempt waits

An `AttemptWait` is one persisted, typed, nonterminal source relation. Exactly one source is set:

```text
AttemptWait
  attempt_id
  source_dispatch_id
  delegation_wave_id? XOR human_request_id? XOR command_run_id?
  created_at
```

The Attempt owns the wait because its execution is suspended. The source owns its result. A wait and current Dispatch cannot coexist.

Signals are disposable post-commit hints:

- `WaveMemberSettled(wave_id)` asks the controller to test the join;
- `DelegationWaveSettled(wave_id)` asks it to open a parent continuation;
- human and command terminal hints do the same for their source family;
- `AttemptContinuationDue` may later unify work routing if it materially simplifies handlers, but it is not required.

Every handler rereads authoritative state and may safely no-op when duplicated, late, paused, cancelled, stale, or already consumed.

## Delegation Waves

A Delegation Wave is Banksia's controller-managed fan-out/fan-in unit. One parent atomically starts one or more current direct-child Assignments, then resumes exactly once after every Wave member has returned a terminal `green` or `blocked` Checkpoint.

Agent operation:

```yaml
delegate:
  assignments:
    - child_id: implementer
      prompt: Implement the bounded fix and verify it.
      files: []
    - child_id: reviewer
      prompt: Review independently without editing.
```

Each entry targets a current direct child and becomes a fresh immutable Assignment. The public operation is exactly the `delegate` wrapper above with its ordered `assignments` list; it adds no summary/details, criteria, outputs, mode, or schedule.

### Fan-out transaction

`delegate` validates the entire request, then atomically:

1. verifies the Task and exact parent Attempt/Dispatch are current and running;
2. resolves current direct children, participation basis, budgets, provider configuration, and the `1..max_wave_members` bound;
3. creates one immutable ordered DelegationWave and member rows;
4. creates every child Assignment, first Attempt, first Dispatch, and exact DispatchRequest;
5. closes the parent source Dispatch for delegation;
6. clears the parent Attempt’s current Dispatch and creates its Wave wait; and
7. commits all-or-none.

Only after commit does it publish one start hint per child Dispatch. Lost hints are recoverable from committed `starting` Dispatches.

Default controller settings are:

```toml
[runtime]
max_child_assignments_per_assignment = 20
max_retries_per_assignment = 1
max_wave_members = 8
```

A Wave of N consumes N child-Assignment units. The baseline rejects an oversized Wave atomically. It does not queue excess work or impose a Task-wide active-lane ceiling. Nested total concurrency is therefore an explicit known operational risk until the deferred scheduler is designed.

### Member settlement

A green or blocked child terminal transaction conditionally fills that exact Wave member’s previously null terminal-boundary relationship. It commits before publishing `WaveMemberSettled`. Retry leaves the relationship null.

### Wave settlement

A fresh conditional transaction changes an open Wave to settled only when no member remains without a terminal boundary. The winning transaction clears the exact matching Wave wait and commits before `DelegationWaveSettled`. Duplicate or early handlers do nothing.

Blocked is a terminal Wave-member result, not a runtime exception. Siblings continue and the Manager receives every result through the collect-all join.

### Parent continuation

A separate idempotent transaction opens a continuation only when:

- the Wave is settled and has no successor;
- all members still have exact terminal boundaries;
- the parent Attempt has neither current Dispatch nor wait;
- global Task lifecycle permits work; and
- structural/control authority still permits the continuation.

It loads complete child Assignments, terminal Checkpoints, outcomes, and file references in authored `order_index`, creates exactly one same-Attempt parent successor Dispatch and request, records that successor on the Wave, and commits before start publication. Pause may delay this transaction without losing the settled result; cancellation makes it illegal.

Startup recovery discovers:

- open Waves whose members are all terminal;
- settled Waves without a successor;
- due current/startable Dispatches; and
- terminal human/command sources not yet continued.

### Recursive join

For `A -> [B,C,D]`, `B -> [E,F]`, and `E -> [G,H]`, A, B, and E each wait on their own local Wave. G/H settle E’s Wave and resume E; only E’s later terminal return settles E’s member under B. The same rule continues upward. The Assignment tree plus local Wave relations is the complete recursive join; no global stack or counter is needed.

## Shared-workspace concurrency

All lanes use the same selected workspace and may execute concurrently with full native access. The runtime does not provide isolation, automatic merges, diff handoff, path leases, or conflict-free write guarantees.

The Manager prompt must make the risk explicit:

- parallelize read-only or independently scoped work freely within the Wave bound;
- do not concurrently delegate two agents to edit the same high-value target unless ownership is credibly disjoint;
- sequence overlapping writes, or assign clearly disjoint paths and retain integration judgment;
- inspect the shared final state rather than assuming a child return still matches untouched bytes; and
- report uncertainty or collisions honestly.

This is an accountability contract, not controller-enforced write isolation.

## Replan

Replan changes the current Task’s team, never the pinned published Workflow. Every operation is authenticated by the current Dispatch; the caller is the implicit authority root and is never submitted as `parent_id`.

### Add one direct child and optional new subtree

```yaml
add_child:
  child:
    title: Research lead
    instruction: >-
      Coordinate a bounded evidence review.
    capabilities:
      human_request: [input, direction]
    children:
      - title: Source reviewer
        instruction: >-
          Verify primary sources.
```

- The top new member attaches directly under the caller.
- Every new member omits `id`; the controller allocates all IDs atomically.
- The whole nested payload is new. It cannot reference/adopt an existing node.
- Optional fields match the authored Member shape: title, description, instruction, provider, capabilities, children. Capabilities may request only typed Human Request kinds and managed Command Run; no limits, arbitrary tools, external MCP, or runtime work fields are accepted.
- New siblings append in request order.

### Update an existing descendant with recursive upserts

```yaml
update_child:
  id: member_research
  patch:
    instruction: >-
      Coordinate evidence and reconcile conflicts.
    capabilities:
      human_request: [direction, review]
      command_run: allow
    children:
      - id: member_source_review
        instruction: >-
          Recheck every primary source.
      - title: Contrarian reviewer
        instruction: >-
          Return consequential contrary evidence.
```

- The selected `id` may be any current descendant inside the caller’s subtree, but never the caller, an ancestor, sibling branch, or outside member.
- Existing IDs in nested entries must be direct children of the enclosing member and remain immutable.
- Missing nested IDs create new members at that location.
- Omitted values and `children` preserve current state.
- Explicit `null` clears nullable prose, provider, or capabilities fields.
- A capabilities patch replaces that Member's complete requested capability block. Omission preserves it; `null` clears it to default deny. Child capabilities never inherit from the caller or enclosing patch.
- Listed children add or update; unlisted children remain.
- `children: []` does not mean delete-all and should reject as ambiguous in the agent operation.
- Existing sibling order is preserved; new nodes append. No reparent or reorder occurs.

### Remove explicitly

```yaml
remove_child:
  id: member_research
```

The selected descendant and its current subtree leave the effective team. Removal never orphans, reparents, cancels, reuses an ID, or erases history.

### Transaction, history, and projection

Every replan operation:

1. authenticates the exact caller lane and reads the current TeamRevision;
2. normalizes the closed recursive payload;
3. validates ancestry, identity, depth/width/text/provider limits, and affected busy-subtree rules;
4. builds a complete candidate and allocates new IDs without exposing them;
5. writes immutable successor MemberConfigurations and one complete ordered TeamRevision, then compare-and-swap advances `Task.current_team_revision_id` from the exact predecessor;
6. records exact added/updated/removed sets and configuration provenance;
7. invalidates participation for every affected containing direct-child branch;
8. preserves all prior TeamRevisions, Members, Assignments, Attempts, Dispatches, Checkpoints, Boundaries, recorded file references, and events unchanged;
9. atomically regenerates `manifest.md`; and
10. returns fresh current direct children, participation, derived behavior, legal actions, and created/changed/removed IDs.

An accepted replan closes the source Dispatch and records its exact structural result. After `manifest.md` is confirmed current, a separate idempotent transition opens exactly one successor Dispatch on the same Attempt. Its Continuation trigger identifies the committed replan result and carries the fresh team, participation, behavior, capabilities, and legal actions. The provider stops after the accepted mutation; it never continues under the old behavior block.

If manifest projection fails, the Attempt remains in an explicit recoverable between-transitions state with no provider work started. Repair regenerates the manifest from DB truth and then performs the same one-winner successor open. It does not roll back the TeamRevision, fabricate an AttemptWait, or ask the closed provider turn to recover itself.

Updates affect future Assignments/Dispatches only. No replan mutates work already created against an older configuration. The operation rejects updates or removals affecting pending/running work; cancellation is separate.

A projection failure does not roll back committed controller truth, but it marks the Task workspace projection unhealthy and blocks later Dispatch start until repair. Agents never infer mutation success from the file.

## Human requests and command runs

HumanRequest and CommandRun retain their typed persisted lifecycle and local Attempt waits. A terminal source contains the exact typed result used by a successor. Submission commits the answer/result source; a later idempotent transition creates the successor Dispatch.

Opening either operation requires the corresponding effective Member grant and current legal action. Human Request checks its exact kind; Command Run checks the literal managed-command grant. Omission is deny, parent grants do not inherit, and controller/deployment policy can narrow at Dispatch time. A successful open atomically closes the Dispatch and creates its typed Attempt wait before any external effect. The provider must stop; other Task lanes continue independently.

The controller-owned system prompt teaches when each exposed operation is proportionate. Workflow notes and Member instructions do not carry this generic teaching. Exact request/result parameters remain in the tool contracts.

### Preserved agent operation names and simplified shapes

Keep the current semantic names `open_human_request` and `start_command_run`. They are Banksia controller tools (MCP may be an adapter transport), not user-authored external MCP extensions. A managed provider binding supplies Task/Dispatch authority; the model never submits `task_id`, `dispatch_id`, a parent selector, capability token, or compatibility scope wrapper.

`open_human_request` accepts one strict `request`:

```yaml
request:
  kind: input | direction | approval | review
  summary: Concise operator-facing purpose.
  items: # 1..3, stable request-local IDs
    - id: compatibility-boundary
      prompt: Which compatibility boundary should the team preserve?
      options: # 2..3 when used
        - id: preserve-v1
          title: Preserve v1
          description: Keep the existing public contract unchanged.
      allow_other: false # optional, default false; only with options
      allow_skip: false # optional, default false
  files: # optional ordered FileReference values
    - path: .banksia/t_7m4k2d9x/artifacts/review-report.md
      description: Evidence the user should inspect before answering.
  timeout: # optional; omission waits without a deadline
    due_at: 2026-07-23T10:00:00Z
    default_behavior: Continue blocked if nobody answers.
```

Every item supplies exactly one of `response_schema` or `options`. `response_schema` remains a bounded valid Draft 2020-12 schema because typed Input needs text, number, date, boolean, and other current product widgets. Remote schema refs, executable/custom formats, and unbounded schema bodies reject. Option and item IDs are unique. `allow_other` is legal only for option items. Timeout `default_behavior` requires `due_at`; it is bounded continuation guidance, not an implicit fabricated answer.

This preserves current typed requests while replacing `context_refs` and `suggested_human_instruction` with the same simple file path/description transfer used by Assignments and Checkpoints. The controller records the reference but does not copy or freeze the file. The open result returns the request ID and committed open state plus the instruction to stop. Terminal resolution preserves `answered | timed_out | cancelled`, typed item responses when answered, bounded summary, time, actor/surface provenance, and the exact original request for Continuation. An answered item is one closed tagged value: `{kind: value, value: ...}`, `{kind: option, option_id: ...}`, `{kind: other, text: ...}`, or `{kind: skipped}`. The last two reject unless the original item explicitly allowed them; labels are never accepted as option identity.

`start_command_run` likewise accepts one strict `request`:

```yaml
request:
  command:
    kind: argv
    argv: ["make", "test-backend"]
    # or: {kind: shell, command: "make test-backend"}
  cwd: . # optional workspace-relative directory
  timeout_seconds: 1800 # optional positive integer
  summary: Run the complete backend verification lane.
```

There is no agent-authored environment-ref list or `expected_outputs` contract. The process receives the controller-approved Task environment. A member may reference the visible Command Run log or any other useful regular workspace file through the same `files` field; no copy or capture operation exists. `cwd` must remain within the Task workspace. The argv form is preferred; shell form is explicit and never inferred from prose.

The open result returns Command ID, committed pending state, visible combined log path, and the instruction to stop. The terminal result contains exact `succeeded | failed | timed_out | cancelled | abandoned` state, bounded summary, optional exit/failure code, start/end time, combined log path, retained/observed byte counts, truncation, and terminal provenance. It contains no separate stdout/stderr refs and never copies raw output into the Continuation.

Command execution preserves commit-before-launch, exact ownership, bounded continuous draining, timeout/cancel/terminate/kill/reap behavior, startup ambiguity handling, and no blind relaunch. Its provider-visible file shape is defined in [Workspace, files, and prompt](workspace-files-and-prompt.md).

## Flow removal migration

Flow is removed only after its invariants have moved and passed one-lane proof:

1. add Attempt-local current Dispatch and typed waits while temporarily comparing them with Flow’s single pointers;
2. migrate provider start, watchdog, node authority, human requests, command runs, continuation, pause/resume/cancel, cleanup, and startup audit one source family at a time;
3. change first/current and predecessor constraints from Flow scope to Attempt scope;
4. delete Flow current Dispatch/wait fields and prove independent nested lanes;
5. introduce one-member and then multi-member Waves;
6. move residual global lifecycle/control/outcome/team-head fields directly to Task with direct tests; and
7. delete the final one-to-one Flow record.

Task-wide controls enumerate all current lanes and waits. Completion requires the accepted root result and no live descendant Attempt or Wave.

## Removed runtime concepts

The final runtime has no TaskCompose, CompiledPlan, generic Definition lookup, Role/Policy, criteria, consume/produce, release basis, evidence declarations, legacy Artifact resource/capture/slot/version/current-pointer protocol, transient localization model, per-Dispatch request files, staged child assignment, yield boundary, Flow-wide current pointer, or model-visible release operation.
