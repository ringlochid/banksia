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
- `[codex]` and `[claude]`: enabled state plus nonsecret route settings;
- `[operator]`: explicit Operator provider plus optional model and effort; and
- `[runtime]`: default provider, concurrency and retry bounds, managed sandbox ceiling, provider-start retry, and watchdog settings.

`banksia init --workspace PATH` writes the default workspace used when HTTP, Console, or Operator Task start omits one. The path must be an existing absolute directory. `BANKSIA_CONTROLLER_WORKSPACE` may override it. CLI Task start instead resolves an omitted workspace from its invocation directory.

Guided first-run initialization is one self-contained human journey over independently committed settings:

1. local controller paths and exact database admission;
2. one explicit Task provider when none is configured, which fills an empty default; and
3. one explicit optional Operator selection when none is configured.

The provider chooser includes an explicit cancel choice. Cancelling preserves completed local initialization and writes no provider configuration. The Operator chooser is `Codex | Claude | Not now`; selecting a managed provider that is not configured first uses the same exact provider configuration, authentication, and diagnostic flow as Task-provider setup. Configuring that additional route preserves the already selected Task-provider default. Model and effort remain optional advanced values.

One initialization journey may reuse a provider check that it just performed when Operator selects the same route. This is transient presentation state only: Banksia does not persist readiness or treat the check as controller truth. A different, unconfigured Operator provider receives its own configuration and compact check. Initialization keeps detailed provider limitations out of the default journey; the focused check command owns that diagnostic readback.

An existing guided installation offers `keep | reconfigure | cancel`. `keep` verifies the current local state. `reconfigure` changes local paths, database, server, and logging settings while explicitly keeping provider routes, the Task-provider default, and Operator configuration. It is not described as full replacement. Completed provider and Operator phases are not reopened, and the final summary labels their retained values as **kept**.

`banksia setup` is the rerunnable settings hub. Its interactive overview routes to Task providers, Operator, or default workspace configuration and derives completion from current durable settings rather than a persisted wizard cursor. The focused `banksia operator setup|status|disable` family owns only the explicit Operator selection. `operator disable` removes the persisted Operator selection without disabling its provider route.

Noninteractive and JSON initialization never prompt or configure a provider or Operator. Automation uses focused explicit mutations such as `banksia setup --provider PROVIDER --non-interactive` and `banksia operator setup --provider PROVIDER --non-interactive`. A passive status/readback command never contacts a provider. Aborting a guided journey does not roll back earlier accepted phases; a rerun reads their current truth.

## Local control-plane boundary

The API listener accepts loopback hosts only. Product browser requests use exact Host and unsafe-request Origin validation. There is no shared product API key.

The optional support API is a separate nonbrowser boundary. It is mounted only when `BANKSIA_SUPPORT_BEARER_TOKEN` supplies at least 32 characters, rejects requests carrying an Origin header, and requires its own bearer credential. Managed Node MCP credentials and provider-native credentials remain separate principals.

## Provider configuration and selection

Codex and Claude are the complete active provider catalog. `banksia providers configure` enables one route and fills `runtime.default_provider` when the default is empty or names the retired OpenClaw route. Configuring another active provider preserves an existing active default. `banksia providers set-default` is the only ordinary operation that replaces it.

Each Dispatch resolves exactly one provider:

- an authored Member provider requests that exact kind;
- omission requests `runtime.default_provider`; and
- missing, disabled, invalid, or unavailable routes fail explicitly.

Banksia never scans for a fallback provider after selection. Authentication, reachability, start rejection, timeout, and uncertain acceptance do not change the route; the same committed Dispatch retries with bounded exponential delay.

Provider availability and platform support are separate facts. Banksia offers every pinned Codex and Claude route on every host documented by that integration. It does not maintain a second OS denylist, remove a route after a failed diagnostic, or rewrite a saved route to obtain readiness. A check may report separately that the integration is installed, authenticated, reachable, and able to honor the exact requested sandbox/network configuration. An unsupported exact configuration fails before provider work begins with an actionable explanation; it never silently widens sandbox/network access or falls back to another provider.

Workflow provider settings remain portable: providers may request model, effort, a legal sandbox/network pair, and `extension_mode`. Credentials, executable paths, provider homes, endpoints, sessions, and fallback lists stay machine-local.

## Provider status, checks, and identity

Bare `banksia`, `banksia status`, and `banksia providers status` are passive. They do not run a model turn, contact a provider, refresh authentication, or write readiness.

`banksia providers check PROVIDER` performs one bounded non-agent diagnostic. It may inspect provider installation, native identity, authentication, and documented reachability, but it creates no Task, Dispatch, binding, or durable readiness cache. A route with acceptable local prerequisites and credentials but no live reachability probe is presented as **Ready for first task**, not as fully tested.

`banksia operator status` is also passive. It reports the explicit selected provider/model/effort, whether the corresponding managed provider route is configured, any effective environment override, and the exact next diagnostic command. It does not start an Operator turn or persist a readiness result.

