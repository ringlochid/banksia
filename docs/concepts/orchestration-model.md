# Orchestration model

AutoClaw coordinates delegated work that must stay inspectable and recoverable. A provider runs an agent loop; AutoClaw decides what work is current, what authority it has, and which evidence can advance the task.

## Why a controller exists

A transcript alone cannot reliably answer:

- Which assignment is current?
- What may this node do?
- Which evidence must exist before release?
- Is the task working, waiting, paused, or complete?
- Can a retry or late tool call still change state?

AutoClaw records those answers in controller-owned runtime rows.

## The execution loop

1. A user publishes roles, policies, and a workflow.
2. Task-compose selects the workflow for one request.
3. AutoClaw commits a task, flow, root assignment, root attempt, and exact flow-start source.
4. After that commit, an independent handler rereads the source, publishes the immutable request pair, and commits the starting dispatch with its refs.
5. Provider start runs independently after the dispatch commit.
6. The provider receives the request and its role-appropriate Node tools.
7. Accepted MCP calls record progress, artifacts, waits, boundaries, or structural changes.
8. An after-commit handler rereads the exact source and opens the next dispatch when the state still permits it.

The source response does not wait for the next provider turn. This keeps the current agent's boundary return independent from successor start.

## Winner and loser behavior

Signals carry exact source identity, such as a dispatch, human request, or command run. A handler rereads current database truth before acting. If the source is stale or another transition already won, it does nothing. Short conditional transactions and database constraints prevent most duplicate or stale controller effects without serializing every task operation behind one large lock.

This model makes repeated signals safe at the controller boundary. It does not claim that an external provider start can be exactly once across every process crash; ambiguous starts are reconciled from recorded acceptance state.

## Providers are replaceable

Codex, Claude, and OpenClaw are provider adapters. They may differ in transport, tool attachment, and stop behavior, but they do not own task truth. Provider output, final responses, sessions, and terminal status are ignored as runtime authority.

## Support files and dispatch requests

The controller materializes manifests, assignments, checkpoints, and artifact indexes so agents and people can read the task. These support files do not control dispatch start. Each dispatch instead has an immutable `instructions.md` and `input.md` request pair that must be complete before the dispatch is committed and started. The prompt and current-context tool expose logical paths for rereading that pair and the workflow manifest; live controller context still wins when a support file is missing or stale.

See [runtime model](runtime-model.md) for the detailed lifecycle.
