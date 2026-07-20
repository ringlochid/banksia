# Run Docker PostgreSQL verification

Status: Current

Last verified: 2026-07-19

Use the repository lane when a change owns PostgreSQL behavior, schema or reset semantics, or the Docker verification shell.

```bash
make test-api-db
```

The target starts the isolated `postgres-test` service, recreates its test database, builds the API test image, runs the PostgreSQL-marked suite, then removes containers and volumes even when the suite fails.

## Verification

A pass proves the current database contract against PostgreSQL, including the dedicated-schema boundary and reset behavior covered by that suite. It does not validate a production database, preserve the test database, or authorize reset against a shared schema.

Use `make test-api-integration` for the repo-native SQLite and runtime-template integration groups. Do not run the PostgreSQL lane merely as a broader substitute for focused tests.
