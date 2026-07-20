# Start a task

AutoClaw starts tasks from current definition-registry state and one task-compose file. A task-compose file selects the workflow and supplies the request for this run.

## Create the launch file

Save this as `task-compose.yaml`:

```yaml
task:
    key: first-research-brief
    title: First research brief
    summary: Produce one concise research brief.
    instruction: >-
      Research local-first orchestration for delegated AI work. Produce a concise Markdown brief with evidence, tradeoffs, and a recommended next step.
workflow:
    key: topic-research-brief
```

The workflow key must exist in the current registry. `autoclaw init` installs the packaged definitions. To publish your own definitions, use the console authoring workbench or `autoclaw definitions import --file ...`.

## Launch

```bash
autoclaw task-compose start --file ./task-compose.yaml --json
```

Keep the returned `task_id`. Open the console and select the task, or use the operator HTTP or MCP read surfaces.

At start, AutoClaw reads the current workflow, role, and policy revisions, validates the launch, and commits a controller-owned task and root dispatch. Provider start happens asynchronously after that commit. The start response does not wait for the provider to finish.

## What success means

A provider finishing is not task success. The task advances when its node uses the allowed MCP tools to record controller-owned progress, artifacts, waits, and boundaries.

For the example workflow, expect a published `research_brief` artifact and a completed controller flow. See [inspect a task](inspect-a-task.md).

For path bindings and a fuller launch contract, read [write a task-compose file](../guides/write-a-task-compose.md).
