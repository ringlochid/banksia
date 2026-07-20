# Provider selection and runtime config

Status: Target

This page owns provider route selection, sparse machine-local configuration, and dispatch provider provenance for the local V2 runtime.

## Core rule

One dispatch has one immutable resolved provider route. Route selection occurs before D2 commits and performs no provider/model I/O. Actual provider start occurs only after D2 and its request refs commit.

Provider authentication, reachability, availability, timeout, rejection, and uncertain acceptance after commit never switch routes. They retry the same `starting` dispatch under the runtime contract.

## Authored provider selection

A workflow node may carry:

```yaml
provider:
  kind: codex | claude | openclaw
```

`provider` is an optional strict discriminated object. In this phase each portable variant contains only `kind`; unknown fields and fields that belong to another provider variant fail validation. The object may appear on root, parent, or worker nodes and must not contain model names, effort settings, Gateway profiles, executable paths, URLs, credentials, sandbox policy, provider session IDs, or fallback lists.

Provider-specific model, effort, Gateway, identity, and connection details remain machine-local configuration. Selection resolves those settings into the committed provider route without copying them into portable authored definitions.

## Resolution rules

Resolution is exact:

1. When `provider` is present, request its exact `kind`.
2. When it is absent, request the configured `runtime.default_provider`.
3. Validate only deterministic local route facts needed to construct the adapter request: supported discriminator, enabled integration, required non-secret configuration shape, and available adapter implementation.
4. Commit the candidate dispatch only with that same resolved provider route.

An explicitly requested route never falls back. An omitted `provider` may use the configured default because the default is the request source, not a fallback candidate. A missing, disabled, broken, or unsupported default is an explicit route error; the resolver never scans installed providers for a substitute.

If no default exists, an explicit route is disabled/unsupported, or deterministic route construction fails, no D2 or provider call is created. An asynchronous automatic source handler conditionally pauses the still-runnable flow with `runtime_transition_failed` and leaves its exact source unconsumed for repair plus operator continue. A watchdog handler also closes its still-current stale D1 in that same pause transaction. A directly awaited operator continue instead returns the structured route failure and leaves the existing pause unchanged.

Full provider checks, network probes, login refresh, and model turns are forbidden during route selection. Once a valid D2 commits, provider-origin failures belong to indefinite same-D2 start retry rather than a second resolution pass.

## Discriminated route model

The committed route is a strict discriminated value:

```yaml
CodexProviderRoute:
  kind: codex
  model_override: string | null
  effort_override: string | null

ClaudeProviderRoute:
  kind: claude
  model_override: string | null
  effort_override: string | null

OpenClawProviderRoute:
  kind: openclaw
  gateway_profile: string

ProviderRoute: CodexProviderRoute | ClaudeProviderRoute | OpenClawProviderRoute
```

Provider-specific fields are legal only in their matching variant. Credentials, raw native configuration, binding material, and provider continuity never enter this model.

## Sparse machine-local config

The target configuration stays small and permits zero enabled providers:

```toml
[runtime]
# default_provider = "codex"
dispatch_launch_retry_initial_backoff_seconds = 1.0
dispatch_launch_retry_max_backoff_seconds = 30.0
watchdog_inactivity_timeout_seconds = 900
watchdog_same_attempt_replacement_limit = 2

[codex]
enabled = false
# model = "..."
# effort = "high"

[claude]
enabled = false
# model = "..."
# effort = "high"

[openclaw]
enabled = false
cli_path = "/absolute/path/to/openclaw"
gateway_url = "ws://127.0.0.1:18789"
gateway_profile = "default"
gateway_auth_mode = "token" # token | password
```

Rules:

- `runtime.default_provider` may be absent when no default is desired;
- when present, it must name an enabled route;
- provider-start retry delay begins at one second and is capped at 30 seconds, without a maximum attempt count;
- the watchdog inactivity timeout defaults to 900 seconds (15 minutes) and its same-attempt replacement cap defaults to two;
- target runtime config has no watchdog poll interval, bootstrap timeout, per-tick limit, auto-recover toggle, or separate execution-stale threshold;
- OpenClaw may be enabled and explicitly/default selected even though its product status remains experimental;
- provider sections own only AutoClaw enablement, non-secret executable/connection fields and authentication-mode selection, sparse explicit overrides, and resolved machine policy;
- Codex and Claude inherit provider-native homes, authentication, project/user settings, skills, model catalogs, and compaction;
- the configured OpenClaw CLI path is resolved to an absolute executable when available so checks and service runtime do not depend on a later shell's `PATH`;
- an OpenClaw gateway profile resolves the exact lawful client identity, handshake, delivery, agent, and compatibility-MCP expectations for one tested installed version; and
- no provider credential is stored in AutoClaw runtime config;
- Codex and Claude subscription credentials remain in their native homes, while an operator-entered Claude API key or OpenClaw Gateway credential may be stored only in the separate owner-only `autoclaw.env` service environment; and
- a shell-supplied supported credential takes precedence for foreground execution without changing either source, while guided setup and provider checks evaluate the managed service environment and can import a compatible shell-only secret only after explicit confirmation.