Interactive `operator setup` defaults to the saved Operator provider, not a hard-coded provider. Keeping the same provider and declining override changes preserves the saved model and effort. Choosing to edit them uses the current values as defaults and accepts `-` as an explicit return to the provider default. Changing provider does not carry provider-specific overrides to the new route unless the user explicitly supplies replacements. A no-op reports **Operator already configured** and offers, rather than forces, the shared provider readiness diagnostic. A changed selection runs that diagnostic. Diagnostic failure is “needs attention” and does not erase or disable the accepted selection.

Provider configuration and identity mutation are CLI-owned. Codex and Claude support subscription and API-key identity flows. When a check finds a working credential, guided setup first offers to keep it; only declining that confirmation opens authentication-method selection or replacement. The config-adjacent `banksia.env` file may contain only `ANTHROPIC_API_KEY`. It is owner-only and rejects unrelated assignments.

## Adapter boundary

One committed current Dispatch supplies exact instruction and input strings, workspace, resolved provider configuration, and allowed Task-member tools to one adapter start. Adapters do not rerender requests or interpret provider output as completion.

Codex and Claude starts receive an ephemeral Dispatch-scoped Node MCP binding and exact tool ceiling. The credential is injected for that invocation, never written to user configuration, and revoked when Dispatch authority ends. Banksia exposes no user-configured Node MCP compatibility projection.

A stale `[openclaw]` section is ignored and removed the next time guided setup rewrites provider configuration. A stale `runtime.default_provider = "openclaw"` is not rerouted silently: authoring reports no usable default and execution rejects the route until setup selects Codex or Claude. Banksia never mutates an external OpenClaw installation or state directory.

Managed-provider authentication state is not an instruction or extension source. A managed Task preserves the provider's supported native authentication location and resolves one requested and effective Skill/MCP extension mode. `inherit` admits enabled user and project Skills plus configured MCP servers only for effective `full_access` plus network `allow`; every narrower Dispatch is automatically isolated. Operator is always isolated. Banksia never rewrites a user's provider configuration to obtain either mode.

The Codex adapter reads effective configuration, enumerates MCP servers and Skills, marks the exact workspace untrusted, suppresses project-document discovery, and validates returned instruction sources and complete MCP status before `turn/start`. Isolated mode disables ambient Skills and MCP servers. Inherited mode admits enabled user and repository Skills plus active configured MCP servers while continuing to disable plugins, hooks, apps, memory, and provider-owned delegation. In both modes the exact Dispatch-bound `banksia_node` operations must equal the binding ceiling and it may expose no resources or resource templates.

For a persistent Codex Operator thread, the top-level `cwd` returned by `thread/resume` is the effective cwd for the resumed invocation and must equal the new temporary Operator directory. The nested `thread.cwd` is provider metadata captured when the thread was created; it is checked on `thread/start` but is not treated as current execution authority on resume. Instruction sources, runtime workspace roots, sandbox, approval policy, model, and complete MCP status are still revalidated before every resumed model turn.

The Claude Task adapter uses standard SDK mode for API-key and personal Pro or Max subscription identities, only after readiness proves that no endpoint-managed policy is installed. Bare mode is not used for Tasks because the pinned CLI skips Skill discovery and SDK hooks in that mode; safe mode also suppresses the external HTTP Node MCP required by a Task Dispatch. Claude Operator may use API-key bare mode or personal-subscription safe mode because its private operation server is an in-process SDK MCP surface. Isolated Tasks use no settings source, Skills, plugins, agents, or ambient MCP. Inherited Tasks load user and project sources for Skill and MCP discovery while invocation-local settings disable filesystem hooks and every configured plugin, and environment controls suppress project instructions, agents, memory, apps, and background features. Startup readback validates the exact Banksia binding and records sanitized Skill and MCP names. Teams or Enterprise subscription identity, unknown subscription classes, and endpoint-managed Claude policy fail readiness until the provider exposes a policy-free SDK boundary.

Every managed Dispatch persists its requested/effective extension mode and source. After an accepted provider start it also stores sanitized observed Skill names and active external MCP server/tool names. No content, path, argument, credential, or result is stored. This readback is diagnostic evidence only: inherited provider-native extension work may not be fully observable or reproducible by Banksia and cannot become controller truth.

On Linux and WSL2, a Claude Dispatch with effective network `deny` requires the host `bubblewrap` and `socat` executables used by Claude Code's native sandbox. The adapter enables that sandbox with fail-closed startup; missing host prerequisites produce a definite provider-start failure rather than silently widening network or filesystem access.

Native Windows controller/runtime support is deferred. WSL2 is a Linux-host installation choice, not an automatic fallback selected by Banksia.

Provider terminal output, session identity, process lifetime, and transport continuity are never controller authority. [Runtime](../architecture/runtime.md) and [built-in runtime tools](../interfaces/runtime-tools.md) own the exact Dispatch and operation semantics.
