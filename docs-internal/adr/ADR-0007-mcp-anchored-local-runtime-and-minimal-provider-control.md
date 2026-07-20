# ADR-0007: MCP-anchored local runtime and minimal provider control

Status: Accepted

> **Partial supersession notice:** [ADR-0009](ADR-0009-exact-source-runtime-control.md) replaces this ADR's `LocalRuntimeSupervisor`, `AgentControlManager`, semantic-only progress clock, broad provider-control budget, stop fencing, and finite start-exhaustion model. This page remains the accepted origin of MCP-anchored controller truth, local-first scope, same-attempt infrastructure recovery, and provider-neutral adapter control.

> **Partial supersession notice:** [ADR-0009](ADR-0009-exact-source-runtime-control.md) replaces this ADR's broad supervisor/manager, semantic-only progress clock, finite provider-control budget, provider-stop fencing, mandatory attempt plan, and provider-start exhaustion details. This page remains the historical decision that established local-first controller truth, provider-output irrelevance, provider-neutral adapters, and same-attempt watchdog recovery.

## Decision summary

AutoClaw V2 is a local-first, same-host runtime whose agent-originated semantic truth arrives through committed node MCP operations. Provider adapters expose only start and stop control plus optional opaque conversation continuity. Provider events, output, tool streams, and terminal frames do not own progress, completion, or workflow advancement.

One lifespan-owned `LocalRuntimeSupervisor` owns provider-control scheduling, watchdog recovery, and managed local agent processes. One 15-minute semantic progress clock replaces provider-signal liveness and overlapping lifecycle monitors.

## Context

The V1 implementation shaped generic runtime state around OpenClaw delivery. It persisted Gateway session and run identifiers on generic dispatch records, normalized provider events into watchdog inputs, and split foreground launch, lifecycle reconciliation, provider ingestion, and watchdog recovery across overlapping owners.

That model added maintenance cost without strengthening controller truth. AutoClaw already receives the events that matter to workflow correctness at its node MCP boundary: plans, checkpoints, structural mutations, external-wait creation, and terminal boundaries. Provider lifecycle observations are useful for diagnostics, but they do not prove that an assignment made progress or completed lawfully.

The current product strategy is one-process, local-tool-first delivery. V2 therefore needs a small portable runtime before it needs remote execution, distributed queues, or generalized exactly-once infrastructure.

## Decision

### Runtime truth

Controller records remain authoritative. For agent-originated work, only a successful, current, accepted node MCP-backed commit may advance semantic progress or close a runtime boundary.

The following never advance progress or completion:

- provider launch acceptance
- provider output or token streams
- provider-native tool events
- provider terminal success or failure
- transport disconnect or reconnect
- read-only node MCP calls
- failed or rejected node MCP calls
- an identical plan update

`return_boundary` remains the semantic egress operation. A provider response may end naturally after the boundary, but that response ending has no controller meaning of its own.

### Local runtime ownership

V2 uses one lifespan-owned `LocalRuntimeSupervisor`. It contains:

- one central `AgentControlManager`
- nonblocking delayed retry scheduling for provider start and stop
- the one runtime watchdog
- managed local Codex and Claude processes
- process and connection cleanup at shutdown

OpenClaw remains externally installed and supervised. AutoClaw controls it through its adapter but does not absorb the Gateway into the local process supervisor.

Distributed workers, remote workspaces, message queues, object-store task roots, and multiple active AutoClaw runtime processes are not part of this decision.

### Minimal provider control

The portable adapter boundary has two operations:

```text
start(prompt, provider_session_hint?) -> provider_session_hint?
stop(provider_session_hint?) -> None
```

The prompt preserves the existing split between AutoClaw instructions and dispatch input. The optional session hint is opaque continuity context. It is not execution truth, MCP authority, or proof that work is live.

Provider fallback resolves before a dispatch is committed. One dispatch uses one resolved provider for its entire provider-control attempt budget.

### Progress and watchdog

Each open dispatch has one `last_progress_at` value. It advances only after a meaningful accepted node MCP-backed commit. Before the first such commit, the watchdog anchors on `adapter_started_at`.

The default stale threshold is 900 seconds. On staleness, recovery closes the old node-session authority, retries provider stop, closes the old dispatch as superseded, and starts a replacement dispatch on the same assignment and attempt. Recovery uses two restart cycles by default. Exhausted recovery or provider-control failure pauses the task with `runtime_recovery_exhausted`; an operator repairs the provider and uses the ordinary continue control.

