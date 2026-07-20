# Console runtime surfaces

Status: Target

This page owns the V2 console product model for current runtime truth, work plans, admitted Node activity, provider start, watchdog recovery, external waits, chronology, and operator controls. Backend schemas and lifecycle legality remain with their named owners.

## Core rule

The console renders controller source rows for current state, task events for ordered chronology, and source-specific routes for complete human-request and command-run detail. It never reconstructs an agent runtime from provider output, provider events, support files, sessions, or adapter handles.

## Primary experience

The runtime console coordinates:

1. task selection and compact controller status;
2. task detail with the current assignment/attempt and active dispatch;
3. ordered task chronology; and
4. selected detail for plans, dispatches, waits, checkpoints, and boundaries.

The task tree answers what work exists, the runtime summary answers what is current, chronology answers what committed, and selected detail exposes lawful actions.

## Active dispatch

The console treats `current_dispatch` as active authority only. It displays `starting` or `open`; closed rows appear only in history. There is no `closing` presentation.

For `starting`, it may show provider route, attempt count, next retry, retry kind, and sanitized error. It never shows a finite maximum or provider-start exhaustion. For `open`, it may show adapter acceptance time, last admitted Node activity, derived watchdog due time, and recovery count.

Provider start state is AutoClaw controller state, not proof that the provider is generating or will complete.

## Work plan

The console renders the complete optional assignment-owned work plan:

- assignment identity and revision;
- optional explanation;
- one to nine ordered steps with `pending`, `in_progress`, or `completed` when a plan exists;
- authoring dispatch; and
- commit time.

Root, parent, and worker assignments may have a plan; all may legally have none. The UI does not synthesize a placeholder, require one before work, infer percent/ETA, or treat completed steps as a boundary.

History comes from `work_plan_set` and `work_plan_cleared` events. Accepted no-ops create no plan event.

## Node activity and watchdog

`last_node_activity_at` means the current dispatch admitted a valid current Node MCP call. Reads, accepted no-ops, and normalized domain failures after admission all refresh it. The UI labels this as Node activity, never semantic progress.

The watchdog due label is derived from controller readback and the client clock for display only. Reaching zero in the browser schedules nothing.

Watchdog replacement appears through the closed historical D1, a new D2 with `opened_reason = watchdog_recovery`, and the current recovery count. Exhaustion presents task `paused`, `pause_reason = runtime_recovery_exhausted`, and ordinary continue after repair.

The console does not create another recovery state machine or imply that provider stop succeeded before D2.

## Provider selection and support status

The console shows requested/resolved provider and `selection_basis = explicit | default`. The target has no provider fallback label or chain.

OpenClaw is labeled experimental but remains selectable explicitly or through the operator-configured default. Incomplete conformance is disclosed as support information; it never becomes a disabled, unhealthy, or globally unavailable state. Codex and Claude are managed target lanes. A badge describes product/selection status only; it never asserts live provider health.

Provider setup, login, enablement, and default mutation are CLI-only for the loopback phase. The console exposes passive provider/default/check readbacks only; it is not a browser provider-mutation surface.

## Effective capabilities

The active-dispatch view presents both independent controller readbacks:

```yaml
provider_native_access:
  effective: full | restricted | denied
  source: default | policy_definition | task_policy | controller
network_access:
  effective: allow | deny
  source: default | policy_definition | task_policy | controller
```

Copy distinguishes the effective value from its controlling source. It never combines network access with provider-native access, treats provider selection as capability provenance, or exposes provider configuration.

## Human-request waits

The console resolves only the exact current open request through its dedicated route. It renders typed `direction`, `approval`, `input`, and `review` controls, immutable terminal history, due time, and provenance.

Resolution returns when the request transaction commits. The UI does not wait for or claim a successor dispatch acknowledgement. It refreshes source state/event chronology until an independently opened successor appears.

Continue is not an answer action. Provider-native question/approval UI is never surfaced as an AutoClaw wait.

## Command-run waits

The console renders exact command source state:

```text
pending_start | running | cancellation_requested | succeeded | failed | timed_out | cancelled | abandoned
```

`cancellation_requested` remains nonterminal until process termination and reap. Bounded summary and log refs come from source reads; raw logs require explicit authorized inspection.

`abandoned` is a terminal audited ownership-loss state. The console presents its sanitized `command_ownership_lost` diagnostic and repair/continuation context without implying that the operating-system process exited or should be relaunched.

Command output is never provider output and never replaces normalized run state.

## Chronology and cursor reset

Task events render in ascending event sequence. Provider/adapter/runtime-signal identities are not event sources.

On `cursor_reset_required`, the client discards event-derived current-state assumptions, rereads task and snapshot source rows, rereads selected source detail when needed, and reconnects after the snapshot head. It never folds events into a replacement state store.

## Operator controls

Pause, continue, cancel, request resolution, and run cancellation use fresh controller guards and their dedicated routes.

The packaged console is a same-origin loopback client. It sends no global operator API key and receives no API-key bootstrap; successful local mutations carry controller-recorded `local_operator` surface provenance rather than an asserted human identity.

- pause/cancel return after the authoritative transaction and do not wait for provider stop;
- continue returns after legal D2+refs commit but before provider start;
- human resolution returns independently of successor opening;
- disabled buttons are presentation only; and
- stable conflict/stale failures trigger a targeted source refresh.

## Data exclusions

Ordinary console views never render or persist:

- raw provider/native tool events, output, or logs;
- provider or managed-MCP credentials;
- provider/MCP session IDs or adapter handles;
- individual Node invocation audit rows;
- support projections as currentness;
- provider-start maximum/exhaustion;
- provider fallback or fabricated health;
- global operator API keys or browser credential bootstrap material;
- semantic-progress claims derived from Node activity; or
- fabricated percent complete, ETA, or throughput.

## Related contracts

- [Console target](../console/README.md)
- [Control API](control-api.md)
- [Task event stream](task-event-stream.md)
- [Runtime lifecycle and watchdog](../architecture/runtime-lifecycle-and-watchdog.md)
- [Runtime records and control state](../architecture/runtime-records-and-control-state.md)
- [Work plan and checkpoint contract](../architecture/work-plan-and-checkpoint-contract.md)
- [Human request and approval contract](human-request-and-approval-contract.md)
- [Command run and external wait](../architecture/command-run-and-external-wait.md)
- [Provider selection and runtime config](provider-selection-and-runtime-config.md)
