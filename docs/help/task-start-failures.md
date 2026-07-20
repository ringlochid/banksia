# Task start failures

Use this page when `autoclaw task-compose start --file ...` is rejected.

## Check the launch file

Confirm that:

- the file exists on the AutoClaw host
- `task.key`, `task.title`, `task.summary`, and `task.instruction` are present
- `workflow.key` names a current registry workflow
- explicit `workspace` and `context` bindings use a supported mode and valid path

## Check registry truth

Open the console authoring workbench or read `GET /definitions/workflows`. Repo YAML is not live registry truth.

Publish a missing definition with the workbench or:

```bash
autoclaw definitions import --file ./workflow.yaml
```

Use `--overwrite allow_new_revision` only when changed content should become a new current revision.

## Read the returned validation error

Task start rereads and validates the current workflow, roles, policies, dependencies, provider selection, and path bindings. Fix the named contract problem rather than changing controller rows or generated files.

See the [definition and task-compose contract](../reference/api/definition-and-task-compose-yaml-contract.md).
