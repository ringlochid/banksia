# Capability, security, and audit

Status: Target

This page owns V2 managed-agent capability decisions, noninteractive provider policy, MCP trust separation, the loopback control-plane boundary, and controller audit provenance.

## Core rule

Controller-owned capability decides which semantic Node actions are legal. Provider policy may narrow local execution but never widens controller authority or becomes controller audit truth.

Native provider tools, provider network access, Node MCP exposure, controller `command_run`, and AutoClaw human requests are separate dimensions. Enabling one does not silently enable or deny another.

## Trust lanes

| Lane | Principal and scope | Admission and authority source | Attached to provider execution |
| --- | --- | --- | --- |
| managed Node MCP | one managed Codex/Claude invocation | opaque `DispatchMcpBinding` credential mapped to exact task + dispatch, followed by fresh controller validation | yes |
| compatibility Node MCP | user-configured experimental OpenClaw client | full `task_id` + `dispatch_id` scope selectors, operator-controlled local reachability, and fresh controller validation | yes, by user configuration |
| Operator MCP | locally admitted operator surface | loopback or OS-owned process boundary plus task-scoped controller legality | never |
| HTTP Control API | local client | enforced loopback boundary plus request-local task, currentness, and operation legality | never |
| packaged console | same-origin local browser application | loopback, exact Host, exact unsafe-request Origin, and controller legality | never |
| provider adapter | AutoClaw service identity | provider-native credential and configuration | invokes provider only |

No lane inherits another lane's credentials or authority. Managed Node credentials do not grant operator control, local operator admission does not grant Node dispatch authority, and provider login never authorizes a controller mutation.

## Local operator boundary

The V2 target has no global operator API key. It defines no `security.api_key`, `X-AutoClaw-API-Key`, API-key bootstrap response, browser bundle or storage path, or equivalent shared operator bearer.

The HTTP Control API, Operator MCP, packaged console, and local nonbrowser clients rely on the enforced loopback listener and the operating-system process/user boundary. Local admission is not blanket controller authority. Every request still passes its route method, strict shape, task scope, currentness, capability, and operation-specific legality checks.

When audit needs an actor reference, these surfaces use a stable value such as `local_operator`. It means that the locally admitted operator surface performed the action; it is not a verified named-human identity.

Provider setup, login, enablement, and default mutation remain CLI-only. Browser and HTTP control surfaces may read bounded provider/default/check status but expose no provider-mutation route and never return provider credentials.

## Managed Node authority

Managed execution receives a private `/_internal/node/mcp` URL, bearer credential, and role-scoped tool allowlist dynamically for one provider-start invocation. The credential resolves to an ephemeral process-local `DispatchMcpBinding`; it is never a prompt field, task file, tool argument, database record, provider continuity value, log field, or public readback.

The transport requires a direct loopback peer, exact allowed Host, and exact Origin handling. It is excluded from public OpenAPI and must not be published by a reverse proxy. Missing or invalid credentials, non-loopback peers, forged Host, and disallowed Origin fail before controller lookup or Node activity.

Every admitted call rereads dispatch, flow, assignment, attempt, role, exposure, and capability. A binding is not a lease; database currentness is the final authority. This dispatch-scoped bearer is distinct from the removed global operator API key and remains required for managed Node MCP.

## Compatibility Node authority

The `/node/mcp` compatibility projection requires full `task_id` and `dispatch_id` selectors on every tool. The IDs select scope but do not authenticate a caller.

This lane has no managed binding credential because AutoClaw does not own or mutate the user's OpenClaw configuration. It remains experimental and must be reachable only inside an operator-controlled local boundary. The server rejects unapproved Host values and, when an Origin header is present, rejects every value outside an exact configured allowlist. It never uses wildcard Origin reflection.

A compatibility call still rereads exact current controller authority and fails rather than redirecting from a stale dispatch to a newer one. Knowing IDs cannot make a stale or role/capability-denied operation legal, but reachable compatibility access is still a weaker authentication boundary and must be documented as such.

