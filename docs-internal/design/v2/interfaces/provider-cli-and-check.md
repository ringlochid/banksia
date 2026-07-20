# Provider CLI and check

Status: Target

This page owns the V2 operator CLI for local setup, passive status, provider-native identity, and bounded provider checks. It does not own runtime provider selection, adapter semantics, browser mutation, or release conformance.

## Product shape

The CLI combines guided terminal entry points with small deterministic commands. The guided flow is orchestration only: it delegates each accepted step to the same local initialization, provider configuration, default-selection, identity, and check operations available as direct commands. It does not introduce a resumable onboarding journal or a second configuration path.

```text
autoclaw
autoclaw status
autoclaw init
autoclaw setup
autoclaw providers list
autoclaw providers status [provider]
autoclaw providers check <provider>
autoclaw providers login <provider> [--method <method>]
autoclaw providers logout <provider>
autoclaw providers configure <provider>
autoclaw providers set-default <provider>
```

Database, service, registry, definition, and diagnostic commands remain separately invocable. Provider commands never become hidden prerequisites for unrelated controller work.

## Zero-provider state

Zero configured providers is a valid controller state. Without Codex, Claude, or OpenClaw readiness, an operator can still:

- initialize AutoClaw-local state;
- inspect passive status;
- maintain and reset the database;
- author, validate, publish, and inspect definitions;
- inspect task history and committed events; and
- run diagnostics that do not require a provider turn.

Only operations that require a dispatch need a valid provider route. A directly awaited continue returns a precise route failure before D2; an already committed asynchronous task/boundary source may instead move to `runtime_transition_failed` for repair. API startup, service startup, status, and registry work do not depend on provider readiness.

## Bare command and status

Bare `autoclaw` and `autoclaw status` are passive, read-only summaries. They do not:

- spawn a provider or model turn;
- make provider network calls;
- refresh authentication;
- write readiness caches;
- repair configuration;
- open a task or dispatch;
- run a compatibility matrix; or
- start background runtime owners.

Status reports configured and observable local facts without presenting an earlier check result as current readiness. Machine output keeps explicit `not_checked` values where freshness is unknown. Human output labels the view as local configuration and points to the exact `providers check` command instead of repeating diagnostic-shaped `not_checked` rows for every provider.

The summary may show:

- AutoClaw config and data paths;
- database configuration/schema visibility from a local nonmutating read;
- service configuration and observable state;
- configured default provider route;
- installed provider integration availability;
- native identity/home location without secret contents; and
- current enabled/experimental/unsupported labels from target support policy.

## Init and setup

On an interactive terminal, `autoclaw init` and `autoclaw setup` are guided flows. `--non-interactive` disables prompts, and non-TTY or `--json` invocation never waits for input. Explicit command options remain usable in either mode.

Interactive human output uses terminal-aware structure and semantic color for sections, current state, success, warnings, and failures. It remains readable without color and as plain text when output is redirected. JSON output is not decorated.

`autoclaw init` guides AutoClaw-local initialization only. A fresh run shows the recommended config path, data path, database, and loopback API settings, allows the user to review alternatives, and confirms before writing. When config already exists, rerunning offers to keep and verify it, explicitly replace it, or cancel; it never overwrites or resets state merely because the command was rerun. The shipped database path still creates an empty current schema or verifies an exact current schema. Schema replacement remains the separate destructive `autoclaw db reset` operation. `init` does not log in to providers, mutate provider selection, install OpenClaw, or start an agent turn.

