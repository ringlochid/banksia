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

The commands below target Linux and macOS. Native Windows is not currently supported; WSL2 uses the Linux installation and filesystem path. Source-development Make targets are not a substitute for native installed-wheel release proof.

## 2. Initialize the workspace

Stay in the Banksia checkout. To use that checkout as the first workspace, run:

```bash
./.venv/bin/banksia init
```

Accept the checkout as the default workspace or enter another existing absolute directory. The initializer writes local configuration, prepares controller storage, and publishes the eight provider-neutral Starter Workflows.

When local initialization succeeds, the same guided journey asks for one Task provider. Choose Codex, Claude, or OpenClaw, then follow the authentication and readiness prompts. Choose `cancel` to keep local initialization complete and defer provider setup.

The final prompt offers Codex, Claude, or **Not now** for the separate Operator. Selecting a managed provider that is not configured first offers to configure it. Provider checks are diagnostics: a failed check reports **Needs attention** and may make the command exit nonzero, but it does not erase or disable an accepted provider or Operator selection.

To configure another project explicitly without prompts:

```bash
./.venv/bin/banksia init --workspace /absolute/path/to/project --non-interactive
```

## 3. Resume or change settings

`banksia setup` is the rerunnable settings hub:

```bash
./.venv/bin/banksia setup
```

Use it to configure Task providers, the separate Operator, or the default workspace. Codex and Claude are managed adapters. OpenClaw is a user-operated compatibility transport, so you remain responsible for its CLI, Gateway, profile, authentication, and workspace exposure.

On Linux or WSL2, install `bubblewrap` and `socat` before using a Claude Member whose effective network setting is `deny`. On Ubuntu or Debian:

```bash
sudo apt-get install bubblewrap socat
```

These are host prerequisites for Claude Code's deny-network sandbox, not general Banksia dependencies. Banksia does not request that sandbox for a Claude route with network access allowed. See the [configuration reference](../reference/configuration.md#managed-sandbox-and-network) and [Claude Code sandboxing guide](https://code.claude.com/docs/en/sandboxing) for platform details.

Confirm current configuration without changing it:

```bash
./.venv/bin/banksia providers status
./.venv/bin/banksia operator status
./.venv/bin/banksia status
```

## 4. Start Banksia

Run:

```bash
./.venv/bin/banksia serve
```

Open `http://127.0.0.1:18125/`. The current product surface is loopback-only.

To install the same controller as the current user's background service instead, run:

```bash
./.venv/bin/banksia service install
./.venv/bin/banksia service status
```

Banksia selects a systemd user service on Linux and a current-user LaunchAgent on macOS. Use `banksia serve` when you prefer a foreground process. Native platform release claims still require the installed-wheel gates described in the project status; the presence of a service command alone is not full platform proof.

## 5. Complete a developer run

In the Console:

1. Open **Runs** and choose **New run**.
2. Select the published `production-feature-delivery` Starter.
3. Enter one complete prompt, for example:

   > Add a guided configuration-import recovery experience across the API and
   > Console. Preserve accepted imports, define the shared error contract,
   > implement the service and user-facing behavior, verify the integrated
   > recovery path, repair consequential findings, and return the
   > release-readiness result with referenced files.

4. Start the run and follow **Team**, **Current plan**, and meaningful **Activity**.
5. Read **Result**. It is the lead's exact final `green` or `blocked` Checkpoint.
6. Open any referenced paths in the workspace for the detailed change, proof, review, or report.

The responsibility tree tells you who owns each part of the work; it does not force a fixed order. The running team chooses sequential, parallel, iterative, batch, or hybrid work from current evidence.

Starters omit provider settings and use the configured default. They grant Human Request or managed Command Run only to the Members whose responsibility needs a material user decision or a long, supervised process. Every omitted capability denies and children never inherit. A Human Request pauses only its current Member until you answer; a managed Command Run appears as an inspectable Action with retained output.

## Researcher path

Start another run with `deep-research-and-decision-brief`:

> Determine whether the proposed storage change fits this repository's current
> recovery contract. Separate local facts, current primary-source claims, and
> inference; challenge provenance and counterevidence; then return one
> confidence-calibrated conclusion with limitations and referenced files.

Use **Advanced → Referenced files** on the start form when the team must inspect a particular workspace file. Banksia records each path and optional description, not a copy of the file.

For a substantial computational or empirical program that needs durable execution and independent replication, choose `experiment-and-replication-program` instead.

## CLI alternative

The Console is the clearest catalog and run view. The terminal can start the same published Workflow interactively:

```bash
./.venv/bin/banksia task start
```

Automation can pass one strict JSON object inline, from `@file`, or through standard input:

```bash
./.venv/bin/banksia task start --json \
  '{"workflow":"production-feature-delivery","prompt":"Deliver the cross-layer configuration recovery experience, verify the integrated behavior and release risks, repair accepted findings, and return the result."}'
```

The controller must already be running. CLI-started runs use the invocation directory as their workspace. To start from another project, change to that directory and invoke the absolute path to the Banksia checkout's `.venv/bin/banksia`.

Next, [compare every Starter](../../examples/workflows/README.md), learn how to [author a Workflow](../guides/author-a-workflow.md), or learn how to [operate a run](../guides/run-and-operate.md).
