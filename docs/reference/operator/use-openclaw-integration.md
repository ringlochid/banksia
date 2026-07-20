# Use the OpenClaw integration

Use OpenClaw only when you accept its experimental compatibility boundary.

## Configure AutoClaw

```bash
autoclaw providers configure openclaw \
  --cli-path /absolute/path/to/openclaw \
  --gateway-url ws://127.0.0.1:18789 \
  --gateway-profile default \
  --gateway-auth-mode token
autoclaw providers login openclaw --method token
autoclaw providers set-default openclaw
autoclaw providers check openclaw
```

The login command prompts for the Gateway token without echoing it; use `--method password` and `--gateway-auth-mode password` for password authentication. AutoClaw keeps the selected secret in its owner-readable service environment and never places it in `config.toml` or command arguments. Omit `set-default` when another provider should stay the default. The first configured provider becomes the default automatically when none exists.

## Configure OpenClaw

In the user-managed `openclaw.json`, add a streamable HTTP MCP server for:

```text
http://127.0.0.1:18125/node/mcp
```

Make the required compatibility tools available to the selected OpenClaw profile. Every tool schema requires the full current `task_id` and `dispatch_id`; AutoClaw supplies those IDs in the dispatch input.

AutoClaw does not write or maintain this configuration. Restart or reload OpenClaw as its own documentation requires.

## Operate tasks separately

Use operator MCP at `/operator/mcp` or the HTTP control routes to inspect and control tasks. Do not give the compatibility Node surface operator duties.

See [OpenClaw integration boundary](openclaw-integration-boundary.md) for ownership and limitations.
