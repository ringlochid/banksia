# Configuration reference

Use the CLI to discover the active configuration rather than assuming a platform-specific path:

```bash
banksia config path
banksia config show
banksia config show --json
```

On a typical Linux installation, configuration is stored at `~/.config/banksia/config.toml` and controller data at `~/.local/share/banksia/`.

## Main sections

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
]

[logging]
level = "WARNING"
```

`paths.workspace` must be an existing absolute directory. HTTP, Console, and Operator Task start use it when the request omits a workspace. CLI Task start uses its invocation directory.

The server host must be loopback: `127.0.0.1`, `::1`, or `localhost`. Console origins must be absolute loopback HTTP or HTTPS origins.

## Providers

```toml
[codex]
enabled = true
model = "gpt-5.6"
effort = "high"

[claude]
enabled = false

[openclaw]
enabled = false
cli_path = "openclaw"
gateway_url = "ws://127.0.0.1:18789"
gateway_profile = "default"
gateway_auth_mode = "token"

[runtime]
default_provider = "codex"
managed_provider_sandbox_mode = "full_access"
managed_provider_network_access = "allow"
max_child_assignments_per_assignment = 20
max_wave_members = 8
max_retries_per_assignment = 1
```

Provider credentials are handled through `banksia providers login`; do not write secrets into public examples. OpenClaw Gateway ownership remains outside Banksia.

Legal managed sandbox/network pairs are `read_only`/`deny`, `workspace_write`/`allow|deny`, and `full_access`/`allow`.

## Operator

```toml
[operator]
provider = "codex"
model = "gpt-5.6"
effort = "high"
```

The Operator provider may be `codex` or `claude`. Model and effort require a selected Operator provider. The corresponding provider must also be enabled and authenticated.

## Environment overrides

Environment values take precedence over TOML. Common direct overrides include:

- `BANKSIA_CONFIG`;
- `BANKSIA_DATA_DIR`;
- `BANKSIA_DATABASE_URL`;
- `BANKSIA_CONTROLLER_WORKSPACE`;
- `BANKSIA_API_HOST` and `BANKSIA_API_PORT`;
- `BANKSIA_LOG_LEVEL`;
- `BANKSIA_DEBUG`; and
- `BANKSIA_DATABASE_ECHO`.

Nested settings use the double-underscore form supported by the configuration model, such as `BANKSIA_RUNTIME__MAX_WAVE_MEMBERS`.

Set `BANKSIA_SUPPORT_BEARER_TOKEN` to a secret of at least 32 characters only when using the separate support API. `banksia config show` redacts secret-bearing values.
