# Runtime records and control state

Status: Target

This page owns the V2 relational records, lifecycle fields, lineage constraints, and current-state read model required by the exact-source runtime. It does not own provider transport handles or process-local `DispatchMcpBinding` state.

## Authority model

Controller database rows own task, flow, assignment, attempt, dispatch, source, wait, plan, checkpoint, pause, and event truth. Request files own only the exact bytes referenced by one committed dispatch. Provider output, provider/MCP sessions, process handles, in-memory signals, and support projections are never current-state authority.

## Task and flow

The task owns stable product identity and definition/workspace provenance. The active flow owns the current execution lineage and high-level control state.

The flow stores at least:

```yaml
flow:
  flow_id: string
  task_id: string
  status: running | paused | completed | cancelled
  terminal_outcome: green | blocked | null
  current_dispatch_id: string | null
  waiting_cause: none | human_request | command_run
  waiting_source_id: string | null
  control_revision: integer
  pause_reason: string | null
  pause_details: bounded object | null
  paused_at: timestamp | null
  paused_by_actor_ref: string | null
```

`current_dispatch_id` points only to a `starting` or `open` dispatch. Closed dispatches remain in lineage but never current authority.

`terminal_outcome` is null unless `status = completed`. A completed green root stores `green`; a completed root whose accepted blocked release closes the task stores `blocked`. `blocked` is a semantic terminal outcome, not a second flow lifecycle state and not an infrastructure pause.

`waiting_source_id` is a convenience pointer backed by the exact source row. The source row and its relationship constraints remain authoritative when the pointer disagrees.

## Assignment and attempt

Each active flow node and immutable node-plan revision preserves the optional authored provider kind from its compiled workflow node. Structural add/update adoption preserves the same field. A missing provider kind means configured-default resolution at successor preparation time; it is not filled with a fallback or copied from a predecessor dispatch.

Assignments own declared work, role, criteria, consume/produce slots, parent/child relationships, assignment-scoped child/retry budget, and the optional current work plan. Attempts own semantic execution tries for an assignment.

The assignment snapshots the applicable pinned policy limit when it is created:

```yaml
child_assignment_limit: integer | null
child_assignments_remaining: integer | null
retry_limit: integer | null
retries_remaining: integer | null
```

Null means the budget axis does not apply or is unlimited. A parent/root child assignment decrements `child_assignments_remaining` in the same conditional transaction that creates the staged child assignment. A semantic retry decrements `retries_remaining` in the same conditional transaction that creates the new attempt. A rejected, stale, duplicate, or losing operation consumes nothing. Human/command continuation, watchdog replacement, provider-start retry, restart, and operator continue consume neither budget.

Infrastructure continuation—provider-start retry, human/command continuation, watchdog replacement, process restart, and operator continue—remains on the same assignment and attempt. Only the semantic boundary outcome `retry` creates a new attempt.

## Dispatch

The controller dispatch lifecycle is exactly:

```text
starting -> open -> closed
```

There is no `closing` state and no state whose purpose is to wait for provider stop.

Minimum dispatch fields:

```yaml
dispatch:
  dispatch_id: string
  task_id: string
  flow_id: string
  assignment_id: string
  attempt_id: string
  node_key: string
  flow_start_source_flow_id: string | null
  predecessor_dispatch_id: string | null
  status: starting | open | closed
  opened_reason: root | boundary | child_return | human_result | command_result | watchdog_recovery | semantic_retry | operator_continue
  requested_provider: codex | claude | openclaw
  resolved_provider: codex | claude | openclaw
  provider_selection_basis: explicit | default
  provider_route: strict non-secret discriminated route
  created_at: timestamp
  adapter_started_at: timestamp | null
  last_node_activity_at: timestamp | null
  node_activity_revision: integer
  closed_at: timestamp | null
  closed_reason: boundary | human_request_wait | command_run_wait | watchdog_superseded | paused | cancelled | control_failed | task_terminal | null
```

