# OpenClaw Gateway RPC Subset

Status: Target

## Purpose

This page freezes the exact OpenClaw Gateway WebSocket RPC subset that AutoClaw depends on in v1.

Use it to prevent two kinds of drift:

- implementers guessing Gateway request or response shapes from prose
- adapter code silently following upstream OpenClaw changes without a pinned schema snapshot and compatibility check

## Core Rule

AutoClaw v1 does not integrate against the whole OpenClaw Gateway surface.

It integrates against one pinned subset:

- handshake: `connect.challenge`, `connect`, `hello-ok`
- machine control: `agent`, `agent.wait`, `sessions.abort`
- the exact lifecycle and stream events needed to normalize provider delivery into controller-owned observability truth

Everything else is out of scope unless canon is patched first.

## Upstream Truth And Version Pin

- OpenClaw TypeBox schema and generated protocol artifacts are upstream truth.
- AutoClaw must not hand-maintain guessed JSON payloads as the primary adapter contract.
- AutoClaw v1 targets the OpenClaw `2026.5.x` release family and pins the subset through the typed local protocol models under `app/runtime/openclaw/` plus live compatibility proof against an installed `2026.5.x` gateway.
- The exact `PROTOCOL_VERSION` integer must come from that pinned `2026.5.x` contract, not from prose examples copied from docs pages.
- If a vendored upstream snapshot lands later, update this page, the golden fixtures, and the compatibility tests in the same slice.

`hello-ok.features.methods` is feature discovery only. It is not schema truth. `hello-ok.pluginSurfaceUrls` is an optional protocol-v4 transport field. The AutoClaw adapter must accept it without promoting hosted plugin-surface URLs into controller truth.

Configurable transport/runtime knobs are a different category:

- endpoint and request-timeout knobs live under `[openclaw]` in the canonical local `config.toml`
- OpenClaw Gateway auth policy lives in OpenClaw-owned config, not AutoClaw-owned config. AutoClaw may consume supported auth material at connect time, but it must not rewrite `gateway.auth.*`.
- drain, watchdog, and recovery cadence knobs live under `[runtime]`
- protocol version, required methods, required scopes, and required payload fields are canon and compatibility truth, not user-configurable settings

See [Install and onboard](../how-to/install-and-onboard.md) for the canonical config owner page.

## Required Handshake Subset

### `connect.challenge`

AutoClaw must accept the pre-connect event:

```json
{
    "type": "event",
    "event": "connect.challenge",
    "payload": {
        "nonce": "...",
        "ts": 1737264000000
    }
}
```

Required consumed fields:

- `type`
- `event`
- `payload.nonce`
- `payload.ts`

### `connect`

AutoClaw must send one `connect` request as the first client frame:

```json
{
    "type": "req",
    "id": "...",
    "method": "connect",
    "params": {
        "minProtocol": 4,
        "maxProtocol": 4,
        "client": {
            "id": "openclaw-control-ui",
            "version": "...",
            "platform": "...",
            "mode": "webchat"
        },
        "role": "operator",
        "scopes": ["operator.read", "operator.write"],
        "caps": [],
        "commands": [],
        "permissions": {},
        "auth": { "token": "..." },
        "locale": "en-US",
        "userAgent": "autoclaw-openclaw-webchat/..."
    }
}
```

Required request rules:

- `minProtocol` and `maxProtocol` are both the vendored `PROTOCOL_VERSION`
- direct loopback Gateway handshakes use `client.id="openclaw-control-ui"` and `client.mode="webchat"`
- `role` is `operator`
- minimum required scopes are `operator.read` and `operator.write`
- any broader scope request must be explicit and bounded by later canon
- `caps`, `commands`, and `permissions` stay empty for the AutoClaw Gateway adapter path
- auth material stays transport-private and never becomes prompt-visible worker context
- supported loopback token auth sends `auth.token`
- supported loopback password auth sends `auth.password`
- supported explicit loopback no-auth omits auth material and emits a hard operator warning before connect
- omit `device` entirely on the loopback webchat wrapper path
- any non-loopback path requires a later remote identity and trust model and is not a shipped v1 AutoClaw feature
- trusted-proxy auth is blocked until wrapper trust canon explicitly lands

