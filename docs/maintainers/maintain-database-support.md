# Maintain database support

Use this guide for schema, persistence, reset, registry, SQLite, or PostgreSQL changes.

## Supported posture

SQLite is the default local database. The optional `postgres` package extra adds `asyncpg`; a PostgreSQL URL still must be configured explicitly.

AutoClaw has one exact current schema. Startup and `autoclaw db upgrade` create it only for an empty database. Any incompatible non-empty schema fails with `autoclaw db reset` guidance. There is no legacy migration, repair, or backup lane.

## Reset boundary

Reset is destructive and must use the configured database:

- SQLite replaces the configured regular file and known sidecars; symbolic-link database paths are rejected.
- PostgreSQL drops and recreates only the configured dedicated non-system schema. The operator must ensure exclusive ownership.
- Both modes recreate the exact schema, reseed definitions, and remove controller task roots inside the configured data directory.
- Neither mode deletes an external workspace.

## Proof

Use focused tests while iterating, then run the applicable lanes:

```bash
make check-api
make test-api-integration
make test-api-db
```

Add the focused E2E lane when the change can affect launched workflows. PostgreSQL proof uses `infra/testing/api/Dockerfile`; it must not become a production image contract.

Review portable constraints, foreign keys, conditional writes, JSON behavior, schema ownership, reseeding, and `/readyz`.