## Effective capability set

The controller freezes one effective capability set for each dispatch:

```yaml
effective_capability_set:
  dispatch_id: string
  provider_native_access:
    effective: full | restricted | denied
    source: default | policy_definition | task_policy | controller
  network_access:
    effective: allow | deny
    source: default | policy_definition | task_policy | controller
  human_request:
    direction: allow | deny
    approval: allow | deny
    input: allow | deny
    review: allow | deny
  command_run: allow | deny
```

`PolicyDefinition.capabilities` owns the authored native-access and network ceilings. Nodes inherit them through `policy_id`; task policy and controller-enforced ceilings may only narrow them.

Rules:

- omitted provider-native access resolves to `full` and omitted network access resolves independently to `allow`;
- resolution chooses the most restrictive applicable value using `full > restricted > denied` and `allow > deny`;
- adapter or local hard ceilings count as `controller`;
- when equally restrictive ceilings tie, reported source precedence is `controller > task_policy > policy_definition > default`;
- omitted special AutoClaw capabilities and omitted human-request kinds resolve to `deny`;
- explicit provider selection never silently falls back to another provider;
- the dispatch's resolved provider and capability set remain fixed for that dispatch;
- a successor recomputes from current controller truth;
- adapter permission systems may be stricter but cannot permit a controller-denied semantic operation;
- managed Node MCP attachment is required for managed Codex/Claude launch rather than an optional semantic capability; and
- pause, continue, cancel, human-request resolution, and command-run cancellation are separately authorized operator controls.

No task file or prompt authorizes capability. Definition preview, current context, runtime/API readback, CLI/status, and console readbacks disclose the same effective values and sources without exposing provider credentials or private configuration.

## Capability enforcement

The minimum special semantic families are:

- `human_request.<direction|approval|input|review>`; and
- `command_run`.

Capability validates during pre-admission current-authority checks. Denial returns the shared structured failure with `code: capability_rejected`, creates no source/wait row, leaves D1 open, emits no domain event, and does not refresh Node activity.

Ordinary read, plan, checkpoint, boundary, definition, and structural operations retain their own role and policy checks. The catalog descriptor and fresh controller state jointly determine whether each is exposed and legal.

## Provider-native access

Provider-native filesystem, shell, search, network, and similar tools remain provider-owned execution surfaces. AutoClaw configures their machine policy explicitly but does not ingest provider tool events as controller truth.

Full provider-native access does not imply:

- permission to call parent/root Node tools;
- permission to use controller `command_run`;
- permission to open a human request;
- managed Node MCP authority for another dispatch; or
- interactive approval prompts.

The provider must be configured noninteractively. A native question/approval mechanism must allow under the declared machine policy, deny with a normal tool failure, or make launch fail if noninteractive behavior cannot be guaranteed. AutoClaw never waits on an unconsumed provider UI.

## Provider selection provenance

Each dispatch records:

```yaml
provider_resolution:
  requested_provider: openclaw | codex | claude
  resolved_provider: openclaw | codex | claude
  selection_basis: explicit | default
```

For an explicit request, requested and resolved values must match or dispatch preparation fails. An omitted request may resolve through the configured default. There is no fallback chain.

Opaque provider session hints, credentials, provider payloads, raw errors, and binding material never appear on public readbacks. Provider identity explains the chosen adapter, not lifecycle or semantic progress.

## Loopback browser boundary

V2 accepts only loopback listener configuration such as `127.0.0.1` or `::1`; `0.0.0.0` and every non-loopback bind value are invalid.

The packaged console is served from the API origin. The server enforces an exact allowlist of loopback Host values, validates the exact configured Origin for unsafe browser requests, and rejects mismatched browser origins before route handling. Development CORS may enumerate exact local origins, methods, and headers, but it never uses wildcard origin reflection or wildcard credentialed CORS.

