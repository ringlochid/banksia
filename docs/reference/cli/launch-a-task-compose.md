# Launch a task compose

Validate the definitions and provider configuration, then start one local task-compose file:

```bash
autoclaw task-compose start --file ./task.yaml
```

Use `--json` for automation. The command uses the same compiler and task-start service as `POST /tasks/start` and operator MCP `start_task`.

Success means the task bootstrap transaction committed. Root dispatch opening and provider start happen after return. Keep the returned `task_id` and inspect it through the console, HTTP control routes, or operator MCP.

See [Task-compose YAML](../api/definition-and-task-compose-yaml-contract.md) for the input contract.
