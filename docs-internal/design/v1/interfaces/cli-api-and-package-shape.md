# CLI, API, and package shape

Status: Target

This page defines the frozen package, CLI, and API boundary at the product surface level.

## Package authority

The root package manifest remains the product authority for:

- packaged Python entrypoints
- packaged console assets
- packaged migrations or Alembic resources
- packaged service templates

The shipped package must make those resources available without relying on repo-local paths.

## Surface split

### CLI

The CLI owns:

- local install and onboarding flows
- AutoClaw-local `init` and `doctor`
- top-level guided onboarding and configuration through `autoclaw onboard` and `autoclaw configure`
- low-level OpenClaw integration maintenance through `autoclaw openclaw check|setup|doctor`
- local DB migration flows
- local doctor/config/service flows
- local definition-import flows through `autoclaw definitions import ...`
- local task-compose file entry and task start flow through `autoclaw task-compose start --file ...`
- OpenClaw connectivity checks
- the high-level output and automation contract for user-facing commands

### API

The API owns:

- public and browser-safe request surfaces
- operator snapshot/trace and flow control surfaces
- guarded definition registry writes
- internal runtime adapter surfaces, including the live OpenClaw dispatch, wait, and abort path under runtime-owned services
- runtime read models

### Package

The package owns:

- installing the backend runtime
- exposing the CLI entrypoint
- shipping bundled console and resources
- shipping migrations and service templates needed by the supported install path

## Config authority

The canonical local `config.toml` owns user-configurable runtime and adapter knobs.

Rules:

- `[openclaw]` owns endpoint, AutoClaw worker/operator agent identity, and request-timeout knobs for the runtime-owned OpenClaw adapter
- OpenClaw Gateway auth policy is host-owned OpenClaw state. AutoClaw may consume supported auth material at connect time, but it must not treat `gateway.auth.*`, bind, TLS, or exposure policy as AutoClaw-owned configuration.
- `[runtime]` owns dispatch-drain, watchdog, and recovery cadence knobs
- `autoclaw config ...` is the direct local config front door
- `autoclaw onboard` and `autoclaw configure` may guide writes to AutoClaw-owned local state plus the AutoClaw-owned OpenClaw integration slice: selected worker/operator agent ids in local AutoClaw config, patched OpenClaw worker/operator agent profiles, OpenClaw-managed AutoClaw MCP server definitions, and AutoClaw wrapper material. They do not become the owner of live runtime dispatch semantics.
- `autoclaw openclaw setup` may reconcile only the AutoClaw-owned OpenClaw integration slice after preflight; it is not a blind wrapper around OpenClaw's own `openclaw setup`
- protocol pins, required Gateway methods, required scopes, and canonical MCP inventories are docs-and-code contract truth, not user-tunable config

## OpenClaw and MCP wrapper rule

AutoClaw exposes exactly two canonical MCP tool surfaces:

1. `operator MCP`
2. `node MCP`

Rules:

- `tool` is the canonical runtime term
- `operator MCP` is the standard external parity surface and carries the operator-safe definition-registry, task-start, runtime-read, and runtime control tools
- `node MCP` is private, internal, and explicit-arg in v1
- `plugin` or `bundle` names one concrete OpenClaw package or wrapper that may expose one or both canonical MCP surfaces
- a plugin or wrapper does not create a third truth surface or rename the runtime model
- task-scoped observability reads, if surfaced as tools, remain operator-safe and stay on `operator MCP`

## Separation rules

- keep the root CLI aligned to the canonical command families on this page, and keep `autoclaw openclaw ...` as low-level lifecycle wrappers rather than a separate runtime-truth authority
- keep `autoclaw onboard` as the primary guided first-run command and `autoclaw configure` as the primary targeted re-entry command
- keep `autoclaw init` AutoClaw-local, low-level, and de-emphasized; keep `autoclaw serve` as a foreground debug and service-manager execution primitive
- keep low-level OpenClaw integration verbs under `autoclaw openclaw check|setup|doctor`
- keep `autoclaw openclaw check` read-only, `setup` dual-surface-write only, and `doctor` dual-surface-repair only
- keep `autoclaw doctor` as the top-level local-and-integration health surface, and keep `autoclaw doctor --fix` bounded to AutoClaw-owned local state plus AutoClaw-owned OpenClaw integration
- keep `autoclaw service start|stop|restart|status` as platform-native managed-service lifecycle, with `serve` remaining the foreground process that a service manager may execute
- keep `bootstrap` out of the primary install and onboarding vocabulary; reserve it for internal runtime or materialization contracts
- keep runtime control API-first, with `operator MCP` and any plugin or MCP wrapper only as adapter-specific parity surfaces over operator-safe routes
- keep actual OpenClaw dispatch, wait, abort, and callback authority validation runtime-owned rather than migrating it into CLI/package or wrapper setup surfaces
- keep guarded definition revision lifecycle API-owned even though local definition import is now a canonical root CLI front door and the standard external plugin or MCP wrapper may mirror those routes
- keep public noun families explicit in the API even when the CLI shape differs
- keep `--json` as output-shape only, keep `--non-interactive` as the automation switch, and keep rich styling TTY-only with `--plain`, `--no-color`, and `NO_COLOR` escape hatches
- keep the rich CLI visual grammar aligned to OpenClaw's lobster-palette, panel-and-section, data-dense terminal layout instead of inventing a separate AutoClaw presentation language
- do not collapse `node MCP` and `operator MCP` into one shared mixed catalog or session

## Effect boundary

- `check` is read-only diagnostics.
- `adapt` is runtime consumption of supported host-owned OpenClaw state such as loopback token, loopback password, or explicit loopback no-auth.
- `set` is limited to AutoClaw-owned local state, AutoClaw service metadata, selected worker/operator agent ids in local AutoClaw config, patched OpenClaw worker/operator agent profiles, OpenClaw-managed AutoClaw MCP server definitions, and AutoClaw-owned OpenClaw wrapper defaults.
- `fix` is limited to state AutoClaw owns or previously wrote, including the same AutoClaw-owned OpenClaw integration slice.
- AutoClaw must not mutate OpenClaw Gateway auth mode, token, password, bind, TLS, or exposure policy.

## Installed-resource expectations

The packaged install must expose:

- CLI entrypoint
- console assets
- migration resources
- service-template resources

## Related contracts

- `cli-surface-and-operator-workflows.md`
- `api-surface-and-trust-lane-map.md`
- `../how-to/install-and-onboard.md`
- `release-and-install-strategy.md`
- `distribution-and-database-support-matrix.md`
