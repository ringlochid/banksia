# Configuration and providers

Banksia stores local settings in `config.toml` and provider records in controller-owned state. Use the CLI readbacks instead of editing generated state by hand.

## Read the active configuration

```bash
banksia config path
banksia config show --json
banksia status --json
```

Pass `--config /path/to/config.toml` to select another install. `BANKSIA_CONFIG` selects the same file for processes that cannot pass the flag.

The important settings are the server bind, data directory, database URL, and runtime defaults. The default server is `127.0.0.1:18125`; the default database is local SQLite.

## Configure providers

```bash
banksia providers list
banksia providers configure codex
banksia providers status codex
banksia providers check codex
```

Use `claude` or `openclaw` in place of `codex`. You may also configure a model and effort where the provider supports them:

```bash
banksia providers configure codex --model <model> --effort <effort>
```

Use `banksia providers login <provider>` or guided `banksia setup`, then run `providers check`. Codex and Claude accept `--method subscription|api-key`; OpenClaw accepts `--method token|password`. Subscription credentials stay in provider-native storage. Subscription login requires an interactive terminal. Noninteractive secret login requires both an explicit method and `--secret-stdin`. Banksia stores an entered Claude API key or OpenClaw Gateway credential only in the owner-readable `banksia.env` provider-secret file beside the selected config, never in `config.toml` or a readback. Other assignments are rejected.

[Anthropic currently requires](https://code.claude.com/docs/en/legal-and-compliance) third-party Agent SDK products to use API-key or supported cloud-provider authentication unless Claude.ai login has been separately approved. Treat the Claude subscription option as release-conformance-gated until that approval exists.

For OpenClaw, configure the non-secret route explicitly:

```bash
banksia providers configure openclaw \
  --cli-path /absolute/path/to/openclaw \
  --gateway-url ws://127.0.0.1:18789 \
  --gateway-profile default \
  --gateway-auth-mode token
banksia providers login openclaw --method token
```

Guided `banksia setup` asks which provider should be the default. With direct commands, the first configured provider fills an empty default and later configuration preserves it. Banksia never silently falls back to another provider. Change the default explicitly:

```bash
banksia providers set-default claude
```

A workflow node may select a configured provider. If it does not, Banksia uses the configured default.

## How tool attachment works

For Codex and Claude, Banksia gives the provider a dispatch-scoped managed MCP connection and only the tools allowed for that node. The connection is attached dynamically; Banksia does not write it into the user's global or project provider configuration.

OpenClaw is different. It is an experimental, explicitly selectable provider. The user maintains the compatibility MCP entry in `openclaw.json`, and those tools carry full task and dispatch selectors. See [use the experimental OpenClaw provider](prepare-openclaw.md).

## Local browser boundary

The packaged console is a loopback, same-origin application. Banksia admits expected loopback `Host` values and exact allowed browser origins. This rejects requests that pretend to target another host while keeping the local setup simple. Do not expose this lane directly to another machine.

Restart `banksia serve` or the managed service after changing server or database settings.
