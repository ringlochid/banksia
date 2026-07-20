# AutoClaw documentation

AutoClaw runs structured AI work from controller-owned tasks, assignments, and evidence. Start one task first. Read the concepts when you need to design or operate a larger workflow.

## Browse by section

- [Start](start/README.md)
- [Concepts](concepts/README.md)
- [Guides](guides/README.md)
- [Help](help/README.md)
- [Reference](reference/README.md)
- [Maintainers](maintainers/README.md)

## Start here

1. [Install and set up AutoClaw](start/getting-started.md).
2. [Choose and check a provider](start/configuration-and-settings.md).
3. [Start a task](start/start-a-task.md).
4. [Inspect the task](start/inspect-a-task.md).

Codex and Claude use a managed tool connection for each dispatch. OpenClaw is also selectable, but it is an experimental lane that you configure in OpenClaw yourself.

## Learn the model

- [Product overview](concepts/overview.md)
- [Orchestration model](concepts/orchestration-model.md)
- [Core concepts](concepts/core-concepts.md)
- [Authoring model](concepts/authoring-model.md)
- [Runtime model](concepts/runtime-model.md)
- [Operator model](concepts/operator-model.md)

## Build and operate

- [Design a workflow](guides/design-workflows-and-instructions.md)
- [Write a role](guides/write-a-role.md)
- [Write a policy](guides/write-a-policy.md)
- [Write a workflow](guides/write-a-workflow.md)
- [Write a task-compose file](guides/write-a-task-compose.md)
- [Inspect and control a task](guides/inspect-and-control-a-task.md)
- [Recover or replan a task](guides/recover-or-replan-a-task.md)

## Find exact details

- [CLI reference](reference/cli/README.md)
- [API reference](reference/api/README.md)
- [Operator reference](reference/operator/README.md)
- [Definition examples](reference/definitions/README.md)
- [Troubleshooting](help/troubleshooting.md)

Maintainers should use the [maintainer docs](maintainers/README.md). Target architecture and shipped-behavior contrast live under `docs-internal/**`.
