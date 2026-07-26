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

Guided first-run initialization continues into provider setup when the selected configuration has no persisted provider. The provider chooser includes an explicit cancel choice; cancelling preserves the completed local initialization and writes no provider configuration. An initialization rerun with an already configured provider does not reopen or mutate provider setup. Noninteractive and JSON initialization never prompt or configure a provider; automation uses `banksia setup --provider PROVIDER --non-interactive` as a separate explicit mutation.

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

Managed-provider authentication state is not an instruction or extension source. A managed Task or Operator invocation preserves the provider's supported native authentication location while disabling ambient instructions, Skills, plugins, agents, hooks, apps, external MCP servers, and equivalent extension surfaces. It must fail before the first model turn when the pinned provider cannot prove that boundary. Banksia never rewrites a user's provider configuration to obtain isolation.

The Codex adapter reads effective configuration, enumerates ambient MCP servers and Skills, disables each named extension in an invocation overlay, marks the exact workspace untrusted, suppresses project-document discovery, and validates the returned instruction sources and complete MCP status before `turn/start`. The only active MCP server may be the exact Dispatch-bound `banksia_node`; its operations must equal the binding ceiling and it may expose no resources or resource templates. Nonempty instruction sources or any other active surface make the provider unavailable for that invocation.

For a persistent Codex Operator thread, the top-level `cwd` returned by `thread/resume` is the effective cwd for the resumed invocation and must equal the new temporary Operator directory. The nested `thread.cwd` is provider metadata captured when the thread was created; it is checked on `thread/start` but is not treated as current execution authority on resume. Instruction sources, runtime workspace roots, sandbox, approval policy, model, and complete MCP status are still revalidated before every resumed model turn.

The Claude Task adapter uses the pinned CLI's documented bare mode for API-key identity. For personal Pro or Max subscription identity it uses explicit SDK isolation without safe mode, only after readiness proves that no endpoint-managed policy is installed; pinned safe mode suppresses the external HTTP Node MCP required by a Task Dispatch. Claude Operator uses API-key bare mode or personal-subscription safe mode because its private operation server is an in-process SDK MCP surface. Every path additionally uses empty setting, Skill, plugin, and agent inputs, strict invocation-local MCP configuration, no provider-native subagent or command tool, disabled memory and background features, and startup readback that admits only the lane's exact Banksia binding and controller-supplied SDK hooks. Teams or Enterprise subscription identity, unknown subscription classes, and endpoint-managed Claude policy fail readiness until the provider exposes a policy-free subscription SDK boundary.

On Linux and WSL2, a Claude Dispatch with effective network `deny` requires the host `bubblewrap` and `socat` executables used by Claude Code's native sandbox. The adapter enables that sandbox with fail-closed startup; missing host prerequisites produce a definite provider-start failure rather than silently widening network or filesystem access.

Provider terminal output, session identity, process lifetime, and transport continuity are never controller authority. [Runtime](../architecture/runtime.md) and [built-in runtime tools](../interfaces/runtime-tools.md) own the exact Dispatch and operation semantics.
