# Design docs (v2)

Status: Target

This tree is the current target product and implementation source of truth for V2-owned surfaces. It succeeds the V1 target baseline where an owner page exists; it is not shipped-behavior contrast and does not claim that target implementation has landed.

## Core direction

V2 preserves these baseline rules:

- controller database rows own runtime truth;
- explicit dispatch, source, wait, boundary, and continuation records beat hidden conversation state;
- provider output, terminal state, transport sessions, prompts, and support projections never decide assignment success;
- parent, worker, operator, and support lanes remain distinct products;
- portable definitions stay separate from machine-local provider configuration; and
- one-process local-tool-first scope remains in force until later canon reopens distributed delivery.

V2's current runtime direction is:

- synchronous concept transactions for boundaries, human requests, command runs, pause/cancel, and other authoritative mutations;
- a thin lifespan-owned `RuntimeEffectRouter` for exact-source after-commit, deadline, process, watchdog, and provider-start work;
- signal-driven steady state with fresh minimum reads, short conditional writes, and database constraints rather than broad polling or per-task serialization;
- request-file materialization before D2 commits, followed by asynchronous provider start;
- indefinite same-D2 provider-start retry with no provider-output/drain/terminal gate;
- an admitted Node MCP activity clock and bounded same-attempt watchdog replacement;
- one logical Node operation catalog with managed binding and explicit-ID compatibility projections;
- optional assignment-owned work plans distinct from checkpoints and boundaries;
- two immutable dispatch request files, `instructions.md` and `input.md`;
- zero-provider controller startup, strict authored provider selection, and one explicit non-fallback default;
- independent native-tool and network ceilings with source-bearing readbacks; and
- a loopback/OS-trusted local control plane with no global operator API key or callback HTTP lane.

## Mandatory runtime read order

1. [Runtime lifecycle and watchdog](architecture/runtime-lifecycle-and-watchdog.md)
2. [Runtime records and control state](architecture/runtime-records-and-control-state.md)
3. [Work plan and checkpoint contract](architecture/work-plan-and-checkpoint-contract.md)
4. [Task root and file access](architecture/task-root-and-file-access.md)
5. [Controller contract and resumable execution](architecture/controller-contract-and-resumable-execution.md)
6. [Minimal provider adapter contract](architecture/adapter-contract.md)

Then read the exact interface or provider owner for the slice.

## Interface and integration owners

1. [Managed Node MCP binding](architecture/managed-node-mcp-binding.md)
2. [Node and Operator MCP surface contract](interfaces/node-and-operator-mcp-surface-contract.md)
3. [Node MCP schema appendix](interfaces/node-mcp-schema-appendix.md)
4. [Capability, security, and audit](interfaces/capability-security-and-audit.md)
5. [Human request and approval contract](interfaces/human-request-and-approval-contract.md)
6. [Command run and external wait](architecture/command-run-and-external-wait.md)
7. [Prompt layer](prompt-layer/README.md)
8. [Workflow node schema](interfaces/workflow-node-schema.md)
9. [Role and policy definition schema](interfaces/role-and-policy-definition-schema.md)
10. [Provider selection and runtime config](interfaces/provider-selection-and-runtime-config.md)
11. [Provider CLI and check](interfaces/provider-cli-and-check.md)
12. [Provider support and compatibility](interfaces/provider-support-and-compatibility.md)
13. [Control API](interfaces/control-api.md)
14. [Task event stream](interfaces/task-event-stream.md)
15. [Console runtime surfaces](interfaces/console-runtime-surfaces.md)
16. [Definition authoring workbench](interfaces/definition-authoring-workbench.md)
17. [Definition authoring API and flat draft contract](interfaces/definition-authoring-api-and-flat-draft-contract.md)

## Decision owners

- [ADR-0009: exact-source runtime control](../../adr/ADR-0009-exact-source-runtime-control.md)
- [ADR-0010: dispatch-scoped managed Node MCP authority](../../adr/ADR-0010-dispatch-scoped-managed-node-mcp-authority.md)
- [ADR-0011: provider routing, defaults, and capability resolution](../../adr/ADR-0011-provider-routing-defaults-and-capability-resolution.md)
- [ADR-0012: loopback control plane without an operator API key](../../adr/ADR-0012-loopback-control-plane-without-operator-api-key.md)

