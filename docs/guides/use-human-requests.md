# Use human requests

Use a human request when the task needs human judgment that current evidence cannot supply.

Choose the narrowest kind:

- `direction` for a route choice
- `approval` before an action that needs permission
- `input` for a missing fact
- `review` for a human quality gate

The node's policy must allow that kind. Opening the request commits an explicit wait and returns promptly. The request deadline is managed asynchronously. Resolving the current request commits its terminal state; an after-commit handler then opens the next dispatch when the task is still eligible.

Resolve requests through the console, operator HTTP, or operator MCP surface. Do not reply in an unrelated provider chat or edit a generated file.

See [capability model](../concepts/capability-model.md).
