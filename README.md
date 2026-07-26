<h1 align="center">Banksia</h1>

<p align="center"><strong>Accountable AI teams for complex work.</strong></p>

<p align="center"> <a href="docs/start/getting-started.md">Get started</a> · <a href="docs/README.md">Documentation</a> · <a href="examples/workflows/README.md">Workflow examples</a> </p>

Banksia is a no-code agent-team runtime for developers, researchers, and anyone whose work needs more structure than one long agent conversation. A Workflow describes a reusable team of responsibilities. The controller turns that team into a trackable Task, lets its members delegate through sequential, parallel, iterative, batch, or hybrid plans, and keeps the result recoverable when a provider process stops.

Banksia is in active development. Its public contracts are being stabilized and it is not yet recommended for production-critical workloads.

## Why Banksia

- **Accountable teams:** every member has a stable identity and an explicit responsibility.
- **Flexible execution:** the team tree describes ownership, not a fixed sequence of steps.
- **Controller-owned truth:** providers perform work; they do not decide whether a Task is complete.
- **Visible handoffs:** assignments, checkpoints, waits, human decisions, and command outcomes remain inspectable.
- **Native collaboration files:** members can exchange notes and deliverables through the Task workspace without an artifact bureaucracy.
- **Operator assistance:** a separate Operator can draft Workflows, start Tasks, answer operational questions, and use the same controller operations as the Console.

## Quick start

Banksia requires Python 3.12 or newer. Install the packaged command in an isolated environment:

```bash
pipx install banksia-ai
banksia init
banksia setup
banksia serve
```

Open `http://127.0.0.1:18125/`. `banksia init` can record a default workspace for Tasks started from the Console, HTTP API, or Operator. `banksia setup` configures a Codex, Claude, or OpenClaw provider route.

From a source checkout, replace the install step with:

```bash
uv sync --all-groups
uv run banksia init
uv run banksia setup
uv run banksia serve
```

Import a Workflow written as YAML or JSON into a draft:

```bash
banksia workflow import --file examples/workflows/advanced-reviewed-code-change.yaml
```

Review and publish that draft in the Console before using it. Packaged installations also bootstrap provider-neutral starter Workflows. Start a Task interactively:

```bash
banksia task start
```

For automation, pass strict JSON inline, from `@file`, or through standard input:

```bash
banksia task start --json \
  '{"workflow":"reviewed-code-change","prompt":"Implement a bounded refactor of Workflow input validation without changing public behavior; add focused regression proof, independently review the integrated change, fix accepted findings, and return the verified result."}'
```

## Current scope

Codex and Claude are managed provider adapters. OpenClaw is a provider transport with an explicit-ID compatibility projection at `/node/mcp`; users continue to own and operate their OpenClaw Gateway.

External MCP servers and reusable Skills are deliberately deferred from Workflow authoring. The current Workflow extension surface is provider selection, managed sandbox settings, Human Request capability, and Command Run capability. Both capabilities deny by default.

The shipped Console is a functional migration-stage interface. It supports Workflow and Task operations, but the final visual studio and broader responsive experience are still under development.

## Documentation

- [Getting started](docs/start/getting-started.md)
- [Workflows and teams](docs/concepts/workflows-and-teams.md)
- [Runtime and results](docs/concepts/runtime-and-results.md)
- [Workspace files](docs/concepts/workspace-and-files.md)
- [Author a Workflow](docs/guides/author-a-workflow.md)
- [Run and operate Tasks](docs/guides/run-and-operate.md)
- [CLI reference](docs/reference/cli.md)
- [HTTP API reference](docs/reference/http-api.md)
- [Controller tools](docs/reference/controller-tools.md)

## License

Banksia is open source under the [MIT License](LICENSE).
