# Install and onboard the design target

Status: Target

This page defines the frozen v1 install and onboard path.

Use `bootstrap` only for internal runtime or materialization contracts. The operator-facing lifecycle uses `onboard`, `configure`, `doctor`, `service`, and the low-level `openclaw check|setup|doctor` integration commands.

Contrast: current install, start, and package behavior lives in [Install And Start Local](../../../current/v1/operations/install-and-start-local.md) and [Packaging CLI And Install](../../../current/v1/interfaces/packaging-cli-and-install.md).

## Minimal path

1. Install the product: `pipx install autoclaw`
2. Run guided first-run setup: `autoclaw onboard`
3. Verify local AutoClaw health: `autoclaw doctor`
4. Verify the OpenClaw integration side without writing: `autoclaw openclaw check`
5. Start the managed service when needed: `autoclaw service start`

Minimal example:

```text
pipx install autoclaw
autoclaw onboard
autoclaw doctor
autoclaw openclaw check
autoclaw service start
```

Daemon-install example:

```text
pipx install autoclaw
autoclaw onboard --install-daemon
autoclaw service status
```

## Targeted re-entry path

Use this path after first-run when only one guided section needs to change.

- `autoclaw configure --section openclaw` revisits the OpenClaw integration slice without rerunning the full guided first-run flow
- `autoclaw configure --section service` refreshes the managed service install path
- `autoclaw configure --section runtime` refreshes local runtime prerequisites and DB readiness
- `autoclaw configure --section definitions` re-seeds the packaged definition registry defaults
- `autoclaw configure --section web` rewrites the default local `console_origins` allowlist for the browser surface
- `autoclaw openclaw check` stays the read-only verification step before or after a targeted change
- `autoclaw openclaw doctor` is the low-level repair path when previously written AutoClaw-owned OpenClaw integration state needs remediation

Targeted example:

```text
autoclaw configure --section openclaw
autoclaw openclaw check --json
autoclaw openclaw doctor
```

## Direct setup path

Use this path when automation or a low-level operator flow needs baseline writes without the guided first-run wrapper.

- `autoclaw openclaw setup` reconciles the AutoClaw-owned OpenClaw integration slice: selected worker/operator agent ids in local AutoClaw config, patched OpenClaw agent profiles for those roles, the OpenClaw-managed AutoClaw MCP server definitions, and the local wrapper material
- `autoclaw openclaw check` remains the read-only follow-up verification
- this command is not a blind wrapper around `openclaw setup`; OpenClaw's own `openclaw setup` owns broader OpenClaw product baseline config, while AutoClaw's setup owns only the AutoClaw-owned OpenClaw integration slice

Direct setup example:

```text
autoclaw init
autoclaw openclaw setup --non-interactive
autoclaw openclaw check --json
```

## Command-role guardrails

- `autoclaw onboard` is the primary first-run command, contains the user-facing `init` class of local setup work, and should fail fast on OpenClaw preflight before writing local config or touching DB or service work
- `autoclaw configure` is the primary targeted re-entry command and should fail fast on OpenClaw preflight before local runtime or service work whenever the requested section includes OpenClaw or managed-service reconciliation
- `autoclaw init` stays AutoClaw-local, low-level, and de-emphasized
- `autoclaw serve` stays a low-level foreground runner for debug and service-manager execution
- `autoclaw service install|start|restart` should fail fast on OpenClaw preflight before mutating or starting the managed service; `stop|status` remain managed-service control/readback surfaces
- `autoclaw openclaw check` is read-only
- `autoclaw openclaw setup` writes only the AutoClaw-owned OpenClaw integration slice
- `autoclaw openclaw doctor` repairs only the AutoClaw-owned OpenClaw integration slice
- `autoclaw doctor` checks local AutoClaw state plus the AutoClaw-owned OpenClaw integration slice, and `--fix` repairs only those same owned surfaces

## CLI interaction and output rules

- `--json` is output-shape only
- `--non-interactive` controls automation and disables guided prompts
- `--plain`, `--no-color`, and `NO_COLOR` disable rich styling
- rich styling is TTY-only
- when styling is present, onboarding, setup, configure, and doctor should mirror OpenClaw's lobster palette and warning-first tone rather than inventing a separate AutoClaw visual language
- rich onboarding and doctor flows should keep OpenClaw's structured terminal-native layout: prominent command header, accent section headings, framed warning/status panels, and dense aligned diagnostics when reporting state

## Canonical local config shape

The canonical target config is controller/runtime-focused. It does not include a configured `definitions_root`, and it does not require a user-facing `[app].env` field.

```toml
[paths]
data_dir = "~/.local/share/autoclaw"

[database]
url = "sqlite+aiosqlite:///~/.local/share/autoclaw/autoclaw.db"
echo = false

[server]
host = "127.0.0.1"
port = 18125
console_origins = ["http://127.0.0.1:5173"]

[logging]
level = "WARNING"

[security]
api_key = "replace-me"

[openclaw]
base_url = "http://127.0.0.1:18789"
agent_id = "autoclaw-worker"
operator_agent_id = "autoclaw-operator"
timeout_ms = 120000

[runtime]
dispatch_drain_timeout_seconds = 30
watchdog_enabled = true
watchdog_interval_seconds = 15
watchdog_execution_stale_after_seconds = 300
watchdog_bootstrap_first_progress_timeout_seconds = 120
watchdog_auto_recover = true
watchdog_max_flows_per_tick = 50
watchdog_max_auto_recoveries_per_tick = 10
```

