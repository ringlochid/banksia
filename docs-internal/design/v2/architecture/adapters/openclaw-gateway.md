# OpenClaw Gateway adapter

Status: Target

This page maps an externally managed OpenClaw Gateway into the minimal AutoClaw provider adapter.

## External basis

- Gateway `agent` accepts work before the run completes: [OpenClaw agent loop](https://docs.openclaw.ai/agent-loop).
- Gateway exposes session/run cancellation and keeps handshake mode separate from delivery channel: [OpenClaw Gateway protocol](https://docs.openclaw.ai/gateway/protocol).
- Reserved trusted identities must not be impersonated by third-party automation: [OpenClaw trusted proxy authentication](https://docs.openclaw.ai/gateway/trusted-proxy).
- Explicit remote Gateway calls require an explicit token or password source: [OpenClaw remote Gateway credentials](https://docs.openclaw.ai/gateway/remote).

## Adapter boundary

OpenClaw remains independently installed, configured, secured, and supervised. AutoClaw neither bundles the Gateway nor manages its service lifecycle or global policy.

One `DispatchStartRequest` submits one `agent` request. An OpenClaw session key, run ID, connection, or abort handle remains private to this adapter.

`StartAccepted` is returned on the supported Gateway acceptance response. Gateway output, tool events, `agent.wait`, disconnects, and completion never advance controller state.

The adapter maps the exact instruction and input lanes to the installed Gateway's supported separate system/input fields. It does not concatenate, rerender, or append compact resume text.

## Compatibility MCP boundary

The adapter does not create a managed binding or inject a secret into OpenClaw configuration. The user has already configured the stable `/node/mcp` compatibility endpoint and OpenClaw tool policy.

Current prompt context contains the full non-secret task and dispatch IDs required by compatibility tool schemas. Every call then performs fresh exact-current controller validation.

AutoClaw never edits `openclaw.json`, changes the user-selected agent/tool profile, or silently disables a route that remains explicitly experimental.

## Gateway identity and delivery

Handshake client mode and agent delivery channel remain distinct fields inside the selected tested Gateway profile. AutoClaw does not freeze `webchat`, `backend`, or another upstream mode as a universal baseline. A configured profile must use a lawful third-party identity for the installed version; incomplete conformance is recorded as an explicit limitation rather than a global activation or selection gate.

AutoClaw must not claim a reserved internal `gateway-client` identity to obtain privileged behavior.

The adapter launches the OpenClaw CLI with `OPENCLAW_GATEWAY_URL` and exactly one selected `OPENCLAW_GATEWAY_TOKEN` or `OPENCLAW_GATEWAY_PASSWORD` in the child environment. It omits the URL and credential from command arguments, removes the unselected credential from that child, and fails before process launch when the selected source is absent. This avoids relying on implicit profile credentials for an explicit remote URL and keeps secrets out of process listings and command diagnostics.

## Stop and connection lifetime

When supported, `stop(dispatch_id)` opens or uses a control connection, issues one bounded `sessions.abort` for the private session/run identity, and returns a successful result only on the documented abort acknowledgement. Runtime proceeds when the result is unsupported, failed, ambiguous, or timed out.

The launch control connection may be released after acceptance only when exact-version conformance proves the run survives. If the installed route requires a retained connection, the adapter may keep it privately without ingesting its events as truth.

Normal boundaries and human/command waits never call abort. There is no `agent.wait`, provider-output drain, or provider-stop fence in controller progression.

## Failure classification

The adapter normalizes configuration, authentication, connection, unavailable, timeout, rejection, unsupported, and uncertain-acceptance outcomes. Every provider-origin outcome keeps the same current D2 in `starting` and retries indefinitely with capped backoff. Ambiguous acceptance gets at most one bounded stop attempt before retry; OpenClaw's lack of reliable cancellation may cause physical overlap, but stop failure never blocks retry and stale compatibility selectors/currentness cannot mutate controller truth.

Raw Gateway payloads, credentials, output, session keys, and run IDs remain out of controller error storage and ordinary logs.

## Experimental conformance

For each exact supported version/profile, conformance evidence records:

- acceptance with exact two-lane delivery;
- compatibility Node calls with full current IDs;
- worker versus parent/root profile behavior;
- legal client identity and independent delivery channel;
- token or password transport through mutually exclusive child-environment sources with no secret argument, log, or readback exposure;
- disconnect-after-acceptance behavior;
- one bounded fresh-connection abort when supported;
- no invisible native approval/question wait; and
- no provider event/output/final effect on controller truth.

A failed item is reported as an explicit route limitation. It does not silently mutate user configuration, change the configured default, or globally erase the experimental route.

## Related contracts

- [Minimal provider adapter contract](../adapter-contract.md)
- [Provider CLI and check](../../interfaces/provider-cli-and-check.md)
- [OpenClaw support and compatibility](../../interfaces/openclaw-support-and-compatibility.md)
- [Node and Operator MCP surface contract](../../interfaces/node-and-operator-mcp-surface-contract.md)
- [ADR-0011: provider routing, defaults, and capability resolution](../../../../adr/ADR-0011-provider-routing-defaults-and-capability-resolution.md)