### `hello-ok`

AutoClaw must accept only a successful `hello-ok` response:

```json
{
    "type": "res",
    "id": "...",
    "ok": true,
    "payload": {
        "type": "hello-ok",
        "protocol": 4,
        "server": {
            "version": "2026.5.12",
            "connId": "conn-123"
        },
        "snapshot": {},
        "pluginSurfaceUrls": {
            "canvas": "https://plugins.example.test/canvas"
        },
        "policy": {
            "tickIntervalMs": 15000,
            "maxPayload": 1048576,
            "maxBufferedBytes": 1048576
        },
        "auth": {
            "role": "operator",
            "scopes": ["operator.read", "operator.write"],
            "issuedAtMs": 1737264000000
        },
        "features": {
            "methods": ["agent", "agent.wait", "sessions.abort"],
            "events": [
                "agent",
                "assistant.delta",
                "assistant.message",
                "run.completed"
            ]
        }
    }
}
```

Required consumed fields:

- `type`
- `id`
- `ok`
- `payload.type`
- `payload.protocol`
- `payload.server.version`
- `payload.server.connId`
- `payload.snapshot`
- `payload.policy.tickIntervalMs`
- `payload.policy.maxPayload`
- `payload.policy.maxBufferedBytes`
- `payload.auth.role`
- `payload.auth.scopes`
- `payload.auth.issuedAtMs` when OpenClaw returns auth timing detail
- `payload.auth.deviceToken` only when a later canon slice reopens device-token persistence for a supported path
- `payload.pluginSurfaceUrls` when OpenClaw advertises hosted plugin surfaces; accept the map and ignore unconsumed surfaces
- `payload.features.methods` only as a presence check for required methods
- `payload.features.events` only as a presence check for the required event family and any extra observed event names the adapter may later normalize; this field is discovery-only rather than a frozen raw run-stream contract

Live event-label note:

- current OpenClaw event names may include labels such as `assistant.delta`, `assistant.message`, `thinking.delta`, `tool.call.started`, `tool.call.delta`, `tool.call.completed`, `tool.call.failed`, `run.completed`, `run.failed`, `run.cancelled`, and `run.timed_out`
- older `response.*` and bare `tool.call` labels may still arrive as compatibility input during rollout
- AutoClaw persists only the normalized monitoring enums; the raw label stays bounded debug detail in `provider_event_name`
- `tool.call.delta` is stream-chunk traffic and is dropped before provider-event storage
- retained `tool.call.started|completed|failed` lifecycle frames are stored only when provider-time freshness pruning accepts them as a new `last_provider_signal_at`

Protocol-v4 note:

- `pluginSurfaceUrls.canvas` replaces the deprecated `canvasHostUrl` alias in the live `2026.5.x` contract; the old alias is not part of the pinned subset

AutoClaw must fail closed when:

- `ok` is false
- `payload.type` is not `hello-ok`
- `payload.protocol` does not match the vendored `PROTOCOL_VERSION`
- returned role/scopes cannot legally support `agent`, `agent.wait`, and `sessions.abort`
- required methods are missing from discovered features when the server advertises them

Reconnect and auth rules:

- AutoClaw discovers OpenClaw host state before connect: binary resolution, Gateway URL, loopback status, auth mode, and required secret availability.
- loopback token auth is supported; AutoClaw resolves token material from explicit AutoClaw input or the discovered OpenClaw config path and sends `auth.token`.
- loopback password auth is supported; AutoClaw resolves password material from explicit AutoClaw input or the discovered OpenClaw config path and sends `auth.password`.
- explicit loopback no-auth is supported only when OpenClaw already exposes that mode; AutoClaw sends no auth material and emits a hard operator warning.
- non-loopback Gateway targets are blocked until a later remote identity and trust model lands.
- trusted-proxy auth is blocked until a later wrapper trust contract lands.
- ambiguous auth state, missing required secret material, unresolved secret references, or unsupported auth modes fail closed with a clear diagnostic and remediation note.
- AutoClaw must not run `openclaw config set gateway.auth.*` or otherwise mutate OpenClaw Gateway auth mode, token, password, bind, TLS, or exposure policy.
- on auth failure, stop automatic reconnect loops and surface operator action guidance.

