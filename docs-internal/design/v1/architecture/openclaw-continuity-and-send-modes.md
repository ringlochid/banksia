# OpenClaw Continuity And Send Modes

Status: Target

> **V2 supersession notice:** This page remains the frozen V1 continuity baseline. V2 treats continuity as an optional opaque provider hint, resends the complete structured prompt on every start, and owns that contract in [Minimal provider adapter contract](../../v2/architecture/adapter-contract.md).

## Purpose

This page records the canonical v1 send-mode truth and keeps transport continuity detail below the canonical v1 session/run/abort architecture.

## Core rule

The controller always regenerates the full canonical prompt package before a dispatch.

Canonical v1 dispatch control does not depend on provider-native continuation. Parent/root same-attempt redispatch reuses the same Gateway `sessionKey` when continuity reuse remains lawful and otherwise falls back to a fresh `sessionKey`, then sends a fresh Gateway `agent` request with a fresh `idempotencyKey` and still emits `full_prompt` by resending the full regenerated canonical prompt package. Gateway then returns a fresh `runId` for that live execution. Continuity-sideband state may still be persisted for observability, but it does not create a live controller path that emits `same_session_continue`. It does not change assignment lineage, attempt lineage, persisted prompt truth, or the controller recovery-action family.

Continuity rule:

- same-session continuity does not change the live-run discriminator
- parent/root same-attempt redispatch may reuse `sessionKey` when continuity reuse remains lawful and otherwise may fall back to a fresh `sessionKey` without changing assignment or attempt lineage, while worker-lane liveness and transport routing still discriminate the live run by the fresh returned `runId`
- pre-accept socket noise must not be promoted into liveness truth by `sessionKey` alone

## Canonical v1 control consequence

- `full_prompt` is the only send mode emitted by the canonical live controller path
- parent/root same-attempt redispatch reuses the same Gateway `sessionKey` when continuity reuse remains lawful and otherwise falls back to a fresh `sessionKey`, always sends a fresh `idempotencyKey`, and accepts a fresh returned `runId`
- worker retry, new attempt, and fresh child assignment use a fresh Gateway `sessionKey` and a fresh `runId`
- `session_key_present` and `invalidation_reason` remain transport-private/operator-facing observability only
- the live prompt transport path does not use `previous_response_id` or `same_session_continue` prompt/request residue

## Controller mapping

| Controller action                                 | Canonical transport mapping                                                                                                                                                                               |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| parent/root `redispatch_same_attempt`             | Gateway WS `agent` with the previous `sessionKey` when continuity reuse remains lawful or a fresh `sessionKey` when it does not, plus a fresh `idempotencyKey`, full resend, and a fresh returned `runId` |
| worker retry or any semantic `create_new_attempt` | `full_prompt` over a fresh-session launch                                                                                                                                                                 |
| `escalate`                                        | no dispatch                                                                                                                                                                                               |

## Continuity shape

The runtime keeps same-session continuity at the Gateway `sessionKey` layer only:

- launch control still emits `full_prompt`
- OpenClaw request envelopes still carry the regenerated canonical prompt package split into provider instruction and user input lanes
- `continuity-state.json` remains an observability projection, not a second dispatch planner

## OpenClaw request mapping

Keep the canonical Gateway WS request shape separate from any OpenResponses HTTP adapter detail.

Canonical Gateway WS `agent` request fields:

- `sessionKey` = the Gateway continuity selector for the current execution context
- `extraSystemPrompt` = AutoClaw `instructions_text`, the regenerated provider-system instruction lane
- `message` = AutoClaw `input_text`, the regenerated node-facing user/input lane
- `idempotencyKey` = the fresh launch/dedupe key for that dispatch request

Canonical Gateway WS response field used by runtime:

- `runId` = the fresh returned live-execution handle for that request

Rules:

- provider/OpenResponses fields are adapter-native transport detail only
- they are not the canonical Gateway WS request shape
- they are not the required controller inputs for parent/root same-attempt redispatch
- fallback to one combined `message` is legal only for explicit older-Gateway rejection of `extraSystemPrompt` before acceptance

The persisted prompt truth remains the full regenerated canonical prompt package for every dispatch. `prompt.md` keeps the combined readback, while the live OpenClaw Gateway request preserves the split through `extraSystemPrompt` plus `message`.

## Send-mode consequences

### `full_prompt`

- sends regenerated `instructions_text` in `extraSystemPrompt` and regenerated `input_text` in `message`
- uses the canonical Gateway WS `agent` path with the same `sessionKey` when continuity reuse remains lawful or a fresh `sessionKey` when it does not, plus a fresh `idempotencyKey`
- accepts a fresh returned `runId` from Gateway
- does not require adapter-private response chaining on the canonical Gateway WS path
- is the locked resend shape for parent/root same-attempt redispatch

## Related contracts

- [OpenClaw session lifecycle](openclaw-session-lifecycle.md)
- [Watchdog and recovery contract](watchdog-and-recovery-contract.md)
- [Render and persistence](../prompt-layer/render-and-persistence.md)
