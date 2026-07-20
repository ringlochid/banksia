# ADR-0011: provider routing, defaults, and capability resolution

Status: Accepted

## Decision summary

AutoClaw V2 uses an optional strict kind-discriminated provider object in portable workflow nodes, resolves omission through one operator-configured default, and never falls back from the selected route. The first successfully configured provider fills an empty default atomically; only an explicit set-default operation replaces it.

Provider-native access and network access are independent policy capabilities. Omitted values default to `full` and `allow`, later policy layers may only narrow them, and every readback exposes both the effective value and its deterministic source.

This ADR records target design. It does not claim that the current CLI, schemas, runtime, or provider integrations have shipped the decision.

## Context

The earlier target mixed a scalar `provider_preference`, machine-local route details, and loosely described capability defaults. It also left default establishment to product convention and allowed OpenClaw conformance language to read like a global activation gate.

Those ambiguities can change provider identity, cost, authority, or network posture without an explicit controller decision. They also make setup and direct configuration disagree about which provider becomes the default, and they cannot explain why an effective capability has a particular value.

## Decision

### Portable authored provider object

A workflow node may contain exactly one optional strict discriminated object:

```yaml
provider:
  kind: codex | claude | openclaw
```

Each current-phase variant contains only `kind`. Unknown fields and fields that belong to another provider variant fail validation. Model, effort, Gateway profile, executable, URL, identity, credential, sandbox, and transport settings stay in machine-local configuration and may appear only in the committed resolved route where appropriate.

Role and policy definitions remain provider-neutral. Nodes inherit policy capabilities through `policy_id`; provider selection stays a workflow-node concern.

### Exact route resolution and no fallback

When `provider` is present, its `kind` is the requested route. When it is absent, `runtime.default_provider` is the request source. Omission does not mean trying every installed provider.

Selection validates only deterministic local facts needed to construct the route and performs no provider/model I/O. The committed dispatch stores one immutable resolved provider route plus:

```yaml
provider_resolution:
  requested_provider: codex | claude | openclaw
  resolved_provider: codex | claude | openclaw
  selection_basis: explicit | default
```

Explicit and resolved provider are always identical. A missing, disabled, broken, or unsupported configured default is an explicit route error. Provider check, authentication, reachability, start rejection, or uncertain acceptance never switches the route or selects a fallback.

Provider-origin start failure remains an asynchronous same-D2 concern. The current `starting` dispatch retries indefinitely with capped backoff; uncertain acceptance gets at most one bounded optional stop attempt whose failure cannot block retry. Provider start never exhausts into a provider-selection pause.

### Default establishment

`autoclaw providers configure <provider>` and the same operation selected through `autoclaw setup` share one atomic configuration path. After deterministic local validation succeeds, the transaction persists/enables the route and fills `runtime.default_provider` only if it is empty.

Configuring later providers preserves the existing default. Guided setup routes an explicit primary/default choice through `autoclaw providers set-default <provider>` after configuration; additional-provider choices do not replace it. Set-default remains the only replacement operation and requires an enabled, deterministically valid route. Failed or rolled-back configuration, later check/authentication failure, and runtime start failure never change the default.

OpenClaw is eligible for explicit selection and for the configured default while remaining experimental. Installation or discovery alone never selects it, another provider's failure never falls back to it, and incomplete conformance is support/readiness information rather than a global enablement switch.

Disabling or removing the current default must explicitly clear it or name a replacement. AutoClaw never silently promotes another installed provider.

### Independent capability ceilings

`PolicyDefinitionInput.capabilities` owns:

```yaml
capabilities:
  provider_native_access: full | restricted | denied
  network_access: allow | deny
```

Omission resolves to `full` and `allow`. Task policy, controller policy, and adapter-local hard ceilings may only narrow values. Resolution takes the most restrictive applicable ceiling using:

```text
full > restricted > denied
allow > deny
```

Each successor recomputes both axes. Provider-native access and network do not silently grant or deny Node MCP, human requests, or controller `command_run`. Adapter-local hard ceilings are controller-enforced and therefore use the `controller` provenance value.