`autoclaw setup` guides provider setup. It shows current provider/default state, asks for the primary/default provider when one was not supplied, saves that route, explicitly selects it as the default, and performs the bounded provider check. For Codex and Claude, setup always presents the supported authentication methods. A detected ready method is only the method prompt default. After the user selects that same method, setup separately asks `Existing <Provider> <method> found. Use it? [Y/n]`. Accepting the default reuses it; declining runs a fresh login for that same method. Choosing another method runs that login directly. For a Claude API key or OpenClaw Gateway credential found only in the invoking shell, setup instead offers to store it in AutoClaw's private service environment; it does not call the managed route ready until the user accepts that write and the service-scoped recheck succeeds. The following check must report both readiness and the selected effective method. A different winning credential source fails setup with precedence guidance instead of presenting the requested change as successful. OpenClaw presents its token/password choice with the Gateway route and confirms reuse of a working stored credential. Setup then asks whether to configure additional providers. Additional providers do not replace the selected primary default. A saved route is never presented as ready until the fresh check confirms a supported credential source. Setup exits unsuccessfully when any selected route still needs attention or an explicitly selected authentication change fails. Interrupting the guide states that already completed steps were kept.

Codex and Claude each offer `subscription` and `api-key`. Codex delegates both methods to its SDK-bundled native CLI. Claude delegates subscription login to the SDK-bundled Claude Code CLI and stores an entered API key as `ANTHROPIC_API_KEY` in AutoClaw's owner-only service environment file. OpenClaw records the resolved non-secret CLI path, asks for Gateway URL, profile, and `token | password`, stores only the selected credential in that same private environment file, and keeps its experimental label. AutoClaw still does not install or supervise the Gateway or patch `openclaw.json`.

Every accepted setup step commits independently through its owning operation. Cancellation therefore preserves completed explicit steps, and rerunning derives the next prompts from current config instead of a setup journal. Setup is not one all-or-nothing transaction and does not silently repair provider, database, or service state.

Guidance distinguishes effective environment overrides from provider enablement persisted in the selected TOML file. It never recommends `set-default` for an environment-only provider because that command can select only a provider enabled in the persisted configuration; it recommends `providers configure` first.

## Provider list and status

`providers list` reports installed integration definitions and their product status: managed target, experimental, unsupported, or unavailable.

`providers status` is passive. It resolves the same service identity and provider home that runtime launch will use, then reports local facts such as executable/library presence, configured route, selected native home, and whether required local fields are present. Managed Codex and Claude availability requires both the SDK library and its bundled native CLI. A configured OpenClaw route uses its recorded CLI path rather than whichever executable a later shell happens to find. Status does not prove authentication or reachability unless those facts are directly readable without a provider operation.

## Provider check

`providers check <provider>` is an explicit fresh bounded diagnostic. It may:

- inspect the provider's native executable, library, and configuration under the runtime service identity;
- perform the provider's documented non-agent authentication or reachability check;
- validate deterministic adapter and managed/compatibility MCP prerequisites;
- report sanitized compatibility/version facts; and
- return stable machine-readable failure categories.

It must not:

- create a task, flow, assignment, attempt, dispatch, binding, or Node MCP invocation;
- run a model turn;
- mutate provider configuration or authentication state;
- refresh credentials through an undocumented flow;
- call runtime Node tools;
- write a persistent readiness cache; or
- substitute for pinned release conformance tests.

Stable outcome categories distinguish at least `ready`, `local_prerequisites_ready`, `not_configured`, `not_installed`, `authentication_failed`, `unreachable`, `incompatible`, `policy_blocked`, and `check_failed`. `ready` requires the provider's bounded native diagnostic to identify a supported effective credential source. An otherwise available integration with an unverified credential source reports `local_prerequisites_ready`, returns a nonzero command status, and is not called ready.

Authentication and reachability are separate `not_checked | passed | failed` machine axes. For Codex and Claude, `authentication: passed` means the documented native diagnostic found a supported effective credential source; it does not mean that AutoClaw sent a model request or remotely validated remaining quota. An adapter changes an axis from `not_checked` only when its bounded diagnostic directly supports that fact. A successful overall check therefore does not imply that both axes were inspected.

