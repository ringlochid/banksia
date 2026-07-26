# Getting started

This path prepares Banksia from source, configures one provider, and takes a developer from a packaged Starter to an exact Result. A concise researcher path follows.

## 1. Prepare a clean source checkout

Banksia is not yet published to a package registry. The current first-use path requires:

- Python 3.12 or newer;
- Make;
- Node.js 20.19 or newer within Node 20, 22.13 or newer within Node 22, or Node 24 or newer; and
- npm.

Clone the repository and prepare both the backend environment and the visual Console:

```bash
git clone https://github.com/ringlochid/banksia.git
cd banksia
make backend-install
make console-install
make console-package-assets
```

`make backend-install` creates `.venv` and installs the project with its development dependencies. The source tree does not contain a prebuilt Console bundle, so `make console-package-assets` builds `console/` and stages the ignored assets that `banksia serve` needs for browser routes. Run the asset command again after changing the Console.

## 2. Initialize the workspace

Stay in the Banksia checkout. To use that checkout as the first workspace, run:

```bash
./.venv/bin/banksia init
```

Accept the checkout as the default workspace or enter another existing absolute directory. The initializer writes local configuration, prepares controller storage, and publishes the seven provider-neutral Starter Workflows.

To configure another project explicitly without prompts:

```bash
./.venv/bin/banksia init --workspace /absolute/path/to/project --non-interactive
```

## 3. Configure one provider

Run the guided setup:

```bash
./.venv/bin/banksia setup
```

Choose Codex, Claude, or OpenClaw. Codex and Claude are managed adapters. OpenClaw is a user-operated compatibility transport, so you remain responsible for its CLI, Gateway, profile, authentication, and workspace exposure.

On Linux or WSL2, install `bubblewrap` and `socat` before using a Claude Member whose effective network setting is `deny`. On Ubuntu or Debian:

```bash
sudo apt-get install bubblewrap socat
```

These are host prerequisites for Claude Code's deny-network sandbox, not general Banksia dependencies. Banksia does not request that sandbox for a Claude route with network access allowed. See the [configuration reference](../reference/configuration.md#managed-sandbox-and-network) and [Claude Code sandboxing guide](https://code.claude.com/docs/en/sandboxing) for platform details.

Confirm current configuration without changing it:

```bash
./.venv/bin/banksia providers status
./.venv/bin/banksia status
```

## 4. Start Banksia

Run:

```bash
./.venv/bin/banksia serve
```

Open `http://127.0.0.1:18125/`. The current product surface is loopback-only.

## 5. Complete a developer run

In the Console:

1. Open **Runs** and choose **New run**.
2. Select the published `reviewed-code-change` Starter.
3. Enter one complete prompt, for example:

   > Add validation for the configuration import failure path without changing
   > accepted behavior. Follow current repository conventions, add focused
   > regression proof, independently review the integrated change, repair
   > accepted findings, and return the verified result with referenced files.

4. Start the run and follow **Team**, **Current plan**, and meaningful **Activity**.
5. Read **Result**. It is the lead's exact final `green` or `blocked` Checkpoint.
6. Open any referenced paths in the workspace for the detailed change, proof, review, or report.

The responsibility tree tells you who owns each part of the work; it does not force a fixed order. The running team chooses sequential, parallel, iterative, batch, or hybrid work from current evidence.

The installed Starters are capability-neutral: they grant neither Human Request nor Command Run. A normal first run therefore does not promise a question or an Action card. Those surfaces appear only when a custom Workflow explicitly grants the relevant Member capability.

## Researcher path

Start another run with `evidence-synthesis`:

> Determine whether the proposed storage change fits this repository's current
> recovery contract. Separate local facts, current primary-source claims, and
> inference; challenge provenance and counterevidence; then return one
> confidence-calibrated conclusion with limitations and referenced files.

Use **Advanced → Referenced files** on the start form when the team must inspect a particular workspace file. Banksia records each path and optional description, not a copy of the file.

For a computational or empirical question that needs independent replication, choose `reproducible-study` instead.

## CLI alternative

The Console is the clearest catalog and run view. The terminal can start the same published Workflow interactively:

```bash
./.venv/bin/banksia task start
```

Automation can pass one strict JSON object inline, from `@file`, or through standard input:

```bash
./.venv/bin/banksia task start --json \
  '{"workflow":"reviewed-code-change","prompt":"Implement the bounded validation change, add focused regression proof, independently review the integrated state, repair accepted findings, and return the verified result."}'
```

The controller must already be running. CLI-started runs use the invocation directory as their workspace. To start from another project, change to that directory and invoke the absolute path to the Banksia checkout's `.venv/bin/banksia`.

Next, [compare every Starter](../../examples/workflows/README.md), learn how to [author a Workflow](../guides/author-a-workflow.md), or learn how to [operate a run](../guides/run-and-operate.md).
