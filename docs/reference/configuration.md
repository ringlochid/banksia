# Configuration reference

Banksia reads one selected TOML configuration, then applies environment overrides. Discover the selected path and effective redacted values through the passive CLI:

```bash
banksia config path
banksia config show
banksia status
```

On a typical Linux installation, the defaults are `~/.config/banksia/config.toml` and `~/.local/share/banksia/`. Platform directories vary; do not hard-code those example paths in automation.

## Selection and precedence

For a CLI command, configuration-file selection is:

1. that command's `--config PATH`;
2. `BANKSIA_CONFIG`; and
3. the platform default configuration path.

Within the loaded settings, precedence is:

1. explicit programmatic/command overrides;
2. `BANKSIA_*` environment values;
3. values from the selected TOML file; and
4. shipped defaults.

Banksia does not implicitly load a repository `.env` file as configuration. Unknown TOML keys inside a known typed section are rejected when that section is validated. `config show` reports effective values and redacts secret-bearing URLs; it does not print provider credentials or the support token.

## Default workspace

`[paths].workspace` is the default workspace for Task starts from HTTP, the Console, and Operator when their request omits `workspace`.

```toml
[paths]
data_dir = "/home/me/.local/share/banksia"
workspace = "/home/me/projects/default-workspace"
```

It must be a nonblank absolute path to an existing directory. The controller resolves it at configuration load; a deleted or relative directory makes the configuration invalid.

Guided `banksia init` suggests its invocation directory. Noninteractive setup can record a value with:

```bash
banksia init --non-interactive --workspace /absolute/project/path
```

For an initialized controller, rerun `banksia setup` and choose **Default workspace**. The settings hub shows the current effective value before prompting.

`BANKSIA_CONTROLLER_WORKSPACE` overrides the TOML value. CLI `banksia task start` deliberately uses its own invocation directory when the request omits `workspace`; it does not use this controller default.

## Database

Banksia supports SQLite and PostgreSQL through the same controller contract. Choose one database for a controller and keep that selection stable: Banksia verifies an exact schema and does not migrate records between database backends.

### SQLite

SQLite is the default for `banksia init`. It requires no external service and stores controller data beneath the platform data directory:

```toml
[database]
url = "sqlite+aiosqlite:////home/me/.local/share/banksia/banksia.persistence"
echo = false
```

This is the simplest choice for a local, single-process Banksia installation.

### PostgreSQL

Install Banksia with its PostgreSQL driver:

```bash
pipx install "banksia[postgres]"
```

If the base package is already installed:

```bash
pipx install --force "banksia[postgres]"
```

Then select PostgreSQL during initialization:

```bash
banksia init \
  --database-url "postgresql+asyncpg://banksia@127.0.0.1/banksia"
```

The URL must use SQLAlchemy's `postgresql+asyncpg` driver. Substitute the host, port, database, role, and credentials required by your PostgreSQL service. Percent-encode reserved characters in credentials and avoid leaving a password in shell history.

Banksia uses a dedicated schema named `banksia` by default. The database role must be able to connect to the selected database and create or use objects in that schema. On first initialization, Banksia creates a missing dedicated schema and creates tables only when that schema is empty. A nonempty schema must match the shipped schema exactly.

```toml
[database]
url = "postgresql+asyncpg://banksia@127.0.0.1/banksia"
postgres_schema = "banksia"
echo = false
```

`postgres_schema` must be a dedicated lowercase PostgreSQL identifier, not `public`, `information_schema`, or an identifier beginning with `pg_`. Do not change it casually after initialization: another name selects another schema rather than migrating controller data.

Use passive readback to confirm the selected backend. Passwords in database URLs are redacted:

```bash
banksia config show
banksia status
```

`BANKSIA_DATABASE_URL` and `BANKSIA_POSTGRES_SCHEMA` can override the file configuration for a process. Keep those values stable for a background service; an environment override changes the effective controller database without rewriting the TOML file.

