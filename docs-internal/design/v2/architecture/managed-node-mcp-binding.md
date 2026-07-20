# Managed Node MCP binding

Status: Target

This page owns the target mechanism that gives one managed provider invocation access to exactly one current AutoClaw dispatch. The logical Node operation catalog and model-visible schemas belong to the [Node and Operator MCP surface contract](../interfaces/node-and-operator-mcp-surface-contract.md); controller records remain owned by [Runtime records and control state](runtime-records-and-control-state.md).

## Core model

AutoClaw creates one managed Node MCP application for the API process and one ephemeral `DispatchMcpBinding` for each managed provider invocation.

```text
one FastAPI process
  -> one managed Node MCP application
       -> binding credential A -> task T1, dispatch D1, worker ceiling
       -> binding credential B -> task T2, dispatch D2, parent ceiling
       -> binding credential C -> task T3, dispatch D3, worker ceiling
```

The server is shared. Credentials, controller scope, and exposed tools are not.

## Binding contract

The process-local binding contains only:

```yaml
DispatchMcpBinding:
  credential_digest: <non-reversible lookup value>
  task_id: <canonical task id>
  dispatch_id: <canonical dispatch id>
  provider_start_revision: <nonnegative committed provider-start generation>
  exposure_ceiling: <stable role/tool ceiling>
  lifecycle_state: active | revoked
```

`provider_start_revision` is nonsecret and binds the credential to one committed provider-start generation of the dispatch. The registry may index by a constant-time digest of the presented credential. It must not store the plaintext credential after construction.

The registry retains active bindings only. Revocation atomically removes the entry rather than accumulating a revoked tombstone. Authentication compares the presented digest in constant time against every currently active digest, so historical retry attempts add neither retained credential state nor authentication work.

The credential has no independent wall-clock TTL in this phase. Its authority ends on dispatch currentness loss, explicit revocation, or process restart. A shorter expiry is not added until a safe rotation/refresh contract exists for a still-current provider invocation.

The binding deliberately does not cache:

- assignment or attempt state;
- flow or structural revision;
- current node role or capability result;
- state-dependent allowed actions;
- provider or MCP session IDs;
- request files or prompt bodies; or
- any database object or `AsyncSession`.

Those facts can change independently and are reread for every invocation.

## Creation sequence

The dispatch starter creates a binding only after it has:

1. received `DispatchStartDue(dispatch_id, provider_start_revision, due_at)`;
2. opened a fresh database session;
3. proved that the dispatch is the current `starting` dispatch at the signal's exact `provider_start_revision`;
4. loaded its exact assignment, role, policy, and effective tool exposure;
5. validated the committed `instructions.md` and `input.md` refs; and
6. proved that the selected provider uses the managed projection.

It then generates a cryptographically random opaque credential, stores only its digest and exact provider-start revision with the binding, builds the provider's exact tool allowlist, and invokes the adapter with the private connection material.

Provider invocation is skipped if binding construction or request validation fails. No binding is created for a losing or uncommitted candidate dispatch.

## Retry and replacement

Every provider-start attempt that is not positively retained as the current accepted execution revokes its binding. The retry receives a fresh credential even though it retains the same `dispatch_id` and request files.

A same-dispatch replacement first conditionally advances and commits the dispatch's `provider_start_revision`. It then removes the old binding, makes the bounded stop attempt when required, and issues a fresh credential bound to the new committed generation. Advancing database truth first ensures that an old credential already inside request handling loses authority before asynchronous registry removal completes.

A definite start failure conditionally advances and commits the next start generation and due time, then removes the failed attempt's credential. An uncertain attempt follows the same generation-first rule, then makes the one bounded stop attempt when supported before a later fresh-binding start.

For an uncertain start, the starter:

1. advances and commits the same dispatch's provider-start generation;
2. removes the prior credential from the registry;
3. makes one bounded adapter stop call when supported;
4. creates a fresh generation-bound binding and credential; and
5. retries the same current `starting` dispatch regardless of unsupported, failed, or timed-out stop.

