# Provider support and compatibility

Status: Target

This page owns the shared local support contract for the `codex`, `claude`, and `openclaw` provider routes.

## Product status

| Provider | Target integration | Runtime ownership | Product status |
| --- | --- | --- | --- |
| Codex | managed local SDK/app-server | AutoClaw owns invocation resources | managed target |
| Claude | managed local Agent SDK | AutoClaw owns invocation resources | managed target |
| OpenClaw | external Gateway + compatibility MCP | user owns Gateway/config/service; AutoClaw owns its route, client credential, and adapter calls | experimental selectable lane |

`Target` freezes the V2 contract; it does not claim the implementation has shipped.

OpenClaw's experimental label does not disable it. An operator may explicitly enable/select it or configure it as the default. Release conformance reports exact limitations rather than hiding the route or becoming a global selectability switch.

## Packaging

The target base AutoClaw distribution carries the tested Codex and Claude adapter dependencies and their supported bundled runtimes. Codex/Claude are not separate product install extras in the target model.

Installing those integrations does not configure or authenticate either provider. Zero enabled/configured providers remains a valid controller installation.

OpenClaw is not bundled. The user installs, upgrades, configures, secures, and supervises it independently.

## Shared managed-start contract

A managed Codex/Claude start receives:

- one committed dispatch's exact `instructions.md` bytes;
- that dispatch's exact `input.md` bytes;
- the resolved task workspace/cwd;
- a dynamic private managed Node MCP URL, bearer credential, and role-scoped tool allowlist;
- explicit noninteractive provider policy; and
- resolved `provider_native_access` and `network_access` ceilings plus sparse route overrides.

The adapter does not persist the MCP connection in provider user/project configuration. Each retry and successor receives a fresh binding credential; concurrent dispatches never share scope or tool ceilings.

## OpenClaw compatibility contract

OpenClaw uses the stable user-configured `/node/mcp` compatibility endpoint. Every Node tool requires full `task_id` and `dispatch_id` selectors. AutoClaw renders the full IDs in current dispatch context but never edits `openclaw.json` or weakens OpenClaw tool, sandbox, exec, approval, bind, or authentication policy.

Compatibility calls share the same logical operations and fresh controller validation as managed calls. The absence of a per-dispatch AutoClaw credential is an explicit experimental security limitation.

The operator maintains the compatibility server entry and tool policy in OpenClaw configuration. AutoClaw never injects or reconciles that entry dynamically.

## Provider start and stop

`start()` returns when the provider has accepted responsibility for the invocation. That acceptance can move a still-current D2 from `starting` to `open`; it does not imply semantic progress or provider completion.

Provider-origin start failures retry the same D2 indefinitely with capped delay. There is no six-call budget, provider-start exhaustion pause, route fallback, final-response window, or provider drain gate.

`stop(dispatch_id)` is a bounded optional control. Runtime uses at most one attempt for uncertain same-D2 retry, watchdog replacement, or post-commit pause/cancel cleanup and proceeds even when stop is unsupported, fails, or times out. Normal boundaries and human/command waits never call stop.

Adapters may privately consume provider streams for SDK/process health. AutoClaw discards provider final output for controller correctness and never waits for it before accepting a boundary or creating a successor.

## Authentication and native configuration

- Codex uses provider-owned ChatGPT subscription or API-key authentication and its native home/configuration.
- Claude uses Claude subscription login in its native home or `ANTHROPIC_API_KEY` supplied through the process environment.
- OpenClaw uses its externally managed Gateway with an AutoClaw-selected token or password client credential.

AutoClaw never copies provider credentials into runtime config or controller storage. Codex and Claude subscription credentials stay provider-native. The one owner-only, config-relative `autoclaw.env` file may contain only an operator-entered Claude API key or OpenClaw Gateway credential; it is not a controller truth or readback. Passive status reports local facts, while explicit checks verify documented non-agent prerequisites without running a model turn.

## Independent readiness

One broken provider does not block API startup or another route. There is no global provider-ready gate.

A route-specific check covers installation, configuration, authentication/reachability where a documented non-agent check exists, native-home identity, policy compatibility, and deterministic MCP prerequisites. It creates no task, dispatch, binding, or agent turn and writes no readiness cache.

Runtime does not run the check before every dispatch. Deterministic route/request validation happens before D2 commit; real provider handshake happens after commit under same-D2 retry.

## Conformance

Every provider-specific lane proves:

- exact delivery of the two committed request lanes;
- zero provider I/O before D2+refs commit;
- correct managed binding injection or explicit compatibility configuration;
- worker versus parent/root tool exposure;
- provider-native questions/approvals cannot become hidden waits;
- bounded stop behavior when supported;
- definite versus uncertain start classification where possible;
- same-D2 retry without prompt rerender;
- no provider output/final/drain progression; and
- secret and private-binding redaction.

Continuity is optional provider-private optimization. Conformance may test it, but loss of a provider thread/session must not change controller truth or prevent a full two-lane start.

Conformance results classify exact-version support and readiness. Incomplete or failed OpenClaw cases remain visible limitations; they do not globally disable explicit selection or an operator-configured OpenClaw default.

## Related contracts

- [Codex support and compatibility](codex-support-and-compatibility.md)
- [Claude support and compatibility](claude-support-and-compatibility.md)
- [OpenClaw support and compatibility](openclaw-support-and-compatibility.md)
- [Provider CLI and check](provider-cli-and-check.md)
- [Provider selection and runtime config](provider-selection-and-runtime-config.md)
- [Minimal provider adapter contract](../architecture/adapter-contract.md)
- [ADR-0011: provider routing, defaults, and capability resolution](../../../adr/ADR-0011-provider-routing-defaults-and-capability-resolution.md)
