# Design docs

Status: Target

This tree describes the target design contract.

Use it to answer two questions:

- what the settled runtime model is supposed to be
- which pages are live owner docs

The current runtime direction is:

- controller/DB state owns runtime truth
- DB-backed registry identity rows plus immutable revision rows own definition truth after successful import or guarded upload
- canonical local definition import is one file or a shallow current-working-directory scan
- public boundaries are `dispatch` ingress and `yield | green | retry | blocked` egress
- parent/root control uses explicit tools such as `assign_child` and `release_green`
- `criteria`, `consumes`, and `produces` are the live assignment contract family
- workflow-manifest, assignment, checkpoint, artifact, and transient surfaces are controller-derived projections
- surfaced refs are path-only in v1
- worker reread is filesystem-first
- callback is write-only, task-scoped, and resolved from trusted controller-owned session authority
- many tasks may run concurrently while one task flow lineage keeps one live execution slot at a time
- watchdog and provider-monitoring files under `_runtime/dispatch/` are observability projections, not ordinary task truth
- watchdog recovery is internal controller behavior; observability surfaces are inspect-only
- canonical route lanes are `/definitions`, `/tasks`, `/runtime`, `/operator`, `/callback`, and `/observability`
- `tool` is the canonical runtime term; `plugin` is adapter-specific only

If a downstream design page still teaches gate-era, handoff-era, or scope-manifest vocabulary, treat the owner pages in this tree and the accepted ADRs under `../../adr/` as the canonical design source of truth.

## Canonical owner entrypoints

- [Architecture overview](architecture/design-overview.md)
- [Runtime boundary and controller loop](architecture/runtime-boundary-and-controller-loop-contract.md)
- [Runtime records and lifecycle](architecture/runtime-records-and-lifecycle.md)
- [Assignment contract](architecture/assignment-contract.md)
- [Checkpoint contract](architecture/checkpoint-contract.md)
- [Manifest contract](architecture/manifest-contract.md)
- [Worker context contract](architecture/worker-context-contract.md)
- [Prompt contract](prompt-layer/contract.md)
- [Workflow definition schema](workflows/workflow-definition-schema.md)
- [API surface and trust-lane map](interfaces/api-surface-and-trust-lane-map.md)

## Settled Runtime Model At A Glance

The shortest concrete summary of the settled model is:

- controller/DB state owns runtime truth
- `dispatch` is the only ingress boundary
- `yield | green | retry | blocked` are the only public egress boundaries
- workflow, role, and policy registry truth uses identity tables plus immutable revision tables
- parent/root nodes act through explicit tools such as `assign_child`, `add_child`, `update_child`, `remove_child`, `release_green`, and `release_blocked`
- assignment is the forward-looking mission contract, and `criteria`, `consumes`, and `produces` are its live contract family
- checkpoint is the backward-looking attempt summary and next-step handover
- retry is node-self only and keeps the same assignment while minting a new attempt
- artifacts are immutable durable publications with explicit controller-owned current pointers
- surfaced refs are path-only in v1
- worker reread is filesystem-first
- callback is write-only, task-scoped, and resolved from trusted controller-owned session authority
- different tasks may execute concurrently while one task flow lineage keeps one live execution slot at a time
- canonical route lanes are `/definitions`, `/tasks`, `/runtime`, `/operator`, `/callback`, and `/observability`
- watchdog and provider projections under `_runtime/dispatch/` are observability surfaces, not ordinary task truth
- local definition import is file-based or shallow current-directory scan only; it is not a configured runtime root
- watchdog recovery is internal and deterministic, not a canonical API control path

## Routing rule

When in doubt:

1. read the architecture owner pages first
2. read the prompt-layer and interface owner pages second
3. use the ADR lane for the durable why, not older implementation leftovers
4. do not recreate deleted archive or execution trees just to satisfy stale references

## Search-first routing

If you are asking:

