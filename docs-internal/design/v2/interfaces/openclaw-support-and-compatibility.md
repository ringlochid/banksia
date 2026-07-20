# OpenClaw support and compatibility

Status: Target

This page owns the externally managed, explicitly experimental `openclaw` provider lane.

## Product status

OpenClaw is experimental but selectable. AutoClaw does not disable the route merely because conformance is incomplete; operators may choose it explicitly or configure it as the default, with limitations reported explicitly.

Installation and discovery alone never select OpenClaw. Failure of Codex, Claude, or another route never falls back to it.

The user installs, upgrades, configures, secures, and supervises OpenClaw and its Gateway independently. AutoClaw owns only the narrow Gateway adapter, controller route record, compatibility Node MCP endpoint, and bounded checks.

## Gateway route

AutoClaw selects one user-authored/tested Gateway profile:

```toml
[openclaw]
enabled = true
cli_path = "/absolute/path/to/openclaw"
gateway_url = "ws://127.0.0.1:18789"
gateway_profile = "default"
gateway_auth_mode = "token" # token | password
```

`cli_path` records the resolved non-secret executable used by both bounded checks and runtime calls. The profile identifies the installed-version-specific lawful client identity, handshake, delivery channel, agent/workspace mapping, and expected compatibility MCP configuration without copying secrets into AutoClaw config. `gateway_auth_mode` selects exactly one private service-environment source: `OPENCLAW_GATEWAY_TOKEN` or `OPENCLAW_GATEWAY_PASSWORD`. AutoClaw does not freeze `webchat`, `backend`, or another upstream mode as a universal product baseline.

Guided setup records the currently resolved OpenClaw executable and collects the Gateway URL, profile, authentication mode, and hidden token/password. The secret is stored only in owner-readable `autoclaw.env`; it never enters `config.toml`, controller rows, task files, prompts, command arguments, or readbacks. An explicit shell value for the selected variable takes precedence for foreground execution; setup offers to store a shell-only value before evaluating managed-service readiness. Service installation and reconciliation preserve the file.

AutoClaw never impersonates an upstream reserved internal identity. A configured profile must name a lawful third-party path for the installed version. Exact adapter conformance records what is known, tested, limited, or unsupported, but an incomplete suite is not a global route, default, or selectability gate.

## User-owned setup

AutoClaw does not install OpenClaw, patch `openclaw.json`, register its MCP endpoint automatically, create an agent profile, or weaken bind/TLS/pairing/authentication/sandbox/tool/exec/approval/deny policy. Collecting the narrow Gateway client credential for AutoClaw's own adapter does not transfer ownership of the Gateway or its configuration.

The user configures the stable AutoClaw compatibility endpoint `/node/mcp` and chooses which OpenClaw worker may use it. AutoClaw documentation/checks may show the required values and validate observable facts, but mutation remains user-owned.

This differs deliberately from Codex/Claude dynamic injection. AutoClaw cannot guarantee per-dispatch configuration injection and revocation through the user-owned OpenClaw profile, so it does not reuse the managed binding model.

## Compatibility Node MCP

Every compatibility Node tool requires full:

```text
task_id
dispatch_id
```

The prompt's dispatch context renders those non-secret IDs. They select the exact controller scope but do not authenticate the caller.

The endpoint applies strict request shape, Host/Origin policy, exact currentness, role/tool exposure, capability, and operation legality. It never redirects a stale dispatch ID to a newer dispatch. Because reachability plus known IDs is weaker than a managed bearer binding, the endpoint must stay inside an operator-controlled local boundary and the provider lane remains experimental.

The worker sees the compatibility projection of the same logical Node catalog. AutoClaw does not give it Operator MCP.

## Workspace and behavior readiness

The configured OpenClaw worker must:

- reach the compatibility MCP endpoint;
- access the expected local task workspace under the user's chosen OpenClaw sandbox/mount policy;
- receive the full current instruction and input request;
- supply the current full IDs to Node tools;
- avoid provider-native question/approval waits that AutoClaw cannot observe; and
- support the documented Gateway acceptance/cancellation behavior claimed by the installed route.

AutoClaw does not prescribe one global OpenClaw workspace layout or disable sandboxing.

## Start and stop

`start()` submits the dispatch through the documented Gateway `agent` path and returns only on acceptance. Gateway output, tool events, `agent.wait`, and final completion are ignored for controller truth.

An OpenClaw session/run identifier may remain private to the adapter for optional continuity or precise `sessions.abort`. It is never persisted as generic controller authority and never authenticates Node MCP.

`stop(dispatch_id)` is best-effort experimental control through the supported abort path. Runtime makes at most one bounded attempt where its generic policy calls for stop and proceeds on unsupported, failed, or timed-out results. Normal boundary/wait transitions do not stop OpenClaw and never wait for provider shutdown.

Every provider-origin start failure keeps the same current D2 in `starting` and retries indefinitely with capped backoff. Uncertain acceptance may receive the one bounded stop attempt before retry; stop failure never pauses the flow, changes the route, or blocks retry.

## Status and check

Passive status may report route enablement, experimental label, configured Gateway endpoint/profile, installed version when locally discoverable, and whether required user-owned fields appear present. It performs no Gateway/model action.

Status distinguishes installation, configured selection/default, observed compatibility, and exact-version conformance. It does not collapse those facts into one global enabled/disabled result.

`autoclaw providers check openclaw` calls the documented non-agent Gateway health path with the configured CLI and selected private credential. Exit status zero is not sufficient: the bounded response must also contain `ok: true`. A successful authenticated response confirms both authentication and Gateway reachability. The check never edits OpenClaw configuration, runs an agent turn, creates an AutoClaw dispatch/binding, or invokes Node tools.

Exact launch/disconnect/abort/MCP behavior is release-conformance evidence, not an ordinary operator check disguised as a model run.

## Required proof and recorded limitations

- accepted Gateway launch with exact two-lane request delivery;
- current full-ID compatibility tool calls for worker and parent/root profiles;
- no user configuration mutation by AutoClaw;
- launch-control disconnect behavior for the exact supported version;
- one bounded fresh-connection abort attempt where supported;
- provider-native questions/approvals do not create hidden waits;
- provider events and final output are absent from controller progression; and
- every failed conformance case remains visible without globally disabling selection;
- explicit and configured-default selection remain available while experimental;
- installation and other-provider failure never select OpenClaw; and
- adapter and compatibility failures remain local to the selected dispatch.

## External basis

- [OpenClaw agent loop](https://docs.openclaw.ai/agent-loop)
- [OpenClaw Gateway protocol](https://docs.openclaw.ai/gateway/protocol)
- [OpenClaw trusted proxy authentication](https://docs.openclaw.ai/gateway/trusted-proxy)
- [OpenClaw remote Gateway credentials](https://docs.openclaw.ai/gateway/remote)
- [OpenClaw Gateway configuration reference](https://docs.openclaw.ai/gateway/configuration-reference)

## Related contracts

- [Provider support and compatibility](provider-support-and-compatibility.md)
- [Provider CLI and check](provider-cli-and-check.md)
- [OpenClaw Gateway adapter](../architecture/adapters/openclaw-gateway.md)
- [Managed Node MCP binding](../architecture/managed-node-mcp-binding.md)
- [Node MCP schema appendix](node-mcp-schema-appendix.md)
- [ADR-0011: provider routing, defaults, and capability resolution](../../../adr/ADR-0011-provider-routing-defaults-and-capability-resolution.md)
