# Current implementation

Status: Current

Last verified: 2026-07-19

This tree describes what AutoClaw ships now. It is implementation evidence, not target design. When this tree and target design disagree about future behavior, the target design wins.

## Start here

- [Runtime architecture](architecture/README.md) explains controller truth, dispatch progression, waits, watchdog recovery, and task-root files.
- [Shipped interfaces](interfaces/README.md) lists HTTP, MCP, CLI, definition, task-start, package, and reset behavior.
- [Operator procedures](operations/README.md) gives the short install and verification paths.

## Main facts

- The controller database is runtime truth. Provider output and support files are not.
- Runtime requests commit explicit source rows. Small after-commit handlers perform the independent follow-on work.
- Managed Codex and Claude dispatches receive a dispatch-scoped Node MCP binding. OpenClaw uses the explicit compatibility Node MCP surface.
- The API is loopback-only and uses peer, Host, and Origin checks instead of a global API key.
- SQLite is the default database. PostgreSQL is supported with a dedicated schema.
- Schema changes use reset, not legacy migration.

## Scope

Each maintained fact has one owner page. Deleted callback, session-key, provider-drain, bridge-worker, and file-backed control descriptions are no longer shipped behavior.
