# CLI reference

The installed entry point is `banksia`. Run `banksia COMMAND --help` for the exact flags in your installed version. The root `--debug` flag may appear before or after a subcommand and adds a traceback to unexpected failures.

## Exit and output contract

| Exit | Meaning |
| --- | --- |
| `0` | The command completed successfully, help/version was shown, or a guided setup was cancelled before mutation. |
| `1` | An operational, validation, readiness, or unexpected failure occurred. For example, `providers check` returns `1` when the route is not ready. |
| `2` | Click rejected command usage, or an interactive abort propagated out of the command. |

Commands that expose `--json` write one JSON document and suppress styled human output. Failures use a closed shape containing `ok: false` and an `error` object with `kind`, `message`, optional `hint`, and `details`. `config show` always prints the effective redacted configuration as JSON; `--json` is accepted for consistency.

Do not assume every command has `--json`. `workflow export`, `serve`, and some service mutation commands use their documented text/file output instead.

Guided `init` and `setup` report a deliberate pre-mutation cancellation and exit `0`. A lower-level Click abort that is not handled by the guided command exits `2`.

## Command inventory

| Command | Shipped surface |
| --- | --- |
| `banksia init` | Write initial configuration and create or verify the exact database schema. |
| `banksia setup` | Guide provider configuration, authentication, and readiness. |
| `banksia status` | Read passive configuration and local provider status. |
| `banksia config path|show` | Print the selected configuration path or effective redacted settings. |
| `banksia providers list|status|configure|login|logout|check|set-default` | Inspect and operate provider routes. |
| `banksia workflow import|export` | Import one draft or export a published Workflow revision. |
| `banksia task start` | Start one Task interactively or from strict JSON. |
| `banksia serve` | Run the loopback application in the foreground. |
| `banksia service render|install|start|stop|restart|status|uninstall` | Render or operate the Linux user service. |
| `banksia db upgrade|reset` | Create or verify exact storage, or destructively reset it. |

Bare `banksia`, `banksia status`, and `banksia providers status` are passive. They do not initialize or upgrade storage, start a service, contact a provider, repair work, or write configuration.

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

An existing configuration is not overwritten without `--force`. Forced initialization replaces the managed configuration but preserves an existing valid `paths.workspace` when `--workspace` is omitted. Supplying `--workspace` replaces it. An invalid value that cannot be preserved stops the command before rewrite.

After local configuration, exact-schema setup, and Starter Workflow bootstrap succeed, guided first-run initialization continues directly into the provider chooser when no provider is configured. Choose `cancel` there to keep initialization complete and defer provider configuration. Rerunning initialization with an already configured provider verifies local state without reopening provider setup. Noninteractive and JSON initialization remain prompt-free.

## Provider setup

Supported provider names are `codex`, `claude`, and `openclaw`.

```bash
banksia setup
banksia providers list
banksia providers status
banksia providers configure codex --model gpt-5.6 --effort high
banksia providers login codex --method subscription
banksia providers check codex
banksia providers set-default codex
```

`setup` is guided only when both terminal streams are interactive and neither `--non-interactive` nor `--json` is present. Noninteractive setup needs `--provider`; the provider-specific route flags are `--model`, `--effort`, `--cli-path`, `--gateway-url`, `--gateway-profile`, and `--gateway-auth-mode`.

Run `banksia setup` directly to resume deferred provider setup, change the primary provider, verify authentication, or add another provider.

`providers configure` enables the named provider and fills `runtime.default_provider` only when no default exists. It never silently replaces another default. Use `providers set-default` for that explicit change.

Codex and Claude login methods are `subscription` and `api-key`. OpenClaw methods are `token` and `password`. A secret can be read without echo in a terminal or from standard input with `--secret-stdin`; do not put it on the command line. Subscription login requires a terminal.

An explicitly selected unavailable provider never falls back to another provider. `providers check` is the active route/readiness command; `providers status` remains passive.

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
banksia workflow export reviewed-code-change \
  --output reviewed-code-change.yaml

banksia workflow export reviewed-code-change \
  --revision 1 \
  --output reviewed-code-change.json

banksia workflow export reviewed-code-change --format yaml
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
  --json '{"workflow":"reviewed-code-change","prompt":"Implement and review the requested change."}'

banksia task start --json @task.json
banksia task start --json - < task.json
```

The object is the exact `TaskStartRequest`:

```json
{
  "workflow": "reviewed-code-change",
  "prompt": "Implement and independently review the requested change.",
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

The Linux user-service surface is:

```bash
banksia service render
banksia service install
banksia service start
banksia service status
banksia service restart
banksia service stop
banksia service uninstall
```

`render`, `install`, and `uninstall` accept service/configuration flags shown by their help. Start, stop, restart, and status accept `--name` and `--json`. `banksia serve` is the portable foreground path.

## Database commands

```bash
banksia db upgrade
banksia db reset
```

Both accept `--revision`, `--json`, `--plain`, `--no-color`, and `--verbose`. `upgrade` creates the exact shipped schema only when the database is genuinely empty. For a nonempty database, it verifies the complete exact schema and issues no migration or repair DDL. Any missing, unexpected, or changed schema detail stops with guidance to use `reset`.

`reset` is destructive controller-storage initialization, not a generic recovery or retry command. It can remove controller data and controller-owned task roots outside accepted workspace Task directories. Back up and verify the selected configuration and data boundary before intentionally using it.
