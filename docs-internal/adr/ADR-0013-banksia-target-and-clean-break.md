# ADR-0013: Banksia target and clean break

Status: Accepted

## Decision summary

Banksia is the product identity, and the maintained subject owners routed from the [internal documentation](../README.md) are its implementation authority. Banksia is a reset-only clean break: one authored Workflow definition, Task/Attempt/Delegation Wave runtime ownership, one shared native workspace, semantic product interfaces, and no AutoClaw compatibility aliases or version-era canon.

## Context

The imported AutoClaw 0.1.8 implementation contains valuable controller mechanisms: relational currentness, immutable source lineage, conditional winner writes, exact Dispatch requests, typed waits, recovery, structural history, durable Checkpoints, and audit chronology. Its public and model-facing shape is substantially more complex than the intended product. Role, Policy, generic Definition compilation, Task Compose, criteria/consume/produce, controller-owned Artifact resources, staged single-child yield, Flow-wide currentness, request-file projections, and runtime-shaped product interfaces must not become Banksia merely through renaming.

The repository also carried simultaneous V1 target, V2 target, current contrast, temporary research, and implementation proposals. Continuing to route agents among those surfaces would leave product authority ambiguous during a multi-package migration.

## Decision

### Banksia identity and authority

The product is Banksia. Its eventual released identities are:

- distribution `banksia`;
- Python import, module, and CLI `banksia`;
- environment and service namespace `BANKSIA_` / `banksia`;
- Console package `@banksia/console`; and
- first release `0.1.0`.

The [Banksia internal documentation](../README.md) routes the authoritative subject owners. Git history preserves deleted migration evidence and prior rationale; it is not a second source of current product, schema, workspace, prompt, tool, or runtime truth.

### Preserve-first implementation

Banksia is reached through evolutionary replacement, not a second runtime and not a delete-and-rewrite event. Each implementation package must:

1. name the target invariant;
2. identify and characterize the proven current mechanism;
3. land the minimum replacement authority seam;
4. move every authoritative writer and reader;
5. prove the replacement through shipped paths; and
6. delete the old path or record a phase-bounded bridge with an exact removal package.

Controller authority, exact lineage, currentness, commit-before-effect, duplicate/lost-signal recovery, provider-start retry, watchdog recovery, typed waits, terminal relation selection, structural compare-and-swap, lifecycle controls, and raw audit chronology remain protected properties even when their record names or owners change.

### One authored Workflow and reset-only state

Workflow is the only authored, draftable, publishable definition. It is one recursive Member responsibility hierarchy with optional team guidance, per-Member provider intent, and narrow default-deny Human Request and managed Command Run grants. JSON and YAML are encodings of the same normalized schema.

Banksia has no released Role, Policy, Skill, generic Definition, external MCP, authored step/stage/schedule graph, Task Compose, criteria, consume, produce, generic capability, or compatibility authoring model. Published Workflow revisions are immutable and Tasks pin one exact revision.

The Banksia schema starts from reset state. AutoClaw databases, definitions, configuration, state directories, imports, commands, and public payloads are not migrated or accepted through aliases. A temporary internal adapter is legal only when a work package names and tests it and a later package deletes it before release.

### Task, Attempt, and Delegation Wave ownership

Task owns global lifecycle, workspace binding, pinned Workflow revision, current team head, controls, and the exact root Result relation. Assignment is one immutable complete request for one Member. Attempt is one execution lane and owns at most one current Dispatch or one typed wait. A Delegation Wave is one immutable ordered, controller-managed fan-out/fan-in group of direct-child Assignments.

The responsibility tree does not encode time. Managers choose sequence, parallelism, iteration, batch work, and hybrid composition at runtime. Local Attempt waits and Wave joins replace Flow-wide single-current delegation and mutable active-set or completion-counter designs. A terminal Task-lead green or blocked Checkpoint is the exact user Result; provider terminal output and a second model summary are never completion authority.

### Shared native workspace and loose files

Every Task binds one provider-visible workspace shared by all Members. The physical `.banksia/t_<id>/` directory contains only the organization manifest, an optional Workflow-note projection, controller-created `notes/`, `artifacts/`, and `command-runs/` directories, and visible Command Run output. The database remains runtime truth.

