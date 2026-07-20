# Inspect and control a task

Read current controller state before changing it.

1. Open the task in the console or read `get_runtime_task`.
2. Read the operator snapshot for current work and actionable waits.
3. Read trace or task events when you need history.
4. Inspect the current assignment, checkpoint, and artifacts.
5. Read the human-request or command-run source when the task is waiting.

Use controls narrowly:

- resolve the exact pending human request
- cancel the command run instead of the task when only the command is wrong
- pause before deliberate operator intervention
- continue only from a fresh current read
- cancel only when the task should terminate

Provider output does not prove progress, and silence does not prove a stall. The provider may be starting, the task may be waiting, or an after-commit handler may still be opening the next dispatch.

Use the [operator reference](../reference/operator/README.md) for exact routes and tools.
