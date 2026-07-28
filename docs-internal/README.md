# Banksia internal documentation

Status: Reference

This is the maintainer-facing source of truth for Banksia's shipped product contracts and implementation boundaries. Public user documentation lives under [`docs/`](../docs/README.md).

## Architecture

- [Product and Workflow](architecture/product-and-workflow.md) owns product language, Workflow authoring, publication, Task start, and Assignment.
- [Runtime](architecture/runtime.md) owns controller records, currentness, Delegation Waves, replan, waits, Checkpoints, and Result selection.
- [Workspace, files, and prompt](architecture/workspace-files-and-prompt.md) owns the shared native workspace, Task files, file references, Dispatch requests, and current-context data boundary.
- [Task-member system prompts](architecture/system-prompts.md) owns exact controller-maintained prompt assets and behavior evaluations.

## Interfaces

- [Built-in runtime tools](interfaces/runtime-tools.md) owns the exact Task-member and Operator operation catalogs.
- [Console and Operator](interfaces/console-and-operator.md) owns product APIs, Console information architecture, and the separate Operator experience.
- [Operator conversation contract](interfaces/operator-conversation-contract.md) owns Operator persistence, provider turns, typed questions, and interruption behavior.

## Operations

- [Configuration and providers](operations/configuration-and-providers.md) owns configuration precedence, workspace defaults, provider selection, credentials, and adapter boundaries.
- [Recovery and observability](operations/recovery-and-observability.md) owns startup recovery, runtime health, projections, support access, and audit readback.
- [Package and reset](operations/package-and-reset.md) owns distribution contents, installed proof, schema verification, and destructive reset.

## Decisions

- [Accepted decisions](adr/README.md) retains durable rationale. Subject owners above remain authoritative for implementation.

## Ownership rule

Keep one factual owner for each contract. Generated readbacks, ordinary workspace files, provider output, screenshots, ignored research, and support projections never override controller truth or these owner pages.