- "What is the runtime loop and boundary model?" -> [Architecture overview](architecture/design-overview.md), [Runtime boundary and controller loop](architecture/runtime-boundary-and-controller-loop-contract.md), and [Runtime records and lifecycle](architecture/runtime-records-and-lifecycle.md)
- "Who owns truth and what is only a projection?" -> [Runtime database and object contract](architecture/runtime-database-and-object-contract.md), [Manifest contract](architecture/manifest-contract.md), and [Runtime monitoring and watchdog automation](architecture/runtime-monitoring-and-watchdog-automation.md)
- "What files does a node read and what do they mean?" -> [Task root layout and generated files](architecture/task-root-layout-and-generated-files.md), [Filesystem layout and roots](architecture/filesystem-layout-and-roots.md), and [Worker context contract](architecture/worker-context-contract.md)
- "What is the current assignment/checkpoint/artifact and `criteria` / `consumes` / `produces` model?" -> [Assignment contract](architecture/assignment-contract.md), [Checkpoint contract](architecture/checkpoint-contract.md), [Artifact ref and storage contract](architecture/artifact-ref-and-storage-contract.md), and [Manifest contract](architecture/manifest-contract.md)
- "How do prompts teach the runtime model?" -> [Prompt contract](prompt-layer/contract.md), [Prompt machine contract](prompt-layer/machine-contract.md), and [Prompt source and sections](prompt-layer/source-and-sections.md)
- "What are workflow definitions, roles, policies, and the `/definitions` lane?" -> [Workflow definition schema](workflows/workflow-definition-schema.md), [Task compose schema](workflows/task-compose-schema.md), and [Role and policy definition schema](interfaces/role-and-policy-definition-schema.md)
- "How do provider-native capabilities fit without generic `skill_refs`?" -> [Provider direction and provider-native capabilities](workflows/provider-direction-and-provider-native-capabilities.md), [Workflow definition schema](workflows/workflow-definition-schema.md), and [Plugin tool reference](interfaces/plugin-tool-reference.md)
- "What are the public tools, canonical lanes, and machine-readable query params (`/definitions`, `/tasks`, `/runtime`, `/operator`, `/callback`, `/observability`)?" -> [API surface and trust-lane map](interfaces/api-surface-and-trust-lane-map.md), [API schema appendix](interfaces/api-schema-appendix.md), [API machine catalog](interfaces/api-machine-catalog.yaml), and [Plugin tool reference](interfaces/plugin-tool-reference.md)
- "How do OpenClaw sessions, continuity, and recovery fit in?" -> [OpenClaw session lifecycle](architecture/openclaw-session-lifecycle.md), [OpenClaw continuity and send modes](architecture/openclaw-continuity-and-send-modes.md), and [Watchdog and provider recovery](architecture/watchdog-and-provider-recovery.md)
- "How do I import local definitions and then trust DB-backed registry truth?" -> [Definition ingest and task-start file contract](interfaces/definition-ingest-and-upload-contract.md) and [Definition registry and upload contract](interfaces/definition-registry-and-upload-contract.md)
- "How do I onboard, debug, or recover the system?" -> [How-to guides](how-to/README.md) and [Tutorials](tutorials/README.md)
- "Which decisions froze the live model?" -> [Durable decisions](../../adr/README.md)

## Start here

- [Architecture](architecture/README.md)
- [Prompt layer](prompt-layer/README.md)
- [Workflows](workflows/README.md)
- [Interfaces](interfaces/README.md)
- [How-to guides](how-to/README.md)
- [Tutorials](tutorials/README.md)
- [Durable decisions](../../adr/README.md)

## Keywords

- controller-owned runtime truth
- staged assignment model
- dispatch and egress boundaries
- assignment and checkpoint context
- checkpoint kind and terminal outcome
- artifact current pointer
- runtime materializer/projector
- path-only surfaced refs
- canonical route lanes
- watchdog projections
- OpenClaw adapter normalization
- validator versus compiler
- criteria consumes produces
- curated context reference files

## Key surfaces

- `architecture/` owns runtime truth, generated projections, monitoring, and adapter normalization.
- `prompt-layer/` owns how the runtime model is taught to nodes.
- `workflows/` owns authored workflow definition, criteria, role, and policy shaping.
- `interfaces/` owns `/definitions`, `/tasks`, `/runtime`, `/operator`, `/callback`, `/observability`, machine-readable route/tool discovery, and adapter-facing trust lanes.
- `../../adr/` owns the durable why and accepted cross-cutting invariants.
- `how-to/` and `tutorials/` own target-facing usage guidance.

## Implementation contrast

Current shipped implementation truth still lives under the [Current architecture front door](../../current/v1/architecture/README.md) until the design lands in code.

## Surface rule

Use the owner pages in this tree for target contract decisions.

Use current docs and archived review logs only for migration contrast or shipped-behavior checks.