The loopback target intentionally adds no browser session, cookie lifecycle, CSRF-token subsystem, login/logout/expiry/revocation machinery, TLS or reverse-proxy profile, non-loopback deployment, remote-browser authentication, or browser-owned provider management. Exact Origin validation is the CSRF boundary for the supported no-cookie, no-browser-credential shape. A later remote or browser-provider-mutation product requires a new decision.

## Task scope and human provenance

Control reads and writes validate task scope and operation legality. Provider login authenticates AutoClaw to a provider; it never authorizes controller mutation.

Every terminal human request stores its request/task identity, terminal kind, actor reference when applicable, resolution surface, timestamp, policy basis, and bounded optional note. The source row is immutable audit truth after terminalization. Full sensitive answer bodies remain on their authorized detail surface rather than generic task events.

## Audit ownership

Controller source rows own current truth. The append-only task event stream owns bounded chronology over committed source changes and may retain chained integrity metadata.

Provider output, native tool events, approval UI, token streams, disconnects, terminal frames, and MCP transport sessions are never controller audit facts. Provider-start readback describes AutoClaw's own attempt state only.

Optional `NodeMcpInvocation` rows remain bounded internal audit evidence. They never contain request/response bodies, file content, binding credentials, provider payloads, raw human answers, command logs, or hidden reasoning. The dispatch's activity timestamp/revision, not invocation classification, is watchdog authority.

## Payload and secret boundary

- human-request list/detail may expose authorized typed source and resolution;
- task events carry bounded identifiers, states, summaries, and provenance rather than full answer bodies;
- command-run detail may expose normalized truth and log refs, while raw logs stay behind an authorized route;
- provider and managed-MCP credentials never enter task rows, events, prompts, files, or browser readbacks;
- no global operator key enters configuration, headers, browser bootstrap, bundles, storage, logs, or readbacks;
- raw environment secrets never enter command specs or generic audit payloads; and
- exact controller IDs are identifiers, not secrets.

The local-first phase does not add heuristic secret scanning as a substitute for these ownership boundaries.

## Required invariants

- managed execution receives Node MCP and never Operator MCP;
- compatibility Node MCP remains explicit, weaker, user-configured, and experimental;
- a worker cannot acquire parent/root tools through native-provider access or MCP discovery;
- effective capability is fixed for one dispatch and recomputed for a successor;
- provider-native access, network access, Node MCP, command run, and human requests remain separate axes;
- provider-native interactive waits are disabled;
- local operator admission never claims a verified human identity;
- provider authentication never authorizes controller mutation;
- browser provider mutation is absent from the loopback-only target;
- the global operator API key is absent while managed binding and provider credentials remain private; and
- controller source rows and events remain the only controller audit truth.

## Framework basis

[Starlette TrustedHostMiddleware](https://www.starlette.io/middleware/#trustedhostmiddleware) provides maintained exact Host enforcement, and [Starlette CORSMiddleware](https://www.starlette.io/middleware/#corsmiddleware) supports explicit origin, method, and header allowlists. [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html) provides the Origin-validation basis for unsafe browser requests. These implementation primitives do not widen the loopback-only product boundary.

## Related contracts

- [ADR-0010: dispatch-scoped managed Node MCP authority](../../../adr/ADR-0010-dispatch-scoped-managed-node-mcp-authority.md)
- [ADR-0012: loopback control plane without an operator API key](../../../adr/ADR-0012-loopback-control-plane-without-operator-api-key.md)
- [Managed Node MCP binding](../architecture/managed-node-mcp-binding.md)
- [Controller contract and resumable execution](../architecture/controller-contract-and-resumable-execution.md)
- [Runtime records and control state](../architecture/runtime-records-and-control-state.md)
- [Node and Operator MCP surface contract](node-and-operator-mcp-surface-contract.md)
- [Provider selection and runtime config](provider-selection-and-runtime-config.md)
- [Role and policy definition schema](role-and-policy-definition-schema.md)
- [Human request and approval contract](human-request-and-approval-contract.md)
- [Command run and external wait](../architecture/command-run-and-external-wait.md)
- [Control API](control-api.md)
- [Task event stream](task-event-stream.md)