`opened_reason` explains why the turn opened. Exact source identity remains in the owned flow-start, boundary, human, command, retry, or predecessor relationship rather than a generic JSON envelope.

The first dispatch of a flow has no synthetic predecessor and links the exact `FlowStartSource` through `flow_start_source_flow_id`. Its ordinary automatic opening uses `opened_reason = root`; a directly awaited repair of that same retained pre-root source uses `opened_reason = operator_continue`. Every later dispatch has one predecessor and no flow-start-source link.

The target has no fallback chain, so `requested_provider` and `resolved_provider` match. Both remain for provenance together with `provider_selection_basis`. `provider_route` stores only the normalized non-secret variant needed by the chosen adapter; it contains no native config body, credential, binding, or continuity identifier.

A dispatch is immutable with respect to task, flow, assignment, attempt, node, predecessor, and resolved provider route after commit.

A current `starting` dispatch may close directly only for `boundary`, `human_request_wait`, `command_run_wait`, `paused`, `cancelled`, `control_failed`, or `task_terminal`. `watchdog_superseded` is legal only from `open`. A provider-acceptance write is conditional on the same dispatch still being current and `starting`; any direct close wins permanently and late acceptance cannot reopen it.

## Workspace binding

Each task owns exactly one logical workspace-binding row:

```yaml
workspace_binding:
  task_id: string
  binding_mode: controller_owned | external
  normalized_root_path: string
  bound_at: timestamp
```

The binding is path provenance and logical-root resolution, not a lease. Multiple live tasks may bind the same normalized external workspace concurrently. No lease table, unique-path exclusion, OS lock, database lock, release transition, or terminal cleanup exists. Pause, cancel, and task completion leave the binding unchanged. Reset never derives a deletion target from a workspace binding and never deletes an external workspace.

## Dispatch capability set

Each dispatch owns one frozen effective capability record:

```yaml
dispatch_capability_set:
  dispatch_id: string
  provider_native_access:
    effective: full | restricted | denied
    source: default | policy_definition | task_policy | controller
  network_access:
    effective: allow | deny
    source: default | policy_definition | task_policy | controller
  human_direction: allow | deny
  human_approval: allow | deny
  human_input: allow | deny
  human_review: allow | deny
  command_run: allow | deny
```

This is controller-derived runtime truth, not authored policy or provider configuration. The two source-bearing objects preserve both the frozen effective value and why that value won. Resolution takes the most restrictive applicable ceiling. When equally restrictive ceilings tie, source attribution is `controller > task_policy > policy_definition > default`; adapter and local hard ceilings report `controller`.

A successor recomputes the record. Role/tool exposure also rereads current role and policy before every Node call; a cached capability row never widens stale dispatch authority. Provider selection provenance remains a separate dispatch record and never substitutes for capability provenance.

## Provider-start retry fields

A current `starting` dispatch persists only the facts required to recover delayed provider start:

```yaml
provider_start_revision: integer
provider_start_attempt_count: integer
next_provider_start_at: timestamp
provider_start_retry_kind: initial | definite_failure | uncertain_acceptance
provider_start_last_error_code: string | null
```

Rules:

- revision and attempt count are non-negative and monotonic;
- `next_provider_start_at` is non-null while the dispatch remains retryable `starting`;
- a successful start moves the dispatch to `open`, sets `adapter_started_at`, and clears due/retry/error fields as appropriate;
- no maximum-attempt or exhausted-at field exists; and
- errors are normalized/sanitized, never raw provider payloads or credentials.

Any `starting` dispatch recovered after process restart whose prior external call cannot be excluded is treated as `uncertain_acceptance` for the next stop-and-retry sequence.

Every provider-origin start failure updates and reschedules this same current `starting` dispatch. It never creates a successor, a semantic retry attempt, or a provider-start exhaustion pause.

## Dispatch prompt refs

Each dispatch has exactly one refs-only request record:

```yaml
dispatch_prompt_refs:
  dispatch_id: string
  instructions_logical_path: string
  input_logical_path: string
  dynamic_input_version: integer
  created_at: timestamp
```

