# ADR-0016: Managed-provider Skill and MCP inheritance

Status: Accepted

## Decision

Codex and Claude Task Members may request one `extension_mode`: `inherit` or `isolated`. Omission resolves from the selected provider's machine-local configuration, whose shipped default is `inherit`.

The controller records requested mode, requested source, effective mode, and effective source on every managed Dispatch. `inherit` is effective only when the Dispatch's effective managed sandbox is `full_access` with network `allow`. Every narrower sandbox or network-denied Dispatch is automatically narrowed to `isolated`; authoring remains valid and support readback identifies the controller as the effective-mode source.

`inherit` covers enabled user and project Skills plus MCP servers already configured in the selected provider. It does not load project/workspace instructions, provider subagents, hooks, apps, memory, background workflows, or a general plugin system. Operator remains isolated.

After provider startup, the Dispatch records a sanitized observed inventory of Skill names and active external MCP server/tool names. It stores no Skill content, extension path, MCP arguments, credentials, or tool results. The inventory is support evidence, not a reproducible extension snapshot or controller authority.

Inherited extensions remain provider-native. Their activity may be absent from Oh My Subagents Activity and cannot replace Oh My Subagents controller operations, currentness, Checkpoints, or Result selection. Oh My Subagents continues to supply its exact Dispatch-scoped `oms_node` binding and validates that binding before the first model turn.

Codex Task effort accepts `max`; `ultra` remains excluded because it enables provider-owned proactive delegation outside Oh My Subagents' team controller. Native Codex settings not overridden by Oh My Subagents, including `service_tier = "fast"`, remain effective alongside explicit Workflow model and effort choices.

## Consequences

- Workflow Studio exposes the requested mode as an advanced provider choice and explains automatic narrowing without rejecting the draft.
- Machine-local `[codex]` and `[claude]` sections may set `extension_mode`.
- General provider plugins and Oh My Subagents-managed external-MCP authoring remain deferred.
- Changing the Dispatch schema follows Oh My Subagents' exact-admission and registered forward-upgrade contract.

## Provider implementation boundary

Codex uses mode-aware process and thread overlays: project instructions and non-Skill/MCP extensions remain disabled in both modes, while inherited mode does not disable enabled user or repository Skills or configured MCP servers. Claude loads user and project setting sources for Skill and MCP discovery, but its invocation-local settings disable filesystem hooks and configured plugins, and its environment suppresses `CLAUDE.md`, rules, memory, agents, apps, and other instruction-bearing features. Both adapters return only the sanitized startup inventory.

Claude Task execution uses the standard SDK mode for both API-key and personal subscription identities because bare mode skips Skill directory discovery and SDK hooks. The readiness check rejects endpoint-managed policy before standard mode starts. Claude Operator may still use bare mode for API-key identity because Operator is isolated and does not need Task filesystem guards or provider-native Skills.

The Claude Agent SDK is pinned at `0.2.128` because `0.2.127` fixed background SDK-MCP calls that could bypass `PreToolUse` hooks. The Codex SDK remains pinned to the current `0.144.4` release.
