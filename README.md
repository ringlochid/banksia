<h1 align="center">Banksia</h1>

<p align="center"><strong>Accountable AI teams for complex work.</strong></p>

<p align="center"> <a href="docs/start/getting-started.md">Get started</a> · <a href="docs/README.md">Documentation</a> · <a href="examples/workflows/README.md">Workflow examples</a> </p>

## Turn subagent workflows into accountable AI teams

Banksia is a no-code AI-team runtime for developers, researchers, and anyone who uses multiple agents to complete complex work accountably.

You operate Banksia as a product rather than embed it as an agent SDK; the controller owns published teams, run state, and completion.

Design reusable responsibilities without hard-coding how the work unfolds. Give the team one complete prompt, follow meaningful progress, respond when a real decision needs you, and receive one exact Result.

> [!WARNING]
> Banksia is in active development. Its public contracts are being stabilized,
> and it is not yet recommended for production-critical workloads.

## From ad-hoc subagents to a reusable team

| Ad-hoc subagents | Banksia |
| --- | --- |
| Recreate roles and prompts for every job | Publish a reusable tree of named responsibilities |
| Reconstruct ownership from a transcript | Follow controller-owned team, activity, and wait state |
| Treat provider completion as the outcome | Accept only the lead's exact `green` or `blocked` Result |
| Recover by piecing together terminal sessions | Recover from durable controller records; keep deliverables in ordinary workspace files |

Banksia gives you:

- explicit responsibility and delegation boundaries;
- sequential, parallel, iterative, batch, or hybrid work chosen from current evidence;
- independent implementation, research, criticism, and verification roles;
- typed human decisions and managed command activity when explicitly granted; and
- one inspectable Result with direct references to the files that carry the detailed work.

## Get to a first Result

Banksia is not yet published to a package registry. Use a clean source checkout with Python 3.12 or newer, Make, and a supported Node.js/npm installation:

```bash
git clone https://github.com/ringlochid/banksia.git
cd banksia
make backend-install
make console-install
make console-package-assets
./.venv/bin/banksia init
./.venv/bin/banksia setup
./.venv/bin/banksia serve
```

`make console-package-assets` prepares the visual Console served by the source checkout. Open `http://127.0.0.1:18125/`, go to **Runs**, and start a run with the `reviewed-code-change` Starter:

> Add validation for the configuration import failure path without changing
> accepted behavior. Follow current repository conventions, add focused
> regression proof, independently review the integrated change, repair accepted
> findings, and return the verified result with referenced files.

Watch who owns the work, read meaningful Activity, then read the exact Result and open its referenced files in your workspace. The [getting-started guide](docs/start/getting-started.md) includes the complete developer path and a researcher path using `evidence-synthesis`.

## Start with a team

`banksia init` publishes seven portable Starters:

| Developer work | Research and decisions |
| --- | --- |
| `reviewed-code-change` | `evidence-synthesis` |
| `debug-and-verify` | `reproducible-study` |
| `cross-layer-feature` | `technical-decision` |
| `bounded-maintenance-batch` |  |

Each Starter separates ownership from independent challenge or verification. Three maintained [advanced references](examples/workflows/README.md) show how to add deliberate provider, sandbox, network, Human Request, and Command Run choices.

## The product loop

**Design → Publish → Run → Respond → Result**

1. **Design** a Workflow definition as a tree of responsibilities, not a timed sequence.
2. **Publish** an immutable revision so every run has a stable team contract.
3. **Run** that revision with one prompt, one workspace, and optional file references.
4. **Respond** only when an explicitly capable Member opens a Human Request, or control the run when a current action is legal.
5. **Result** is the lead's exact final `green` or `blocked` Checkpoint, with referenced files for detailed deliverables.

## Current scope

- Banksia runs as one loopback-bound process and is local-tool-first.
- Codex and Claude are managed providers. OpenClaw is a compatibility transport that you configure and operate.
- A run uses one shared provider-visible workspace. Per-Member isolation and automatic merging are not current product behavior.
- Human Request and Command Run capabilities deny by default. The installed Starters grant neither.
- File references record a workspace-relative path and optional description, not a snapshot. A referenced file can later change or disappear.
- External MCP servers, reusable Skills, distributed delivery, and broad multi-user operation are deferred.
- The Console supports the current authoring and operating paths and is currently desktop-oriented. Mature visual design and mobile/tablet experiences are deferred.

## Learn more

- [Choose a guide by intent](docs/README.md)
- [Understand Workflows and teams](docs/concepts/workflows-and-teams.md)
- [Author a Workflow](docs/guides/author-a-workflow.md)
- [Run and operate work](docs/guides/run-and-operate.md)
- [Use the Console and Operator](docs/guides/console-and-operator.md)
- [Troubleshoot an installation](docs/help/troubleshooting.md)
- [Contribute to Banksia](CONTRIBUTING.md)
- [Report an issue](https://github.com/ringlochid/banksia/issues)

Banksia is open source under the [MIT License](LICENSE).
