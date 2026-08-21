# ADR-0017: OpenClaw provider retirement

Status: Accepted

## Decision

Oh My Subagents supports Codex and Claude as its only active Task providers. OpenClaw is retired from Workflow authoring, provider configuration, CLI choices, adapter execution, Console controls, and the Node MCP transport surface.

The retired `openclaw` literal remains decodable only where existing immutable Workflow revisions, Task teams, Dispatches, events, and support readbacks need it. Historical controller facts are never rewritten as Codex or Claude. Existing Workflow revisions and drafts remain readable and editable, but a draft containing a retired provider selection is invalid until every affected Member selects Codex, Claude, or the installation default. It cannot be published or started.

At startup, Oh My Subagents pauses each nonterminal Task whose current Team still selects OpenClaw. The Task records `provider_retired`, closes current Dispatch authority, preserves all runtime rows and workspace files, and offers cancellation rather than Resume. The user repairs the Workflow and starts a new Run; Oh My Subagents never silently reroutes historical work.

The physical runtime schema continues to accept the `openclaw` literal and its historical Gateway route shape so existing databases remain verifiable without a reset or destructive rewrite. Active code cannot create a new OpenClaw Dispatch. This historical decoder is not a provider compatibility alias.

The user-configured `/node/mcp` compatibility projection is removed. Managed Codex and Claude Dispatches continue to use only the private `/_internal/node/mcp` binding.

## Configuration consequence

Fresh and rewritten configuration contains only `[codex]` and `[claude]` provider sections. Runtime loading ignores a stale `[openclaw]` section. A stale OpenClaw default is treated as unavailable provider intent and guided setup replaces it when the user selects Codex or Claude. Oh My Subagents does not stop, uninstall, or delete an external OpenClaw installation, Gateway, home, or credential store.

## Consequences

- public provider catalogs and Workflow authoring schemas contain Codex and Claude only;
- legacy Workflow readback identifies OpenClaw as retired and supplies a repair path rather than an integrity failure;
- support readbacks may still contain the historical provider literal;
- no database upgrade or reset is required for retirement; and
- steering or Member guidance remains a separate product change.
