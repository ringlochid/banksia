# Codex app-server adapter

Status: Target

This page maps the supported Codex SDK/app-server runtime into the minimal AutoClaw provider adapter.

## External basis

- Codex app-server exposes thread/turn control and interruption: [Codex app-server](https://developers.openai.com/codex/app-server/).
- Codex owns ChatGPT/API authentication and its native credential home: [Codex authentication](https://developers.openai.com/codex/auth/).
- Codex owns normal user/project model, reasoning, sandbox, approval, instruction, skill, MCP, and compaction settings: [Codex configuration reference](https://developers.openai.com/codex/config-reference/).
- The supported SDK/runtime shape is pinned and release-tested: [Codex SDK](https://developers.openai.com/codex/sdk/).

## Adapter mapping

One `DispatchStartRequest` starts one new or continuity-assisted Codex turn. Thread IDs, active turn handles, JSON-RPC connection state, and child-process handles stay private to this adapter.

`StartAccepted` is returned on the documented app-server acceptance boundary. Streamed items, output text, tool events, token usage, turn completion, and final response are discarded for controller progression.

The adapter does not render or concatenate prompts. It delivers the exact `instructions` and `input` lanes from the request through the pinned supported fields.

## Per-dispatch correctness overlay

Each start applies an ephemeral overlay containing:

- exact task cwd;
- current instruction and input lanes;
- managed Node MCP URL and bearer authorization;
- exact role-scoped enabled Node tools;
- noninteractive approval policy;
- resolved native-tool/network/sandbox policy; and
- optional explicit model/effort overrides.

The overlay is supplied dynamically to that thread/turn invocation. It never rewrites user/project `config.toml`, stores the bearer credential in provider config, or changes another concurrent dispatch.

The exact app-server/SDK request fields are selected by the pinned implementation and conformance-tested. The stable contract is dynamic nonpersistent injection, not one frozen upstream wire spelling.

## Tool exposure and authority

Provider-side enabled tools mirror the binding's stable exposure ceiling. A worker turn is not shown parent/root structural tools. App-server exposure is defense in depth; every call still authenticates the binding and rereads controller currentness/capability.

Provider-native approval events are resolved noninteractively under the machine policy. They are never translated into controller human requests after the fact.

## Continuity

A Codex thread may be reused only when the pinned integration can still deliver both complete current request lanes and the fresh dispatch MCP binding. Otherwise the adapter starts a fresh thread.

Continuity is an optimization, not a correctness input. A thread ID is not persisted as generic controller state, does not authenticate Node MCP, and may be lost on process restart.

## Stop and cleanup

When supported, `stop(dispatch_id)` sends one bounded interrupt for the adapter-owned active turn and returns `Stopped` or `NotRunning` only on the documented stop acknowledgement. Runtime proceeds when the call is unsupported, fails, or times out.

Normal boundary/human/command transitions never invoke this method. The adapter may continue consuming app-server frames privately to keep the child transport healthy, but runtime does not await a final response or drain completion and no dispatch enters a closing fence.

Shutdown closes adapter resources under the main FastAPI lifespan after binding revocation. Cleanup cannot modify committed controller truth.

## Failure classification

The adapter normalizes configuration, authentication, connection, unavailable, timeout, rejection, unsupported, and uncertain-acceptance failures. When acceptance may have occurred, it reports uncertainty so runtime can revoke the old binding, make the one bounded interrupt attempt, and retry the same D2 with a fresh binding.

Raw app-server payloads, provider output, credentials, binding material, and thread IDs are excluded from controller error storage and ordinary logs.

## Required conformance

- exact two-lane delivery;
- dynamic per-dispatch MCP attachment and role allowlist;
- no persistent provider config mutation;
- noninteractive approval behavior;
- acceptance and interrupt boundaries for the pinned version;
- definite versus uncertain start classification where observable;
- same-D2 retry with a new binding and identical request bytes; and
- no provider output/final/drain effect on controller state.

## Related contracts

- [Minimal provider adapter contract](../adapter-contract.md)
- [Managed Node MCP binding](../managed-node-mcp-binding.md)
- [Provider CLI and check](../../interfaces/provider-cli-and-check.md)
- [Codex support and compatibility](../../interfaces/codex-support-and-compatibility.md)
- [Node and Operator MCP surface contract](../../interfaces/node-and-operator-mcp-surface-contract.md)
