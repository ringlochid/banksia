# Current packaging, install, and reset

Status: Current

Last verified: 2026-07-19

`pyproject.toml` is the package contract. AutoClaw requires Python 3.12 or newer and installs the `autoclaw` console command.

## Distribution contents

The wheel and source distribution include:

- API and runtime Python packages
- packaged role, policy, and workflow seeds
- shared and role-family instruction assets
- the built web console
- the systemd user-service template

They must not include environment files, Python cache files, old callback or session-key assets, or old prompt files.

`make package-build` rebuilds the console assets before building the wheel and source distribution.

## Installed proof

`scripts/testing/verify_installed_distribution.py` checks both artifacts and installs the wheel into a fresh virtual environment outside the repository without `PYTHONPATH`. It exercises packaged resources, application lifespan, foreground health/readiness and shutdown, SQLite upgrade/reset, provider configuration and default selection, definition import, task start, and the complete user-service command sequence inside an isolated fake home.

This proof catches source-tree imports and missing package data that editable installs cannot catch.

## User service

Linux installations may use the shipped systemd user service. `autoclaw service install` writes or reconciles the selected config and its canonical sibling `autoclaw.env` path in the generated unit and can start it. The selected TOML file remains the only data-directory source. Reconciliation preserves the provider-secret file and enforces owner-only permissions. The render, start, stop, restart, status, uninstall, and root `make install-user-service` surfaces use the same managed-service support. Lifecycle commands operate on the named unit and do not accept a misleading config override. Service status reports systemd process state; API health remains `not checked` until an HTTP health probe is actually run. A failed lifecycle command preserves bounded `systemctl` detail and reports the exact status, journal, and reconciliation commands.

The repository installer invokes `autoclaw init --non-interactive` with resolved paths so automation never waits for terminal input.

The service still binds only to loopback.

## Exact schema rule

Startup and `autoclaw db upgrade` create the schema only when the database is genuinely empty. Otherwise they require an exact current schema. A mismatch stops with guidance to run `autoclaw db reset`; no legacy migration, repair, or backup is attempted.

Reset is destructive:

- SQLite reset accepts only the configured file-backed database, rejects a symbolic-link database, and replaces that file and its known sidecars
- PostgreSQL reset drops and recreates only the configured dedicated schema and requires operator-assured exclusive ownership
- both modes recreate the exact schema, reseed packaged definitions, and remove controller task roots inside the configured data boundary
- neither mode deletes an external workspace

## Evidence

- `pyproject.toml`
- `apps/api/src/autoclaw/interfaces/cli/bootstrap/database.py`
- `apps/api/src/autoclaw/platform/managed_services/`
- `scripts/install-systemd-user.sh`
- `scripts/testing/verify_installed_distribution.py`
- `apps/api/tests/integration/runtime_schema_contract/`
- `apps/api/tests/integration/bootstrap/`
