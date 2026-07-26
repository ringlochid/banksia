# Getting started

This path starts Banksia locally, configures one provider, and launches a Task from a packaged starter Workflow.

## 1. Install

Banksia requires Python 3.12 or newer:

```bash
pipx install banksia-ai
```

From a source checkout:

```bash
uv sync --all-groups
```

Prefix later commands with `uv run` when you are using the source environment.

## 2. Initialize

Run the guided initializer from the project directory you normally want the Console, HTTP API, and Operator to use:

```bash
banksia init
```

Accept the invocation directory as the suggested default workspace or enter another existing absolute directory. Automation can set it explicitly:

```bash
banksia init --workspace /absolute/path/to/project --non-interactive
```

The initializer writes configuration, prepares controller storage, and bootstraps provider-neutral starter Workflows. Use `banksia config show` to confirm the effective workspace and database.

## 3. Configure a provider

Run:

```bash
banksia setup
```

Choose Codex, Claude, or OpenClaw. The guide configures the route, handles supported login, checks availability, and sets the default provider.

Codex and Claude are managed adapters. OpenClaw is a user-operated transport: you remain responsible for its CLI, Gateway, profile, and authentication.

Confirm the result without changing state:

```bash
banksia providers status
banksia status
```

## 4. Start the application

Run:

```bash
banksia serve
```

Open `http://127.0.0.1:18125/`. Banksia's current product surface is loopback-only.

On Linux, you can install a user service instead:

```bash
banksia service install
banksia service status
```

## 5. Start a Task

Use the Console's **New run** path or start interactively in the terminal:

```bash
banksia task start
```

Choose one of the published starter Workflows, then enter the one complete Task prompt. The Task detail view shows current work, Checkpoints, Human Requests, Command Runs, Activity, and the final Result.

For automation:

```bash
banksia task start --json \
  '{"workflow":"reviewed-code-change","prompt":"Review this repository change and report the consequential findings."}'
```

## 6. Try a reference Workflow

Importing a YAML or JSON definition creates a draft:

```bash
banksia workflow import --file examples/workflows/advanced-reviewed-code-change.yaml
```

Open that draft in the Console, validate it, and publish it before Task start. The maintained [Workflow examples](../../examples/workflows/README.md) demonstrate advanced provider, sandbox, network, Human Request, and Command Run choices for developer and researcher teams.

Next, read [Workflows and teams](../concepts/workflows-and-teams.md) or [Run and operate Tasks](../guides/run-and-operate.md).