### Effective readback and provenance

Preview, current-context, runtime, API, CLI/status, and console readbacks expose both axes in the same shape:

```yaml
provider_native_access:
  effective: full | restricted | denied
  source: default | policy_definition | task_policy | controller
network_access:
  effective: allow | deny
  source: default | policy_definition | task_policy | controller
```

When multiple equally restrictive ceilings produce the effective value, the single reported source uses `controller > task_policy > policy_definition > default`.

### Provider mutation surface

Provider configuration, login/logout, enablement, and default mutation are CLI-only in the loopback phase. Passive browser surfaces may display controller readbacks but do not mutate provider state. This decision does not require server sessions, cookies, CSRF tokens, TLS/proxy support, or remote-browser authentication.

## Consequences

- Portable definitions stay deterministic and machine-independent.
- The configured default is explicit durable operator intent rather than install order, provider health, or fallback behavior.
- Setup and direct configuration cannot disagree about default establishment.
- OpenClaw remains usable as an experimental explicit/default route while conformance gaps stay visible.
- Capability narrowing is monotonic, inspectable, and consistent across providers.
- Consumers must carry capability provenance instead of exposing an unexplained scalar.
- Implementing the target requires clean removal of scalar `provider_preference` and any implicit provider fallback path.

## Alternatives rejected

### Keep scalar `provider_preference`

Rejected because it cannot provide strict variant validation and encourages provider-local fields to leak into portable authored definitions.

### Try providers in order or fall back after failure

Rejected because fallback can silently change identity, model, policy, cost, and continuity after the controller has selected a route.

### Let installation order or latest configuration replace the default

Rejected because discovery and repeated setup should not mutate existing operator intent. Only the first successful empty-default compare-and-set is implicit; replacement is explicit.

### Put native and network authority inside provider variants

Rejected because the capabilities are policy ceilings shared across providers and must remain independent from route identity.

### Gate OpenClaw selection on a completely green suite

Rejected because OpenClaw is an active experimental lane. Exact-version conformance describes support confidence and limitations; it is not a global route switch.

### Hide capability provenance

Rejected because an effective scalar cannot explain whether the result came from omission defaults, authored policy, task policy, or a controller/adapter ceiling.

## Proof obligations

- Schema tests accept only the three kind-only variants and reject scalar, unknown, and provider-inapplicable fields.
- Resolution tests distinguish explicit selection from omission, reject a broken/disabled default, and prove no provider fallback.
- CLI tests prove direct configure and setup share one atomic empty-default compare-and-set, guided primary selection delegates replacement to set-default, additional configuration preserves the default, and only set-default replaces it.
- Failure tests prove configure rollback, check/authentication failure, and provider-start failure never mutate the default.
- OpenClaw tests prove explicit and configured-default selection remain available while installation and other-route failure never select it; conformance gaps remain readback rather than activation authority.
- Policy tests prove omission defaults, monotonic narrowing, successor recomputation, and the two independent capability axes.
- Contract tests prove identical `{effective, source}` objects and deterministic source attribution across every named readback.
- Provider-start tests prove indefinite same-D2 retry, one bounded optional stop attempt for uncertain acceptance, and no provider-start exhaustion pause.

## Canonical references

- [Provider selection and runtime config](../design/v2/interfaces/provider-selection-and-runtime-config.md)
- [Workflow node schema](../design/v2/interfaces/workflow-node-schema.md)
- [Role and policy definition schema](../design/v2/interfaces/role-and-policy-definition-schema.md)
- [Provider CLI and check](../design/v2/interfaces/provider-cli-and-check.md)
- [Provider support and compatibility](../design/v2/interfaces/provider-support-and-compatibility.md)
- [OpenClaw support and compatibility](../design/v2/interfaces/openclaw-support-and-compatibility.md)
- [Runtime lifecycle and watchdog](../design/v2/architecture/runtime-lifecycle-and-watchdog.md)
- [Minimal provider adapter contract](../design/v2/architecture/adapter-contract.md)
