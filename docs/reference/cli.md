# CLI reference

The installed entry point is `banksia`. Run `banksia COMMAND --help` for the exact flags in your installed version. The root `--debug` flag may appear before or after a subcommand and adds a traceback to unexpected failures.

## Exit and output contract

| Exit | Meaning |
| --- | --- |
| `0` | The command completed successfully, help/version was shown, or a guided setup was cancelled before mutation. |
| `1` | An operational, validation, readiness, or unexpected failure occurred. For example, `providers check` returns `1` when the route is not ready. |
| `2` | Click rejected command usage, or an interactive abort propagated out of the command. |

Commands that expose `--json` write one JSON document and suppress styled human output. Failures use a closed shape containing `ok: false` and an `error` object with `kind`, `message`, optional `hint`, and `details`. `config show` always prints the effective redacted configuration as JSON; `--json` is accepted for consistency.

Do not assume every command has `--json`. `workflow export`, `serve`, and `service render` use their documented text/file output instead.

Guided `init` and `setup` report a deliberate pre-mutation cancellation and exit `0`. A lower-level Click abort that is not handled by the guided command exits `2`.

## Command inventory

| Command | Shipped surface |
| --- | --- |
| `banksia init` | Prepare local controller state, then offer first-run Task-provider and optional Operator setup. |
| `banksia setup` | Reopen the settings hub for Task providers, Operator, or the default workspace. |
| `banksia status` | Read passive configuration and local provider status. |
| `banksia config` | `path`, `show` — print the selected configuration path or effective redacted settings. |
| `banksia providers` | `list`, `status`, `configure`, `login`, `logout`, `check`, `set-default` — inspect and operate provider routes. |
| `banksia operator` | `setup`, `status`, `disable` — configure or inspect the separate Operator without changing Task-provider routing. |
| `banksia workflow` | `import`, `export` — import one draft or export a published Workflow revision. |
| `banksia task start` | Start one Task interactively or from strict JSON. |
| `banksia serve` | Run the loopback application in the foreground. |
| `banksia service` | `render`, `install`, `start`, `stop`, `restart`, `status`, `logs`, `uninstall` — render or operate this host's per-user background service. |
| `banksia db` | `upgrade`, `reset` — create or verify exact storage, or destructively reset it. |

Bare `banksia`, `banksia status`, `banksia providers status`, and `banksia operator status` are passive. They do not initialize or upgrade storage, start a service, contact a provider, repair work, or write configuration.

Most stateful commands accept `--config PATH`. When omitted, configuration selection follows `BANKSIA_CONFIG` and then the platform default. See [Configuration](configuration.md).

## Initialization

Guided initialization requires terminal input and output:

```bash
banksia init
```

It suggests the invocation directory as `paths.workspace`. For automation, provide all required values and disable prompting:

```bash
banksia init \
  --non-interactive \
  --workspace /absolute/path/to/project \
  --json
```

Important flags are:

- `--config`, `--data-dir`, and `--database-url`;
- `--workspace`, which must name an existing directory;
- `--host`, `--port`, and `--log-level`;
- `--skip-db-upgrade`;
- `--non-interactive`; and
- `--force`.

