# Authoring model

AutoClaw keeps reusable definitions separate from one task launch.

| Object | Owns | Does not own |
| --- | --- | --- |
| Role | specialist behavior and evidence habits | one task's scope or paths |
| Policy | node authority, capabilities, and budgets | specialist identity or workflow structure |
| Workflow | node tree, missions, criteria, inputs, and outputs | live runtime state |
| Task-compose | one task instruction, workflow key, and optional path bindings | reusable behavior |

## Evidence fields

- `criteria` are hard requirements that can block closure.
- `consumes` names evidence a node must read.
- `produces` names durable artifacts a node must publish.

For a fixed workflow, declare the evidence handoff precisely. For a dynamic workflow, keep a few stable artifact and criteria slots while a parent chooses the next child from current evidence.

## Registry lifecycle

The definition registry owns current and historical revisions. The authoring workbench stores drafts, validates them, and publishes a new current revision. Preview and validation do not start a task. Task start rereads the current registry and pins the revisions used for that run.

Use the console authoring workbench or `autoclaw definitions import --file ...`. Repo example files are examples and seed inputs, not live registry truth.

Next:

- [Design workflows and instructions](../guides/design-workflows-and-instructions.md)
- [Write a role](../guides/write-a-role.md)
- [Write a policy](../guides/write-a-policy.md)
- [Write a workflow](../guides/write-a-workflow.md)
