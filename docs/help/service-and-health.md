# Service and health problems

`/healthz` proves the process is answering. `/readyz` also checks controller database readiness.

## Check the foreground path

```bash
autoclaw serve
```

In another shell:

```bash
curl -sS http://127.0.0.1:18125/healthz
curl -sS http://127.0.0.1:18125/readyz
```

If this works, the application and active config are usable.

## Check the managed service

```bash
autoclaw service status --json
autoclaw service render
```

The managed service lane uses a Linux user service. The generated unit selects one config file; that TOML file owns the data directory, database URL, and port. Its canonical sibling `autoclaw.env` file contains only supported provider credentials. Rerun `autoclaw service install` to reconcile an older generated unit after upgrading AutoClaw; it preserves that private file and restores owner-only permissions. Installation rejects a busy target owned by another process, but an already-running named AutoClaw service can reclaim its own configured target during reconciliation.

If start or restart fails, AutoClaw prints bounded `systemctl` output and the exact inspection commands. You can also run them directly:

```bash
systemctl --user status autoclaw.service --no-pager
journalctl --user -u autoclaw.service -n 50 --no-pager
```

Remove obsolete settings named by validation errors from the selected config or unsupported assignments from `autoclaw.env`, then rerun `autoclaw service install`. Validation output names the field without echoing its rejected value. `--debug` works before or after the leaf command, for example `autoclaw service start --debug`; parse mistakes remain concise.

`autoclaw service status` reports systemd process state. Its `healthy` JSON field is `null` because the command does not make an HTTP request. Use `/healthz` and `/readyz` when you need API health and database-readiness proof.

If health succeeds and readiness fails, continue with [Postgres and database problems](postgres-and-database.md).
