# Use long command runs

Use a command run when command work needs controller-owned logs, a deadline, cancellation, or continuation after the current provider turn.

The worker's policy must allow command runs. The worker submits the command through its node tool. AutoClaw commits the wait, launches and supervises the process asynchronously, records terminal state, and signals continuation from that exact run.

Operators can inspect the run, read its log, and request cancellation without cancelling the whole task.

Keep ordinary short commands in the provider's normal shell tool. A command run is an external wait, not a pool of provider calls and not a general replacement for shell execution.

See [capability model](../concepts/capability-model.md) and the [operator reference](../reference/operator/README.md).
