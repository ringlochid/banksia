# Write a task-compose file

Task-compose describes one launch, not reusable behavior.

```yaml
task:
    key: fix-invoice-date
    title: Fix invoice date parsing
    summary: Fix and verify one reported date parsing regression.
    instruction: >-
      Reproduce the reported regression, fix the narrow cause, add focused regression proof, and do not change unrelated import behavior.
workflow:
    key: bugfix-review-release
```

Omit `roots` for a task-owned workspace. Bind an existing project when needed:

```yaml
roots:
    workspace:
        mode: use_existing_host
        host_path: /home/you/projects/example
```

Other modes are `ensure_task_default` and `ensure_host_path`. Never put credentials in task-compose.

Start the task:

```bash
autoclaw task-compose start --file ./task-compose.yaml --json
```

See the [task-compose examples](../reference/definitions/task-compose/README.md).
