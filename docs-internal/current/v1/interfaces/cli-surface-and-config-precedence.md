# Current CLI surface and configuration

Status: Current

Last verified: 2026-07-19

The installed command is `autoclaw`. On a terminal, `init` and `setup` are guided. `--non-interactive`, non-TTY input, and `--json` use the deterministic command path without prompts. Other commands remain non-interactive unless they invoke a provider's own identity flow.

## Passive status

`autoclaw` and `autoclaw status` print the same read-only local summary. They read the selected config and provider settings. They do not contact providers, inspect authentication, test reachability, start a service, or change local state. JSON keeps unchecked facts as `not_checked`; human provider status shows one local-only explanation and the exact check command instead of repeating raw unchecked axes.

## Command groups

- `autoclaw init` guides local config and creates or verifies the exact database schema
- `autoclaw serve` runs the loopback API
- `autoclaw setup` guides primary/default provider selection, provider checking and supported login, and optional additional providers
- `autoclaw providers list|status|check|configure|set-default|login|logout`
- `autoclaw config path|show`
- `autoclaw db upgrade|reset`
- `autoclaw definitions import`
- `autoclaw task-compose start`
- `autoclaw service render|install|uninstall|start|stop|restart|status`

`db upgrade` keeps its compatibility name, but it creates an empty current schema or verifies an exact current schema. It does not migrate a legacy runtime. `db reset` is the destructive schema-change path.

## Provider setup

Codex and Claude are managed integrations. OpenClaw is an experimental compatibility integration over an independently managed Gateway and remains selectable, including as the default.

The guided setup flow asks for the primary/default provider. It routes that explicit choice through the same configure and set-default operations exposed by the direct provider commands, then asks whether to configure additional providers without replacing the primary default. A direct `providers configure` fills the default only when none exists; later direct configuration preserves it.

Guided setup checks each selected provider. Codex and Claude always offer subscription login or API key; an already detected method becomes the method prompt default but does not suppress the choice. Selecting that ready method opens a second confirmation such as `Existing Codex subscription login found. Use it? [Y/n]`. Yes reuses it; no runs a fresh login for the same method. Choosing the other method runs that login directly. A compatible Claude or OpenClaw secret found only in the invoking shell is offered for explicit storage in the private service environment and is then rechecked there. The fresh check must report the selected effective method; if another native credential store still wins, setup reports the precedence conflict and exits unsuccessfully. OpenClaw records the resolved CLI path, collects Gateway URL/profile and token or password, then confirms reuse of a working stored credential or asks for one. Codex delegates both methods to its bundled CLI. Claude delegates subscription login to its bundled CLI and stores an entered API key in the private service environment. OpenClaw stores only the selected Gateway credential there. Each accepted step is committed independently, so cancellation keeps completed selections, Ctrl-C reports that fact, and rerunning resumes from current config rather than a setup journal.

`providers status` is passive. `providers check` is the explicit bounded diagnostic and does not run an agent task. Human checks render the credential as found, missing or rejected, or not inspected; they render reachability as reachable, unreachable, or not tested and name the non-secret method. JSON uses stable machine enums. Codex reads typed ChatGPT/API-key account state. Claude reads bundled native auth status and honors an effective environment API-key source over the broader native login label. Both leave model reachability untested because no query is sent. OpenClaw performs an authenticated Gateway health call. An unverified credential source reports `local_prerequisites_ready`, returns nonzero, and is not presented as ready.

Interactive setup, provider status/check, and service status use terminal-aware Rich panels, tables, and semantic colors. Redirected output and `NO_COLOR` use readable plain text. JSON remains undecorated.

OpenClaw users maintain their own Gateway, `openclaw.json`, agent/tool policy, and compatibility Node MCP entry. AutoClaw does not inject that configuration; it manages only its adapter's private Gateway credential and non-secret route selection.

Provider configuration and identity changes are CLI-owned. The HTTP API and browser console do not expose provider mutation.

## Configuration precedence

The CLI `--config` option selects the TOML file for that command. Without it, `AUTOCLAW_CONFIG` or the platform default path is used.

For settings values, explicit constructor values win, then `AUTOCLAW_*` environment values, then TOML, then built-in defaults. Nested environment names use `__`. AutoClaw does not load an implicit `.env` file. Foreground runtime commands load the one owner-only `autoclaw.env` provider-secret file beside the selected config, and an already exported supported credential wins over the file value. That file accepts only the shipped Claude/OpenClaw credential variables. Guided setup and explicit provider checks instead use the exact private credential set and default provider-native homes available to the managed service. Passive status does not read secrets, but it reports those same managed-service homes. Unrelated local commands do not read the file.

The API host must be loopback. The default port is `18125`. SQLite is the default database; PostgreSQL requires a dedicated non-system schema.

## Evidence

- `apps/api/src/autoclaw/interfaces/cli/root.py`
- `apps/api/src/autoclaw/interfaces/cli/commands/`
- `apps/api/src/autoclaw/interfaces/cli/providers/`
- `apps/api/src/autoclaw/config.py`
- `apps/api/tests/integration/public_surfaces/root_cli/`
