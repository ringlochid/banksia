# Watchdog And Recovery Contract

Status: Target

> **V2 supersession notice:** This page remains the frozen V1 watchdog baseline. The V2 watchdog and recovery state machine are superseded by [Runtime lifecycle and watchdog](../../v2/architecture/runtime-lifecycle-and-watchdog.md).

## Purpose

This page freezes the lean v1 watchdog classification and controller recovery model.

## Core rule

Watchdog is conservative and controller-truth-first.

- watchdog reads controller/DB state directly as ground truth
- generated files under `_runtime/dispatch/<dispatch_id>/` are observability projections only
- watchdog is a periodic controller-side loop with deterministic classification over current truth
- watchdog classifies delivery and liveness incidents tied to internal dispatch chronology
- watchdog does not redefine assignment result truth by itself
- watchdog does not scan projections as its source of truth
- watchdog is not a node action, callback action, or public boundary family
- detailed support-state enums and projection schemas remain below the core lock

Foreground-control separation:

- start/open and abort handshakes are foreground controller operations
- pre-send launch retry and post-send launch ambiguity are foreground launch control outcomes
- watchdog is the background reconciler/escalator for stale or ambiguous cases
- watchdog must not race a live foreground handshake on the same dispatch slot
- a bounded post-boundary drain window is also foreground controller behavior, not watchdog behavior

Ownership table:

| Lifecycle slice                                                         | Primary owner         |
| ----------------------------------------------------------------------- | --------------------- |
| launch handshake, pre-send launch retry, and post-send launch ambiguity | foreground controller |
| live execution                                                          | foreground controller |
| bounded drain window while `control_state = live`                       | foreground controller |
| abort handshake while `control_state = abort_requested`                 | foreground controller |
| stale or ambiguous post-deadline cases                                  | watchdog              |

## Controller read basis

When watchdog classifies a live dispatch, it rereads current dispatch, assignment/attempt, Gateway session/run state, and current delivery/continuity/watchdog support truth and computes liveness time from, in order:

- the latest normalized provider progress-or-terminal signal
- the latest node semantic write timestamp
- dispatch accepted and prepared timestamps

Checkpoint remains semantic truth for handoff, retry reread, release legality, and incident classification. It is not part of stale-timeout anchoring in the stronger design locked by this page.

Raw socket receipt, transport-local buffers, and uncommitted adapter state are never watchdog truth.

This contract uses first-progress and dispatch-progress wording only. It does not depend on ack-era terminology.

Watchdog should also read:

- `DispatchTurn.control_state`
- `DispatchTurn.control_deadline_at`
- `DispatchTurn.gateway_session_key`
- `DispatchTurn.gateway_run_id`
- the latest relevant checkpoint and surfaced evidence only when a semantic classification needs them, for example `terminal_provider_without_controller_checkpoint`

## Watchdog trigger families

The frozen v1 trigger-family set is closed to:

- `bootstrap_pending_callback.bootstrap_callback_timeout`
- `bootstrap_pending_callback.terminal_provider_without_first_callback`
- `execution_running.execution_stale`
- `execution_running.delivery_path_rebound`
- `execution_running.terminal_provider_without_controller_checkpoint`

`watchdog-state.json.current_watchdog_kind` echoes exactly one of those strings or `null`. Observability/readback docs must not rename or widen this set.

Meaning notes:

- `bootstrap_pending_callback.bootstrap_callback_timeout` remains the frozen trigger-family name, but in the stronger design it means the dispatch timed out before the first provider progress or node semantic write arrived after acceptance
- `execution_running.execution_stale` means liveness timed out from the latest provider progress or node semantic write anchor, not from checkpoint cadence

Not watchdog triggers:

- ordinary dependency waits
- explicit operator pause or cancel
- child business blockers already summarized in checkpoint
- parent/root review disagreement
- missing durable output discovered by release legality

## Recovery actions

Canonical watchdog recovery actions are:

- `redispatch_same_attempt`
- `escalate`

Exact meanings:

| Recovery action           | Exact meaning                                                                                                                                                                                                                  |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `redispatch_same_attempt` | The controller keeps the same assignment and same attempt, then opens one replacement dispatch. Parent/root must keep the same `sessionKey` when this path is legal; worker stability recovery does not rely on session reuse. |
| `escalate`                | The controller does not auto-redispatch and instead returns control to the higher owner or operator path.                                                                                                                      |

