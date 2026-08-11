# Getting started

Install Banksia, configure an AI provider, and complete a first developer or researcher run.

## Before you start

You need:

- Python 3.12 or newer;
- Linux, macOS 13+, or Windows 11 x64; WSL2 uses the Linux path;
- an existing project or research directory for the team's workspace; and
- a Codex or Claude account and authentication path.

Native Windows requires a local NTFS workspace. UNC/network paths, device paths, non-NTFS volumes, and paths traversing reparse points reject at admission rather than weakening filesystem safety.

## Install Banksia

Use [pipx](https://pipx.pypa.io/stable/) to install the command-line application in its own environment:

```bash
pipx install banksia
banksia --version
```

If `pipx` is not installed, follow its [platform installation guide](https://pipx.pypa.io/stable/how-to/install-pipx.html). Contributors who need a source checkout should use the [contributing guide](../../CONTRIBUTING.md) instead.

### Optional: install with PostgreSQL

SQLite is the default and needs no database server. Choose PostgreSQL before initialization when you want Banksia controller data in an existing PostgreSQL service:

```bash
pipx install "banksia[postgres]"
```

If the base package is already installed, replace that application environment with the PostgreSQL-enabled package:

```bash
pipx install --force "banksia[postgres]"
```

The PostgreSQL role must be able to connect to the selected database and create or use Banksia's dedicated schema. The [database configuration reference](../reference/configuration.md#database) contains the complete contract.

## Initialize Banksia

Change to the directory you want to use as the default workspace, then run:

```bash
cd /absolute/path/to/project
banksia init
```

Guided initialization:

1. confirms the default workspace and local controller settings;
2. creates the SQLite database and publishes the Starter Workflows;
3. configures at least one Task provider; and
4. optionally configures the separate Operator.

Choose Codex or Claude for Task work, then follow its authentication and readiness prompts. Choose **Not now** for Operator if you only want direct Console and CLI control.

To initialize PostgreSQL instead of SQLite, pass the database URL explicitly:

```bash
banksia init \
  --database-url "postgresql+asyncpg://banksia@127.0.0.1/banksia"
```

Use the URL required by your PostgreSQL service. Percent-encode reserved characters in credentials, avoid leaving passwords in shell history, and use `banksia config show` for redacted readback. Initialization creates a missing dedicated `banksia` schema and initializes it only when that schema has no tables and the role has permission.

For an unattended SQLite setup:

```bash
banksia init \
  --workspace /absolute/path/to/project \
  --non-interactive
```

## Check providers and settings

Rerun the settings journey at any time:

```bash
banksia setup
```

Use it to add or change Task providers, choose a different Operator, or update the default workspace. Check the effective configuration without changing it:

```bash
banksia config show
banksia providers status
banksia operator status
banksia status
```

Codex and Claude are the supported Task-provider adapters.

On Linux or WSL2, install `bubblewrap` and `socat` before using a Claude Member whose effective network setting is `deny`. On Ubuntu or Debian:

```bash
sudo apt-get install bubblewrap socat
```

These packages are Claude Code sandbox prerequisites, not general Banksia dependencies. See [Managed sandbox and network](../reference/configuration.md#managed-sandbox-and-network) and [Claude Code sandboxing](https://code.claude.com/docs/en/sandboxing).

## Open the Console

Start the controller in the foreground:

```bash
banksia serve
```

Open `http://127.0.0.1:18125/`.

The Console has three main working areas:

- **Workflows** is the team library. Open a Starter or draft, add and edit Members on the visual responsibility tree, validate the current draft, and publish when it is ready.
- **Runs** starts work and shows each live or completed team, meaningful Activity, Human Requests, managed Actions, referenced files, and the exact Result.
- **Operator** is a separate conversational agent for the same product operations. It can help draft or revise a Workflow, find and start a suitable team, inspect current work, and perform an explicitly requested legal action.

Operator and the visual screens use the same controller-owned Workflow and Run truth. A conversational edit does not create a separate copy of the team.

To run Banksia as the current user's background service instead:

```bash
banksia service install
banksia service status
```

Banksia uses a systemd user service on Linux, a current-user LaunchAgent on macOS, and a least-privilege current-user Scheduled Task on Windows.

## Complete a developer run

In the Console:

1. Open **Runs** and choose **New run**.
2. Select `production-feature-delivery`.
3. Enter one complete prompt, for example:

   > Add a guided configuration-import recovery experience across the API and Console. Preserve
   > accepted imports, define the shared error contract, implement the service and user-facing
   > behavior, verify the integrated recovery path, repair consequential findings, and return the
   > release-readiness result with referenced files.

4. Start the run and follow **Team**, **Current plan**, and meaningful **Activity**.
5. Select a Member to inspect its plan. Use **Steer** when an active Member needs new context or a changed direction; answer a Human Request when the team needs a decision before it can continue.
6. Read **Result**, then open its referenced workspace files for the detailed change, proof, review, or report.

The responsibility tree defines ownership, not a fixed timeline. The running team chooses sequential, parallel, iterative, batch, or hybrid work from current evidence.

Starters omit provider settings and use the configured default. Human Request and managed Command Run capabilities are granted only to Members that need them; every omitted capability denies, and children never inherit capabilities.

## Complete a research run

Start another run with `deep-research-and-decision-brief`:

> Determine whether the proposed storage change fits this repository's recovery contract. Separate
> local facts, current primary-source claims, and inference; challenge provenance and
> counterevidence; then return one confidence-calibrated conclusion with limitations and referenced
> files.

Use **Advanced → Referenced files** when the team must inspect a particular workspace file. Banksia records its workspace-relative path and optional description, not a copy of its contents.

Choose `experiment-and-replication-program` for a substantial computational or empirical program that needs durable execution and independent replication.

## Start a run from the terminal

The Console is the clearest catalog and run view. The terminal can start the same published Workflow interactively:

```bash
banksia task start
```

Automation can pass one strict JSON object inline, from `@file`, or through standard input:

```bash
banksia task start --json \
  '{"workflow":"production-feature-delivery","prompt":"Deliver the cross-layer configuration recovery experience, verify the integrated behavior and release risks, repair accepted findings, and return the result."}'
```

The controller must already be running. CLI-started runs use the invocation directory as their workspace.

Next, [compare every Starter](../../examples/workflows/README.md), learn how to [author a Workflow](../guides/author-a-workflow.md), or learn how to [operate a run](../guides/run-and-operate.md).