Provider start and stop each use six total calls by default with waits of 1, 2, 4, 8, and 16 seconds. Delayed retries re-enter the central queue rather than sleeping inside its worker. Repeated stops coalesce, and stop cancels a delayed start for the same dispatch.

### Plans, checkpoints, and waits

Every worker owns a current `AttemptPlan`, including one-step workers. Plan updates are the normal visible progress surface. Checkpoints remain durable handoff and terminal-evidence records rather than a plan-step diary.

Human requests and command runs are task-lineage waits. Opening either closes the current dispatch and node-session authority, lets the provider response end naturally, and does not call provider stop or `return_boundary`. Resolution opens a new dispatch on the same attempt when the lineage remains current.

### Runtime records and migration

V2 keeps generic dispatch, node-session, attempt, checkpoint, boundary, and external-wait truth. It adds a current attempt plan, a minimal node MCP invocation record, semantic progress time, opaque provider session continuity, and bounded provider-control readback.

V2 deletes the provider-event, delivery-state, continuity-state, and watchdog-state record families and their four dispatch support files. Generic dispatches no longer store Gateway run or session identifiers. This is a reset-only schema change; stale local databases fail with guidance to run `autoclaw db reset`.

## Consequences

- Adding Codex, Claude, or another local adapter does not require new watchdog semantics.
- The runtime can explain progress through plans, checkpoints, boundaries, and controller events without consuming provider streams.
- Provider crashes, silent stalls, and provider responses that end without a boundary converge on the same semantic-progress timeout and recovery path.
- Failure detection may be slower than provider-terminal event handling, but the behavior is portable and considerably easier to maintain.
- Normal completion and legal external waits do not enter the provider-stop lane.
- Optional provider continuity improves context reuse but is never required for correctness.
- The local runtime remains self-contained for managed Codex and Claude while preserving OpenClaw as an external integration.

## Superseded decisions

This ADR supersedes the following parts of earlier accepted decisions:

- ADR-0004's choice of OpenClaw as the primary target adapter for core runtime design
- ADR-0004's provider-event normalization role in runtime monitoring
- ADR-0004's treatment of transport continuity and watchdog behavior as shared adapter correctness inputs
- ADR-0001's inclusion of provider delivery, continuity, and watchdog record families in the target relational runtime model
- ADR-0005's dispatch-level delivery, continuity, watchdog, and provider-event projection families

It preserves ADR-0001's controller-first relational truth, ADR-0003's explicit tree and boundary model, and ADR-0005's rule that generated files never outrank controller truth. The V2 task-root owner separately decides which remaining file projections survive.

## Alternatives rejected

### Keep provider events as a watchdog input

Rejected because event names, availability, and connection lifecycles differ by provider. They add an adapter-shaped second account of progress.

### Treat provider terminal success as completion

Rejected because provider completion does not prove checkpoint, boundary, or workflow legality.

### Keep persistent provider connections in the controller

Rejected as a portable requirement. An adapter may privately drain an SDK or maintain a connection when its provider requires that, but controller correctness does not consume the stream.

### Keep separate foreground, lifecycle, and watchdog owners

Rejected because they race over the same dispatch slot and make retries, shutdown, and recovery harder to explain.

### Add execution generations, new MCP credentials, replay, or client idempotency keys

Rejected for this phase. Existing task and node recognition stays in place, and the minimal invocation record exists only for audit and progress timing.

### Build remote or distributed execution now

Rejected for the current strategy. Provider and file boundaries remain useful code seams, but V2 does not turn them into separately deployed services.

## Migration direction

1. Land the V2 lifecycle, record, plan, and checkpoint contracts.
2. Introduce the lifespan-owned supervisor and central provider-control queue.
3. Route all adapter start and stop operations through that owner.
4. Commit node-session authority before provider launch.
5. Switch watchdog anchoring to `adapter_started_at` and `last_progress_at`.
6. Add attempt plans and minimal node MCP invocation recording.
7. Move legal external waits to closed-dispatch, same-attempt continuation.
8. Remove provider-event correctness, generic Gateway identifiers, and the four dispatch-monitor record and file families.
9. Reset stale local databases and prove the provider-neutral runtime contract before redesigning the CLI around it.

## Canonical references

- `../design/v2/architecture/runtime-lifecycle-and-watchdog.md`
- `../design/v2/architecture/runtime-records-and-control-state.md`
- `../design/v2/architecture/work-plan-and-checkpoint-contract.md`
- `../design/v2/architecture/controller-contract-and-resumable-execution.md`