## Required Machine-Control Subset

### `agent`

AutoClaw uses `agent` to start one Gateway run for one controller dispatch.

Runtime ownership rule:

- the actual OpenClaw dispatch call belongs to the runtime-owned adapter surfaces under `apps/api/src/autoclaw/runtime/*`
- CLI, package, setup, and wrapper surfaces may configure or verify this adapter path, but they do not own live `agent` dispatch semantics

Required request behavior:

- use the controller-selected agent-scoped `sessionKey` as the canonical session selector
- send `message`, optional `extraSystemPrompt`, and `idempotencyKey`; do not send the older split root fields `account`, `instructions`, `input`, `meta`, or `previousResponseId`
- map AutoClaw `instructions_text` to Gateway `extraSystemPrompt` and AutoClaw `input_text` to Gateway `message`
- retry with the combined prompt readback in `message` and no `extraSystemPrompt` only when an older Gateway explicitly rejects `extraSystemPrompt` before acceptance
- keep any delivery, provider, or model-tuning extensions adapter-private
- send a deterministic idempotency key when the upstream schema requires one
- side-effecting requests must supply the vendored upstream idempotency-key shape; do not invent an adapter-local substitute
- keep strict delivery behavior by default; do not enable best-effort delivery fallback unless canon explicitly reopens it

Required consumed response fields:

- `runId`
- `status`
- `acceptedAt`

Launch-ordering rule:

- for the launched run, OpenClaw returns the accepted response with the authoritative `runId` before emitting same-run agent/chat events for that run
- that is not a connection-wide quiet period; unrelated broadcasts may still interleave on the same socket before or around that accepted response
- pre-accept socket noise must not become dispatch liveness or support-state truth unless it is already provably bound to the accepted `runId`

AutoClaw must not infer assignment success from `agent` acceptance.

### `agent.wait`

AutoClaw uses `agent.wait` only as terminal confirmation for one live `runId`.

Required consumed response shape:

```json
{
    "runId": "...",
    "status": "ok|error|timeout",
    "startedAt": "...",
    "endedAt": "...",
    "error": {}
}
```

Rules:

- `runId` is the canonical wait correlation key
- `agent.wait` is a terminal snapshot or confirmation API, not a progress-ingestion channel
- adapter compatibility must accept current terminal metadata such as string `error`, `stopReason`, `livenessState`, `aborted`, and `yielded` without treating them as a transport-schema failure
- some live timeout responses may omit `startedAt` / `endedAt`; the adapter must still treat `status=timeout` as an ambiguous transport outcome
- only bare `status=timeout` with no terminal metadata is the live ambiguous wait outcome
- `status=timeout` with terminal metadata such as `endedAt`, `error`, `stopReason`, `livenessState`, `aborted`, or `yielded` is a terminal provider outcome that must reconcile as terminal failure rather than `transport_timeout`
- `status=timeout` is transport uncertainty, not assignment outcome
- `error` is support-only transport detail unless canon explicitly promotes it

### `sessions.abort`

AutoClaw uses `sessions.abort` as the canonical machine abort surface.

Required request rules:

- canonical AutoClaw call path sends `key=sessionKey` and `runId` when the current `runId` is known
- `runId`-only resolution is compatibility behavior, not the canonical AutoClaw adapter contract

Required consumed behavior:

- abort-triggered events may appear before the `sessions.abort` RPC response
- abort acceptance does not by itself prove the old run is terminal
- terminal confirmation still comes from `agent.wait` and/or the exact lifecycle event family this page freezes

## Required Event Subset

