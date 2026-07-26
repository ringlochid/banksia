# Configuration and providers

Status: Reference

This page owns the local configuration, provider-selection, credential, and adapter operating contract.

## Configuration source and precedence

The selected TOML file is the durable machine-local configuration. The CLI selects it with `--config`; otherwise `BANKSIA_CONFIG` or the platform default path applies. Individual settings resolve in this order:

1. explicit constructor or command environment;
2. `BANKSIA_*` environment variables, using `__` for nested fields;
3. the selected TOML file; and
4. built-in defaults.

Banksia does not load an implicit project `.env`. `banksia config path` reports the selected file. `banksia config show` emits effective nonsecret values and redacts database or Gateway user information.

The TOML owners are:

- `[paths]`: controller data directory and optional default `workspace`;
- `[database]`: URL, dedicated PostgreSQL schema, and echo setting;
- `[server]`: loopback host, port, and exact development Console origins;
- `[logging]`: level;
- `[codex]`, `[claude]`, and `[openclaw]`: enabled state plus nonsecret route settings;
- `[operator]`: explicit Operator provider plus optional model and effort; and
- `[runtime]`: default provider, concurrency and retry bounds, managed sandbox ceiling, provider-start retry, and watchdog settings.

`banksia init --workspace PATH` writes the default workspace used when HTTP, Console, or Operator Task start omits one. The path must be an existing absolute directory. `BANKSIA_CONTROLLER_WORKSPACE` may override it. CLI Task start instead resolves an omitted workspace from its invocation directory.

## Local control-plane boundary

The API listener accepts loopback hosts only. Product browser requests use exact Host and unsafe-request Origin validation. There is no shared product API key.

The optional support API is a separate nonbrowser boundary. It is mounted only when `BANKSIA_SUPPORT_BEARER_TOKEN` supplies at least 32 characters, rejects requests carrying an Origin header, and requires its own bearer credential. Managed Node MCP credentials and provider-native credentials remain separate principals.

## Provider configuration and selection

Codex and Claude are managed provider integrations. OpenClaw is an explicitly selected, user-managed compatibility integration. `banksia providers configure` enables one route and fills `runtime.default_provider` only when the default is empty. Configuring another provider preserves the existing default. `banksia providers set-default` is the only operation that replaces it.

Each Dispatch resolves exactly one provider:

- an authored Member provider requests that exact kind;
- omission requests `runtime.default_provider`; and
- missing, disabled, invalid, or unavailable routes fail explicitly.

Banksia never scans for a fallback provider after selection. Authentication, reachability, start rejection, timeout, and uncertain acceptance do not change the route; the same committed Dispatch retries with bounded exponential delay.

Workflow provider settings remain portable: managed providers may request model, effort, and a legal sandbox/network pair. Credentials, executable paths, provider homes, endpoints, sessions, and fallback lists stay machine-local. OpenClaw authoring accepts only its provider kind.

## Provider status, checks, and identity

Bare `banksia`, `banksia status`, and `banksia providers status` are passive. They do not run a model turn, contact a provider, refresh authentication, or write readiness.

`banksia providers check PROVIDER` performs one bounded non-agent diagnostic. It may inspect provider installation, native identity, authentication, and documented reachability, but it creates no Task, Dispatch, binding, or durable readiness cache.

Provider configuration and identity mutation are CLI-owned. Codex and Claude support subscription and API-key identity flows; OpenClaw supports a selected Gateway token or password. The config-adjacent `banksia.env` file may contain only `ANTHROPIC_API_KEY`, `OPENCLAW_GATEWAY_TOKEN`, or `OPENCLAW_GATEWAY_PASSWORD`. It is owner-only, rejects unrelated assignments, and keeps the two OpenClaw credentials mutually exclusive.

## Adapter boundary

One committed current Dispatch supplies exact instruction and input strings, workspace, resolved provider configuration, and allowed Task-member tools to one adapter start. Adapters do not rerender requests or interpret provider output as completion.

Managed Codex and Claude starts receive an ephemeral Dispatch-scoped Node MCP binding and exact tool ceiling. The credential is injected for that invocation, never written to user configuration, and revoked when Dispatch authority ends. OpenClaw uses the explicit-ID `/node/mcp` compatibility projection configured by the user; Banksia does not edit `openclaw.json` or weaken its sandbox, tool, execution, or approval policy.

Provider terminal output, session identity, process lifetime, and transport continuity are never controller authority. [Runtime](../architecture/runtime.md) and [built-in runtime tools](../interfaces/runtime-tools.md) own the exact Dispatch and operation semantics.
