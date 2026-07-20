# CLI surface and configuration precedence

The installed command is `autoclaw`. On a terminal, `init` and `setup` are guided. Add `--non-interactive` for scripts. Non-TTY and `--json` invocations do not prompt. Other commands are non-interactive unless a provider opens its own identity flow.

## Passive front door

Running `autoclaw` without a subcommand is the same as `autoclaw status`. It reads local config and provider selections only. It does not contact providers, inspect provider authentication, start a service, upgrade a database, or write files. JSON reports unchecked facts as `not_checked`; human output says that the view is local-only and points to the explicit check command.

## Command families

| Command | Shipped purpose |
| --- | --- |
| `autoclaw init` | Guide local config, then create or verify the exact current schema. |
| `autoclaw setup` | Guide primary/default provider setup, checking, supported login, and optional extra providers. |
| `autoclaw status` | Read passive local status. |
| `autoclaw serve` | Run the loopback API in the foreground. |
| `autoclaw config path|show` | Locate or read effective config. |
| `autoclaw providers list|status|check|configure|set-default|login|logout` | Manage provider selection and explicit diagnostics. |
| `autoclaw definitions import` | Publish a definition file. |
| `autoclaw task-compose start` | Start one task from a local task-compose file. |
| `autoclaw db upgrade|reset` | Create or verify the exact schema, or destructively reset it. |
| `autoclaw service render|install|uninstall|start|stop|restart|status` | Manage the Linux user service. |

Use `autoclaw <command> --help` for exact options. Removed command families such as `onboard`, `doctor`, and `openclaw` are not compatibility aliases.

## Provider behavior

Codex and Claude are managed integrations. OpenClaw is an experimental compatibility integration over an independently managed Gateway; it remains selectable and may be the default.

Guided setup asks for the primary/default provider and explicitly selects it. Adding providers in that flow preserves the chosen primary. Direct `providers configure` sets the default only when none exists; later direct configuration preserves it. Use `autoclaw providers set-default <provider>` for an explicit direct change.

Guided setup always offers Codex/Claude subscription or API key. A detected working method is the method prompt default. Selecting that method opens a separate `Existing <Provider> <method> found. Use it? [Y/n]` confirmation. Yes reuses it; no runs a fresh same-method login. Choosing the other method runs its login directly. A compatible Claude or OpenClaw secret found only in the invoking shell can be stored for the AutoClaw service after a separate confirmation. The next service-scoped check must report the selected method as effective or setup fails with credential-precedence guidance. OpenClaw setup collects its URL, profile, and token/password mode, then confirms reuse of a working stored credential or asks for one. Setup steps commit independently: cancellation preserves completed explicit steps, and rerunning reads current config rather than a setup journal.

`providers status` is passive. `providers check` performs the explicit bounded diagnostic and never runs an agent task. Human output says whether a supported credential was found and whether reachability was tested, then names the non-secret method; JSON retains stable values. Ready requires a supported effective credential source. Codex/Claude reachability may remain not tested because the check sends no model request; OpenClaw health accepts the configured credential and reaches the Gateway.

Interactive setup and status use structured, colored terminal output. Redirected output and `NO_COLOR` remain readable plain text, and JSON is never decorated.

The HTTP API and browser console do not mutate provider configuration or identity.

## Configuration precedence

`--config` selects the TOML file for one command. Otherwise AutoClaw uses `AUTOCLAW_CONFIG`, then the platform default path.

For individual settings, explicit constructor values win, followed by `AUTOCLAW_*` environment values, TOML, and built-in defaults. Nested environment names use `__`. AutoClaw does not load an implicit `.env` file. Foreground execution loads the canonical private `autoclaw.env` beside the selected config, and an already exported supported provider credential takes precedence. The file accepts only supported Claude/OpenClaw credential assignments. Guided setup and provider checks use its exact credentials and the service account's default provider-native homes. Passive status does not read secrets but reports those same homes. Unrelated local commands do not read the file.

The API host must be `127.0.0.1`, `localhost`, or `::1`. The default port is `18125`. SQLite is the default database. PostgreSQL requires its own non-system schema.
