# Runtime reads and operator surfaces

Use current controller reads to answer what a task is doing now. Use task events or the trace to explain how it got there. Generated files and provider output are support evidence only.

## HTTP and MCP parity

The HTTP control domain and operator MCP use the same runtime services. Equivalent reads and mutations must enforce the same task identity, current revisions, and state legality.

Operator MCP is mounted at `/operator/mcp` and exposes these tools:

- definitions: `search_definitions`, `get_definition`, `list_definition_versions`, `upload_definition`
- launch: `start_task`
- current reads: `list_runtime_tasks`, `get_runtime_task`, `get_operator_snapshot`, `get_operator_trace`
- chronology: `get_task_events`
- human requests: `get_human_requests`, `resolve_human_request`
- command runs: `get_command_runs`, `get_command_run`, `get_command_run_log`, `cancel_command_run`
- controls: `pause_task`, `continue_task`, `cancel_task`

Definition draft authoring remains on the HTTP `/authoring` routes.

## Read order

1. Read `get_runtime_task` for task status and fresh control revisions.
2. Read `get_operator_snapshot` for the current actionable view.
3. Read human requests or command runs when the task is waiting on one.
4. Read `get_operator_trace` or `get_task_events` only when chronology matters.

Do not use `continue_task` as a status check. It is a mutation for a paused flow and requires fresh `expected_active_flow_revision_id` and `expected_control_revision` values.

## Chronology

Task events are ordered, bounded, controller-owned facts. Cursors are exclusive and task-bound. If a cursor can no longer resume, reread current state and restart the chronology instead of guessing across the gap.

Events do not contain provider output, managed MCP credentials, raw human answers, command logs, or in-memory wakeup state.

## Mutation timing

Operator responses report the controller transaction they committed. Independent work may continue after return:

- task start returns before root dispatch and provider start
- human-request resolution commits the answer before successor opening
- command cancellation returns at `cancellation_requested`, before process exit and terminalization
- pause and cancel do not wait for provider shutdown

There is no provider-output or provider-drain completion contract.
