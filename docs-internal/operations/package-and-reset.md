# Package and reset

Status: Reference

This page owns distribution contents, installed verification, exact schema admission, and destructive reset.

## Distribution boundary

`pyproject.toml` is the package contract. The distribution, Python package, and console command are `banksia` at version `0.1.6`, and Python 3.12 or newer is required.

The built wheel contains:

- the `banksia` backend and public entry point;
- the packaged Console assets;
- provider-neutral Starter Workflow resources;
- Task-member and Operator prompt assets; and
- the Banksia user-service template.

The native desktop host contract is:

- supported Linux distributions with the required Python and user systemd facilities, including WSL2 when its Linux filesystem/runtime capabilities pass the same admission checks; and
- macOS 13 or newer through the current-user LaunchAgent lane; and
- Windows 11 x64 on a local NTFS volume through the current-user Task Scheduler lane.

Windows UNC, network, device, non-NTFS, and reparse-point workspace paths are outside the native host contract. WSL2 remains the Linux lane. Provider routes on supported controller hosts remain governed by their pinned official integrations rather than a second Banksia OS allowlist. Host support additionally requires Banksia's workspace, private-path, Command Run, install, reset, and service proof; installing a provider wheel alone is not platform proof.

It contains no environment file, provider credential, Python cache, ignored research, source-only test fixture, request-pair file, or removed compatibility entry point.

`make package-build` builds and stages the Console, creates wheel and source distribution artifacts, and verifies their identity and contents. `make package-verify` rebuilds those artifacts and runs the complete installed candidate proof in a trapped temporary directory outside the repository. The verifier rejects an in-repository workspace and proves that the repository Git-exclude file remains byte-identical. A bare `python -m build` does not prove the packaged Console or installed behavior.

The installed-distribution verifier installs the wheel into a fresh virtual environment outside the repository and exercises imports, CLI, initialization, exact schema setup, provider configuration, Workflow bootstrap, Task start, server health/readiness, restart, and the isolated user-service command path.

## Schema admission and forward upgrade

Startup and initialization create the schema only when the configured database is genuinely empty. Otherwise they compare the complete registered metadata contract with the selected SQLite database or dedicated PostgreSQL schema. Missing, unexpected, or changed tables, columns, keys, constraints, indexes, defaults, and computed expressions stop admission without issuing DDL. The CLI and raw foreground/background startup failure direct the operator to run `banksia db upgrade` with the same configuration before considering destructive reset.

`banksia db upgrade` applies only an explicitly registered, sequential Banksia schema upgrade whose complete starting-schema differences match the expected predecessor exactly. An unknown, skipped, partially changed, locally modified, or already-corrupt schema is never guessed or repaired. Every supported upgrade runs transactionally where the database supports transactional DDL, ends with the same complete exact-schema verifier used at startup, and preserves controller rows unless its named contract explicitly says otherwise.

Before an eligible upgrade changes an existing database, Banksia must create a backup or abort without DDL. SQLite uses an adjacent owner-private backup through SQLite's online backup facility and requires a successful integrity check. PostgreSQL uses `pg_dump` to create a nonempty custom-format archive of the dedicated Banksia schema under the configured data directory. The CLI reports the resulting path. PostgreSQL additionally keeps upgrade DDL in one transaction.

The first supported forward upgrade adds the Attempt watchdog replacement budget. Existing Attempts receive `0`, which grants one fresh recovery budget at the upgrade boundary, while historical Dispatches and every other controller record remain unchanged.

The next supported upgrade widens the closed Task Event type constraint for `member_steered` without rewriting event or Dispatch rows. A database that still needs both registered changes is recognized as one exact combined predecessor and receives both changes under one backup and verification transaction.

The next supported upgrade widens Command Run terminal exit codes to an unsigned-compatible 32-bit storage lane. PostgreSQL changes the column to `BIGINT` while preserving every Command Run row. SQLite `INTEGER` already stores signed 64-bit values, so existing SQLite databases need no table rewrite and remain exact under the SQLite type-affinity contract.

Banksia has no AutoClaw or other legacy-state import path. Supported Banksia schema upgrades do not introduce compatibility aliases, dual runtime truth, or acceptance of nonexact schemas.

After schema creation or verification, bootstrap transactionally validates and publishes the packaged Starter Workflow set. Identical package-owned content is idempotent, and reseeding never replaces a user-authored current revision.

## Destructive reset

`banksia db reset` is explicit destructive replacement:

- SQLite requires a configured file-backed database, rejects a symlinked or nonregular database, and removes only that file plus known regular/symlink sidecars before recreating the schema.
- PostgreSQL drops and recreates only the configured dedicated non-system schema and requires operator-assured exclusive ownership.
- Both backends recreate the exact schema and reseed Starter Workflows.

Before reset deletes a controller-owned Task root or replaces an existing database/schema, Banksia must create the same backup used by forward upgrade and report its path. Backup failure is a hard stop. A nonexistent SQLite database or PostgreSQL schema has nothing to preserve, so reset may initialize it without creating an empty backup artifact. PostgreSQL reset and upgrade therefore require a compatible `pg_dump` client on the controller host.

Reset may delete controller-owned Task roots recorded inside the configured data boundary. It deliberately preserves accepted workspace Task directories matching `.banksia/t_<id>/`; shared user workspaces and their loose files are never recursively deleted by database reset.

## Managed background service

`banksia service install|start|stop|restart|status|uninstall|logs` operates one per-user Banksia background service from the selected TOML file and its canonical sibling `banksia.env`:

- Linux uses a systemd user service;
- macOS uses a current-user LaunchAgent under `~/Library/LaunchAgents`; and
- Windows uses `\Banksia\Controller`, a current-user Scheduled Task with an interactive-token logon trigger and least-privilege run level.

Native definitions contain only the exact interpreter, `banksia serve`, selected config path, and bounded service-log path. They contain no provider credential, password, shell wrapper, or elevated/root account. The shared CLI reports definition/startup state plus bounded controller health/readiness rather than presenting systemd and launchd process strings as equivalent truth. Platform-specific raw state is debug detail.

Service rendering and replacement are atomic and reject a pre-existing non-regular target. Installation is idempotent. The native manager owns definition and lifecycle operations; a small coordinator owns API readiness. Installation and verification must stay isolated, and release proof must not install or mutate a real user's service outside its disposable native lane.

Schema and runtime recovery details are owned by [Recovery and observability](recovery-and-observability.md).
