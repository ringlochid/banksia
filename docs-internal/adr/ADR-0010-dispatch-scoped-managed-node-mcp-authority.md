# ADR-0010: dispatch-scoped managed Node MCP authority

Status: Accepted

## Decision summary

Managed Codex and Claude execution uses one shared AutoClaw Node MCP application plus one ephemeral `DispatchMcpBinding` per provider invocation. The binding authenticates an opaque credential to the exact current task and dispatch while leaving all model-visible managed tool schemas free of controller selectors and credentials.

OpenClaw remains an experimental lane selectable explicitly or through an operator-configured default, using a separate compatibility projection at `/node/mcp`. Compatibility tools add full `task_id` and `dispatch_id` selectors to the same logical operation catalog and perform the same fresh controller validation, but they do not inherit managed binding authentication.

## Context

ADR-0008 retained `NodeSession.session_key` as model-visible recognition authority. That duplicates dispatch lifecycle, exposes a secret-like value in tool schemas and prompts, couples controller authority to provider/session machinery, and still requires fresh currentness validation.

Managed provider integrations can receive a private per-dispatch HTTP credential dynamically. OpenClaw cannot rely on the same injected configuration and remains user-managed, so the two transports need different identity projections without forking semantic operations or controller rules.

## Decision

### One logical operation catalog

AutoClaw owns one provider-neutral Node operation catalog. Each operation descriptor owns its logical name, semantic input and output schema, allowed roles, required capability, mutation classification, and teaching metadata.

The target dependency direction is:

```text
runtime/node_tools/
  catalog
  authority
  operations/

interfaces/mcp/node/
  managed/
  compatibility/
```

Runtime operations own controller reads, validation, and transaction boundaries. MCP projections own transport registration and schema adaptation only. Provider integrations may select a projection and pass connection material but never duplicate Node operations or authority rules.

### DispatchMcpBinding

`DispatchMcpBinding` is a process-local registry entry with only:

- a digest or lookup key for one opaque credential;
- the canonical `task_id` and `dispatch_id`;
- the nonsecret, nonnegative committed `provider_start_revision` for this provider invocation;
- the maximum role/tool exposure ceiling established at dispatch start; and
- active or revoked lifecycle state.

It is not a database row, provider thread, MCP protocol session, prompt field, task file, public API model, or cached controller snapshot. Assignment, attempt, structural revision, role, capability, tool exposure, and operation legality are reread from the database on every invocation.

The binding is created only for a committed current `starting` dispatch with valid request refs and the exact committed provider-start revision. Closing, superseding, pausing, retrying, or cancelling the dispatch revokes its credential. Revocation removes the registry entry rather than retaining a tombstone. Every provider-start retry receives a fresh credential. API-process restart invalidates the whole registry.

A same-dispatch replacement first advances and commits `provider_start_revision`, then removes the old registry entry, and only then issues a fresh credential bound to the new generation. Both short Node database phases require the binding's exact generation as well as dispatch currentness, so an old in-flight request loses authority as soon as the generation advance commits.

### Managed projection

The managed projection is one stateless Streamable HTTP application created once and entered through the main FastAPI lifespan. It is privately mounted at `/_internal/node/mcp`, excluded from public OpenAPI, and rejects non-loopback peers. The deployment must not proxy this path to an untrusted network.

Every request carries `Authorization: Bearer <opaque credential>`. Credentials never appear in the URI, query, prompt, task files, provider continuity fields, logs, events, or readbacks. Transport handling validates the exact allowed Host and Origin posture in addition to credential authentication.

Managed model-visible tool schemas contain semantic arguments only. `tools/list` resolves the binding and exposes only its stable dispatch tool ceiling; a worker never receives parent/root-only operations. Provider-side allowlists are defense in depth and model guidance, not controller authority.

### Compatibility projection

The OpenClaw compatibility projection keeps the provider-neutral `autoclaw-node` identity and existing `/node/mcp` endpoint. Every tool adds required full `task_id` and `dispatch_id` arguments before its semantic fields.

Those IDs are public scope selectors, not credentials. The projection has no managed binding or separate per-dispatch secret. It validates Host and Origin, relies on operator-controlled reachability, and remains explicitly experimental because anyone who can reach it and knows current IDs can attempt the operations that controller validation permits.

The compatibility application is created once and entered through the main FastAPI lifespan. It may advertise the complete compatibility catalog during `tools/list` because no dispatch scope exists at discovery. Call-time validation remains authoritative.

AutoClaw does not inject, edit, or maintain `openclaw.json`. The user configures the compatibility endpoint and tool exposure in OpenClaw. AutoClaw does not weaken OpenClaw bind, authentication, sandbox, tool, exec, or approval policy to make the lane work.