Rules:

- send mode does not widen this action family
- parent/root same-attempt redispatch reuses the same Gateway `sessionKey` when continuity reuse remains lawful and otherwise falls back to a fresh `sessionKey`, while still sending a fresh `idempotencyKey`, resending the full regenerated prompt, and accepting a fresh returned `runId`
- worker semantic retry remains a fresh-session runtime action outside watchdog recovery
- same-attempt redispatch, if internally limited, is a controller-owned watchdog recovery cap rather than an authored policy field
- authored worker `retry_limit` does not apply to watchdog recovery
- parent/root have no authored retry budget
- any retained `same_session_continue` transport detail remains adapter-private only and must not override the canonical same-session plus full-resend rule for parent/root redispatch

## Recovery decision table

| Situation                                                                                             | Legal automatic action    | Illegal shorthand                                                            |
| ----------------------------------------------------------------------------------------------------- | ------------------------- | ---------------------------------------------------------------------------- |
| The same attempt is still current and bounded work should continue                                    | `redispatch_same_attempt` | Calling it `retry` or inventing a transport-shaped recovery family           |
| The current attempt lineage is no longer trustworthy or safe same-attempt redispatch cannot be proven | `escalate`                | Auto-minting a new attempt or describing the result as a same-attempt resend |
| Budget exhausted, ambiguity persists, multiple candidates exist, or no eligible candidate exists      | `escalate`                | Hidden provider retry loop                                                   |

## Abort-confirm-before-replace

Canonical abort control uses Gateway WS RPC surfaces:

- `agent` opens the run
- `agent.wait` observes terminal completion
- `sessions.abort` is the canonical machine abort surface

Before replacement work can start on one execution slot:

1. call `sessions.abort`
2. mark local dispatch `abort_requested`
3. wait for terminal confirmation
4. if confirmed, mark the old dispatch non-current and terminal
5. only then open the replacement run

If terminal confirmation does not arrive before deadline:

- for accepted-boundary running cleanup, foreground control may fence the slot while preserving `delivery_status = transport_ambiguous`, then allow internal replacement progression
- otherwise mark the slot `ambiguous`
- do not open a replacement run on that slot unless controller cleanup has already fenced it
- escalate/operator review when cleanup cannot prove the slot is no longer capable of live work

Drain-window rule:

- if same-session continuity preservation is still desired, the controller may wait through a bounded drain window before aborting
- default drain timeout is `30` seconds through target runtime config
- Gateway lifecycle terminal events and `agent.wait` results should short-circuit that window immediately
- watchdog only becomes relevant after the drain window is stale, abort is requested, or the slot is already `ambiguous`
- the slot remains replacement-blocked while still `live`, including that bounded drain-window subphase

Ownership rule:

- while `DispatchTurn.control_state` is `launching` or `abort_requested`, foreground control owns the handshake and watchdog should not issue competing recovery
- watchdog may intervene only when that state is stale past deadline or already `ambiguous`

Timeout and reconciliation rule:

- use event-driven confirmation first and deadlines second
- treat committed normalized provider progress as the primary liveness hint for stale-timeout anchoring
- treat Gateway lifecycle terminal events as the primary fast signal
- use `agent.wait` as the confirmatory read before replacement or escalation
- reconcile controller truth before any retry or replacement decision
- do not use blind exponential resend loops for launch or abort control
- retry pre-send launch failures only through explicit controller launch retry state with proof that no request was sent
- treat post-send no-run-id launch failure as ambiguous unless cleanup proof shows no live Gateway work remains

## What watchdog may and may not do

Watchdog may:

- classify a real delivery or liveness problem
- choose exactly one controller recovery action
- commit recovery dispatch truth only through ordinary controller write paths
- open a new dispatch only after older dispatch truth is no longer current
- act only after the slot is no longer live, no longer inside an open drain window, or no longer abort-pending, unless it is already stale or `ambiguous`

Watchdog must not:

- interpret ordinary business blockers as transport stalls
- silently publish `green`, `retry`, or `blocked`
- invent a separate gate-era decision surface
- replace checkpoint as the durable handoff surface
- treat provider terminal success as proof that the assignment succeeded
- expose `dispatch_id` as a required node-facing or public operator input

