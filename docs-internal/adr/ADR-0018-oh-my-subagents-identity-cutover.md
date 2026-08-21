# ADR-0018: Oh My Subagents identity cutover

Status: Accepted

## Decision summary

Banksia is renamed publicly to **Oh My Subagents**, abbreviated **OMS**. Release `0.2.0` uses the PyPI distribution `oh-my-subagents` and the canonical `oms` command. The existing `banksia` Python import, workspace layout, database identifiers, and managed Node binding remain stable protocol identities for this release. Compatibility is explicit, observable, and subordinate to the OMS product identity.

This decision supersedes only the released-identity list in [ADR-0013](ADR-0013-banksia-target-and-clean-break.md). ADR-0013's runtime, authority, workspace, clean-break, and recovery decisions remain accepted.

## Context

The public Banksia name obscures the product's narrow purpose: turning ad-hoc parent and subagent delegation into durable, supervised, accountable work. The new name states that category directly.

Some old names are presentation only. Others are installed or durable interfaces:

- `banksia` is the import package used throughout the implementation and by integrations;
- `.banksia/t_<id>/` paths are stored in accepted Assignments, Checkpoints, prompts, and file references;
- `banksia.persistence` and the default PostgreSQL `banksia` schema may contain the only controller truth for active or completed Tasks;
- `banksia_node` and `mcp__banksia_node__*` identify a private Dispatch-scoped provider binding; and
- native service definitions and `BANKSIA_*` environment variables may outlive one executable installation.

Replacing all of those strings as branding would create data, startup, and recovery risk without improving the ordinary user experience.

## Decision

### Canonical released identity

The released identities from `0.2.0` are:

- product name **Oh My Subagents**;
- abbreviation **OMS**;
- PyPI distribution `oh-my-subagents`;
- canonical console command `oms`;
- canonical environment prefix `OMS_`;
- Console package `@oh-my-subagents/console`; and
- repository name `oh-my-subagents` when the external cutover is authorized.

The package version continues the existing repository history at `0.2.0`. It does not restart at `0.1.0` merely because the PyPI distribution name changes.

### Stable compatibility protocols

The following remain canonical implementation or storage protocols in `0.2.x`:

- Python import package `banksia`;
- workspace container `.banksia/` and accepted Task-root paths;
- SQLite filename `banksia.persistence`;
- configured PostgreSQL schema values, including the default `banksia` value;
- private MCP identities `banksia_node` and `banksia-node-managed`;
- committed prompt XML roots `banksia_system` and `banksia_dispatch_request`; and
- existing native service identifiers while an installed definition is being migrated.

These names are not shown as the current product brand in ordinary UI, CLI help, prompts, or documentation. Maintainer reference may name them when exact protocol lookup matters.

### CLI compatibility

The `oh-my-subagents` distribution installs both `oms` and `banksia`. `oms` is canonical. Invoking `banksia` emits one concise deprecation notice to standard error and then runs the same command implementation. Machine-readable JSON output remains valid JSON on standard output.

The compatibility command remains through the `0.2.x` line. Its removal requires a new accepted decision and evidence that supported upgrade paths no longer depend on it.

### Configuration compatibility

`OMS_CONFIG` selects the configuration file, and `OMS_*` supplies canonical setting overrides. Existing `BANKSIA_*` variables remain accepted during `0.2.x` with a visible warning on interactive CLI startup.

If both prefixes supply the same setting:

- equal values are accepted; and
- different values fail before initialization, provider contact, service mutation, or runtime startup.

The implementation must not silently prefer one conflicting value. Persisted TOML keys do not change because they are product concepts rather than brand-prefixed identifiers.

### Local data and native service migration

The `0.2.x` runtime continues using the existing platform application directory and database by default. This preserves upgrades without copying controller truth between two implicit locations.

`oms service install` reconciles the new executable into the one existing per-user service definition. It must stop before mutation when another live controller owns the configured listener or when the selected configuration and installed definition disagree. Service replacement preserves configuration, provider credentials, database, logs, and accepted workspace Task roots.

Renaming native service identifiers or the platform application directory is a separate migration. It requires backup, rollback, clean-host proof, and exact one-controller verification before a later release may adopt it.

### Historical and external state

Historical releases, Git tags, immutable records, and ADR context keep the Banksia name. The old PyPI project is not deleted. A separately authorized final Banksia transition release may direct users to `oh-my-subagents` only after the new distribution has passed a real-index installation check.

GitHub rename, PyPI upload, tags, releases, and announcements are external publication steps. Local implementation and verification do not authorize them.

## Consequences

- Ordinary users see one product identity and one canonical command immediately.
- Existing configuration, Tasks, file references, provider continuations, and service data remain recoverable.
- The distribution and import package intentionally differ; installed verification must assert both identities.
- Compatibility behavior is tested and documented instead of hidden in ad-hoc fallback readers.
- Exact old-name searches require a maintained allowlist separating durable protocols and historical records from stale branding.