SQLite is the default. PostgreSQL needs the `banksia[postgres]` installation extra and an explicit `--database-url`; see [Database configuration](configuration.md#database).

An existing guided configuration offers `keep`, `reconfigure`, or `cancel`. **Reconfigure** changes local paths, database, server, and logging settings while keeping provider routes, the Task-provider default, and Operator settings; the final summary labels those values as **kept**. It is not a full configuration reset.

Noninteractive initialization does not overwrite an existing configuration without `--force`. Forced initialization applies the same bounded local reconfiguration and preserves an existing valid `paths.workspace` when `--workspace` is omitted. Supplying `--workspace` replaces it. An invalid value that cannot be preserved stops the command before rewrite.

After local configuration, exact-schema setup, and Starter Workflow bootstrap succeed, guided first-run initialization continues into the Task-provider chooser when no provider is configured. Choose `cancel` there to keep initialization complete and defer provider configuration. It then offers Codex, Claude, or **Not now** for Operator when no Operator is selected.

Initialization never guesses how to change a nonexact existing database. When a supported older Banksia schema is found, preserve it and run the upgrade with the same configuration:

```bash
banksia db upgrade
```

An applied upgrade reports a private backup path. SQLite uses an adjacent integrity-checked online backup; PostgreSQL writes a nonempty custom-format dump of the dedicated Banksia schema under `paths.data_dir/database-backups/` and requires a compatible `pg_dump` client. Unknown or locally changed schemas are refused.

`banksia db reset` is still destructive, but it now creates the same backup before deleting controller-owned Task roots or replacing an existing database/schema. The command reports `backup_path` in JSON and prints it in ordinary output. If backup creation fails, reset stops before deletion. Preserve that file until you have verified the replacement and no longer need rollback.

Operator may use a different provider. For example, selecting Codex for Tasks and then Claude for Operator offers to configure Claude, keeps Codex as the Task default, and saves Claude only for Operator. Selecting the same provider reuses the check already performed by that initialization call rather than repeating it. This does not create a persisted readiness cache.

Rerunning initialization preserves existing provider and Operator selections. Noninteractive and JSON initialization remain prompt-free and never configure either lane.

## Settings and Task-provider setup

Supported provider names are `codex` and `claude`.

```bash
banksia setup
banksia providers list
banksia providers status
banksia providers configure codex --model gpt-5.6 --effort high
banksia providers login codex --method subscription
banksia providers check codex
banksia providers set-default codex
```

Interactive `setup` is a rerunnable hub for **Task providers**, **Operator**, and **Default workspace**. It is guided only when both terminal streams are interactive and neither `--non-interactive` nor `--json` is present.

Noninteractive `setup` configures one Task provider and therefore needs `--provider`. Its provider-specific route flags are `--model`, `--effort`, and `--extension-mode`. Use the focused Operator commands for noninteractive Operator configuration.

`providers configure` enables the named provider and fills `runtime.default_provider` only when no default exists. It never silently replaces another default. Use `providers set-default` for that explicit change.

Codex and Claude login methods are `subscription` and `api-key`. An API key can be read without echo in a terminal or from standard input with `--secret-stdin`; do not put it on the command line. Subscription login requires a terminal.

An explicitly selected unavailable provider never falls back to another provider. `providers check` is the active route/readiness diagnostic; `providers status` remains passive. **Ready for first task** means local prerequisites and credentials passed while live reachability remains for the first Task. A failed check returns exit `1` but does not disable, rewrite, or replace the saved route.

## Operator setup

Operator is a separate control-plane agent and may use Codex or Claude:

```bash
banksia operator setup
banksia operator status
banksia operator disable
```

Interactive `operator setup` defaults to the saved provider. A missing managed route uses the same configuration, authentication, and diagnostic flow as Task-provider setup. Existing model and effort overrides are preserved unless you choose to change them; enter `-` while editing either value to restore the provider default. Changing providers does not carry the prior provider's overrides automatically.

A changed selection runs the shared provider diagnostic. An unchanged selection reports **Operator already configured** and asks whether to run that diagnostic. A diagnostic failure may make the command exit `1`; the accepted Operator selection remains saved.

Automation must provide the provider:

```bash
banksia operator setup \
  --provider codex \
  --non-interactive \
  --json
```

Noninteractive setup saves configuration without contacting the provider. `operator status` is passive and reports persisted and effective values, environment overrides, route configuration, and the next diagnostic. `operator disable` removes only the persisted Operator selection; it neither disables the provider nor changes `runtime.default_provider`. An effective `BANKSIA_OPERATOR__*` override remains until the environment is corrected.

## Workflow import

Import accepts one JSON or YAML file:

```bash
banksia workflow import --file workflow.yaml
banksia workflow import --file workflow.json
banksia workflow import --file - --format yaml < workflow.yaml
```

A file extension must be `.json`, `.yaml`, or `.yml`. Standard input requires `--format json|yaml`. The parser rejects duplicate keys, non-JSON-compatible YAML features, extra fields, and semantic Workflow errors.

Import creates or replaces an active draft; it does not publish. Replacing an existing draft requires its current opaque ETag:

```bash
banksia workflow import --file workflow.yaml --etag '<current-etag>'
```

Without the current ETag, or when another edit has advanced it, the mutation fails instead of overwriting current controller truth.

## Workflow export

Export selects the current publication by default or one exact immutable revision:

```bash
banksia workflow export production-feature-delivery \
  --output production-feature-delivery.yaml

banksia workflow export production-feature-delivery \
  --revision 1 \
  --output production-feature-delivery.json

banksia workflow export production-feature-delivery --format yaml
```

The output extension selects JSON or YAML when writing a file. Standard output requires `--format`. Existing files are not overwritten unless `--force` is present.

## Task start

The controller must already be reachable. Interactive mode requires a terminal:

```bash
banksia task start
```

The command exhausts every controller Workflow-library page, keeps published entries, and puts their exact case-sensitive IDs into one `click.Choice` prompt. Click validates a typed value; it is not a searchable, numbered, fuzzy, or paginated in-process menu. A large catalog, especially around 50 or more IDs, is awkward even though the CLI fetched all pages. Use Workflow Studio for discovery or strict JSON when you already know the ID.

After selection, the CLI opens an editor for the complete Markdown Task prompt. Empty or cancelled editor input aborts before Task submission. The workspace defaults to the invocation directory.

Machine mode accepts exactly one strict JSON source: an inline object, `@file`, or `-` for standard input.

```bash
banksia task start \
  --json '{"workflow":"production-feature-delivery","prompt":"Deliver the consequential cross-layer feature, verify the integrated outcome and release risks, repair accepted findings, and return the result."}'

banksia task start --json @task.json
banksia task start --json - < task.json
```

The object is the exact `TaskStartRequest`:

```json
{
  "workflow": "production-feature-delivery",
  "prompt": "Deliver and independently verify the consequential cross-layer feature.",
  "workspace": "/absolute/path/to/project",
  "files": [
    {
      "path": "docs/accepted-scope.md",
      "description": "Accepted scope"
    }
  ]
}
```

`workflow` and nonblank `prompt` are required. `workspace` and `files` are optional; machine mode fills an omitted workspace with the invocation directory. Unknown fields, duplicate JSON keys, nonfinite numbers, invalid file references, and multiple `--json` sources are rejected.

Success prints JSON in machine mode. Interactive success prints the Task ID, Workflow revision, workspace, and manifest path. Acceptance means the controller committed the Task; provider work still starts asynchronously.

## Server and service

Run the foreground loopback application with:

```bash
banksia serve
```

The per-user background-service surface is:

```bash
banksia service render
banksia service install
banksia service start
banksia service status
banksia service restart
banksia service stop
banksia service logs --lines 200
banksia service uninstall
```

Banksia selects one native current-user manager:

| Host | Background service |
| --- | --- |
| Linux | systemd user service |
| macOS | current-user LaunchAgent |
| Windows | current-user Scheduled Task (`\Banksia\Controller`) |

Native Windows requires Windows 11 x64 and local NTFS configuration, data, workspace, and Command Run paths. UNC/network, device, non-NTFS, and reparse-point paths reject. WSL2 uses the Linux lane.

`service install` verifies the selected configuration and exact database schema, creates the private sibling `banksia.env` when needed, atomically reconciles the fixed native definition, enables startup, and starts it unless `--no-start` is supplied. Re-running install reconciles an outdated definition. A schema mismatch stops before service changes and directs you to run `banksia db upgrade` with the same `--config` before considering reset.

`render`, `install`, `start`, `stop`, `restart`, `status`, and `uninstall` accept the normal `--config PATH` where applicable. Lifecycle and status commands offer `--json`; there is no user-authored service name, unit directory, or port override. Change the API port through initialization or configuration, then rerun `service install`.

`service status` combines native definition/startup state with bounded controller health and readiness. `service logs` reads the portable bounded controller log; `--follow` cannot be combined with `--json`. `service uninstall` removes the native definition but preserves controller configuration, database/data, and provider credentials.

`banksia serve` remains the portable foreground path. A native service implementation on a host does not by itself establish full platform readiness; supported-platform claims require the installed-wheel filesystem, private-path, Command Run, reset, and lifecycle gates.

## Database commands

```bash
banksia db upgrade
banksia db reset
```

Both accept `--revision`, `--json`, `--plain`, `--no-color`, and `--verbose`. `upgrade` creates the exact shipped schema when the database is genuinely empty, verifies an exact current schema, or applies a registered forward upgrade from one exact supported predecessor after creating a backup. Unknown, skipped, partially changed, or locally modified schemas remain untouched. Inspect an unavailable upgrade before using destructive `reset`, and use reset only when you accept replacing controller history.

`reset` is destructive controller-storage initialization, not a generic recovery or retry command. It can remove controller data and controller-owned task roots outside accepted workspace Task directories. Back up and verify the selected configuration and data boundary before intentionally using it.
