# Operator model

An operator inspects and steers controller-owned tasks. It is separate from the root, parent, and worker nodes that perform assignments.

## Operator surfaces

Humans use the local console. Trusted automation can use the operator HTTP or MCP surfaces. They expose the same controller concepts through different interfaces.

Operators can:

- list and inspect tasks
- read snapshots, traces, and task events
- inspect and resolve human requests
- inspect command runs and request cancellation
- pause, continue, or cancel a task
- search, publish, and launch definitions where authorized

Use the narrowest control that fits the problem. Cancelling a command run is not the same as cancelling a task.

## Observe before changing state

Read current task state and a fresh snapshot before a control action. Trace and event streams explain history, but source rows own current truth. Generated task files are useful evidence, not a control interface.

See [inspect and control a task](../guides/inspect-and-control-a-task.md) and the [operator reference](../reference/operator/README.md).
