# ADR-0019: OMS backend identity migration

Status: Accepted

## Decision summary

Oh My Subagents `0.3.0` completes the canonical backend rename. New installations, new Tasks, new prompt documents, provider bindings, and native service definitions use OMS identifiers. Released Banksia state remains readable through exact, bounded compatibility paths and an explicit `oms migrate-from-banksia` command.

This decision supersedes the `0.2.x` compatibility identities and migration deferral in [ADR-0018](ADR-0018-oh-my-subagents-identity-cutover.md). ADR-0018 remains the historical authority for the public `0.2.0` cutover.

## Canonical identities

The canonical `0.3.0` identities are:

- distribution `oh-my-subagents`, import package `oh_my_subagents`, and command `oms`;
- platform application directory `oh-my-subagents`, SQLite file `oms.persistence`, and provider environment `oms.env`;
- new Task container `.oms/`;
- prompt roots `oms_system` and `oms_dispatch_request`;
- managed bindings `oms_node`, `oms-node-managed`, and `oms_operator`;
- systemd unit `oh-my-subagents.service`;
- LaunchAgent label `io.github.ringlochid.oh-my-subagents`;
- Windows Scheduled Task `\Oh My Subagents\Controller`; and
- service logger `oh_my_subagents.service`.

One typed source contract defines the canonical and exact legacy identifiers. New implementation code does not construct either family ad hoc.

## Import and command compatibility

`src/oh_my_subagents/` is the sole backend implementation. The temporary `banksia` package contains only the compatibility module launcher needed by an installed `0.2.x` service definition. The `banksia` console entry point invokes the canonical CLI with its existing deprecation notice. No mirrored subpackages, module aliasing, or second implementation tree ship.

The compatibility launcher and command remain through `0.3.x`. Removal requires a later accepted decision and installed-upgrade evidence. Oh My Subagents does not claim a public Python-library compatibility API for `banksia.*` imports.

## Local-state migration

Fresh installations use the canonical platform directories immediately. An existing default installation is not migrated during ordinary startup. Mutating commands detect legacy default state and direct the user to:

```text
oms migrate-from-banksia
```

The migration:

1. rejects conflicting live canonical and legacy state;
2. stops the legacy service and proves controller/listener release;
3. creates a required database backup;
4. stages canonical configuration, SQLite state, and provider environment with owner-private permissions;
5. verifies database integrity, exact schema admission, configuration readback, and Task readback;
6. installs and starts the canonical native service;
7. verifies native ownership plus controller readiness; and
8. records completion while retaining legacy state for rollback.

One small private migration journal makes those steps idempotent across process or host interruption. The command supports a non-mutating dry run. It never merges two independent controller databases and never deletes legacy state.

Explicit custom configuration, data directories, database URLs, PostgreSQL database names, roles, and schemas remain where the user configured them. Fresh PostgreSQL configuration defaults to schema `oms`; an existing configured `banksia` schema stays admitted and is not renamed as part of the ordinary identity migration.

## Workspace and persisted protocol compatibility

Existing Tasks retain their persisted `.banksia/t_<id>/` roots and immutable file references. New Tasks use `.oms/t_<id>/`. Runtime, recovery, reset, file reference, and Command Run behavior derive the active layout from each Task's persisted root and accept only those two exact containers.

New prompt documents use the OMS roots. Parsers continue accepting exact committed Banksia roots; historical request bodies are never rewritten. Provider bindings use only the new OMS identity after the controller has quiesced for the upgrade. Pre-upgrade provider continuation is covered by installed-upgrade proof, not by exposing duplicate MCP servers.

## Native service replacement

Migration inspects both service identities, rejects two live controllers, stops the legacy identity, installs and starts the canonical identity, verifies readiness, and removes the legacy definition only after success. A failed switch removes the incomplete canonical definition and restores the captured legacy definition. No platform may run both controllers against one database.

## Historical compatibility

The following remain valid legacy evidence rather than canonical output:

- historical releases, tags, ADR text, and PyPI records;
- persisted `.banksia/` Task roots and file references;
- committed Banksia prompt documents and provider history;
- migration code, compatibility fixtures, and retained backups; and
- explicitly configured legacy PostgreSQL schemas or custom paths.

The repository identity gate allows Banksia strings only on those named surfaces. New runtime records, resources, defaults, definitions, and ordinary documentation must use OMS.

## Release proof

Release proof installs the real `0.2.0` distribution, creates controller state and a native service, upgrades to the candidate artifact, runs the migration, and verifies old Task readback, new Task creation, provider continuation, exactly one canonical service, readiness, interruption recovery, and rollback. Fresh-install and upgrade proof run on Linux, macOS, and Windows. SQLite and PostgreSQL retain their existing strong database lanes.
