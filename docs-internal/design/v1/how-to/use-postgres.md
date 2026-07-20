# Use Postgres in the design target

Status: Target

This page defines the frozen stronger verification and concurrency lane.

## Package path

Install the Postgres-enabled package:

```bash
pipx install "autoclaw[postgres]"
```

## Runtime configuration

Set the exact DB environment variable:

```bash
AUTOCLAW_DATABASE_URL=postgresql+asyncpg://autoclaw:autoclaw@127.0.0.1:5432/autoclaw
```

## Product procedure

1. Install the Postgres extra
2. Set `AUTOCLAW_DATABASE_URL`
3. Run onboarding: `autoclaw onboard`
4. Run migrations: `autoclaw db upgrade`
5. Confirm health: `autoclaw doctor`
6. Verify the OpenClaw integration side without writing: `autoclaw openclaw check`
7. Start the managed service: `autoclaw service start`

`autoclaw init` remains available as a low-level AutoClaw-local bootstrap primitive for automation, tests, and package smoke. `autoclaw serve` remains available as a foreground debug runner and as the process a service manager may execute.

## Strong verification lane

Use the stronger Docker-backed verification path:

```bash
make docker-up
make test-api-db
make docker-down
```

## Lane rule

Postgres + Docker is the stronger verification lane and the required release proof path for DB-backed behavior.
