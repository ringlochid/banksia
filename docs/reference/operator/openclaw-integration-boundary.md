# OpenClaw integration boundary

OpenClaw is an experimental, user-managed compatibility provider. It is installed and supervised outside AutoClaw, remains explicitly selectable, and may be configured as the default.

## AutoClaw owns

- strict provider selection and the committed dispatch route
- the exact `instructions.md` and `input.md` request pair
- a bounded Gateway `agent` acceptance call and best-effort abort
- the non-secret Gateway URL/profile/authentication-mode route and its private adapter credential
- controller state, Node operation legality, checkpoints, boundaries, waits, and task events
- the loopback compatibility Node MCP endpoint at `/node/mcp`

AutoClaw does not wait for `agent.wait`, provider output, final text, or Gateway process completion.

## The user owns

- installing, securing, issuing credentials for, and running OpenClaw and its Gateway
- `openclaw.json`
- the compatibility MCP server entry and OpenClaw tool policy
- choosing an OpenClaw profile that can use the required Node tools

AutoClaw never edits OpenClaw configuration or silently selects OpenClaw as a fallback.

## Compatibility Node MCP

The compatibility server exposes the same logical Node operation catalog as the managed server. Every call includes full `task_id` and `dispatch_id` selectors because static OpenClaw configuration cannot carry a dispatch-scoped private binding.

Those IDs are not credentials. The server rereads the current dispatch, role, capability set, and legal state for every call. A stale dispatch ID loses the race and cannot change controller truth.

Unlike managed Codex and Claude bindings, the compatibility endpoint has no dispatch scope during tool discovery, so it may advertise the complete compatibility catalog. The user-managed OpenClaw profile should expose only the tools its role needs: a worker should not receive parent or operator tools. The controller still rejects every operation that the current node may not use.

## Known experimental boundary

Gateway acceptance and cancellation support depend on the installed OpenClaw version. Ambiguous acceptance can cause overlapping physical provider work when cancellation is not reliable. Exact-current controller checks still prevent stale work from committing Node operations.