Provider selection is independent of this transport distinction. An operator may select OpenClaw explicitly or configure it as the default; installation, discovery, another provider's failure, and incomplete conformance never select it implicitly or globally disable it.

### Fresh call-time admission

Every managed or compatibility invocation follows this sequence:

```text
establish exact task and dispatch scope
  -> authenticate managed binding or parse compatibility selectors
  -> parse strict semantic input
  -> reread dispatch, flow, assignment, attempt, node, role, capability, and exposure
  -> require exact current starting/open authority
  -> admit and refresh Node activity once
  -> perform the exact read or conditional mutation
  -> commit only while the owning predicates remain true
```

The activity refresh occurs once for every admitted call, including reads, accepted no-ops, and normalized domain failures. Calls rejected before admission do not refresh it.

A stale or wrong task, dispatch, role, capability, exposure, or operation fails without falling through to another execution. Currentness is optimistic and backed by controller constraints; a binding is never a lease.

### Provider injection

Managed adapters receive the private MCP URL, opaque credential, and exact provider-side tool allowlist dynamically for each dispatch. This material is not written to user or project provider configuration.

Codex and Claude adapter conformance owns the exact SDK/app-server injection shape because provider wire fields may change. The invariant is stable: each dispatch gets its own credential and exposure, multiple concurrent dispatches share one server without sharing authority, and provider continuity never authenticates a Node mutation.

### Trust boundaries

Managed Node MCP, compatibility Node MCP, Operator MCP, the HTTP Control API, provider adapters, and the packaged console are distinct principals. No lane inherits another lane's authority.

The local Operator MCP, HTTP Control API, packaged console, and local nonbrowser clients rely on the enforced loopback or OS-owned process boundary rather than a global operator API key. The managed `DispatchMcpBinding` bearer remains a separate credential with one-dispatch Node scope. Provider-owned credentials likewise remain separate and private.

Provider configuration and login remain CLI-only. The loopback browser boundary uses exact Host and unsafe-request Origin checks without adding a browser session, cookie, CSRF-token, TLS/proxy, or remote-browser authentication stack.

Callback HTTP is absent from the V2 target. No callback route, callback bearer/session-key authority, callback schema, provider callback client/configuration, runtime callback handler, or supported target test remains as a second Node mutation projection.

## Consequences

- one shared MCP application supports many concurrent dispatches without per-dispatch servers;
- each dispatch sees only its intended tool set and has an independently revocable credential;
- managed tools have simpler semantic schemas while compatibility stays explicit and auditable;
- controller currentness, not provider or MCP session continuity, remains authority;
- process restart intentionally invalidates managed credentials;
- OpenClaw stays usable explicitly or as the configured default while remaining a user-managed experimental lane; and
- callback HTTP and a global operator key do not survive as parallel authority paths.

## Partial supersession of ADR-0008

This ADR supersedes ADR-0008's `NodeSession.session_key` recognition model, model-visible managed identity arguments, progress-only invocation classification, and assumption that one static Node MCP projection serves every provider identically.

It preserves ADR-0008's task-relative read family, safe logical-path resolver, provider-native workspace editing, controller-owned artifact publication, and rule that generated files never outrank database truth.

## Alternatives rejected

### One MCP server per dispatch

Rejected because lifecycle, ports, discovery, and concurrent dispatch isolation are simpler with one shared server plus binding-scoped credentials.

### Put task and dispatch IDs in managed schemas

Rejected because managed execution already receives a private binding. Repeating selectors in every call is noisy and does not replace authentication or currentness validation.

### Use provider or MCP session IDs as authority

Rejected because they are transport continuity, can outlive controller currentness, and differ across providers.

### Give OpenClaw the managed credential path

Rejected because AutoClaw cannot reliably inject and revoke that credential without owning the user's OpenClaw configuration. The compatibility projection makes the weaker boundary explicit.

### Split semantic operations by provider

Rejected because provider-specific operation implementations would fork controller truth and concept behavior.

### Keep callback HTTP beside Node MCP

Rejected because it would preserve a second session-key mutation authority, duplicate operation schemas and clients, and prevent Node MCP from being the sole target agent-control surface.

## Canonical references

- [Managed Node MCP binding](../design/v2/architecture/managed-node-mcp-binding.md)
- [Node and Operator MCP surface contract](../design/v2/interfaces/node-and-operator-mcp-surface-contract.md)
- [Node MCP schema appendix](../design/v2/interfaces/node-mcp-schema-appendix.md)
- [Capability, security, and audit](../design/v2/interfaces/capability-security-and-audit.md)
- [ADR-0012: loopback control plane without an operator API key](ADR-0012-loopback-control-plane-without-operator-api-key.md)
- [Minimal provider adapter contract](../design/v2/architecture/adapter-contract.md)
- [OpenClaw support and compatibility](../design/v2/interfaces/openclaw-support-and-compatibility.md)
