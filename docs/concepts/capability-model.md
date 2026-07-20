# Capability model

Capabilities are policy-granted controller powers. They are separate from provider-native tools and from budgets.

## Human requests

A human request creates a typed wait for human judgment:

- `direction`
- `approval`
- `input`
- `review`

Use one only when a person must decide or supply something. Do not use it for status updates or long commands.

## Command runs

A command run is controller-managed external work with a command, deadline, log, terminal state, and cancellation path. Use it when a command needs to outlive an ordinary inline tool call or remain observable after the current provider turn.

## Budgets

Budgets limit repeated controller actions; they do not grant tools:

- worker policies can limit retries
- root and parent policies can limit child assignments
- an omitted budget means that controller counter is not applied

## Recovery choices

- Retry when the assignment shape is still correct.
- Replan when the workflow shape is wrong.
- Request human input when judgment is missing.
- Block when required facts, authority, tools, or external state remain unavailable.

See [use human requests](../guides/use-human-requests.md), [use long command runs](../guides/use-long-command-runs.md), and [recover or replan a task](../guides/recover-or-replan-a-task.md).