Human output renders the credential axis as `found`, `missing or rejected`, or `not inspected`, and reachability as `reachable`, `unreachable`, or `not tested`; machine output retains the stable enum values. It also reports the non-secret method as `subscription`, `api_key`, `token`, or `password`. A Codex `account/read` response identifies a typed ChatGPT or API-key account source. Claude's native `auth status --json` identifies the effective subscription or API-key source without retaining account details; `apiKeySource` takes precedence over the broader native authentication label. An authenticated OpenClaw `health` call accepts the selected Gateway credential and reaches the Gateway. Codex and Claude checks intentionally send no model request, so remote model reachability remains `not_checked` and human output explains that live provider access is exercised by the first task.

## Login and logout

Provider identity remains provider-owned, but AutoClaw owns the local onboarding operation. `providers login` and `providers logout` use only the methods supported by the selected integration. Codex and Claude accept `subscription | api-key`; OpenClaw accepts `token | password`. Interactive commands prompt with hidden input. Noninteractive login requires an explicit method. API-key, token, and password automation also requires `--secret-stdin`; subscription login requires a terminal because the provider-native browser or device flow must remain visible. Secrets never appear in command arguments, JSON, human output, or logs.

The command must identify the operating-system service account and native provider home that runtime will use. A login performed under another user or home does not make the AutoClaw service ready.

Codex uses the service account's default native credential store. Claude subscription login uses the service account's default Claude home; a Claude API key uses `ANTHROPIC_API_KEY`. OpenClaw uses the service account's default state home and exactly one of `OPENCLAW_GATEWAY_TOKEN` or `OPENCLAW_GATEWAY_PASSWORD` according to the non-secret configured authentication mode. Shell-only `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, and `OPENCLAW_STATE_DIR` overrides do not silently change the managed route.

## Provider configuration boundary

`config.toml` stores provider selection and non-secret route settings only. AutoClaw does not maintain a second provider profile or copy native subscription credential stores. Its one canonical sibling `autoclaw.env` file may contain only an operator-entered Claude API key or OpenClaw Gateway token/password. Custom service-environment paths and unrelated assignments are not supported. The file is owner-only, is loaded by foreground and managed-service execution, survives service-unit reconciliation, and is never a controller/runtime truth or readback surface. Foreground execution preserves an explicitly exported supported credential over the file value. Guided setup and `providers check` deliberately evaluate the exact private credentials available to the managed service instead; setup offers to copy a compatible shell-only secret into the private file with explicit confirmation.

The CLI never:

- copies provider token caches;
- writes provider secrets into `config.toml`, task files, controller rows, prompts, command arguments, or readbacks;
- writes dispatch MCP credentials into provider config;
- patches `openclaw.json`;
- weakens OpenClaw bind, sandbox, tools, exec, approval, or deny lists;
- changes Codex or Claude global tool policy to make one dispatch work; or
- silently falls back from an explicitly selected route.

Managed Codex/Claude MCP connection material is injected dynamically for one dispatch by the adapter. OpenClaw compatibility MCP is configured and maintained by the user.

### Configure and default selection

`autoclaw providers configure <provider>` validates and commits AutoClaw-owned enablement plus non-secret route settings. Direct invocation and setup use this same operation; setup does not maintain a second configuration path.

When configuration succeeds, its transaction fills `runtime.default_provider` only when no default exists. Configuring a later provider preserves the existing default. Guided setup routes the user's explicit primary-provider choice through the same default-selection operation exposed by `autoclaw providers set-default <provider>`; additional-provider steps do not replace it.

`autoclaw providers set-default <provider>` is the owning operation that replaces an existing default, whether invoked directly or by guided setup after an explicit primary-provider choice. It requires an enabled, deterministically valid configured route. OpenClaw is eligible while retaining its experimental label.

A failed or rolled-back configure operation leaves the default unchanged. Later check, authentication, reachability, compatibility, or runtime-start failure also leaves it unchanged and never selects a fallback. A missing, disabled, or broken configured default produces an explicit route error. Disabling or removing the current default must explicitly clear it or select a replacement.

## Runtime readback

Passive CLI runtime summaries consume controller read models. They may show:

- resolved provider and selection source;
- `provider_native_access: {effective, source}` where `effective` is `full | restricted | denied`;
- `network_access: {effective, source}` where `effective` is `allow | deny`;
- dispatch state `starting | open | closed`;
- provider-start attempt count, next retry time, retry kind, and sanitized error;
- watchdog activity/deadline and recovery count;
- pause reason and legal operator actions; and
- active human-request or command-run source.

They never show raw credentials, managed binding material, provider output, provider events, provider/MCP session IDs as authority, raw human answers, or command logs.

Provider start has no finite attempt maximum. A display therefore says `attempt N; next retry ...`, not `attempt N/M` or `exhausted`. Watchdog replacement retains its separate bounded cap and pause outcome.

For both capability axes, `source` is `default | policy_definition | task_policy | controller`. Equal effective ceilings report `controller > task_policy > policy_definition > default`; adapter-local hard ceilings report `controller`.

## Command behavior and output

Mutating commands state the requested mutation before performing it and return one stable result. Read commands remain read-only. JSON output is versioned by its owning contract and uses the same semantic categories as human output.

Failures identify the exact command, provider route, service identity/home, and safe next explicit action. They do not recommend destructive reset, global policy weakening, or provider fallback unless the owning command truly requires it.

## Browser boundary

Provider configuration, login/logout, enablement, and default mutation are CLI-only in the loopback phase. The console may display passive provider status and controller readbacks, but browser provider mutation is out of scope. This target does not introduce a server session, cookie lifecycle, CSRF-token system, TLS/proxy mode, or remote-browser authentication to reopen it.

## Removed commands and concepts

The target removes:

- monolithic `autoclaw onboard`;
- generic `doctor --fix` as a hidden mutation owner;
- broad `configure --section all` orchestration;
- OpenClaw-first setup or service gating;
- persistent provider readiness/`last_check` caches;
- AutoClaw-owned provider profiles and alternate homes;
- implicit provider fallback; and
- provider start or Node MCP calls inside checks.

Focused subsystem diagnostics may retain a read-only `check` command. Repair remains an explicit owning mutation, not an option hidden in a diagnostic.

## Required proof

- controller initialization, API/service startup, registry work, and passive status succeed with zero providers;
- bare/status commands perform no provider network or model work and no writes;
- check creates no task, dispatch, binding, Node MCP call, config change, or credential refresh;
- setup/status/check/runtime resolve the same service identity and native provider home;
- interactive init preserves existing state by default, confirms replacement, and never resets a mismatched schema;
- non-TTY, `--non-interactive`, and `--json` invocation never waits for input;
- noninteractive provider login requires an explicit method and secret input where applicable;
- guided setup and direct commands share provider configuration, default-selection, identity, and check operations;
- guided setup always offers the Codex/Claude subscription or API-key choice, separately confirms reuse of a selected ready method, verifies that fresh login made the selected method effective, offers OpenClaw token or password with its route, and preserves the chosen primary default while adding providers;
- route-saved and readiness results remain distinct, and unverified authentication never yields a successful ready check;
- private environment writes are owner-only, redact all values, keep token/password mutually exclusive, and survive service reconciliation;
- the private environment has one config-relative path, rejects unrelated assignments, and cannot override provider-native homes;
- first successful configuration fills only an empty default, later configuration preserves it, and only set-default replaces it;
- configure/check/authentication/start failures never mutate the default or trigger fallback;
- explicit provider routes never fall back;
- OpenClaw commands never mutate user-owned global configuration;
- CLI readbacks show indefinite provider-start retry without a fake maximum; and
- JSON and human output redact credentials and binding material.

## Related

- [Provider selection and runtime config](provider-selection-and-runtime-config.md)
- [Provider support and compatibility](provider-support-and-compatibility.md)
- [Capability, security, and audit](capability-security-and-audit.md)
- [Minimal provider adapter contract](../architecture/adapter-contract.md)
- [Runtime lifecycle and watchdog](../architecture/runtime-lifecycle-and-watchdog.md)
- [ADR-0011: provider routing, defaults, and capability resolution](../../../adr/ADR-0011-provider-routing-defaults-and-capability-resolution.md)