The row contains no prompt text, hash, static/catalog/renderer version, provider session, physical root, or readiness state. The two logical paths are immutable after commit.

## Activity and Node invocation audit

`last_node_activity_at` and `node_activity_revision` are updated once for every admitted exact-current Node MCP invocation. The revision is the watchdog generation and must be usable in a conditional `UPDATE`/compare-and-swap predicate.

A minimal optional invocation audit row may store:

```yaml
node_invocation:
  invocation_id: string
  task_id: string
  dispatch_id: string
  logical_tool_name: string
  outcome_code: string
  started_at: timestamp
  ended_at: timestamp
```

It stores no request/response bodies, binding credential, provider payload, raw human answer, command log, or hidden reasoning. It is audit/support data, not a task-event source or watchdog authority.

## Boundary source

An accepted boundary binds exactly to its source dispatch, assignment, attempt, outcome, required checkpoint/evidence, commit time, and optional successor dispatch ID.

One source dispatch may have at most one accepted boundary and at most one successor. Boundary acceptance closes D1 in the same transaction; asynchronous continuation later fills the one successor relationship if still legal.

## Assignment decisions and release basis

A source dispatch may own at most one immutable assignment-decision fact. Its discriminator is exactly one of:

- `staged_child`, binding one direct child assignment and its first attempt;
- `release_green`, binding the current assignment, structural revision, selected checkpoints, and exact artifact versions used to justify release; or
- `release_blocked`, binding the root assignment, structural revision, selected blocked checkpoints, and exact descendant terminal facts used to justify whole-flow blocked release.

The discriminator and database checks make staged-child and release decisions mutually exclusive for one dispatch. Evidence membership is stored through typed association rows to controller IDs and artifact versions, not as copied provider prose or a generic JSON authority envelope. A later boundary references the decision fact it consumes. Decision facts do not close a dispatch by themselves.

Assignments store explicit `parent_assignment_id` lineage. A staged-child decision binds its child to the current parent assignment, authoring dispatch, source structural revision, and first attempt. The one accepted `yield` that consumes it records the consumption; no timestamp or latest-child query may choose a child.

## Human-request source

Each human request binds to:

- task, flow, assignment, attempt, and source dispatch;
- typed request kind/items and capability basis;
- immutable `due_at` and timeout/default policy when configured;
- `open | resolved | timed_out | cancelled` status;
- typed terminal resolution/provenance; and
- optional successor dispatch ID.

Opening the request creates the wait and closes D1 atomically. Terminalization clears only the matching wait. The source remains a watchdog exclusion until its continuation is consumed or the flow becomes terminal.

## Command-run source

Each command run binds to:

- task, flow, assignment, attempt, and source dispatch;
- command specification, cwd policy, environment-reference policy, timeout, and log refs;
- `pending_start | running | cancellation_requested | succeeded | failed | timed_out | cancelled | abandoned` state;
- process ownership revision and bounded locally owned process metadata;
- terminal result/provenance; and
- optional successor dispatch ID.

`cancellation_requested` is nonterminal. Terminal state commits only after the owning process outcome rules, including termination and reap for cancellation, are satisfied.

`pending_start` stores `due_at = null`, even when the request has a timeout. Successful process start stores immutable `started_at` and, when a timeout applies, immutable `due_at = started_at + timeout_seconds`. Restart-time loss of exact ownership terminalizes the durable source as `abandoned` with `terminal_failure_code = command_ownership_lost`; it never authorizes blind relaunch or termination.

Any command-run row owned by D1 remains a watchdog exclusion until its exact continuation is consumed or the flow becomes terminal, including terminal-but-unrouted command state.

## Waiting cause

At most one human request or command run may own the current flow wait. Opening either source, setting the matching wait, and closing D1 is one transaction.

Terminal source state and flow pause are orthogonal. A source may terminalize while paused; its successor remains absent until legal continue or resumed routing consumes it.

