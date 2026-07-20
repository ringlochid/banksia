# Workspace model

Task-compose can bind two named paths:

- `workspace` for working material
- `context` for supporting material

If `roots` is omitted, AutoClaw creates task-owned defaults. An explicit binding can:

- `ensure_task_default`: create the task-owned path
- `ensure_host_path`: use and create a named host path
- `use_existing_host`: require an existing host path

These bindings are launch inputs, not the workflow's `root` node. Choose task-owned paths for isolation and host paths when the task must work in an existing project.

See [write a task-compose file](../guides/write-a-task-compose.md) for YAML.
