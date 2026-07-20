# Console component system

Status: Target

This page owns reusable V2 console semantics for runtime truth. It does not freeze a framework, final visual values, backend fields, or controller transitions.

## Core rule

Components make controller state scannable without turning provider, transport, timer, or support detail into product truth.

## Shell and composition

The task runtime shell keeps task navigation, current summary, tree/trace, chronology, and selected detail/action context distinct. Wide layouts may place them side by side; narrow layouts preserve the same semantic order.

Current state and lawful primary actions must not be hover-only or desktop-only. Human requests and command runs remain task-scoped sibling details.

## Tokens and variants

Shared console tokens use the `--ac-*` namespace for surface hierarchy, text, borders/focus, spacing/density, shape/elevation, and semantic information/success/warning/failure/paused/waiting/neutral treatments.

Color always has a text or icon-label equivalent. Variants are explicit mappings of finalized controller states, never arbitrary classes constructed from backend strings.

## Work-plan panel

The plan panel renders optional assignment plan, revision, explanation, ordered steps, authoring provenance, and chronology access.

Step variants are `pending`, `in_progress`, and `completed`. Zero or one active step is legal. The panel adds no percentage, progress bar, ETA, mandatory-plan warning, or completion claim.

## Node-activity component

The component renders `last_node_activity_at` with exact time available to assistive technology and optional relative text. Null uses neutral copy.

Its labels say Node activity. They do not say semantic progress, provider activity, heartbeat, percent, or health.

## Provider-selection component

The component renders provider plus `explicit` or `default` selection basis. Requested/resolved provenance is available in detail. It never renders fallback.

OpenClaw uses an accessible `experimental` product-status badge that does not look like disabled, failed, or unauthorized.

## Provider-start component

For a `starting` dispatch, the component renders attempt count, next-attempt countdown, retry kind, and bounded sanitized error. It never renders a denominator/max, exhausted provider start, stop operation, provider completion, or provider health.

Countdown changes do not resize rows or announce every tick. Reaching zero schedules nothing.

## Watchdog notice

The watchdog component renders due time/recovery count and the `runtime_recovery_exhausted` pause when present. Exhaustion includes precise reason, repair guidance, and ordinary continue after repair.

It never offers provider-native reconnect or claims provider stop completed.

## External-wait cards

Human-request and command-run cards share a compact wait structure while preserving distinct states/actions.

Human cards show typed kind, title/summary, due/status, and resolve only for the exact current open source. They do not show a successor acknowledgement requirement.

Command cards show exact source state, bounded update/result, and cancel only when legal. `cancellation_requested` uses a nonterminal waiting treatment.

## Event rows and selected context

Event rows preserve type, sequence, occurrence time, and controller context. Work-plan, dispatch-start, checkpoint, boundary, wait, and task-control details use bounded disclosures.

Provider, adapter, timer, and runtime signal are not event-source variants. Raw payload dumps are not default UI.

The task tree stays read-only and compact. Rich assignment, checkpoint, artifact, dispatch, request, or run detail belongs in selected context rather than repeated cards.

## Controls and feedback

Buttons, inputs, disclosures, status chips, empty/error states, dialogs, and drawers share visible focus, stable dimensions, disabled explanation where needed, exact pending-action feedback, and normalized failure/next-step presentation.

Pause/cancel pending UI never claims provider cleanup. Continue pending/success distinguishes D2 commit from later provider acceptance. Destructive task cancel remains distinct from command-run cancel and nonterminal pause.

Dialogs trap/restore focus, have accessible names, and associate field errors correctly.

## Responsive and accessibility rules

- preserve task status, current wait, watchdog notice, and lawful primary action at narrow widths;
- make timestamps, retry count, selection basis, experimental status, and source state textual;
- announce material source changes without announcing every countdown tick;
- keep plan/event disclosures keyboard operable;
- preserve readable source order when panes stack; and
- avoid nested scroll regions that hide actions or errors.

## Exclusions

No component variant exists for provider/native events, credentials, binding material, provider/MCP session or run IDs, raw provider logs/output, fabricated fallback/health, provider-start maximum/exhaustion, semantic-progress claims from activity, percentage, ETA, or throughput.

The explicit command log viewer is a source-specific controller component, not a provider-log component.

## Related contracts

- [Console target](README.md)
- [API and view-model boundary](api-and-view-model-boundary.md)
- [Page state contracts](page-state-contracts.md)
- [Console runtime surfaces](../interfaces/console-runtime-surfaces.md)