### Default establishment

The provider configure operation owns one atomic configuration transaction. After deterministic local validation succeeds, it persists/enables that route and fills `runtime.default_provider` only when the default is empty. If a default already exists, configuring another provider preserves it.

`autoclaw providers set-default <provider>` is the only operation that replaces an existing default. Failed or rolled-back configuration, provider check, authentication failure, and runtime start failure never change the default or select a fallback. Disabling or removing the current default must explicitly clear it or name a replacement.

OpenClaw participates in the same rule while retaining its experimental product label. Installation or discovery alone never establishes a default.

The effective settings precedence is:

1. AutoClaw correctness overlay for exact cwd/request lanes, Node MCP projection, role tool ceiling, and noninteractive behavior;
2. sparse explicit AutoClaw route overrides;
3. provider-native user/project configuration; and
4. provider defaults.

## Capability axes

`PolicyDefinitionInput.capabilities` owns two independent authored ceilings:

```yaml
capabilities:
  provider_native_access: full | restricted | denied
  network_access: allow | deny
```

Omission resolves to `full` and `allow`. A node inherits the policy-definition values through `policy_id`; task policy, controller policy, and adapter-local hard ceilings may only narrow them. Resolution takes the most restrictive applicable value using:

```text
full > restricted > denied
allow > deny
```

Each successor recomputes the effective values from current controller inputs. A local adapter ceiling is attributed to `controller`, not to portable authored policy.

Every preview, current-context, runtime, API, CLI/status, and console readback that exposes these axes uses:

```yaml
provider_native_access:
  effective: full | restricted | denied
  source: default | policy_definition | task_policy | controller
network_access:
  effective: allow | deny
  source: default | policy_definition | task_policy | controller
```

When equally restrictive ceilings tie, the single reported source uses `controller > task_policy > policy_definition > default`.

Neither axis silently controls Node MCP, human requests, controller `command_run`, or parent/root Node tools. Those capabilities remain independent as owned by [Capability, security, and audit](capability-security-and-audit.md).

## Local execution assumption

Codex and Claude are managed same-host adapters. AutoClaw, the provider runtime, the private Node MCP endpoint, and the task workspace share one compatible OS/filesystem namespace and service identity.

Provider-native configuration and authentication must be visible through the service identity's default home and normal service environment. Shell-only alternate-home variables do not redirect managed routes. A login/configuration in another host, container, WSL distribution, user, or home is not implicitly visible.

OpenClaw is externally managed. Its worker must reach the compatibility Node MCP endpoint and the configured local workspace through the user's OpenClaw integration. AutoClaw does not mutate that provider configuration.

## Provenance and readback

Each dispatch stores bounded selection provenance:

```yaml
provider_resolution:
  requested_provider: codex | claude | openclaw
  resolved_provider: codex | claude | openclaw
  selection_basis: explicit | default
```

For explicit selection, requested and resolved values are identical. For default selection, both identify the chosen default while `selection_basis` explains the source.

Controller readback may expose the route, selection basis, current provider-start attempt count, next retry, retry kind, and sanitized error code. It never exposes credentials, private MCP connection material, raw provider errors/output, or provider session IDs as authority.

## Startup isolation

Zero configured providers and individual broken providers do not block AutoClaw API startup, database/definition work, passive status, or other providers. Only a source that needs to create a dispatch requires a valid selected route.

Provider checks are explicit diagnostics. Runtime dispatch start does not depend on a cached or recent check result.

## Required invariants

- an explicit route never falls back;
- an omitted `provider` uses at most the configured default;
- configuring the first successful route fills only an empty default;
- later configuration and every provider failure preserve the default;
- route selection performs zero provider/model I/O;
- D2 and its route commit before provider start;
- a committed D2 never switches providers during retry;
- provider-origin start failure retries the same D2 without a finite maximum;
- OpenClaw remains selectable and visibly experimental; and
- zero-provider startup remains legal.

## Framework basis

[Pydantic discriminated unions](https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions) are the preferred implementation mechanism for the strict provider-route variants. The runtime must still enforce selection and no-fallback behavior outside schema parsing.

## Related contracts

- [Workflow node schema](workflow-node-schema.md)
- [Provider support and compatibility](provider-support-and-compatibility.md)
- [Provider CLI and check](provider-cli-and-check.md)
- [Capability, security, and audit](capability-security-and-audit.md)
- [Minimal provider adapter contract](../architecture/adapter-contract.md)
- [Runtime lifecycle and watchdog](../architecture/runtime-lifecycle-and-watchdog.md)
- [ADR-0011: provider routing, defaults, and capability resolution](../../../adr/ADR-0011-provider-routing-defaults-and-capability-resolution.md)
