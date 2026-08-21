# Migrate from Banksia

Oh My Subagents `0.2.0` changes the distribution and primary command without moving controller truth. Existing configuration, database rows, accepted Task roots, provider credentials, and native service identity remain valid.

## Before changing the installation

Read the passive current state and keep the output until the replacement is verified:

```bash
banksia --version
banksia config path
banksia status --json
banksia service status --json
```

Do not reset the database or remove `.banksia/` directories. They are stable storage protocols, not stale branding.

## Replace the isolated application

Stop the existing controller before replacing its executable environment:

```bash
banksia service stop
pipx uninstall banksia
pipx install oh-my-subagents
```

The new distribution provides `oms` as the canonical command and a temporary `banksia` compatibility command. Confirm that both resolve to `0.2.0`:

```bash
oms --version
banksia --version
```

The compatibility command writes a deprecation notice to standard error. Commands using `--json` still emit one valid JSON document on standard output.

## Rename environment overrides

Rename `BANKSIA_*` settings to `OMS_*`, preserving the suffix and nested `__` separators. For example:

```text
BANKSIA_CONFIG                    -> OMS_CONFIG
BANKSIA_CONTROLLER_WORKSPACE      -> OMS_CONTROLLER_WORKSPACE
BANKSIA_CODEX__ENABLED            -> OMS_CODEX__ENABLED
BANKSIA_RUNTIME__DEFAULT_PROVIDER -> OMS_RUNTIME__DEFAULT_PROVIDER
```

The `0.2.x` line still accepts the old prefix with a warning. If both names supply the same setting, equal values are accepted and different values fail before startup or mutation.

## Reconcile and verify the service

Use the same configuration path reported before replacement:

```bash
oms service install --config /path/to/config.toml
oms service status --config /path/to/config.toml --json
oms status --config /path/to/config.toml --json
```

Service installation replaces the executable in the one existing per-user definition. It does not delete configuration, the database, provider credentials, logs, or workspace Task roots. Verification requires an installed current definition and a ready loopback controller.

## Roll back before new work begins

The schema and storage formats are unchanged in `0.2.0`, so the executable replacement is reversible before new work begins:

```bash
oms service stop
pipx uninstall oh-my-subagents
pipx install banksia==0.1.7
banksia service install --config /path/to/config.toml
```

After rollback, confirm `banksia service status --json` and `banksia status --json`. Never use database reset as a rename rollback.
