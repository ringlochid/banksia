# Console API and view-model boundary

Status: Target

This page owns how the console consumes finalized Control API and task-event contracts and maps them into render-ready runtime views. It does not define wire fields, controller currentness, events, or legality.

## Core rule

Source-row reads own current state. Task events own chronology. Explicit view-model mappers preserve that split; components do not parse raw controller payloads or event frames deep inside rendering code.

## Data sources

| Console need | Canonical source |
| --- | --- |
| current flow, assignment/attempt, active dispatch, plan, Node activity, provider start, effective capabilities, recovery, and waits | `GET /control/tasks/{task_id}` |
| operator-ready summary and stream anchor | task snapshot |
| dispatch/checkpoint/boundary/graph history | task trace |
| work-plan revisions, dispatch-start revisions, waits, checkpoints, boundaries, and controls in order | event list and SSE |
| complete human request/resolution | human-request route |
| complete command source/result/provenance | command-run list/detail routes |
| explicit authorized command output | command-run log route |

No mapper reads currentness from support files, provider streams/events, runtime signals, or client-local state.

## Active dispatch mapping

`current_dispatch` maps only `starting` or `open`. Closed dispatches map from trace/history. A frontend `closing` variant is forbidden.

The mapped dispatch preserves full IDs, assignment/attempt, predecessor, opened reason, provider selection, adapter start time, activity revision/time, watchdog due, provider-start readback, and both effective capability readbacks exactly as supplied.

## Work-plan mapping

`current_plan` maps assignment ID, revision, explanation, ordered steps, authoring dispatch, and timestamp. Null is rendered as a legal absence for every role; it is not renamed to `awaiting` or synthesized as an empty controller record.

History uses `work_plan_set` and `work_plan_cleared` in `event_seq` order. Mappers never derive revisions from step differences or keep unsaved browser edits as controller truth.

## Node activity mapping

The timestamp source is `current_dispatch.last_node_activity_at`. A relative label is a pure presentation of that value. The view-model name and copy must retain `activity`, not `semantic progress`.

`node_activity_revision` is useful for detail/support correlation but does not become a user-facing count of work performed.

## Provider selection mapping

Provider selection preserves:

- requested provider;
- resolved provider; and
- `selection_basis: explicit | default`.

A mapper may derive `isExperimental` from the supported product-status catalog for OpenClaw. It may not derive `isFallback`, a fallback chain, provider health, model, or private run/session identity.

OpenClaw may be selected explicitly or through the configured default. Experimental or incomplete-conformance disclosure must not map to disabled, unhealthy, or unselectable state.

## Capability mapping

The controller's two source-bearing objects map independently:

- `provider_native_access.effective` and `provider_native_access.source`;
- `network_access.effective` and `network_access.source`.

Mappers preserve the exact enums and source vocabulary. They may format the source for display but may not merge the axes, infer capability from provider selection, or turn a restrictive value into provider health.

## Provider-start mapping

Current start display maps:

- revision;
- attempt count;
- next attempt timestamp;
- retry kind; and
- sanitized last error code.

There is no max-attempt field, stop-operation state, or provider-completion state. The countdown is `max(0, next_attempt_at - client_now)` for presentation only and schedules nothing.

`dispatch_start_updated` events remain chronology. The source read is authoritative after any event or reconnect.

## Recovery mapping

Recovery uses current watchdog count, active/closed dispatch lineage, activity/due data, task status, and pause reason. `runtime_recovery_exhausted` selects the repair-and-continue presentation; `runtime_transition_failed` selects integrity/config repair guidance. No frontend-only recovery state machine is added.

## External-wait mapping

Task readbacks supply compact current waiting cause/source. Dedicated routes supply full request items/resolutions or command detail/result/log refs.

Events prompt refresh and populate chronology; they never replace complete source records or authorize an action.

## Mutation mapping

Pause, continue, cancel, human resolve, and command cancel use generated request/response types and fresh guards.

The browser client relies on the packaged same-origin loopback boundary. It has no global operator API-key header, config bootstrap field, or key storage. Controller audit records these local mutations with `local_operator` surface provenance; the client does not claim a human identity.

- no optimistic state claims success before the response;
- pause/cancel success means controller truth committed, not provider cleanup completed;
- continue success may include newly committed D2 but never provider start completion;
- human resolve success means the source terminalized, not successor opening acknowledged;
- command cancellation intent may remain nonterminal; and
- stale/conflict/illegal failures trigger a targeted source refresh.

## Event and cursor mapping

The event client preserves `event_id`, `event_seq`, event type/source, occurrence time, dispatch/attempt context, and bounded payload. It orders by sequence, deduplicates identity, and renders only documented families.

On `cursor_reset_required`, it stops the stale stream, clears event-derived current display assumptions, refetches task/snapshot and selected source detail, resets ordering around the fresh anchor, and reconnects after `stream_head_event_id`.

## Failure boundary

The client normalizes structured operation failures, HTTP local-admission errors, network/abort errors, cursor-reset failures, and malformed event frames. Render views use bounded summary, retryability, field path where present, and suggested next step.

Raw provider exceptions, stack traces, credentials, environment values, binding material, and provider output are never placed in view models, fixtures, browser storage, or diagnostics.

Provider setup, login, enablement, and default mutation remain CLI-only. Provider status in the console is passive readback, not a hidden browser mutation client. Callback HTTP is not a V2 console data or mutation lane.

## Related contracts

- [Console target](README.md)
- [Page state contracts](page-state-contracts.md)
- [Console runtime surfaces](../interfaces/console-runtime-surfaces.md)
- [Control API](../interfaces/control-api.md)
- [Task event stream](../interfaces/task-event-stream.md)
- [Human request and approval](../interfaces/human-request-and-approval-contract.md)
- [Command run and external wait](../architecture/command-run-and-external-wait.md)