`banksia db upgrade` creates an empty selected schema or verifies an existing exact schema. It is not a migration or repair command. `banksia db reset` is destructive: for PostgreSQL it replaces the configured dedicated schema and removes its controller history. See [Troubleshooting](../help/troubleshooting.md#you-are-considering-database-reset) before using reset.

## TOML sections and fields

### Core controller settings

```toml
[paths]
data_dir = "/home/me/.local/share/banksia"
workspace = "/home/me/projects/default-workspace"

[database]
url = "sqlite+aiosqlite:////home/me/.local/share/banksia/banksia.persistence"
postgres_schema = "banksia"
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

[claude]
enabled = false
```

Both managed-provider sections accept:

- `enabled`;
- optional exact provider-native `model`; and
- optional adapter-supported `effort`.

An explicit model or effort never silently falls back. Provider credentials are managed by `banksia providers login`, not public TOML examples. `banksia providers check NAME` is a bounded diagnostic: failure does not disable or rewrite the configured route.

### OpenClaw

```toml
[openclaw]
enabled = false
cli_path = "openclaw"
gateway_url = "ws://127.0.0.1:18789"
gateway_profile = "default"
gateway_auth_mode = "token"
```

OpenClaw is a user-operated transport. Its fields are `enabled`, `cli_path`, `gateway_url`, `gateway_profile`, and `gateway_auth_mode` (`token` or `password`). Banksia does not configure or prove the Gateway's model, provider-visible workspace, sandbox, or network access.

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
banksia operator setup
banksia operator status
banksia operator disable
```

Guided initialization offers Operator after Task-provider setup. `banksia setup` reopens the settings hub later. Disabling Operator removes only its persisted selection; it does not disable the provider route or change the default Task provider.

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
watchdog_inactivity_timeout_seconds = 900
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
| `watchdog_inactivity_timeout_seconds` | `900` | Inactivity duration before watchdog handling. |
| `watchdog_same_attempt_replacement_limit` | `2` | Bounded same-Attempt watchdog replacement count. |

### Managed sandbox and network

Legal managed sandbox/network pairs are:

| Sandbox | Network |
| --- | --- |
| `read_only` | `deny` |
| `workspace_write` | `deny` or `allow` |
| `full_access` | `allow` |

A Workflow may request a sandbox under an individual Codex or Claude `provider` block. If that authored block is omitted, provider resolution first forms a `full_access` plus `allow` request. The two runtime values then act as a controller ceiling: they preserve an equally or more restrictive request and narrow a broader one. They do not replace the omitted authored request. Each Dispatch records both requested and effective provenance, and the managed-provider adapter receives the effective pair. There is no standalone `network_access` field in a Workflow.

On Linux and WSL2, a Claude Dispatch with effective network `deny` uses Claude Code's native sandbox with fail-closed startup. Install the host packages `bubblewrap` and `socat` before using either `read_only`/`deny` or `workspace_write`/`deny`; otherwise the provider turn does not start. These packages are Claude deny-network sandbox prerequisites, not general Banksia dependencies, and Banksia does not enable this sandbox for Claude's allow-network pairs. See [Claude Code sandboxing](https://code.claude.com/docs/en/sandboxing) for distribution and AppArmor guidance.

`providers configure NAME` enables a provider and fills `runtime.default_provider` only if it is empty. Use `providers set-default NAME` for an intentional replacement. Banksia never falls back silently from an explicit unavailable provider, and a failed readiness diagnostic never changes the saved route.

## Environment overrides

Common direct environment names are:

- `BANKSIA_CONFIG`;
- `BANKSIA_DATA_DIR`;
- `BANKSIA_DATABASE_URL` and `BANKSIA_POSTGRES_SCHEMA`;
- `BANKSIA_CONTROLLER_WORKSPACE`;
- `BANKSIA_API_HOST`, `BANKSIA_API_PORT`, and `BANKSIA_CONSOLE_ORIGINS`;
- `BANKSIA_LOG_LEVEL`;
- `BANKSIA_DEBUG` and `BANKSIA_DATABASE_ECHO`; and
- `BANKSIA_SUPPORT_BEARER_TOKEN`.

Nested models use a double underscore. Examples:

```bash
export BANKSIA_RUNTIME__MAX_WAVE_MEMBERS=4
export BANKSIA_CODEX__ENABLED=true
export BANKSIA_OPERATOR__PROVIDER=codex
```

Boolean compatibility overrides `BANKSIA_DEBUG` and `BANKSIA_DATABASE_ECHO` accept `1|true|yes|on` and `0|false|no|off`, case-insensitively.

`BANKSIA_SUPPORT_BEARER_TOKEN` enables the separate support API and must contain at least 32 characters. Treat it as a secret. Product browser admission does not use this token.

## Configuration failures

An invalid configuration stops the owning command or application startup. Safe readback is:

```bash
banksia config path
banksia config show
banksia status
```

Correct the selected TOML or environment value explicitly. Do not use database reset to repair a path, provider, origin, or sandbox configuration error.
