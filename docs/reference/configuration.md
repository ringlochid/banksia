# Configuration reference

Oh My Subagents reads one selected TOML configuration, then applies environment overrides. Discover the selected path and effective redacted values through the passive CLI:

```bash
oms config path
oms config show
oms status
```

On a typical Linux installation, the defaults are `~/.config/oh-my-subagents/config.toml` and `~/.local/share/oh-my-subagents/`. Platform directories vary; do not hard-code those example paths in automation.

The OMS platform directories, `oms.persistence`, configured PostgreSQL schema, and `.oms/` Task roots are the canonical storage protocols in Oh My Subagents `0.3.x`. The canonical environment prefix is `OMS_`. Legacy `BANKSIA_*` values are accepted with a warning during `0.3.x`; conflicting old and new values fail before startup or mutation.

## Selection and precedence

For a CLI command, configuration-file selection is:

1. that command's `--config PATH`;
2. `OMS_CONFIG`; and
3. the platform default configuration path.

Within the loaded settings, precedence is:

1. explicit programmatic/command overrides;
2. `OMS_*` environment values;
3. values from the selected TOML file; and
4. shipped defaults.

Oh My Subagents does not implicitly load a repository `.env` file as configuration. Unknown TOML keys inside a known typed section are rejected when that section is validated. `config show` reports effective values and redacts secret-bearing URLs; it does not print provider credentials or the support token.

## Default workspace

`[paths].workspace` is the default workspace for Task starts from HTTP, the Console, and Operator when their request omits `workspace`.

```toml
[paths]
data_dir = "/home/me/.local/share/oh-my-subagents"
workspace = "/home/me/projects/default-workspace"
```

It must be a nonblank absolute path to an existing directory. The controller resolves it at configuration load; a deleted or relative directory makes the configuration invalid.

Guided `oms init` suggests its invocation directory. Noninteractive setup can record a value with:

```bash
oms init --non-interactive --workspace /absolute/project/path
```

For an initialized controller, rerun `oms setup` and choose **Default workspace**. The settings hub shows the current effective value before prompting.

`OMS_CONTROLLER_WORKSPACE` overrides the TOML value. CLI `oms task start` deliberately uses its own invocation directory when the request omits `workspace`; it does not use this controller default.

## Database

Oh My Subagents supports SQLite and PostgreSQL through the same controller contract. Choose one database for a controller and keep that selection stable: Oh My Subagents verifies an exact schema and does not migrate records between database backends.

### SQLite

SQLite is the default for `oms init`. It requires no external service and stores controller data beneath the platform data directory:

```toml
[database]
url = "sqlite+aiosqlite:////home/me/.local/share/oh-my-subagents/oms.persistence"
echo = false
```

This is the simplest choice for a local, single-process Oh My Subagents installation.

### PostgreSQL

Install Oh My Subagents with its PostgreSQL driver:

```bash
pipx install "oh-my-subagents[postgres]"
```

If the base package is already installed:

```bash
pipx install --force "oh-my-subagents[postgres]"
```

Then select PostgreSQL during initialization:

```bash
oms init \
  --database-url "postgresql+asyncpg://oms@127.0.0.1/oms"
```

The URL must use SQLAlchemy's `postgresql+asyncpg` driver. Substitute the host, port, database, role, and credentials required by your PostgreSQL service. Percent-encode reserved characters in credentials and avoid leaving a password in shell history.

Oh My Subagents uses a dedicated schema named `oms` by default. The database role must be able to connect to the selected database and create or use objects in that schema. On first initialization, Oh My Subagents creates a missing dedicated schema and creates tables only when that schema is empty. A nonempty schema must match the shipped schema exactly. Migrated PostgreSQL configurations keep the legacy `banksia` schema explicitly.

```toml
[database]
url = "postgresql+asyncpg://oms@127.0.0.1/oms"
postgres_schema = "oms"
echo = false
```

`postgres_schema` must be a dedicated lowercase PostgreSQL identifier, not `public`, `information_schema`, or an identifier beginning with `pg_`. Do not change it casually after initialization: another name selects another schema rather than migrating controller data.

