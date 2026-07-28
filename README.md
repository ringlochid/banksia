<p align="center"> <img src="console/public/assets/banksia-mark.svg" alt="Banksia recursive team mark" width="128" height="128"> </p>

<h1 align="center">Banksia</h1>

<p align="center"><strong>Build adaptable, accountable AI teams in minutes—and run them on complex work.</strong></p>

<p align="center">Design them easily, run them reliably, and stay in control from the first decision to the final Result.</p>

<p align="center"> <a href="https://pypi.org/project/banksia/"><img src="https://img.shields.io/pypi/v/banksia" alt="PyPI version"></a> <a href="https://pypi.org/project/banksia/"><img src="https://img.shields.io/badge/python-%3E%3D3.12-3776AB?logo=python&logoColor=white" alt="Python 3.12 or newer"></a> </p>

<p align="center"> <a href="docs/start/getting-started.md">Get started</a> · <a href="docs/README.md">Documentation</a> · <a href="examples/workflows/README.md">Starter teams</a> </p>

## Install and start

Banksia requires Python 3.12 or newer and currently supports Linux and macOS. Install the command-line application in an isolated environment with [pipx](https://pipx.pypa.io/stable/):

```bash
pipx install banksia
banksia init
banksia serve
```

Open `http://127.0.0.1:18125/`. The installed package includes the visual Console. Guided initialization chooses a default workspace, configures a Task provider, and can configure the separate Operator that helps you build and run teams.

Banksia uses SQLite by default, so a local installation needs no database server. For PostgreSQL, install the optional driver and supply a SQLAlchemy URL during initialization:

```bash
pipx install "banksia[postgres]"
banksia init \
  --database-url "postgresql+asyncpg://banksia@127.0.0.1/banksia"
```

See [Getting started](docs/start/getting-started.md) for provider prerequisites and a complete first run, or [Database configuration](docs/reference/configuration.md#database) for PostgreSQL permissions, schemas, and environment overrides.

## Design and operate visually

The Console is the primary Banksia experience. It keeps the common path no-code while preserving advanced provider, sandbox, and capability controls when a team needs them.

- **Workflow library** makes reusable teams and drafts easy to find, compare, start, or remove.
- **Workflow Studio** shows the complete responsibility hierarchy on a horizontal canvas. Add a child with one `+`, select any Member to edit its purpose and instructions, validate the draft, and publish an immutable revision explicitly.
- **Run Studio** shows the live team, current plan, meaningful Activity, requests that need your attention, managed Actions, referenced files, and the exact completed or blocked Result.

The **Operator** is a separate conversational agent inside the Console. Ask it to draft or revise a Workflow, explain the current team, validate and publish when you request it, start and control Runs, answer Human Requests, or inspect managed Action output. It uses the same controller-owned operations as the visual interface, so chat does not create a second hidden source of truth.

## Why Banksia

Banksia makes complex multi-agent work easier to create, adapt, recover, and trust:

- **Create an AI team easily.** Use the visual Console or conversational Operator to shape, publish, and run a reusable team.
- **Let the team adapt how it works.** Managers choose sequential, parallel, iterative, batch, or hybrid work from the Task and current evidence.
- **Keep complex work moving.** Durable state lets eligible work pause, wait, replan, retry safely, recover, and resume without discarding accepted history.
- **Stay accountable from start to Result.** Follow explicit responsibility, team revisions, decisions, Activity, referenced files, managed Actions, and the one Result accepted by the lead.

## What a team can do

A Workflow defines reusable responsibility rather than a fixed schedule. You publish a team, give its lead one complete prompt, and let each Manager choose the approach that fits the work. If the current team itself no longer fits, a bounded replan changes its responsibility tree while preserving earlier revisions and completed work.

- Delegate through a responsibility tree without forcing a fixed sequence into the Workflow.
- Combine independent research, implementation, criticism, integration, and verification.
- Ask you a typed question when an authorized Member genuinely needs a decision.
- Run a managed command when the Workflow explicitly grants that capability.
- Replan a current responsibility subtree without rewriting the Task's earlier team or work history.
- Preserve progress across browser or provider interruption.
- Return one human-readable Result with direct references to detailed workspace files.

Capabilities deny by default and never inherit from a parent. Provider, model, sandbox, and capability choices remain available when a team needs them, without making them mandatory for every Workflow.

## Upgrade ad-hoc delegation

If you already coordinate subagents by hand, Banksia turns those recurring delegation patterns into reusable teams without making subagents the product boundary:

| Ad-hoc subagents                              | Banksia                                                                                |
| --------------------------------------------- | -------------------------------------------------------------------------------------- |
| Recreate roles and prompts for every job      | Publish a reusable tree of named responsibilities                                      |
| Reconstruct ownership from a transcript       | Follow controller-owned team, activity, and wait state                                 |
| Treat provider completion as the outcome      | Accept only the lead's final `green` or `blocked` Result                               |
| Recover by piecing together terminal sessions | Recover from durable controller records; keep deliverables in ordinary workspace files |

## Start with a proven team

`banksia init` publishes eight provider-neutral Starters. Choose one when the work is consequential or broad enough that independent responsibility can improve the outcome:

| Starter                                 | Use it when                                                                                                                             |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `production-feature-delivery`           | A feature crosses contracts, implementation boundaries, integrated verification, and release readiness.                                |
| `incident-investigation-and-recovery`   | A serious or intermittent failure needs competing hypotheses, supported recovery, verification, and prevention.                        |
| `migration-and-modernisation`           | A large migration needs inventory, dependency-aware batches, cutover, and stale-path removal.                                           |
| `deep-research-and-decision-brief`      | A consequential question needs independent evidence, claim verification, and one accountable recommendation.                           |
| `decision-through-competing-prototypes` | Alternatives should be tested under one fair rubric instead of decided from prose alone.                                                |
| `idea-to-validated-demo`                | A product idea should become an evidence-backed position, working first demo, launch strategy, and credible pitch.                      |
| `experiment-and-replication-program`    | An empirical or computational program needs explicit methods, durable execution, independent replication, and claim audit.             |
| `security-audit-and-hardening`          | A security program needs attack-surface mapping, specialised audits, validated remediation, and adversarial re-verification.            |

The [Starter catalog](examples/workflows/README.md) includes example missions, expected deliverables, and guidance on when a simpler team is better.

## How a run works

1. **Choose or design a team.** Start from a Starter or shape a responsibility tree in Workflow Studio.
2. **Publish a stable revision.** Every run keeps the exact team contract it started with.
3. **Give the lead one complete prompt.** The team plans, delegates, adapts, and records meaningful progress while detailed work stays in ordinary workspace files.
4. **Follow the work and receive the Result.** Answer real Human Requests, inspect managed Actions, and read the lead's exact final outcome.

## Know before you start

Banksia is best suited to complex developer and researcher work on a trusted local machine. The controller runs as one loopback-bound process, and every Member in a Task shares one provider-visible workspace.

Codex and Claude are managed providers. OpenClaw is a user-operated compatibility transport. Native Windows is not currently supported; WSL2 uses the Linux path. External MCP servers, reusable Skills, distributed delivery, broad multi-user operation, and per-Member isolated workspaces are outside the current product boundary.

## Documentation

- [Getting started](docs/start/getting-started.md)
- [Understand Workflows and teams](docs/concepts/workflows-and-teams.md)
- [Author a Workflow](docs/guides/author-a-workflow.md)
- [Run and operate work](docs/guides/run-and-operate.md)
- [Use the Console and Operator](docs/guides/console-and-operator.md)
- [Configure Banksia](docs/reference/configuration.md)
- [Troubleshoot an installation](docs/help/troubleshooting.md)
- [Contribute](CONTRIBUTING.md)
- [Report an issue](https://github.com/ringlochid/banksia/issues)

Banksia is open source under the [MIT License](LICENSE), except for the visual Console in [`console/`](console/), which contains material derived from n8n and is distributed under the [Sustainable Use License](console/LICENSE). That license permits internal business, non-commercial, and personal use; redistribution is limited to free, non-commercial distribution. See the [Console notice](console/NOTICE) for attribution and the modification notice.
