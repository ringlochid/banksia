# ADR-0012: loopback control plane without an operator API key

Status: Accepted

## Decision summary

AutoClaw V2 is a loopback-only control plane with no global operator API key. The HTTP Control API, Operator MCP, packaged console, and local nonbrowser clients rely on the enforced loopback listener or an OS-owned local process boundary, then pass their task, currentness, capability, and operation-specific legality checks.

The packaged browser surface uses exact Host and unsafe-request Origin validation. Provider configuration and login remain CLI-only. This phase adds no browser session/cookie stack, remote-browser deployment, or callback HTTP compatibility lane.

This ADR records target design and does not claim that the shipped V1 API-key and callback surfaces have already been removed.

## Context

The shipped local console bootstrap returns a global operator API key to browser JavaScript, which then sends the key on operator HTTP requests. Retaining that key in the target would create one broad bearer shared by unrelated local clients while offering little additional protection from code already running as the same local user.

An earlier target direction compensated with a server browser session, cookie lifecycle, CSRF token, expiry/revocation/logout machinery, TLS/proxy rules, and a remote-browser security gate. That is substantially larger than the one-process, local-tool-first product boundary.

Managed Node MCP and provider adapters still need private credentials for different principals. Removing the global operator key must not weaken those narrower credential families or confuse public task/dispatch selectors with authentication.

## Decision

### Loopback and OS-owned local admission

The API listener accepts only loopback bind configuration such as `127.0.0.1` or `::1`. Configuration using `0.0.0.0` or any non-loopback address is invalid and prevents startup.

HTTP Control API and packaged-console requests are admitted through that listener. Operator MCP and other local nonbrowser clients use either the same loopback boundary or an OS-owned local process transport. The supported product does not claim protection from arbitrary code already running as the same operating-system user.

There is no target `security.api_key`, `X-AutoClaw-API-Key`, API-key bootstrap field, browser storage key, or equivalent shared operator bearer. Local admission does not bypass controller rules: every operation still validates strict input, task scope, currentness, capability where applicable, and its exact legal transition.

### Browser request boundary

The packaged console is served same-origin from the loopback API. The server applies:

- an exact allowlist of loopback Host values;
- exact Origin validation for unsafe browser requests before route handling;
- unsafe HTTP methods for state changes rather than mutating `GET` routes;
- exact enumerated development origins, methods, and headers when development CORS is enabled; and
- no wildcard origin reflection or wildcard credentialed CORS.

Origin validation is the CSRF boundary for the supported no-cookie, no-browser-credential shape. This phase adds no server browser session, cookie lifecycle, CSRF token, login/logout/expiry/revocation machinery, TLS or reverse-proxy deployment profile, non-loopback listener, or remote-browser authentication.

### Provider mutation stays CLI-only

Provider setup, login, enablement, credential changes, and default mutation remain on trusted local CLI operations. Browser and HTTP control surfaces may read bounded provider/default/check status but expose no provider-mutation endpoint and return no provider credential.

A future remote or browser-owned provider-management product requires a new security decision. It is not an activation switch hidden inside this local target.

### Credential families remain separate

The managed `DispatchMcpBinding` bearer remains required on `/_internal/node/mcp`. It authenticates one managed provider invocation to one exact task and dispatch and is not operator authority.

Provider-native credentials remain owned by their provider integrations and private from controller readbacks. The OpenClaw compatibility projection adds no per-dispatch secret: its full `task_id` and `dispatch_id` arguments are public scope selectors, and operator-controlled local reachability plus fresh controller validation define its explicitly weaker experimental boundary.

Neither removing the operator key nor trusting the local boundary widens Node, provider, or compatibility authority.

### Local audit provenance

Local mutations may record `local_operator` as their stable actor/surface reference. The value means that the locally admitted operator surface performed the action. It is not a cryptographically authenticated human identity and must not be presented as one.

### Callback HTTP is absent

Callback HTTP is not a deprecated, fallback, or compatibility path in V2. The target has no callback routes, callback bearer/session-key authority, callback request or response schemas, provider callback clients/configuration, runtime callback handlers, or supported callback tests. Retained Node operations use the managed or explicit-ID compatibility Node MCP projection.

Historical ADRs and shipped-current pages may describe callback HTTP until implementation removes it. They do not make it target authority.

## Consequences

- local setup and operation avoid a shared secret that would otherwise be exposed to the packaged browser;
- the supported security boundary is small enough to teach and test directly;
- Host and Origin validation remain necessary even on loopback because browser and DNS-rebinding requests can cross application boundaries;
- local processes running as the same OS user are within the trusted operator boundary;
- remote or multi-user browser access is unsupported rather than partially secured;
- provider configuration remains a CLI workflow;
- managed Node and provider credential isolation remain unchanged; and
- callback HTTP can be deleted without retaining dual mutation authority.

## Alternatives rejected

### Keep a global operator API key

Rejected because one shared bearer would span HTTP, CLI/automation, Operator MCP, and browser bootstrap while being delivered to JavaScript in the packaged local-console design. It does not establish a useful named-user boundary for the local phase.

### Add a browser session and remote-deployment stack now

Rejected because session cookies, CSRF-token lifecycle, login/logout, expiry/revocation, TLS/proxy ownership, and remote-browser authentication solve a product boundary that V2 does not support.

### Rely on loopback without Host or Origin validation

Rejected because listener scope alone does not reject forged Host or cross-origin browser requests. Exact Host and unsafe-request Origin checks are part of the local boundary.

### Reuse the managed Node bearer for operators

Rejected because the managed bearer has one-dispatch Node scope and lifecycle. Reusing it would merge provider execution with operator authority.

### Treat OpenClaw selectors as credentials

Rejected because task and dispatch IDs are public correlation values. Compatibility remains an explicit weaker local projection and repeats current controller validation on every call.

### Retain callback HTTP during target implementation

Rejected because a second session-key mutation lane would duplicate authority, schemas, provider clients, and tests. Implementation ordering may prove Node MCP coverage before deletion without making callback HTTP part of the target.

## Proof obligations

- listener configuration rejects wildcard and non-loopback bind values;
- unapproved Host and unsafe browser Origin values fail before route work;
- packaged console requests are same-origin and development CORS accepts only exact configured origins;
- configuration, schemas, headers, clients, bootstrap responses, browser bundles/storage, and logs contain no global operator API key;
- HTTP and browser routes expose no provider-configuration mutation;
- local operator mutations retain task/currentness/operation legality and use `local_operator` only as surface provenance;
- managed Node MCP still rejects missing or wrong binding credentials and never accepts operator authority;
- provider credentials and managed binding material remain absent from public readbacks; and
- route, OpenAPI, schema, provider-client/configuration, runtime-handler, and target-test inventories contain no callback HTTP lane.

## Canonical references

- [Capability, security, and audit](../design/v2/interfaces/capability-security-and-audit.md)
- [Node and Operator MCP surface contract](../design/v2/interfaces/node-and-operator-mcp-surface-contract.md)
- [Managed Node MCP binding](../design/v2/architecture/managed-node-mcp-binding.md)
- [ADR-0010: dispatch-scoped managed Node MCP authority](ADR-0010-dispatch-scoped-managed-node-mcp-authority.md)
- [Control API](../design/v2/interfaces/control-api.md)
- [OpenClaw support and compatibility](../design/v2/interfaces/openclaw-support-and-compatibility.md)
