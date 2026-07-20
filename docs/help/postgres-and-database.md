# Postgres and database problems

SQLite is the default local database. Postgres requires the package extra and an explicit database URL.

```bash
pipx install "autoclaw[postgres]"
autoclaw init --database-url postgresql+asyncpg://user:password@127.0.0.1:5432/autoclaw
```

Use real local credentials and keep them out of reports.

If `/readyz` fails, compare the database URL used by your shell with the one used by the managed service. Confirm the Postgres server is reachable, the database exists, and the installed environment includes the async driver.

`autoclaw status --json` and `autoclaw config show --json` are safe first reads. Do not use destructive database commands as generic repair. Preserve the database and exact error until you understand whether the failure is configuration, connectivity, schema compatibility, or service environment.

Maintainers can use the [database support reference](../reference/maintainers/distribution-and-database-support-matrix.md) for supported verification lanes.
