# Provider and OpenClaw problems

Check the selected provider directly:

```bash
autoclaw providers status <provider> --json
autoclaw providers check <provider> --json
```

## Codex or Claude

Confirm the provider is installed and authenticated through its supported native flow. AutoClaw attaches the managed MCP connection dynamically for each dispatch; do not add it to global or project provider configuration.

If a dispatch remains in `starting`, inspect controller state and the provider check. The runtime retries retriable provider-start failures after commit. Provider stdout or a final response does not advance the task.

## OpenClaw

OpenClaw is experimental. Confirm:

- its local Gateway is reachable at the configured loopback URL
- the configured `token` or `password` authentication mode matches the Gateway
- its `openclaw.json` contains the current compatibility MCP entry
- worker tools require full `task_id` and `dispatch_id` selectors
- worker and operator tool access are separate

Reconfigure the AutoClaw provider record when its Gateway URL or profile changes:

```bash
autoclaw providers configure openclaw \
  --cli-path /absolute/path/to/openclaw \
  --gateway-url ws://127.0.0.1:18789 \
  --gateway-auth-mode token
autoclaw providers login openclaw --method token
autoclaw providers check openclaw
```

Use `password` for both options when the Gateway uses password authentication. The login command replaces only the selected private service-environment credential; it never edits `openclaw.json`.

See [configure OpenClaw tools](../guides/set-up-openclaw-agents-and-skills.md).