Rules:

- app/API auth uses API keys
- OpenClaw Gateway auth policy stays in the OpenClaw config family and is not set by AutoClaw
- `server.port` is the AutoClaw API and MCP loopback port and is configurable in local `config.toml`
- `openclaw.base_url` stays the canonical v1 way to configure the loopback OpenClaw gateway target; changing its port is how AutoClaw records the selected OpenClaw port in `config.toml`
- `openclaw.agent_id` is the selected worker agent id for AutoClaw runtime dispatch
- `openclaw.operator_agent_id` is the selected OpenClaw operator agent id for AutoClaw MCP/operator access; AutoClaw owns this id locally and patches the matching OpenClaw agent profile instead of storing role mapping as OpenClaw-side MCP agent scoping
- the runtime-owned OpenClaw adapter connects through the WebChat-compatible operator path with `client.id="openclaw-control-ui"` and `client.mode="webchat"`
- AutoClaw supports loopback token auth, loopback password auth, and explicit loopback no-auth by adapting at connect time
- AutoClaw does not silently reset, unset, rotate, or rewrite `gateway.auth.*`, bind, or TLS policy
- older configs may still carry `runtime.watchdog_bootstrap_ack_timeout_seconds`; treat it as a temporary compatibility alias for the canonical target knob `runtime.watchdog_bootstrap_first_progress_timeout_seconds`
- if a loopback token connect needs token material, the adapter may resolve it from explicit AutoClaw config or environment, then from the OpenClaw config path chosen by preflight
- if a loopback password connect needs password material, the adapter may resolve it from explicit AutoClaw config or environment, then from the OpenClaw config path chosen by preflight
- explicit loopback no-auth is accepted only when OpenClaw already exposes that mode; AutoClaw prints a hard warning and sends no auth material
- non-loopback Gateway connects require a later remote identity and trust model and are not a shipped v1 path
- older local configs may still carry `openclaw.account`; the current runtime drops that legacy TOML key during config load and does not use it in live Gateway requests
- local definition import reads explicit files or a shallow current-working-directory scan
- runtime does not depend on a configured definitions root after import
- actual OpenClaw dispatch, wait, abort, and callback authority validation stays in the runtime-owned adapter path; this config only supplies its tunable inputs
- OpenClaw setup writes only the AutoClaw-owned OpenClaw integration slice: worker/operator agent selection in local AutoClaw config, patched OpenClaw agent profiles, OpenClaw-managed AutoClaw MCP server definitions, wrapper config, workspace material, default AutoClaw wrapper profile material, and the canonical MCP tool-surface definitions. It does not reassign controller-owned runtime truth or host-owned Gateway policy.

## Effect and support matrix

| Surface                    | Effect                                                                     | Allowed writes                                                                                                                                                                                                                                                                                       |
| -------------------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `autoclaw openclaw check`  | read-only check                                                            | none                                                                                                                                                                                                                                                                                                 |
| runtime adapter connect    | adapt                                                                      | none; consumes supported host-owned Gateway auth mode                                                                                                                                                                                                                                                |
| `autoclaw openclaw setup`  | set integration defaults                                                   | selected worker/operator agent ids in local AutoClaw config, patched OpenClaw agent profiles, OpenClaw-managed AutoClaw MCP server definitions, and AutoClaw wrapper material                                                                                                                        |
| `autoclaw openclaw doctor` | fix integration drift                                                      | selected worker/operator agent ids in local AutoClaw config, patched OpenClaw agent profiles, OpenClaw-managed AutoClaw MCP server definitions, and AutoClaw wrapper material                                                                                                                        |
| `autoclaw doctor`          | check or fix local AutoClaw state plus AutoClaw-owned OpenClaw integration | local AutoClaw config, dirs, DB, packaged resources, service metadata, selected worker/operator agent ids in local AutoClaw config, patched OpenClaw agent profiles, OpenClaw-managed AutoClaw MCP server definitions, and AutoClaw wrapper material                                                 |
| `autoclaw onboard`         | guided check, set, adapt, and optional service install                     | local AutoClaw state, selected worker/operator agent ids in local AutoClaw config, patched OpenClaw agent profiles, OpenClaw-managed AutoClaw MCP server definitions, AutoClaw wrapper material, and optional service metadata; support preflight runs before any local config, DB, or service write |

| OpenClaw host shape          | AutoClaw behavior                            |
| ---------------------------- | -------------------------------------------- |
| loopback token auth          | supported; resolve token and connect         |
| loopback password auth       | supported; resolve password and connect      |
| explicit loopback no-auth    | supported with warning; connect without auth |
| non-loopback Gateway         | blocked until remote identity canon lands    |
| trusted-proxy auth           | blocked until wrapper trust canon lands      |
| ambiguous or unresolved auth | blocked with diagnostic and remediation      |

## Minimum checks

- config created
- database path exists
- API keys configured
- canonical runtime watchdog config is present when watchdog automation is enabled
- chosen provider reachable if configured
- OpenClaw check passes without requiring writes
- OpenClaw binary can be resolved from explicit override or `PATH`
- Gateway URL, loopback status, auth mode, and required secret availability are classified
- selected worker/operator agent ids, patched OpenClaw worker/operator agent profiles, default AutoClaw wrapper profile material, and OpenClaw-managed AutoClaw MCP server definitions are present when setup has run