ADR-0009 partially supersedes the implementation shape in ADR-0007. ADR-0010 partially supersedes the recognition/projection shape in ADR-0008. ADR-0011 freezes strict routing, empty-default establishment, and independent capability provenance. ADR-0012 freezes local control admission, removes the global operator key, and removes callback HTTP from the target. The older ADRs remain historical context and carry explicit notices.

## Search-first routing

- Runtime sync/async ownership, signals, races, deadlines, provider start, or watchdog -> [Runtime lifecycle and watchdog](architecture/runtime-lifecycle-and-watchdog.md)
- Relational rows, lifecycle states, lineage, revisions, or constraints -> [Runtime records and control state](architecture/runtime-records-and-control-state.md)
- Why broad task workers/locks/polling are absent -> [ADR-0009](../../adr/ADR-0009-exact-source-runtime-control.md)
- Managed per-dispatch MCP attachment, credentials, revocation, or concurrent isolation -> [Managed Node MCP binding](architecture/managed-node-mcp-binding.md)
- Managed versus OpenClaw tool schemas or role-specific exposure -> [Node and Operator MCP surface](interfaces/node-and-operator-mcp-surface-contract.md) and [Node MCP schema appendix](interfaces/node-mcp-schema-appendix.md)
- Plans versus checkpoints/boundaries -> [Work plan and checkpoint](architecture/work-plan-and-checkpoint-contract.md)
- Exact request files, publication, file reads, or support projections -> [Task root and file access](architecture/task-root-and-file-access.md) and [Prompt system](prompt-layer/prompt-system.md)
- Human request behavior and timeout -> [Human request and approval](interfaces/human-request-and-approval-contract.md)
- Command process ownership, timeout, cancellation, and continuation -> [Command run and external wait](architecture/command-run-and-external-wait.md)
- Provider selection, no-fallback behavior, and sparse config -> [Provider selection and runtime config](interfaces/provider-selection-and-runtime-config.md)
- Strict authored provider shape, default establishment, and capability provenance -> [ADR-0011](../../adr/ADR-0011-provider-routing-defaults-and-capability-resolution.md)
- Zero-provider status/setup/check behavior -> [Provider CLI and check](interfaces/provider-cli-and-check.md)
- Codex, Claude, or experimental OpenClaw conformance -> [Provider support and compatibility](interfaces/provider-support-and-compatibility.md)
- Loopback trust, Host/Origin admission, no global operator key, callback removal, or capability dimensions -> [Capability, security, and audit](interfaces/capability-security-and-audit.md) and [ADR-0012](../../adr/ADR-0012-loopback-control-plane-without-operator-api-key.md)
- HTTP controller routes or current readbacks -> [Control API](interfaces/control-api.md)
- SSE chronology and cursor recovery -> [Task event stream](interfaces/task-event-stream.md)
- Console presentation -> [Console runtime surfaces](interfaces/console-runtime-surfaces.md) and [Console target](console/README.md)

## V1 contrast routing

Use `design/v1` for target-baseline surfaces V2 has not superseded:

- [V1 design front door](../v1/README.md)
- [V1 runtime boundary and controller loop](../v1/architecture/runtime-boundary-and-controller-loop-contract.md)
- [V1 human and operator control surface](../v1/interfaces/human-and-operator-control-surface.md)
- [V1 prompt-layer front door](../v1/prompt-layer/README.md)
- [V1 OpenClaw worker and Gateway contract](../v1/architecture/openclaw-worker-and-gateway-contract.md)

Use `docs-internal/current/v1/**` for shipped-behavior contrast. Target owners win when target and shipped code/docs disagree.

## Scope note

This tree does not reopen MQ, multiple active runtime processes, remote workspaces, distributed-safe retry, non-loopback browser deployment, or browser provider mutation. Provider setup, login, enablement, and default changes remain CLI-only; this phase adds no browser session/cookie stack, CSRF-token machinery, TLS/proxy profile, or remote-browser authentication.
