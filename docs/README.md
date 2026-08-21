# Oh My Subagents documentation

Oh My Subagents is a local runtime for persistent, supervised parent–subagent delegation with Codex and Claude. Reusable responsibility trees define who owns the work while controller-owned state persists Assignments, waits, Checkpoints, recovery, and one accountable Result.

## Why Oh My Subagents

- **Reuse explicit responsibility trees** instead of recreating roles and prompts for every job.
- **Delegate without polling** while the runtime commits Assignments, persists waits, supervises returns, and continues the parent.
- **Recover from committed state** after a provider interruption, browser closure, or controller restart.
- **Return one accountable Result** after the Task lead inspects the team's Checkpoints, evidence, and referenced files.

## Start here

- [Getting started](start/getting-started.md) — install Oh My Subagents, configure a provider, and complete a first developer or researcher run.
- [Starter team catalog](../examples/workflows/README.md) — choose among the eight installed Workflows using realistic missions and expected deliverables.

## Understand the product

- [Workflows and teams](concepts/workflows-and-teams.md) — understand responsibility trees, Members, providers, capabilities, and adaptive work.
- [Runtime and Results](concepts/runtime-and-results.md) — understand Tasks, Assignments, Checkpoints, and the lead's final Result.
- [Workspace and files](concepts/workspace-and-files.md) — understand the shared workspace, loose file references, notes, and deliverables.

## Build and run teams

- [Author a Workflow](guides/author-a-workflow.md) — start from a Starter, shape responsibilities in Workflow Studio or with the Operator, validate, and publish.
- [Run and operate](guides/run-and-operate.md) — start work, read the run view, respond to allowed waits, and use legal controls.
- [Console and Operator](guides/console-and-operator.md) — visually edit and publish teams, inspect live work and Results, or use the separate conversational Operator for the same product operations.
- [Migrate from Banksia](guides/migrate-from-banksia.md) — copy an existing installation into canonical OMS state.

## Configure and integrate

- [Configuration reference](reference/configuration.md) — configure SQLite or PostgreSQL, providers, workspace defaults, sandboxing, and Operator.
- [Workflow definition reference](reference/workflows/README.md) — use the public JSON/YAML schema and field contract.
- [CLI reference](reference/cli.md) — automate local setup and product operations.
- [HTTP API](reference/http-api.md) — integrate through the loopback product API.
- [Controller tools](reference/controller-tools.md) — understand the exact Task-member and Operator tool surfaces.

## Fix a problem

- [Troubleshooting](help/troubleshooting.md) — diagnose initialization, database, provider, controller, Workflow, and recovery problems.
- [Report an issue](https://github.com/ringlochid/oh-my-subagents/issues) — include the smallest redacted evidence that reproduces the problem.

## Contribute

- [Contributing](../CONTRIBUTING.md) — prepare a source checkout, follow repository owners, work in a bounded slice, and report executable proof.
- [Maintainer verification](maintainers/README.md) — run the repository's quality, contract, and release-readiness checks.