For watchdog replacement, the D1 binding is already invalid through the atomic D1-close/D2-create commit. The starter also removes its registry entry, makes the bounded D1 stop attempt, then creates a distinct D2 binding and starts D2.

Physical provider overlap is possible when an adapter cannot stop reliably. It cannot produce legal controller mutations because the old credential is revoked and fresh admission also proves current dispatch identity.

The initial binding is valid for the current `starting` dispatch because the provider may invoke a tool before the adapter acceptance response reaches AutoClaw. If such a tool lawfully closes the dispatch, the binding immediately loses database currentness and a late acceptance write cannot reopen it.

## Revocation

A binding becomes unusable when any of these facts is observed:

- its explicit registry state is revoked;
- its dispatch is no longer current;
- its dispatch is closed or superseded;
- its flow is paused, cancelled, or terminal;
- its role/capability/exposure no longer admits the requested operation; or
- the API process restarted and the binding registry no longer contains the credential.

Database currentness and provider-start generation are the authoritative backstops. Registry removal may happen asynchronously after a commit, but an old call cannot pass the fresh database check in the interim. Removed entries are not retained as revoked tombstones.

After API-process restart, an already `open` managed dispatch remains controller history/current state but has no reconstructed binding. Startup registers its existing watchdog deadline and does not blind-start another provider or mint a credential for an unknown old execution. The next lawful watchdog replacement or operator control establishes fresh authority. OpenClaw compatibility is different because its explicit-ID endpoint has no managed registry; that weaker restart behavior remains part of its experimental lane.

## Managed HTTP transport

The managed application is mounted at `/_internal/node/mcp` in the existing API process. It is not included in the public API router or OpenAPI schema.

The managed transport requires:

- a direct loopback peer;
- an allowed loopback Host value;
- MCP-compliant Origin validation;
- `Authorization: Bearer <opaque credential>` on every request;
- no credential in a path, query, cookie, prompt, or MCP argument; and
- no reverse-proxy exposure of the private path.

The main FastAPI lifespan explicitly enters the managed MCP application's lifespan context. Mounted subapplications do not receive main-app lifespan automatically. The application is created once, not per request or per dispatch.

The server remains stateless at the MCP transport layer. MCP protocol session IDs may optimize transport behavior but never select the binding or authorize controller work.

This bearer is a private one-dispatch Node credential, not a global operator API key. Removing the global operator key from local Control API, Operator MCP, and console surfaces does not remove or weaken managed binding authentication.

## Tool discovery and admission

For managed `tools/list`, the server authenticates the binding, freshly requires its dispatch to remain exact current `starting` or `open` authority, and returns only operations within its stable exposure ceiling. A worker binding therefore never discovers parent/root mutation tools. Discovery itself is not a logical Node invocation and does not refresh activity.

State-dependent legality is not frozen in the listing. Every tool invocation uses two short independently owned phases:

1. authenticates the credential and establishes exact `task_id + dispatch_id` scope;
2. parses the strict semantic request;
3. creates a new `AsyncSession`;
4. rereads current dispatch, its exact binding `provider_start_revision`, flow, assignment, attempt, node, role, capability, and exposure;
5. transaction A requires that exact generation, conditionally refreshes `last_node_activity_at` and `node_activity_revision` once after admission, and commits;
6. publishes the exact watchdog-deadline change after transaction A commits;
7. transaction B opens a fresh session, rereads exact currentness and the same binding generation, and performs the exact read or conditional mutation; and
8. transaction B commits only if the operation's currentness predicates still hold.

Accepted reads, no-ops, and normalized domain failures count as admitted activity. Authentication, stale-scope, role, capability, and exposure rejection do not.