## Pause and control revision

Pause stores reason, bounded details, timestamp, actor/subsystem owner, and monotonic `control_revision`.

Minimum automatic reasons are:

- `runtime_recovery_exhausted` for watchdog cap exhaustion; and
- `runtime_transition_failed` for deterministic controller/request integrity failure.

Provider connection/start failure and uncertain acceptance do not create a pause reason; the current D2 stays `starting` and retries.

Operator pause uses its explicit operator reason. A local loopback control mutation records stable `local_operator` surface provenance without claiming an authenticated human identity. The pause transaction closes any current `starting` or `open` dispatch and clears current authority while retaining an active external source and any terminal result.

Operator continue requires the caller's observed `control_revision`, a paused nonterminal flow, no unresolved active wait, and an exact unconsumed continuation source or lawful lineage tail. Its final transaction moves the flow to `running` and creates at most one successor.

## Work plan and checkpoint

The current work plan is assignment-owned and optional. The assignment stores a monotonic `work_plan_revision`. The setter accepts zero to nine ordered steps; a present snapshot stores one to nine steps plus that revision, optional explanation, authoring dispatch, and commit time. `steps: []` increments the revision only when a current plan exists, then clears the current snapshot.

Checkpoints are immutable assignment/attempt evidence rows with exact authoring dispatch identity, bounded summary/evidence, declared refs, and terminal outcome when required. Each attempt stores an optional exact `latest_checkpoint_id` pointer updated in the same checkpoint transaction. A plan never substitutes for a checkpoint or boundary.

The exact contract belongs to [Work plan and checkpoint](work-plan-and-checkpoint-contract.md).

Artifact publications are immutable version rows owned by one task, assignment, attempt, checkpoint, declared slot, and logical path. Versions are monotonic within one assignment and slot. The current pointer references that exact publication. A boundary that relies on a publication reaches it through its checkpoint or immutable decision-basis association; filesystem presence cannot supply the link.

Transient localizations are separate first-class rows containing task, assignment, attempt, optional checkpoint, logical source provenance, localized logical path, description, retention status, and timestamps. `active` has no `removed_at`; `expired` has an exact `expires_at` generation and no `removed_at`; `removed` has both timestamps. A transient row never receives an artifact version/current pointer and never becomes durable merely because a checkpoint references it. Checkpoint-to-transient association rows preserve the exact surfaced set.

## Watchdog recovery lineage

Watchdog recovery count is derived or persisted from exact same-attempt predecessor lineage with `opened_reason = watchdog_recovery`; it must not rely on provider events or support files.

The recovery transaction matches D1's activity revision and due time, closes D1, and creates D2 atomically. D2 carries `predecessor_dispatch_id = D1` and the same assignment/attempt.

Exhaustion stores the pause/control transition and closes D1 without a successor.

## Constraints and indexes

Database-enforced backstops must work in both supported SQLite and PostgreSQL lanes:

- unique first dispatch per flow where `predecessor_dispatch_id IS NULL`;
- unique non-null predecessor dispatch ID;
- partial unique current dispatch per flow where status is `starting` or `open`;
- one prompt-ref row per dispatch;
- one capability-set row per dispatch;
- requested/resolved provider equality and a valid provider-route discriminator;
- unique accepted boundary per source dispatch;
- unique assignment-decision fact per source dispatch, with discriminator-specific ownership checks;
- unique current external source/wait relationship;
- exactly one of human-request ID or command-run ID on a present flow wait;
- immutable source-dispatch lineage on human requests and command runs;
- one current work-plan snapshot per assignment, ordered step indexes `0..8`, and at most one `in_progress` step;
- non-negative assignment budget limits and remaining values, with each remaining value bounded by its present limit;
- an attempt's latest-checkpoint pointer bound to the same task, flow, assignment, and attempt;
- artifact publication ownership through an exact checkpoint and versioned current pointer;
- typed transient provenance and checkpoint association without an artifact pointer;
- non-negative activity, provider-start, plan, ownership, and control revisions; and
- foreign keys for task/flow/assignment/attempt/dispatch/source relationships.

