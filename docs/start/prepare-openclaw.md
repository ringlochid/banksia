# Use the experimental OpenClaw provider

OpenClaw remains installed, selectable, and usable as an experimental provider. AutoClaw does not select it implicitly unless it is your configured default.

## Configure the provider

Run OpenClaw's own setup first, then configure the local Gateway in AutoClaw:

```bash
autoclaw providers configure openclaw \
  --cli-path /absolute/path/to/openclaw \
  --gateway-url ws://127.0.0.1:18789 \
  --gateway-profile default \
  --gateway-auth-mode token
autoclaw providers login openclaw --method token
autoclaw providers check openclaw
```

The login command prompts for the token without echoing it. Use `--method password` when the Gateway uses password authentication. The Gateway must use the supported local loopback shape. You may set OpenClaw as the default:

```bash
autoclaw providers set-default openclaw
```

## Maintain the compatibility MCP entry

Unlike Codex and Claude, the OpenClaw lane does not receive a dynamic dispatch-scoped MCP attachment. Configure the compatible node MCP tools in `openclaw.json` and keep that entry current when AutoClaw changes.

The compatibility tools require explicit `task_id` and `dispatch_id` selectors because the static OpenClaw configuration does not carry dispatch-bound identity. AutoClaw still checks those selectors against current controller state before accepting a transition.

Expose only the tools the OpenClaw worker needs. A worker should not receive parent routing or operator tools. Keep operator access in a separate trusted OpenClaw profile when you choose to use it.

## Understand the support boundary

- The Gateway, OpenClaw configuration, compatibility MCP entry, and credential issuance are user-managed. AutoClaw stores only its selected Gateway client credential in its private service environment.
- The lane is experimental and may have incomplete conformance.
- Provider output and provider terminal status never become task truth.
- Node MCP transitions remain the runtime authority.

See [OpenClaw integration problems](../help/openclaw-integration.md) when its check fails.
