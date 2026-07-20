# Inspect waits and watchdog recovery

Read current task state before taking action. A quiet provider is not proof that a task is stuck.

## Human requests

Use `get_human_requests` or `GET /control/tasks/{task_id}/human-requests`. Resolve the exact open request through `resolve_human_request` or its matching HTTP route. Do not use task continue to answer a human request.

A request remains a watchdog exclusion until its terminal result has been routed or the flow is terminal.

## Command runs

Use the command-run list and detail reads first. Read the bounded log only when needed. Cancel one command with `cancel_command_run`; do not cancel the whole task when the command is the only problem.

Cancellation first commits `cancellation_requested`. The process owner then terminates, reaps, and records the terminal result. A command source remains a watchdog exclusion until its continuation is consumed.

## Watchdog

The default inactivity deadline is 15 minutes. Admitted Node MCP calls advance the current dispatch activity revision and reschedule the deadline.

At a due signal, the handler rereads the exact dispatch, activity revision, and deadline. It does nothing when the dispatch changed, activity advanced, the deadline is not due, a human or command source is still active or unrouted, or the flow is paused or terminal.

If the dispatch is still stale, one transaction closes it and opens a same-attempt replacement. After two same-attempt replacements, AutoClaw pauses the flow for recovery instead of opening another dispatch.

The watchdog does not poll provider output and does not wait for provider shutdown.

## Task controls

Pause, continue, and cancel need fresh active-flow and control revisions from a current read. Prefer the narrow wait-specific operation when it matches the problem.
