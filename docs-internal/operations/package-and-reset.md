# Package and reset

Status: Reference

This page owns distribution contents, installed verification, exact schema admission, and destructive reset.

## Distribution boundary

`pyproject.toml` is the package contract. The distribution, Python package, and console command are `banksia` at version `0.1.2`, and Python 3.12 or newer is required.

The built wheel contains:

- the `banksia` backend and public entry point;
- the packaged Console assets;
- provider-neutral Starter Workflow resources;
- Task-member and Operator prompt assets; and
- the Banksia user-service template.

The native desktop host contract is:

- supported Linux distributions with the required Python and user systemd facilities, including WSL2 when its Linux filesystem/runtime capabilities pass the same admission checks; and
- macOS 13 or newer through the current-user LaunchAgent lane.

Native Windows controller/runtime support is deferred. Provider routes on supported controller hosts remain governed by their pinned official integrations rather than a second Banksia OS allowlist. Host support additionally requires Banksia's workspace, private-path, Command Run, install, reset, and service proof; installing a provider wheel alone is not platform proof.

It contains no environment file, provider credential, Python cache, ignored research, source-only test fixture, request-pair file, or removed compatibility entry point.

`make package-build` builds and stages the Console, creates wheel and source distribution artifacts, and verifies their identity and contents. `make package-verify` rebuilds those artifacts and runs the complete installed candidate proof in a trapped temporary directory outside the repository. The verifier rejects an in-repository workspace and proves that the repository Git-exclude file remains byte-identical. A bare `python -m build` does not prove the packaged Console or installed behavior.

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

## Managed background service

`banksia service install|start|stop|restart|status|uninstall|logs` operates one per-user Banksia background service from the selected TOML file and its canonical sibling `banksia.env`:

- Linux uses a systemd user service;
- macOS uses a current-user LaunchAgent under `~/Library/LaunchAgents`.

Native definitions contain only the exact interpreter, `banksia serve`, selected config path, and bounded service-log path. They contain no provider credential, password, shell wrapper, or elevated/root account. The shared CLI reports definition/startup state plus bounded controller health/readiness rather than presenting systemd and launchd process strings as equivalent truth. Platform-specific raw state is debug detail.

Service rendering and replacement are atomic and reject a pre-existing non-regular target. Installation is idempotent. The native manager owns definition and lifecycle operations; a small coordinator owns API readiness. Installation and verification must stay isolated, and release proof must not install or mutate a real user's service outside its disposable native lane.

Schema and runtime recovery details are owned by [Recovery and observability](recovery-and-observability.md).