AutoClaw pins the upstream Gateway event envelope and one required event family. It does not freeze a guessed upstream raw run-event vocabulary here.

Pinned upstream truth:

- `connect.challenge` during handshake
- the generic Gateway event envelope `{type:"event", event, payload, seq?, stateVersion?}`
- presence of the `agent` event family in `hello-ok.features.events` when the server advertises event discovery

AutoClaw-owned normalization may consume additional observed raw event names only when they correlate to the active dispatch/run and can be mapped into controller-owned observability truth. Extra event names advertised by Gateway are discovery-only until that normalization contract accepts them.

Transport-policy rules:

- validate and record `hello-ok.policy.tickIntervalMs` rather than keeping a stale local heartbeat default after the handshake succeeds
- enforce `hello-ok.policy.maxPayload` and `hello-ok.policy.maxBufferedBytes` rather than stale local buffer or payload defaults after handshake
- treat payload or buffered-output violations as transport compatibility or delivery failures, not as assignment meaning
- normalize accepted raw progress and terminal signals into controller-owned observability enums rather than persisting raw OpenClaw event names as controller truth
- top-level websocket frame `seq` is connection-scoped/optional transport detail and must not be treated as a run event index
- request-local `observed_events` are not part of the target live adapter contract and must not survive as authoritative runtime truth under concurrent transport traffic
- controller-owned normalized provider progress becomes watchdog-visible only after controller-owned ingest commit and stale-replay pruning, never on raw socket receipt or uncommitted adapter buffers

## Target Runtime Transport Architecture

Canonical target design for the worker-lane dispatch path:

- one live dispatch owns one dispatch-scoped runtime RPC handle
- that handle owns one websocket connection or equivalent live transport handle, one reader, and one accepted-run-correlated ingest queue/worker
- startup compatibility probing may reuse transport primitives, but it is not the same thing as a shared process-global live dispatch client

Explicitly rejected as target canon:

- a process-global fan-out registry as the default worker-lane transport model
- per-request raw event buffers being treated as dispatch-local evidence under concurrency
- inline DB ingest inside the transport reader

### AutoClaw Event Consumption Table

| Raw material                                                                                                 | Consumed by AutoClaw | Required meaning when consumed                                        | Normalized output    | Liveness relevance | Dedupe / correlation rule                                                                                                        |
| ------------------------------------------------------------------------------------------------------------ | -------------------- | --------------------------------------------------------------------- | -------------------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| `connect.challenge` event                                                                                    | yes                  | pre-connect handshake challenge                                       | none                 | none               | not part of run liveness                                                                                                         |
| `hello-ok.features.events` entry `agent`                                                                     | yes                  | required event-family presence check                                  | none                 | none               | discovery-only handshake check                                                                                                   |
| Generic event envelope `type,event,payload,seq?,stateVersion?`                                               | yes                  | raw carrier only; not semantic truth by itself                        | none directly        | none directly      | envelope may enter the dispatch queue only after accepted `runId` correlation, then event-specific normalization revalidates it  |
| Raw event correlated to the active dispatch/run and showing first meaningful provider data                   | yes                  | provider stream proved initial live progress                          | `first_data`         | yes                | dedupe by `seq` when present; otherwise use bounded fallback heuristics and require dispatch/run correlation before accepting it |
| Raw event correlated to the active dispatch/run and showing subsequent provider output progress              | yes                  | provider stream advanced after first meaningful data                  | `output_delta`       | yes                | same dedupe and correlation rule as above                                                                                        |
| Raw event correlated to the active dispatch/run and showing tool-side provider activity                      | yes                  | provider-side tool activity occurred on the active dispatch/run       | `tool_event`         | optional hint only | same dedupe and correlation rule as above                                                                                        |
| Raw event correlated to the active dispatch/run and showing provider terminal success                        | yes                  | provider transport ended normally for that run                        | `response_completed` | yes, terminal      | same dedupe and correlation rule as above                                                                                        |
| Raw event correlated to the active dispatch/run and showing provider terminal failure                        | yes                  | provider transport ended with provider-reported failure for that run  | `response_failed`    | yes, terminal      | same dedupe and correlation rule as above                                                                                        |
| Session-correlated event such as `session.message` or session-only `sessions.changed` without live-run proof | no for liveness      | socket/session activity outside authoritative live-run discrimination | none                 | none               | do not use `sessionKey` alone as live-run liveness proof                                                                         |
| Unrelated buffered event such as `presence`, `tick`, or other uncorrelated broadcast traffic                 | no for liveness      | observability noise outside the active dispatch/run                   | none                 | none               | drop before the dispatch event queue when it lacks accepted-run correlation; never update progress anchors                       |
| Broadcast transport event such as `health` or `shutdown` with no active dispatch/run correlation             | no for liveness      | connection/runtime broadcast outside dispatch truth                   | none                 | none               | ignore for dispatch-liveness truth                                                                                               |

