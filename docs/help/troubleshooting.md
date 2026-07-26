# Troubleshooting

Start with passive reads:

```bash
banksia status
banksia config show
banksia providers status
```

Add `--json` when collecting machine-readable diagnostics. Add top-level `--debug` only when a traceback is useful.

## Task start reports no default workspace

HTTP, Console, and Operator starts need either an explicit absolute workspace or `paths.workspace` in configuration. Record one with:

```bash
banksia init --workspace /absolute/path/to/project
```

Guided `banksia init` suggests the invocation directory. Remember that `init --force` replaces the managed configuration. Confirm the effective value with `banksia config show`.

## No published Workflow is available

Import creates a draft; it does not publish:

```bash
banksia workflow import --file workflow.yaml
```

Open the Workflow in the Console or use the Operator or HTTP draft endpoints to validate and publish it. Packaged starter Workflows are created during database bootstrap.

## A provider is unavailable

Inspect and check the exact route:

```bash
banksia providers status
banksia providers check codex
```

Then run `banksia setup` or the explicit `providers configure`, `login`, and `set-default` commands. Banksia does not silently fall back from an explicit provider selection.

OpenClaw is user-operated. Check the configured CLI, Gateway URL, profile, authentication mode, and Gateway health outside Banksia as well.

## A Task is waiting

Open the Task detail route. A Human Request needs an explicit answer. A Command Run may still be active or cancelling. A Manager may be waiting for every member of its current Delegation Wave; blocked members are still terminal join results.

Do not infer progress from a provider process alone. Controller Activity, Checkpoints, waits, and the selected Result are authoritative.

## Command output is large

The controller keeps bounded output for product reads. The full log remains in the selected workspace under:

```text
.banksia/t_<id>/command-runs/c_<id>/output.log
```

Open it with ordinary filesystem tools. A missing path should be treated as an operational problem, not silently reconstructed from truncated database text.

## Console access is rejected

Banksia accepts configured loopback hosts and origins only. Use the exact address printed by the service, normally `http://127.0.0.1:18125/`, and do not proxy the current local product surface to another machine.

## Database or service repair

Inspect the available commands before changing state:

```bash
banksia db --help
banksia service status
```

Back up controller data before reset. A reset can recreate controller storage, but it does not make loose workspace files canonical or rewrite historical blocked work into success.