Use passive readback to confirm the selected backend. Passwords in database URLs are redacted:

```bash
oms config show
oms status
```

`OMS_DATABASE_URL` and `OMS_POSTGRES_SCHEMA` can override the file configuration for a process. Keep those values stable for a background service; an environment override changes the effective controller database without rewriting the TOML file.

`oms db upgrade` creates an empty selected schema, verifies the current exact schema, or applies a registered forward upgrade from one exact supported Oh My Subagents predecessor. It never guesses how to repair an unknown or locally changed schema. Every schema-changing upgrade first reports a private backup; PostgreSQL also uses transactional DDL. `oms db reset` remains destructive, but it must create a backup before replacing an existing SQLite database or dedicated PostgreSQL schema. PostgreSQL backup requires a compatible `pg_dump` client. See [Troubleshooting](../help/troubleshooting.md#you-are-considering-database-reset) before using reset.

## TOML sections and fields

### Core controller settings

```toml
[paths]
data_dir = "/home/me/.local/share/oh-my-subagents"
workspace = "/home/me/projects/default-workspace"

[database]
url = "sqlite+aiosqlite:////home/me/.local/share/oh-my-subagents/oms.persistence"
postgres_schema = "oms"
echo = false

[server]
host = "127.0.0.1"
port = 18125
console_origins = [
  "http://127.0.0.1:5173",
  "http://localhost:5173",
  "http://127.0.0.1:4173",
  "http://localhost:4173",
]

[logging]
level = "WARNING"
```

| Section | Fields |
| --- | --- |
| `paths` | `data_dir`, optional `workspace` |
| `database` | `url`, `postgres_schema`, `echo` |
| `server` | `host`, `port`, `console_origins` |
| `logging` | `level` |

The server host is loopback-only: `127.0.0.1`, `::1`, another loopback IP, or `localhost`. Console origins must be absolute loopback HTTP or HTTPS origins without credentials, paths, queries, or fragments.

### Managed providers

```toml
[codex]
enabled = true
model = "gpt-5.6"
effort = "high"
extension_mode = "inherit"

[claude]
enabled = false
```

Both managed-provider sections accept:

- `enabled`;
- optional exact provider-native `model`; and
- optional adapter-supported `effort`; and
- `extension_mode = "inherit" | "isolated"`.

An explicit model or effort never silently falls back. Provider credentials are managed by `oms providers login`, not public TOML examples. `oms providers check NAME` is a bounded diagnostic: failure does not disable or rewrite the configured route.

`extension_mode` defaults to `inherit`. It makes enabled user and project Skills plus configured MCP servers available to trusted Task Members while implicit workspace instructions and general plugins remain disabled. An effective sandbox narrower than `full_access` plus network `allow` is isolated automatically. Operator is always isolated and does not use this setting.

Configure the value without editing TOML directly:

```bash
oms providers configure codex --extension-mode isolated
```

Codex Task effort also accepts `max`; `ultra` remains unavailable to Task Members. Native Codex configuration not overridden by Oh My Subagents, including `service_tier = "fast"`, remains effective beside explicit Oh My Subagents model and effort choices.

### Operator

```toml
[operator]
provider = "codex"
model = "gpt-5.6"
effort = "high"
```

`operator.provider` may be `codex` or `claude`. `model` and `effort` require a selected Operator provider. The corresponding managed provider must also be enabled and authenticated. Operator is a separate control-plane agent; this section does not set Task-member defaults.

Prefer the focused CLI over manual edits:

```bash
oms operator setup
oms operator status
oms operator disable
```

Guided initialization offers Operator after Task-provider setup. `oms setup` reopens the settings hub later. Disabling Operator removes only its persisted selection; it does not disable the provider route or change the default Task provider.

### Runtime

```toml
[runtime]
default_provider = "codex"
managed_provider_sandbox_mode = "full_access"
managed_provider_network_access = "allow"
max_child_assignments_per_assignment = 20
max_wave_members = 8
max_retries_per_assignment = 1
dispatch_launch_retry_initial_backoff_seconds = 1.0
dispatch_launch_retry_max_backoff_seconds = 30.0
watchdog_inactivity_timeout_seconds = 2700
watchdog_same_attempt_replacement_limit = 2
```

| Field | Default | Meaning |
| --- | --- | --- |
| `default_provider` | unset | Provider used when a Workflow Member omits `provider`; it must name an enabled route. |
| `managed_provider_sandbox_mode` | `full_access` | Controller ceiling for managed-provider native access. |
| `managed_provider_network_access` | `allow` | Controller ceiling for managed-provider network access. |
| `max_child_assignments_per_assignment` | `20` | Total child-Assignment budget owned by one Assignment. |
| `max_wave_members` | `8` | Maximum members in one Delegation Wave. |
| `max_retries_per_assignment` | `1` | Semantic retry budget snapshotted for an Assignment. |
| `dispatch_launch_retry_initial_backoff_seconds` | `1.0` | Initial retry delay for provider launch handling. |
| `dispatch_launch_retry_max_backoff_seconds` | `30.0` | Maximum provider-launch retry delay. |
| `watchdog_inactivity_timeout_seconds` | `2700` | Inactivity duration before watchdog handling. |
| `watchdog_same_attempt_replacement_limit` | `2` | Same-Attempt watchdog replacements available between successful user Resumes. |

### Managed sandbox and network

Legal managed sandbox/network pairs are:

| Sandbox | Network |
| --- | --- |
| `read_only` | `deny` |
| `workspace_write` | `deny` or `allow` |
| `full_access` | `allow` |

A Workflow may request a sandbox under an individual Codex or Claude `provider` block. If that authored block is omitted, provider resolution first forms a `full_access` plus `allow` request. The two runtime values then act as a controller ceiling: they preserve an equally or more restrictive request and narrow a broader one. They do not replace the omitted authored request. Each Dispatch records both requested and effective provenance, and the managed-provider adapter receives the effective pair. There is no standalone `network_access` field in a Workflow.

On Linux and WSL2, a Claude Dispatch with effective network `deny` uses Claude Code's native sandbox with fail-closed startup. Install the host packages `bubblewrap` and `socat` before using either `read_only`/`deny` or `workspace_write`/`deny`; otherwise the provider turn does not start. These packages are Claude deny-network sandbox prerequisites, not general Oh My Subagents dependencies, and Oh My Subagents does not enable this sandbox for Claude's allow-network pairs. See [Claude Code sandboxing](https://code.claude.com/docs/en/sandboxing) for distribution and AppArmor guidance.

`providers configure NAME` enables a provider and fills `runtime.default_provider` only if it is empty. Use `providers set-default NAME` for an intentional replacement. Oh My Subagents never falls back silently from an explicit unavailable provider, and a failed readiness diagnostic never changes the saved route.

## Environment overrides

Common direct environment names are:

- `OMS_CONFIG`;
- `OMS_DATA_DIR`;
- `OMS_DATABASE_URL` and `OMS_POSTGRES_SCHEMA`;
- `OMS_CONTROLLER_WORKSPACE`;
- `OMS_API_HOST`, `OMS_API_PORT`, and `OMS_CONSOLE_ORIGINS`;
- `OMS_LOG_LEVEL`;
- `OMS_DEBUG` and `OMS_DATABASE_ECHO`; and
- `OMS_SUPPORT_BEARER_TOKEN`.

Nested models use a double underscore. Examples:

```bash
export OMS_RUNTIME__MAX_WAVE_MEMBERS=4
export OMS_CODEX__ENABLED=true
export OMS_OPERATOR__PROVIDER=codex
```

Boolean compatibility overrides `OMS_DEBUG` and `OMS_DATABASE_ECHO` accept `1|true|yes|on` and `0|false|no|off`, case-insensitively.

`OMS_SUPPORT_BEARER_TOKEN` enables the separate support API and must contain at least 32 characters. Treat it as a secret. Product browser admission does not use this token.

## Configuration failures

An invalid configuration stops the owning command or application startup. Safe readback is:

```bash
oms config path
oms config show
oms status
```

Correct the selected TOML or environment value explicitly. Do not use database reset to repair a path, provider, origin, or sandbox configuration error.