## Escalation rule

`escalate` is required when:

- same-attempt redispatch is illegal
- the relevant internal watchdog redispatch limit is exhausted
- multiple watchdog-blocked candidates exist
- no eligible candidate exists
- structural or currentness basis is stale
- automatic recovery would rewrite or guess over ambiguous truth

After escalation:

- no automatic dispatch commit happens
- no hidden provider retry loop runs
- later handling proceeds through ordinary higher-owner or observability and operator surfaces
- if later agents must understand the incident durably, checkpoint or another surfaced durable file must summarize it

## Redispatch sequencing rule

Before watchdog-triggered redispatch:

1. reread authoritative dispatch, attempt, session, run, and currentness truth
2. require the old dispatch to already be `fenced` or otherwise terminal by stronger committed truth
3. commit any required supersession/readback truth
4. only then mint the new dispatch
5. only then allow the next live agent run

Same-attempt recovery therefore means same assignment plus same attempt under a replacement dispatch. It never means continuing the stopped run. Parent/root should preserve the same `sessionKey` when continuity reuse remains lawful, but watchdog may still open a fresh-session same-attempt redispatch when continuity reuse is unavailable or invalid and the broader controller truth still proves that replacement safe.

When a parent/root same-attempt replacement is reopening the same lawful turn lineage, watchdog should also preserve the previous dispatch's `staged_child_assignment_id` only when that staged child basis still validates through current controller truth. That staged child basis remains dispatch-local evidence for one open turn; it is not attempt-owned continuation state.

## Support-state demotion

This page intentionally does **not** freeze the full watchdog, delivery, or continuity support-state machine as core v1 truth.

The core lock owns only:

- trigger families
- recovery actions
- abort/replace sequencing
- ambiguity and escalation rules
- the single-live-run invariant

Detailed support enums, support projections, and transport-specific continuity catalogs may remain in support or adapter docs. Non-behavioral readback residue such as `controller_observation_state`, broad continuity catalogs, `previous_response_id` echoes, or prompt/send-mode compatibility mirrors are current/debt cleanup targets, not frozen v1 schema surfaces.

## Runtime config placement

The canonical runtime config for watchdog and drain behavior lives under `[runtime]` in the local `config.toml` owner surface documented in [Install and onboard](../how-to/install-and-onboard.md).

Rules:

- these are runtime/controller knobs, not authored workflow grammar
- do not scatter them across wrapper-local files, env-only conventions, or hardcoded service literals
- canonical target wording uses `watchdog_bootstrap_first_progress_timeout_seconds`; older configs may still carry `watchdog_bootstrap_ack_timeout_seconds` as a temporary compatibility alias during rollout
- same-attempt watchdog redispatch limit belongs here as a controller-owned stability cap; default target value is `2`
- same-attempt redispatch legality still comes from controller truth, not config alone
- observability surfaces may inspect the resulting watchdog state, but they do not trigger recovery

## Exact watchdog projection

`watchdog-state.json` uses this exact readback shape:

```json
{
    "dispatch_id": "dispatch.parent.01",
    "attempt_id": "attempt.parent.01",
    "assignment_key": "parent.assign-01",
    "node_key": "implementation_subtree",
    "watchdog_state": "clear",
    "current_watchdog_kind": null,
    "current_watchdog_reason": null,
    "recovery_action": null,
    "recovery_reason": null,
    "recovery_dispatch_id": null,
    "previous_dispatch_id": null,
    "superseded_by_dispatch_id": null,
    "classified_at": "2026-05-03T10:00:15Z",
    "updated_at": "2026-05-03T10:00:15Z"
}
```

That file remains an observability projection over controller truth. It is not the watchdog's source of truth.

Operator/public investigation should start from `task_id`; runtime/support tooling may resolve internal dispatch chronology and read the matching watchdog projection as needed.

## Related contracts

- [Runtime monitoring and watchdog automation](runtime-monitoring-and-watchdog-automation.md)
- [Runtime observability and boundary log](runtime-observability-and-boundary-log.md)
- [OpenClaw session lifecycle](openclaw-session-lifecycle.md)
- [OpenClaw continuity and send modes](openclaw-continuity-and-send-modes.md)