Conditional controller writes repeat currentness and source predicates; constraints are the final safety net, not a replacement for useful conflict errors.

## Task events and readbacks

Task events are bounded chronology emitted from committed source changes. They may identify dispatch creation/open/close, boundary acceptance, wait open/terminal, plan/checkpoint changes, pause/continue/cancel, provider-start retry schedule/acceptance, and watchdog recovery.

Events do not carry in-memory signal state, provider output, binding credentials, raw human answers, command logs, or provider/MCP session IDs.

Current API/console/CLI readbacks may expose:

- dispatch state and lineage;
- `adapter_started_at`, Node activity timestamp/revision, and computed watchdog due time;
- provider-start attempt count, next due time, retry kind, and sanitized error;
- active wait/source summary;
- watchdog recovery count and pause/control revision;
- provider selection provenance; and
- `provider_native_access` and `network_access` effective values with their exact controlling sources.

They do not present support projections or events as current authority.

## Process-local and provider-private state

The following are explicitly absent from relational controller truth:

- `DispatchMcpBinding` and bearer credentials;
- MCP protocol session IDs;
- Codex/Claude/OpenClaw thread, session, or run IDs as authority;
- live SDK clients, subprocess handles, tasks, and cancellation tokens;
- provider output/events/final responses; and
- in-memory deadline or queue generations beyond their durable source values.

Adapters may hold private resources during the process lifetime, but restart discards them and the exact-source audit reconstructs only controller work.

## Reset boundary

This target is reset-only relative to the shipped V1 runtime schema. Remove obsolete NodeSession, provider delivery/continuity/watchdog/provider-event families, prompt body/hash/request envelopes, `closing`, semantic `last_progress_at`, finite launch-exhaustion fields, and generic provider session/run identifiers. Stale local databases fail with clear `autoclaw db reset` guidance rather than receiving compatibility shadow columns.

Reset is destructive schema replacement, not migration or repair:

- ordinary startup creates tables only for a genuinely empty database; a nonempty database must match the exact table, column, foreign-key, check, and required-index contract without DDL;
- SQLite reset rejects a symlinked configured database path, removes only that configured file and its safe sidecars, recreates the full schema, and restores seeds;
- PostgreSQL reset requires a dedicated AutoClaw schema and operator-assured exclusive service ownership, then drops and recreates that schema before restoring seeds;
- reset never copies compatible rows, repairs legacy columns, or creates a backup; and
- before schema destruction, reset reads controller-owned task roots, deletes only roots contained beneath the configured AutoClaw data boundary, rejects a symlink as a deletion root, does not traverse child symlinks, and never treats workspace bindings as deletion targets.

Exclusive service ownership is an operator precondition, not a runtime lease or distributed-lock protocol. This phase does not add a database-owner marker or infer ownership from a generic service status. The CLI must state the destructive precondition and may refuse only when a later reliable, configuration-matched owner check exists.

## Required proof

- SQLite and PostgreSQL enforce one root, one successor, and one current starting/open dispatch;
- concurrent source handlers produce one winner without a broad lock;
- D1 close and source/wait creation are atomic;
- watchdog D1 close and D2 creation are atomic;
- provider retry updates one current D2 and has no exhaustion field;
- every admitted Node call increments activity revision once;
- source completion while paused is retained without successor;
- current readbacks derive from controller rows;
- capability readbacks preserve both independent effective values and deterministic source attribution; and
- removed secrets/provider/session/support fields do not survive reset.

## Related

- [ADR-0009: exact-source runtime control](../../../adr/ADR-0009-exact-source-runtime-control.md)
- [Runtime lifecycle and watchdog](runtime-lifecycle-and-watchdog.md)
- [Controller contract and resumable execution](controller-contract-and-resumable-execution.md)
- [Task root and file access](task-root-and-file-access.md)
- [Managed Node MCP binding](managed-node-mcp-binding.md)
