# Task-compose model

Task-compose is one launch request. It should stay small.

It owns:

- task key, title, summary, and instruction
- selected workflow key
- optional `workspace` and `context` path bindings

It does not own reusable role behavior, policy authority, workflow structure, runtime evidence, or operator decisions.

At task start, AutoClaw validates task-compose against current definition-registry truth and pins the revisions used by the task. Later definition changes do not silently rewrite that running task.

See [write a task-compose file](../guides/write-a-task-compose.md) for examples.