## Trusted Execution Context Rule

One current controller dispatch maps to one trusted OpenClaw execution context:

- `task_id`
- `assignment_key`
- `attempt_id`
- `dispatch_id`
- `sessionKey`
- current live `runId`

Rules:

- `sessionKey` is the primary private binding key for `node MCP`
- `runId` is the live-run correlation key for `agent.wait`, `sessions.abort`, and run-correlated provider-event routing
- `sessionKey` is routing context and an additional guard only; it must not be used as sessionKey-only liveness proof for the worker-lane dispatch path
- `runId` is not the canonical callback authority identity
- callback authority comes from trusted session context resolved server-side, not prompt-visible tokens, env files, or caller-supplied dispatch ids
- canonical parent/root same-attempt redispatch reuses the same `sessionKey` when continuity reuse remains lawful and otherwise falls back to a fresh `sessionKey`, while still sending a fresh `idempotencyKey` and accepting a fresh returned `runId`
- worker retry, new attempt, and fresh child assignment use a fresh `sessionKey`, a fresh `idempotencyKey`, and a fresh returned `runId`
- any retained `same_session_continue` transport detail is adapter-private only and must not replace the full-resend Gateway `agent` request contract

## Compatibility And Failure Rules

At adapter startup and reconnect time, AutoClaw must validate:

- negotiated protocol version
- returned role and scopes
- presence of `agent`, `agent.wait`, and `sessions.abort`
- presence of required event families
- policy limits the adapter must obey, including payload and buffering limits

Failure classes must stay explicit:

- protocol mismatch -> fail closed, compatibility error
- missing required method or event -> fail closed, compatibility error
- missing auth or scope in `hello-ok` -> fail closed, compatibility error
- payload or buffer policy violation -> fail closed, transport compatibility or delivery error
- `agent` acceptance without boundary truth -> transport success only
- `agent.wait timeout` -> ambiguous transport outcome, not assignment success

## Required Proof Artifacts

A conforming implementation must land all of these:

- one vendored OpenClaw protocol snapshot for the pinned upstream target
- typed adapter models derived from that snapshot
- golden fixtures for:
    - `connect.challenge`
    - `connect`
    - `hello-ok`
    - `agent` accepted response
    - `agent.wait` success, error, and timeout responses
    - `sessions.abort` request and confirmation path
    - normalized stream-event examples
- startup compatibility checks
- reconnect/auth-drift handling for persisted device tokens and one bounded token-mismatch retry
- a live compatibility lane against a real OpenClaw Gateway

Config writes or bootstrap config presence are not sufficient proof.

## Related Contracts

- [OpenClaw worker and gateway contract](openclaw-worker-and-gateway-contract.md)
- [OpenClaw session lifecycle](openclaw-session-lifecycle.md)
- [OpenClaw continuity and send modes](openclaw-continuity-and-send-modes.md)
- [Provider, worker, and operator boundary](provider-worker-and-operator-boundary.md)
- [Install and onboard](../how-to/install-and-onboard.md)
- [MCP, plugin, and CLI boundary](../interfaces/mcp-plugin-and-cli-boundary.md)
