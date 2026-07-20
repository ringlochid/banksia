# Task stuck or waiting

Quiet provider output is not proof that a task is stuck. Read current controller state first.

## Observe

Use the console or operator MCP in this order:

1. `get_runtime_task`
2. `get_operator_snapshot`
3. `get_operator_trace` when history is needed
4. the exact human request or command run when the task is waiting

## Act on the source

- Resolve a pending human request through its operator control.
- Inspect or cancel the current command run without cancelling the whole task.
- If the task is paused, reread current state before continuing it.
- If a dispatch is `starting`, check provider availability and its committed `instructions.md` and `input.md` request refs.
- If an open dispatch is inactive, let the watchdog compare the exact current dispatch and admitted activity.

The watchdog default is 15 minutes. It ignores provider output and does not compete with an active human-request or command-run wait. A stale watchdog signal has no effect.

Use retry when the assignment is still right and replan when the workflow shape is wrong. See [recover or replan a task](../guides/recover-or-replan-a-task.md).
