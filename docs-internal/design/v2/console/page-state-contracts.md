# Console page state contracts

Status: Target

This page owns the runtime states the V2 console must render. It consumes finalized Control API and event names without adding frontend lifecycle states.

## Shared states

Every data-backed surface supports initial loading, ready, lawful empty, normalized error, stale mutation followed by targeted refresh, and narrow layout without hiding current status/actions.

Event-backed surfaces additionally show disconnected, reconnecting, and cursor-reset states. Those are transport presentation, not task/provider state.

## Task detail

Task detail bootstraps from task plus snapshot reads, then attaches chronology. It must expose:

- task/current assignment/attempt identity;
- optional current work plan;
- active dispatch and provider-start readback;
- admitted Node activity and watchdog/recovery;
- exact provider selection basis and experimental label where applicable;
- independent provider-native and network effective values with their controlling sources;
- current external wait;
- ordered chronology and selected trace/source detail; and
- lawful task controls.

Source state remains usable when SSE is disconnected.

## Work-plan states

| Source state | Presentation |
| --- | --- |
| `current_plan = null` | no current work plan; do not imply the agent is late or blocked |
| plan with an `in_progress` step | show ordered steps and emphasize only that step |
| plan with no `in_progress` step | show statuses exactly; do not manufacture an active step |
| all steps completed | show completed plan without implying a boundary/task completion |
| `work_plan_set` history | show bounded snapshots by assignment/revision in event order |
| `work_plan_cleared` | show plan removal in chronology without inventing an empty revision body |

## Active-dispatch and provider-start states

| Source state | Presentation |
| --- | --- |
| no current dispatch | no active provider authority; use flow/wait/pause state for explanation |
| current `starting`, initial attempt | provider start pending for committed dispatch |
| current `starting`, retry scheduled | attempt count, next attempt countdown, retry kind, bounded error |
| current `open` | accepted active dispatch, adapter time, Node activity, watchdog due |
| closed history row | close reason and lineage in trace/chronology only |

There is no `closing`, `attempt N/M`, provider-start exhausted, or provider-complete view.

## Node activity states

`last_node_activity_at` appears as exact time with optional relative label. Null on `open` means no admitted Node call since provider acceptance; it does not mean zero work, failure, disconnect, or provider inactivity.

The UI never calls this semantic progress and never derives it from provider output, transport traffic, task events, or support files.

## Provider selection states

| Selection basis | Presentation |
| --- | --- |
| `explicit` | selected provider, explicitly requested |
| `default` | selected provider, machine default |

Requested/resolved values remain available as provenance and should match under target rules. OpenClaw additionally shows `experimental`; it may still be selected explicitly or by the configured default, and incomplete conformance is not a disabled or unhealthy state.

## Effective-capability states

The active dispatch shows `provider_native_access.effective`, `provider_native_access.source`, `network_access.effective`, and `network_access.source` as two separate value/source pairs. Missing readback is a contract error rather than an invitation to infer from provider, role, prior dispatch, or browser state.

The UI may explain `default`, `policy_definition`, `task_policy`, or `controller` in product language while preserving the exact source value for inspection. A `controller` source includes adapter or local hard ceilings and is not a provider-health state.

## Watchdog states

| Source state | Presentation/action |
| --- | --- |
| recovery count zero | ordinary activity/watchdog display |
| replacement opened | preserve same-assignment plan; show D1/D2 lineage and count |
| paused `runtime_recovery_exhausted` | exhaustion notice, repair guidance, ordinary continue |
| paused `runtime_transition_failed` | deterministic transition-integrity/config repair guidance |
| repaired pause | continue explicitly; never auto-run from browser countdown/readiness |

Watchdog does not run while an exact human/command source owns the dispatch lineage. The UI does not imply provider stop must finish before a replacement starts.

## Task controls

Pause, continue, and cancel use current flow/control revisions and distinct confirmations.

- Pause success closes current authority synchronously; cleanup is not shown as a blocking phase.
- Continue waits for legal D2+refs commit, then shows `starting`; it does not wait for provider acceptance.
- Cancel is terminal controller intent; post-commit cleanup cannot make it fail.
- Continue is never an answer or command-completion action.

The same-origin packaged console uses the loopback local-control boundary without an operator API-key bootstrap or stored key. Accepted mutations are audited as `local_operator` surface activity, not authenticated-human identity.

## Human requests

The request page supports no history, exact open typed request, validation without losing draft answers, source-terminal success, immutable resolved/timed-out/cancelled history, and stale resolve failure.

After resolve success, it shows the committed terminal request and refreshes normally. It does not display a required successor ACK or hold the response open until D2 appears.

## Command runs

The command page supports empty history, `pending_start`, `running`, `cancellation_requested`, all terminal states, bounded summary, detail, explicit log loading, and cancel success/denial/staleness.

`cancellation_requested` stays nonterminal and keeps the task waiting until termination/reap. Raw output appears only in the authorized log view.

## Chronology and reset

Chronology supports REST backfill, ascending sequence, reconnect/deduplication, work-plan changes, provider-start revisions, checkpoints/boundaries, waits, controls, empty history, and cursor reset.

Provider events, provider stop cleanup, runtime signals, and per-Node-invocation rows never appear.

On reset, the page discards event-derived current assumptions, rereads task/snapshot and selected source detail, then reconnects from the new head.

## Exclusions

No page adds a debug/fallback rendering for credentials, global operator API keys, browser credential bootstrap, binding material, provider/native events/output/logs, provider/MCP session IDs, provider run IDs, provider fallback/health, provider-start maximum, semantic progress inferred from activity, percentage, ETA, or throughput.

Provider setup, login, enablement, and default mutation have no browser page state in the loopback phase; they remain CLI-only. Callback HTTP likewise has no V2 console state.

## Related contracts

- [Console target](README.md)
- [API and view-model boundary](api-and-view-model-boundary.md)
- [Component system](component-system.md)
- [Console runtime surfaces](../interfaces/console-runtime-surfaces.md)
- [Control API](../interfaces/control-api.md)
- [Task event stream](../interfaces/task-event-stream.md)
