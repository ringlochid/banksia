---
name: "autoclaw-runtime-operator"
description: "Inspect and control existing AutoClaw tasks through operator MCP. Use for task status, human requests, command runs, pause, continue, cancel, definition reads, definition upload, or explicit task start."
---

# AutoClaw runtime operator

Use operator MCP for existing AutoClaw tasks. Do not use Node MCP for operator work.

## Available tools

- definitions: `search_definitions`, `get_definition`, `list_definition_versions`, `upload_definition`
- task start: `start_task`
- current reads: `list_runtime_tasks`, `get_runtime_task`, `get_operator_snapshot`, `get_operator_trace`
- chronology: `get_task_events`
- human requests: `get_human_requests`, `resolve_human_request`
- command runs: `get_command_runs`, `get_command_run`, `get_command_run_log`, `cancel_command_run`
- controls: `pause_task`, `continue_task`, `cancel_task`

Definition draft authoring stays on the HTTP `/authoring` API.

## Inspect before acting

Always make a fresh read. Task state may change between turns.

1. Use `list_runtime_tasks` when the task ID is unknown.
2. Use `get_runtime_task` for current status and fresh flow and control revisions.
3. Use `get_operator_snapshot` for current actionable state.
4. Read human requests or command runs when the task is waiting.
5. Use `get_operator_trace` or `get_task_events` only when chronology matters.

Task events explain changes but do not replace current state. Cursors are exclusive and task-bound. If a cursor must reset, reread current truth and restart chronology.

## Human requests

Read every item, option, recommendation, and timeout policy. Ask the user for any judgment they have not delegated. Resolve the exact open request with `resolve_human_request`; never use `continue_task` as an answer.

Resolution returns after the answer commits. Successor opening is independent, so reread current task state afterward.

## Command runs

Use `get_command_runs` to find the run, `get_command_run` for details, and `get_command_run_log` only when needed. Use `cancel_command_run` for one command instead of cancelling the task.

Cancellation returns when `cancellation_requested` commits. It does not wait for process exit or terminalization.

## Task controls

Pause, continue, and cancel are writes. Use fresh `expected_active_flow_revision_id` and `expected_control_revision` values from `get_runtime_task`.

- pause only to stop forward progress intentionally
- continue only to resume a paused task
- cancel only when the user wants the task stopped
- prefer human-request resolution or command-run cancellation when that is the narrower action

Do not use `continue_task` for polling.

## Definition and launch writes

`upload_definition` and `start_task` read files on the AutoClaw host and mutate controller state. Use them only when the user asked for that write and the path is known.

`start_task` returns after bootstrap commit, before root dispatch and provider start. Capture the `task_id`, make one current read, and stop unless the user asked for ongoing supervision.

## OpenClaw boundary

The user manages the experimental OpenClaw provider, its Gateway, and `openclaw.json`. AutoClaw does not inject or maintain the OpenClaw MCP entry.

The static compatibility Node server is `/node/mcp`. Every Node tool call includes full current `task_id` and `dispatch_id` selectors. These selectors do not grant operator authority. Operator MCP remains the separate local control surface at `/operator/mcp`.
