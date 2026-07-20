# Use PostgreSQL

Install AutoClaw with the `postgres` extra, then configure a dedicated non-system schema:

```toml
[database]
url = "postgresql+asyncpg://autoclaw:secret@127.0.0.1:5432/autoclaw"
postgres_schema = "autoclaw"
```

Initialize or verify the exact schema:

```bash
autoclaw init
autoclaw db upgrade
autoclaw serve
```

`db upgrade` does not migrate an incompatible database. Use destructive reset only when the configured schema is exclusively owned by AutoClaw and its data may be deleted.

Repository verification is self-contained:

```bash
make test-api-db
```

The test lane uses the isolated `postgres-test` service and `infra/testing/api/Dockerfile`, then removes its containers and volumes. It is not a production deployment image or a reset procedure for an existing database.