This split is intentional: admitted activity remains committed even when the domain operation returns a normalized failure, while the operation never inherits stale ORM state or a rolled-back activity update. A winner between the phases can make transaction B return `stale_dispatch` or `conflict`; it cannot erase the already admitted activity or mutate the newer dispatch. No task-wide lock or shared `AsyncSession` spans the phases.

## Provider injection

The adapter receives a per-dispatch private connection description conceptually containing:

```yaml
managed_node_mcp:
  url: http://127.0.0.1:<api-port>/_internal/node/mcp
  authorization: Bearer <opaque credential>
  enabled_tools:
    - <exact logical tool name>
```

The exact Codex app-server or Claude Agent SDK field shape is provider-conformance detail. AutoClaw must use a dynamic invocation/thread override and must not persist this connection into user, project, or provider configuration.

Provider-side `enabled_tools` narrows model exposure and improves teaching, but the server repeats the binding and controller checks for every call.

## Compatibility contrast

OpenClaw uses the separate compatibility projection at `/node/mcp`:

| Concern | Managed Codex/Claude | OpenClaw compatibility |
| --- | --- | --- |
| Model-visible scope | semantic arguments only | required full `task_id + dispatch_id` |
| Caller authentication | opaque per-dispatch bearer credential | no AutoClaw per-dispatch credential |
| Tool listing | binding-scoped | static compatibility catalog |
| Configuration | injected dynamically by AutoClaw | maintained by the user in OpenClaw |
| Status | target managed lane | explicit experimental lane |

Both projections call the same runtime-owned operations and fresh authority validator. Neither exposes Operator MCP.

## Lifecycle ownership

The main FastAPI lifespan creates and tears down the registry and MCP application together with the runtime effect router and provider resources. Request handlers and provider adapters consume that lifespan-owned service; they do not expose or manually coordinate application-level `start()` and `close()` methods.

Shutdown revokes every binding before adapter cleanup. Provider cleanup is best effort and does not rewrite already committed controller truth.

## Readback and secrecy

Public and operator readbacks may show the canonical task and dispatch IDs, selected provider, effective tool exposure, and sanitized invocation outcomes. They never show:

- binding credentials or digests;
- registry lifecycle internals;
- provider/MCP session IDs as authority;
- raw Node request or response bodies; or
- provider configuration overrides containing the credential.

Logs identify the dispatch and logical operation through canonical non-secret IDs. Credential values are redacted before structured logging and exception rendering.

## Required proof

- concurrent dispatches using one server cannot cross-resolve credentials or tool sets;
- a worker cannot list or call parent/root-only operations;
- stale, closed, superseded, paused, wrong-task, and wrong-dispatch calls fail before semantic effect;
- retry revokes the old credential and issues a new one for the same dispatch;
- restart invalidates every old credential and safely reschedules eligible starting dispatches;
- credentials never appear in prompts, files, events, API readbacks, logs, or provider configuration;
- managed and compatibility projections preserve semantic schema/result parity; and
- Host, Origin, loopback, and bearer checks fail closed for the managed mount.

## Framework and protocol basis

- [MCP Streamable HTTP transport security](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports) requires Origin validation and recommends local binding for local servers.
- [MCP authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization) supplies the HTTP authorization model; AutoClaw's private dispatch bearer remains a narrower local binding credential rather than an operator identity.
- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) owns application resources and documents the mounted-subapplication lifespan boundary that the main app must enter deliberately.

## Related

- [ADR-0010: dispatch-scoped managed Node MCP authority](../../../adr/ADR-0010-dispatch-scoped-managed-node-mcp-authority.md)
- [Runtime lifecycle and watchdog](runtime-lifecycle-and-watchdog.md)
- [Minimal provider adapter contract](adapter-contract.md)
- [Node and Operator MCP surface contract](../interfaces/node-and-operator-mcp-surface-contract.md)
- [Capability, security, and audit](../interfaces/capability-security-and-audit.md)
- [OpenClaw support and compatibility](../interfaces/openclaw-support-and-compatibility.md)
