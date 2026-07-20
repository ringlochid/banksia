# ADR-0004: OpenClaw-first adapter normalization and worker transport boundary

Status: Accepted

## Decision summary

OpenClaw is the v1 transport adapter and normalization layer. It is not the owner of canonical runtime semantics, and the live runtime term is `tool`, not `skill`.

## Superseded in part

[ADR-0007](ADR-0007-mcp-anchored-local-runtime-and-minimal-provider-control.md) supersedes this record's OpenClaw-first provider-event normalization, transport-continuity, dispatch-monitoring, and watchdog decisions. The decisions that provider transport remains subordinate to controller truth and that `tool` is the canonical runtime term remain accepted.

## Context

V1 is OpenClaw-first for delegated worker transport, but the live runtime model can no longer treat OpenClaw as the owner of canonical worker semantics.

The current runtime contract already freezes:

- controller/DB truth as authoritative
- `dispatch` ingress and `yield | green | retry | blocked` egress
- explicit parent/root control tools
- checkpoint, artifact, transient, and manifest surfaces as the shared agent context model

This means OpenClaw must fit underneath the runtime model as an adapter and normalization layer, not as the owner of a separate skill-centric contract.

## Decision

OpenClaw is the primary v1 worker transport adapter and provider-event normalization surface.

The controller owns:

- runtime truth
- dispatch legality and caller binding
- assignment and attempt lineage
- checkpoint recording
- artifact currentness and release decisions
- parent/root control-tool meaning

OpenClaw owns:

- prompt delivery to the provider
- transport continuity and response-id tracking
- normalization of raw provider/OpenClaw events into canonical monitoring enums
- generation of adapter-facing observability projections under `_runtime/dispatch/<dispatch_id>/...`

`tool` is the canonical runtime term. `plugin` is adapter-specific terminology only, used where a concrete packaging or parity surface is being discussed.

Provider transport success does not equal assignment success. Raw OpenClaw protocol names may survive only as debug detail; they are not the public runtime contract.

## Historical contrast

This ADR keeps the file path for continuity, but the settled model is no longer skill-centric.

What remains live:

- OpenClaw as delivery adapter
- OpenClaw as provider-event normalization surface
- OpenClaw-specific continuity and recovery details as monitoring/adapter facts

What is removed from the live runtime core:

- skill ownership as the main semantic framing
- provider-specific callback meaning as public runtime truth
- adapter vocabulary overriding the canonical `tool` surface

## Consequences

- OpenClaw remains the v1 delivery adapter without becoming the owner of live runtime truth
- worker transport, operator-safe external lanes, and internal controller truth stay distinct
- skill-centric ownership language is removed from the accepted decision
- generic target-level `skill_refs` remain removed from the authored workflow model
- transport, continuity, and watchdog semantics remain monitoring/adapter concerns rather than worker-facing planning surfaces
- later multi-runtime support can keep the same canonical runtime model while swapping or adding adapters

## Search keywords

- OpenClaw adapter
- provider normalization
- tool not skill
- plugin adapter-specific only
- provider success is not assignment success
- transport boundary

Canonical references:

- `../design/v1/architecture/openclaw-worker-and-gateway-contract.md`
- `../design/v1/architecture/openclaw-session-lifecycle.md`
- `../design/v1/architecture/openclaw-continuity-and-send-modes.md`
- `../design/v1/architecture/runtime-monitoring-and-watchdog-automation.md`
- `../design/v1/architecture/runtime-boundary-and-controller-loop-contract.md`