Notes and artifact files are ordinary mutable workspace files. A generic file reference is only an ordered workspace-relative path plus optional short description on its owning Assignment, Checkpoint, or Human Request. Banksia does not create a generic file resource, copy, hash, version, current pointer, or content registry. Native provider filesystem access replaces Banksia list/read/write-note tools.

### Semantic product surface

The ordinary HTTP, Console, CLI, and Operator experience communicates Workflow and Run meaning, attention, legal actions, semantic Activity, referenced files, and the exact Result. Assignment, Attempt, Dispatch, Boundary, Wave, revisions, hashes, provider routing, raw events, and protected audit details stay in a separate support and audit plane.

The Console is an independently authored React/Tailwind product for nontechnical users. Pinned n8n source and curated screenshots may inform mature interaction behavior only under the tracked provenance protocol; no n8n code, markup, CSS, tests, strings, tokens, assets, enterprise files, or product model enters Banksia.

### No released compatibility or version-era canon

The final repository has one Banksia implementation and one live documentation system. No AutoClaw import, CLI, environment, config, database, service, generated-contract, UI, or documentation alias ships. No V1/V2/vnext/current target lane remains live. Git history is the historical archive.

External MCP integration, Skills, distributed execution, a Task-wide provider queue, isolated worktrees and automatic merge, directory/remote file references, authored execution phases, and free-positioned canvas nodes remain deferred without placeholder schema.

## Consequences

- Implementation can retain robust controller mechanics without forcing users to author or understand those mechanics.
- Every removed concept needs an explicit writer/read/deletion ledger and replacement proof; clean break does not mean unsafe bulk deletion.
- Reset is required at Banksia identity and schema cutover. Existing AutoClaw state remains historical data, not an input accepted by the new product.
- Reference examples and packaged Starter Workflow seeds remain separate. Only the provider-neutral seed inventory is eligible for bootstrap.
- Git history preserves deleted migration evidence without creating a second live authority.
- Release is blocked by any surviving compatibility bridge, target-authority fork, unowned invariant, or unexplained required-proof gap.

## Alternatives rejected

### Rename AutoClaw in place and retain its public model

Rejected because naming obsolete Role/Policy/compiler/Artifact/Flow concepts after Banksia would preserve the complexity and authoring burden the product is designed to remove.

### Delete the implementation and rebuild from scratch

Rejected because it would discard proven concurrency, recovery, source lineage, conditional-write, persistence, and audit behavior and make subtle regressions difficult to detect.

### Ship compatibility aliases or migrate AutoClaw state

Rejected because dual names and schemas create parallel authority, enlarge the test matrix, and obscure whether runtime behavior follows the old or new contract. This first Banksia baseline is reset-only.

### Keep V1/V2/current as parallel live canon

Rejected because an implementation agent cannot resolve contradictory target truth safely from chronology. Maintained subject owners provide one explicit authority; Git history preserves deleted evidence.

### Put orchestration timing in Workflow authoring

Rejected because responsibility is reusable while sequence, parallelism, iteration, and batch choices depend on the actual Task and current evidence.

## Proof obligations

- Every preserved invariant has an owner and direct proof through the applicable command matrix in the root agent contract.
- Workflow schema, maintained reference examples, and packaged seeds validate as distinct inventories; seeds contain no provider or capability fields.
- Each package proves new authority before deleting the old reader/writer and records any temporary bridge plus its deletion package.
- Final fresh-clone, reset, SQLite, PostgreSQL, provider, runtime, Console, browser, accessibility, docs, and package lanes pass through shipped paths.
- Exact searches find no released AutoClaw identity, compatibility alias, obsolete public concept, ignored-reference dependency, or live version-era owner.
- Two independent whole-program review and repair rounds finish with no open P0/P1 or release-blocking evidence gap before a release go decision.

## Canonical references

- [Banksia internal documentation](../README.md)
- [Product and Workflow](../architecture/product-and-workflow.md)
- [Runtime](../architecture/runtime.md)
- [Workspace, files, and prompt](../architecture/workspace-files-and-prompt.md)
- [Console and Operator](../interfaces/console-and-operator.md)
- [Banksia coding agent contract](../../AGENTS.md)
