# ADR-0014: Operator tool isolation and effect authority

Status: Superseded

Superseded by [ADR-0015: Minimal Operator agent](ADR-0015-minimal-operator-agent.md). This record remains as rationale for the rejected invocation/effect wrapper and is not target implementation authority.

## Decision summary

Banksia ships the first separate Operator through Claude Agent SDK with exactly the seventeen controller-owned Operator operations and no provider-native tools. Codex Operator support is deferred until its SDK can enforce the same global tool ceiling. Model-authored confirmation fields never authorize product effects; guarded effects use controller-owned proposals and exact, single-use confirmations.

## Context

Operator is a control-plane agent, not a Workflow Member or a second Task runtime. It needs durable conversation continuity and broad ordinary product coverage while remaining unable to read the host filesystem, run commands, inspect support data, or invent mutation authority.

The pinned Claude Agent SDK can remove all built-in tools, load no external settings/Skills/Plugins, and expose only an invocation-scoped in-process MCP server. The pinned Codex SDK cannot globally allowlist model-visible tools: its tool builder retains planning and MCP resource helpers and may retain file tools even when shell, web, apps, and related features are disabled. An OpenAI Responses or Agents implementation could provide a closed function-tool set, but it would add a separately authenticated and billed OpenAI API provider rather than implement the configured Codex SDK path.

The imported Operator MCP surface also allowed the model to submit `confirmed`. That treats the actor requesting an effect as the source of its own authority and cannot support an accountable product boundary.

## Decision

- Claude Agent SDK is the supported baseline Operator provider.
- Operator provider selection is explicit and never inherits Task runtime or Workflow Member provider choices.
- Selecting Codex returns `operator_codex_tool_isolation_unsupported` and starts no provider work.
- A future Codex adapter must prove the exact same model-visible tool ceiling; Banksia does not weaken the ceiling or maintain a provider fork.
- The provider receives a fresh invocation-scoped in-process MCP binding over the exact seventeen operations. The browser uses product HTTP only.
- Reversible Workflow draft create/open/edit effects may execute from the Operator request and return receipts/Undo.
- Publish, discard, Undo, Task start/control, Human Request response/cancel, and Command cancellation always become controller-owned proposals when requested by the model.
- Guarded schemas contain no `confirmed` input. A single-use confirmation is bound to conversation, stored payload, and current ETag/action guard.
- Every mutation is journaled before execution. An ambiguous post-commit crash is reconciled or marked indeterminate; it is never blindly replayed.

The exact routes, records, transitions, and recovery behavior live in the [Operator conversation contract](../design/appendices/operator-conversation-contract.md).

## Consequences

- Banksia can make a truthful no-host-filesystem and exact-tool claim for the shipped Operator.
- Users configured only for Codex see an explicit unsupported explanation instead of a silent fallback or a weaker security boundary.
- Adding an OpenAI API Operator later is a distinct provider decision with its own authentication, billing, configuration, adapter, and proof.
- Operator conversation persistence stays small and separate from Task runtime records.
- Some accepted product mutations may be indeterminate after a narrow crash window until their owning product service supports correlated exactly-once receipts. The UI reports that uncertainty rather than replaying.

## Alternatives rejected

### Permit harmless Codex utility tools

Rejected because provider-native planning, resource, and file tools make the tool boundary provider-dependent and invalidate the exact catalog claim.

### Treat `confirmed: true` from the model as authority

Rejected because the effect requester cannot attest its own user authority.

### Add OpenAI Responses or Agents SDK under the Codex name

Rejected because that introduces a different authentication, billing, model, dependency, and conversation surface and would mislabel it as Codex.

### Replay every stale executing effect

Rejected because a process may fail after the owning product transaction commits; replay can duplicate consequential work.
