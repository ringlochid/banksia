# Claude Agent SDK adapter

Status: Target

This page maps the supported Claude Agent SDK into the minimal AutoClaw provider adapter.

## External basis

- The Agent SDK exposes Claude Code's tools, sessions, permissions, hooks, and MCP integration: [Claude Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview).
- `ClaudeSDKClient` supports multi-turn work, resume, and interruption: [Claude Agent SDK Python reference](https://code.claude.com/docs/en/agent-sdk/python).
- The SDK supports programmatic Streamable HTTP MCP servers and server-scoped allowed tools: [Claude Agent SDK MCP](https://code.claude.com/docs/en/agent-sdk/mcp).
- Native user questions and permission callbacks require an explicit embedding policy: [Claude Agent SDK user input](https://code.claude.com/docs/en/agent-sdk/user-input).
- The current pinned SDK may use a Claude plan through native Claude Code login: [Use the Claude Agent SDK with your Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan).

## Adapter mapping

One `DispatchStartRequest` issues one new or continuity-assisted Claude query. Session IDs, `ClaudeSDKClient` instances, response iterators, hook state, and child-process handles stay private to the adapter.

`StartAccepted` reflects the pinned SDK acceptance boundary. SDK messages, native tool/hook events, token streams, final responses, and provider terminal state never update controller truth.

The adapter delivers the request's exact instruction lane through the supported system-instruction overlay and the exact input lane as the dispatch query. It does not concatenate, summarize, or rerender them.

## Per-dispatch correctness overlay

Each start supplies:

- exact task cwd;
- explicit supported native user/project/local setting sources;
- the native `claude_code` system-prompt preset plus current AutoClaw instructions;
- current input bytes;
- one programmatic managed Streamable HTTP MCP server with bearer authorization;
- a server-scoped role tool allowlist;
- noninteractive native question/permission handling;
- resolved native-tool/network/sandbox policy; and
- optional sparse model/effort overrides.

The MCP configuration is constructed for that invocation only. It is never written to Claude user/project configuration and is not reused across dispatch credentials.

## Tool exposure and authority

The server-scoped allowlist matches the binding ceiling; worker sessions do not discover parent/root operations. Claude's tool policy remains defense in depth. Binding authentication and fresh controller reads remain authoritative.

`AskUserQuestion` and unresolved approval callbacks are denied or resolved under the declared machine policy. Intentional human waits use AutoClaw Node MCP and its controller capability.

## Continuity

A Claude session may be resumed only when the pinned SDK can receive both complete request lanes and the fresh MCP binding. Otherwise a new session is started.

Session continuity is optional and non-authoritative. It is not generic persisted controller state, is not Node authentication, and may be discarded on restart.

## Stop, interrupted-response handling, and cleanup

When supported, `stop(dispatch_id)` makes one bounded interrupt attempt. It returns a successful result only at the pinned SDK's documented stop boundary; runtime nevertheless proceeds on unsupported, failed, or timed-out stop.

If the SDK requires the interrupted response to be consumed before a client can be reused, the adapter never reuses that client prematurely. It may discard the client or consume the response privately in resource cleanup. Runtime does not wait for that drain, provider final response, or client reuse before creating/retrying a dispatch.

Lifecycle resources belong to the main FastAPI lifespan. Binding revocation precedes adapter cleanup, and cleanup cannot rewrite controller state.

## Failure classification

The adapter normalizes configuration, authentication, connection, unavailable, timeout, rejection, unsupported, and uncertain-acceptance failures. Ambiguous acceptance triggers the generic fresh-binding stop-and-retry sequence on the same D2.

Raw SDK messages, provider output, credentials, environment values, binding material, and session IDs are excluded from controller error storage and ordinary logs.

## Authentication boundary

The target product integration accepts Claude subscription login or an Anthropic API key. Subscription login is delegated to the SDK-bundled Claude Code CLI, subject to the unresolved Anthropic approval gate owned by [Claude support and compatibility](../../interfaces/claude-support-and-compatibility.md). API-key input is kept only in AutoClaw's owner-only provider-secret environment as `ANTHROPIC_API_KEY`. The adapter inherits the effective provider environment and never returns or logs credential contents. The bounded check reads native authentication status without creating a query; model reachability remains unproved until a dispatch starts.

## Required conformance

- exact two-lane delivery;
- programmatic per-dispatch MCP attachment and role allowlist;
- no persistent native config mutation;
- no hidden native question/approval wait;
- acceptance/interrupt behavior for the pinned SDK;
- safe interrupted-client disposal without a runtime drain gate;
- same-D2 retry with identical request bytes and a fresh binding; and
- no provider event/output/final effect on controller state.

## Related contracts

- [Minimal provider adapter contract](../adapter-contract.md)
- [Managed Node MCP binding](../managed-node-mcp-binding.md)
- [Provider CLI and check](../../interfaces/provider-cli-and-check.md)
- [Claude support and compatibility](../../interfaces/claude-support-and-compatibility.md)
- [Human request and approval](../../interfaces/human-request-and-approval-contract.md)
