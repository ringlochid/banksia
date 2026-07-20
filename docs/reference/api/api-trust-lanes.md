# API trust lanes

AutoClaw is a one-process, loopback-only application. The database owns runtime truth; each public surface has a narrower job.

## Local HTTP lane

HTTP and operator MCP calls are admitted by direct-loopback peer, exact `Host`, and, for unsafe browser requests, exact `Origin` checks. There is no browser session, cookie, CSRF token, or global API key in the shipped local lane.

This lane can browse and author definitions, start tasks, inspect controller state, resolve human requests, inspect or cancel command runs, and pause, continue, or cancel tasks. It cannot act as a node dispatch.

## Managed Node MCP

Codex and Claude receive a private, short-lived binding for one dispatch at `/_internal/node/mcp`. The binding supplies task identity, dispatch identity, provider-start revision, and the maximum tool exposure. Managed tool schemas therefore contain semantic arguments only.

The server still rereads current controller truth for every call. A stale or revoked binding cannot mutate the task.

## Compatibility Node MCP

OpenClaw uses the user-configured `/node/mcp` endpoint. Its static schemas add full `task_id` and `dispatch_id` arguments to every tool. Those selectors identify the intended dispatch; they are not secrets and do not bypass currentness, role, capability, or state checks.

AutoClaw does not write `openclaw.json` or inject a filtered OpenClaw tool set. The user owns the OpenClaw MCP entry and tool policy. OpenClaw remains experimental but may be selected explicitly or configured as the default provider.

## Node roles and tools

All node kinds may receive current-context, contained file-read, work-plan, checkpoint, boundary, human-request, and command-run operations when their role and capabilities allow them.

Parent and root nodes may also search definitions, assign or revise children, and record green release readiness. Only root nodes may record blocked release readiness. A worker never receives parent/root-only tools.

## Operator MCP

Operator MCP is a trusted local control surface at `/operator/mcp`. It shares controller services with HTTP, so the two surfaces must return the same domain truth and enforce the same currentness rules. Operator identity never grants Node MCP authority, and Node identity never grants operator controls.

## Commit and return rules

Mutations commit controller rows first. A boundary, human request, or command-run request closes its source dispatch in that transaction. After-commit handlers perform independent continuation, provider start, process ownership, cleanup, and projection work.

The caller does not wait for provider output, provider shutdown, a final response, or a generic drain. Task events and support files are readbacks of committed truth, not an authority path.
