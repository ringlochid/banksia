# Migrate from Banksia

Oh My Subagents `0.3.x` moves the Python package, default platform directories, SQLite filename, provider environment file, new Task roots, prompt/MCP identifiers, and native service identity to OMS names. Migration is explicit: startup never moves state automatically.

## Replace the distribution

Read the old state before changing the isolated installation:

```bash
banksia config path
banksia status --json
banksia service status --json
```

Then replace the package:

```bash
pipx uninstall banksia
pipx install oh-my-subagents
oms --version
```

The `banksia` command remains as a deprecated launcher during the `0.3.x` migration window. The implementation package is only `oh_my_subagents`.

## Run the migration

For a default installation, run one command:

```bash
oms migrate-from-banksia
```

Run migration before `oms init`. When legacy default state exists, `oms init` stops before creating a second controller database and directs you back to this command.

The command:

- copies the legacy config into the OMS platform config directory;
- copies the default data directory and renames the primary SQLite file from `banksia.persistence` to `oms.persistence`;
- copies `banksia.env` as `oms.env`;
- preserves custom data paths, database URLs, and the existing PostgreSQL schema instead of guessing a data move;
- replaces an installed Banksia native service with the canonical OMS service and preserves whether it was running; and
- refuses to overwrite different OMS state.

The operation is idempotent. Repeating it verifies and reuses identical targets. It never deletes the source config, source database, provider environment, or `.banksia/` Task roots.

For a nondefault legacy config, name both paths:

```bash
oms migrate-from-banksia \
  --source-config /path/to/banksia/config.toml \
  --config /path/to/oms/config.toml
```

Use `--no-service` only when the controller has no native service or service replacement is being managed separately.

## Recover an accidental initialization

If `oms init` from `0.3.0` created canonical state before migration, the migration refuses to merge the two databases. Do not delete either database and do not use `oms db reset`.

First verify that no Tasks or other work were created in the new OMS database. Stop an installed OMS service, then preserve the accidental state under timestamped sibling directories:

```bash
oms service status --json
oms service uninstall

stamp=$(date -u +%Y%m%dT%H%M%SZ)
mv ~/.config/oh-my-subagents ~/.config/oh-my-subagents.before-banksia-migration-$stamp
mv ~/.local/share/oh-my-subagents ~/.local/share/oh-my-subagents.before-banksia-migration-$stamp

oms migrate-from-banksia
```

If `oms service status` says the service is not installed but port `18125` remains occupied, stop the foreground `oms serve` or older controller process that owns it before continuing. If both databases contain work, stop here: migration deliberately does not guess how to merge controller history.

## Rename environment overrides

Rename `BANKSIA_*` process settings to `OMS_*`, preserving suffixes and nested `__` separators:

```text
BANKSIA_CONFIG                    -> OMS_CONFIG
BANKSIA_CONTROLLER_WORKSPACE      -> OMS_CONTROLLER_WORKSPACE
BANKSIA_CODEX__ENABLED            -> OMS_CODEX__ENABLED
BANKSIA_RUNTIME__DEFAULT_PROVIDER -> OMS_RUNTIME__DEFAULT_PROVIDER
```

`0.3.x` accepts the old prefix with a warning. Equal old and new values are accepted; conflicting values fail before startup or mutation.

## Verify

```bash
oms config path
oms config show
oms db upgrade
oms service status --json
oms status --json
```

New Tasks use `.oms/t_<id>/`. Existing database rows that point to `.banksia/t_<id>/` continue to use those exact roots; do not rename or delete them.

## Roll back before new work

The migration copies state and leaves the Banksia source untouched, so executable rollback is possible before creating new OMS Tasks:

```bash
oms service uninstall
pipx uninstall oh-my-subagents
pipx install banksia==0.1.7
banksia service install --config /path/to/banksia/config.toml
```

Do not roll back after accepting new work into `oms.persistence` or `.oms/`; Banksia does not own those new records and roots. Never use database reset as a rename rollback.
