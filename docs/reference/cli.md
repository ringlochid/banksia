# CLI reference

Run `banksia COMMAND --help` for the exact options available in the installed version.

## Top-level commands

| Command | Purpose |
| --- | --- |
| `banksia init` | Create or replace configuration and initialize the database. |
| `banksia setup` | Guided provider selection, authentication, and route check. |
| `banksia status` | Read passive configuration, database, provider, and service status. |
| `banksia config` | Print the effective configuration or configuration path. |
| `banksia providers` | Configure, authenticate, inspect, and choose provider routes. |
| `banksia workflow` | Import a draft or export a published Workflow revision. |
| `banksia task start` | Start one Task interactively or from strict JSON. |
| `banksia serve` | Run the loopback application in the foreground. |
| `banksia service` | Install and operate the Linux user service. |
| `banksia db` | Inspect, upgrade, verify, or reset the controller database. |

`banksia` and `banksia status` are passive reads. They do not initialize, upgrade, repair, or start services.

## Initialize

```bash
banksia init
banksia init --workspace /absolute/project/path
```

Guided initialization suggests the invocation directory as the default workspace. Automation can use `--non-interactive`, explicit values, and `--json`. `--force` replaces the managed configuration, including `paths.workspace`.

## Providers

```bash
banksia setup
banksia providers list
banksia providers status
banksia providers configure codex --model gpt-5.6 --effort high
banksia providers login codex --method subscription
banksia providers check codex
banksia providers set-default codex
```

Supported provider names are `codex`, `claude`, and `openclaw`. Banksia does not silently fall back from an unavailable explicitly selected provider.

## Workflows

Import YAML or JSON into an active draft:

```bash
banksia workflow import --file workflow.yaml
banksia workflow import --file workflow.json
banksia workflow import --file - --format yaml < workflow.yaml
```

Replacing an existing draft requires its current opaque ETag:

```bash
banksia workflow import --file workflow.yaml --etag '<current-etag>'
```

Import does not publish. Publish the validated draft through the Console, Operator, or HTTP API.

Export the current or an exact published revision:

```bash
banksia workflow export workflow-id --output workflow.yaml
banksia workflow export workflow-id --revision 2 --output workflow.json
banksia workflow export workflow-id --format yaml
```

Output paths are not overwritten unless `--force` is present. Standard output requires `--format`.

## Task start

Interactive:

```bash
banksia task start
```

Strict JSON inline, through standard input, or from a file:

```bash
banksia task start --json '{"workflow":"reviewed-delivery","prompt":"Review the change."}'
banksia task start --json - < task.json
banksia task start --json @task.json
```

The CLI uses its invocation directory as the default workspace. It never chooses from an unbounded searchable catalog; the current interactive selector is a bounded terminal choice surface, so use JSON or the Console when a large catalog makes selection awkward.

## Service

```bash
banksia service install
banksia service start
banksia service status
banksia service restart
banksia service stop
banksia service uninstall
```

This surface manages a Linux user service. `banksia serve` remains the portable foreground path.

## Machine-readable output

Commands that expose `--json` write one JSON result suitable for scripts. Use `--debug` only when a traceback is useful; ordinary failures are concise and do not print secrets.
