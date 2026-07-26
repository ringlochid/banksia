# Package and reset

Status: Reference

This page owns distribution contents, installed verification, exact schema admission, and destructive reset.

## Distribution boundary

`pyproject.toml` is the package contract. The distribution is `banksia-ai`, the Python package and console command are `banksia`, and Python 3.12 or newer is required.

The built wheel contains:

- the `banksia` backend and public entry point;
- the packaged Console assets;
- provider-neutral Starter Workflow resources;
- Task-member and Operator prompt assets; and
- the Banksia user-service template.

It contains no environment file, provider credential, Python cache, ignored research, source-only test fixture, request-pair file, or removed compatibility entry point.

`make package-build` is the complete candidate command: it builds and stages the Console, builds wheel and source distribution artifacts, and verifies package data. A bare `python -m build` does not prove the packaged Console or installed behavior.

The installed-distribution verifier installs the wheel into a fresh virtual environment outside the repository and exercises imports, CLI, initialization, exact schema setup, provider configuration, Workflow bootstrap, Task start, server health/readiness, restart, and the isolated user-service command path.

## Exact schema admission

Startup and `banksia db upgrade` create the schema only when the configured database is genuinely empty. Otherwise they compare the complete registered metadata contract with the selected SQLite database or dedicated PostgreSQL schema. Missing, unexpected, or changed tables, columns, keys, constraints, indexes, defaults, and computed expressions stop admission with guidance to run `banksia db reset`.

`db upgrade` retains its conventional command name but does not migrate or repair a nonexact schema. Banksia has no legacy-state import path.

After schema creation or verification, bootstrap transactionally validates and publishes the packaged Starter Workflow set. Identical package-owned content is idempotent, and reseeding never replaces a user-authored current revision.

## Destructive reset

`banksia db reset` is explicit destructive replacement:

- SQLite requires a configured file-backed database, rejects a symlinked or nonregular database, and removes only that file plus known regular/symlink sidecars before recreating the schema.
- PostgreSQL drops and recreates only the configured dedicated non-system schema and requires operator-assured exclusive ownership.
- Both backends recreate the exact schema and reseed Starter Workflows.

Reset may delete controller-owned Task roots recorded inside the configured data boundary. It deliberately preserves accepted workspace Task directories matching `.banksia/t_<id>/`; shared user workspaces and their loose files are never recursively deleted by database reset.

## Managed service

The packaged Linux user-service template runs the canonical `banksia` command with the selected TOML file and its canonical sibling `banksia.env`. Service render/install/start/stop/restart/status/uninstall commands use the same machine-local configuration. Installation and verification must stay isolated; release proof must not install or mutate a real user's service.

Schema and runtime recovery details are owned by [Recovery and observability](recovery-and-observability.md).
