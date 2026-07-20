# Console target

Status: Reference

This directory translates the V2 [Console runtime surfaces](../interfaces/console-runtime-surfaces.md) contract into frontend data boundaries, page states, and reusable component semantics. It does not redefine backend truth.

## Pages

- [API and view-model boundary](api-and-view-model-boundary.md) owns source-row, event, mapping, failure, and cursor-reset boundaries.
- [Page state contracts](page-state-contracts.md) owns required runtime render states and lawful actions.
- [Component system](component-system.md) owns shared interaction, responsive, and accessibility semantics.

These four files are the complete live V2 console target set.

## Authority order

1. Control API source rows for current state and mutation legality
2. task events for chronology and live refresh hints
3. human-request and command-run source routes for complete external-wait detail
4. console runtime surfaces for product composition
5. pages here for frontend mapping and presentation

Generated OpenAPI types remain the TypeScript wire source. Explicit mappers may create render-ready views but must preserve controller identities, states, and timing.

## Scope

This subtree covers:

- active `starting|open` dispatch and closed dispatch history;
- optional assignment-owned work plan and plan chronology;
- admitted Node activity and watchdog due/recovery presentation;
- exact provider selection basis and indefinite provider-start retry;
- experimental OpenClaw labeling without disabling selection;
- human-request and command-run waits;
- pause/cancel/continue timing; and
- source refresh, task-event chronology, and cursor reset.

It does not own definition authoring, provider setup/configuration mutation, backend schemas, runtime behavior, task-file projections, or implementation evidence programs.

## Non-negotiable exclusions

The console does not invent lifecycle states, provider-start maxima, fallback chains, health, semantic progress from Node activity, percentages, ETA, or action legality. Ordinary product views never expose provider/native events, credentials, binding material, provider/MCP session identity, raw provider output, or raw provider logs.

## Related contracts

- [Console runtime surfaces](../interfaces/console-runtime-surfaces.md)
- [Control API](../interfaces/control-api.md)
- [Task event stream](../interfaces/task-event-stream.md)
- [Runtime lifecycle and watchdog](../architecture/runtime-lifecycle-and-watchdog.md)
