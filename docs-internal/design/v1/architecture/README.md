# Design architecture

Status: Target

This surface is the architecture front door for the design.

The architecture now centers on:

- controller/DB state as the only runtime truth owner
- `dispatch` ingress plus `yield | green | retry | blocked` egress
- explicit parent/root control tools instead of a live `parent_gate` runtime surface
- `criteria`, `consumes`, and `produces` as the live assignment contract family
- runtime-generated workflow-manifest, assignment, checkpoint, artifact, transient, and observability projections
- path-only surfaced refs in v1
- filesystem-first worker reread
- write-only callback scoped by task and authorized by trusted session binding
- many tasks running concurrently with one live execution slot per task flow lineage
- watchdog and provider-monitoring projections kept separate from ordinary task truth
- canonical route lanes `/definitions`, `/tasks`, `/runtime`, `/operator`, `/callback`, and `/observability`
- OpenClaw documented as an adapter-normalization layer, not the canonical runtime model
- workflow, role, and policy definition truth uses identity rows plus immutable revision rows

## Search-first routing

If you are asking:

- "What is the shortest picture of the design?" -> [Design overview](design-overview.md)
- "What is the exact controller loop and boundary model?" -> [Runtime boundary and controller loop](runtime-boundary-and-controller-loop-contract.md)
- "What records and lifecycle facts does the controller own?" -> [Runtime records and lifecycle](runtime-records-and-lifecycle.md) and [Runtime database and object contract](runtime-database-and-object-contract.md)
- "What is the narrative end-to-end lifecycle across launch, dispatch, checkpoint, and closure?" -> [Runtime lifecycle overview](runtime-lifecycle-overview.md)
- "What is the worker-facing shared context and contract-family model?" -> [Manifest contract](manifest-contract.md), [Assignment contract](assignment-contract.md), [Checkpoint contract](checkpoint-contract.md), and [Worker context contract](worker-context-contract.md)
- "What do the task-root files and folders mean?" -> [Task root layout and generated files](task-root-layout-and-generated-files.md) and [Filesystem layout and roots](filesystem-layout-and-roots.md)
- "How do artifacts, current pointers, and surfaced refs work?" -> [Artifact ref and storage contract](artifact-ref-and-storage-contract.md)
- "How do watchdog, continuity, and provider monitoring work on observability surfaces?" -> [Runtime monitoring and watchdog automation](runtime-monitoring-and-watchdog-automation.md), [Watchdog and recovery contract](watchdog-and-recovery-contract.md), and [Runtime observability and boundary log](runtime-observability-and-boundary-log.md)
- "Where does OpenClaw fit?" -> [OpenClaw Gateway RPC subset](openclaw-gateway-rpc-subset.md), [OpenClaw session lifecycle](openclaw-session-lifecycle.md), [OpenClaw continuity and send modes](openclaw-continuity-and-send-modes.md), and [OpenClaw worker and gateway contract](openclaw-worker-and-gateway-contract.md)
- "What exact Gateway handshake and machine-control subset does AutoClaw depend on?" -> [OpenClaw Gateway RPC subset](openclaw-gateway-rpc-subset.md)
- "How do provider, node, operator, and the canonical route lanes split?" -> [Provider, worker, and operator boundary](provider-worker-and-operator-boundary.md) and [Runtime lane separation rationale](runtime-lane-separation-rationale.md)

## Historical-term routing

If you are searching with old design words, route directly to the live owner:

- `brief`, `flow-brief`, `scope-brief`, or `_runtime/views/` -> [Manifest contract](manifest-contract.md), [Worker context contract](worker-context-contract.md), [Task root layout and generated files](task-root-layout-and-generated-files.md), and [Artifact ref and storage contract](artifact-ref-and-storage-contract.md)
- `execution slice`, `lineage ack`, `manifest ack`, or worker acknowledgement phrasing -> [Manifest contract](manifest-contract.md), [Worker context contract](worker-context-contract.md), and [Runtime records and lifecycle](runtime-records-and-lifecycle.md)
- `manifest slice` or manifest-plus-slice wording -> [Manifest contract](manifest-contract.md), [Worker context contract](worker-context-contract.md), and [Runtime records and lifecycle](runtime-records-and-lifecycle.md)
- `packet`, `bundle`, `handoff packet`, or `storage_uri` -> [Artifact ref and storage contract](artifact-ref-and-storage-contract.md), [Worker context contract](worker-context-contract.md), and [Filesystem layout and roots](filesystem-layout-and-roots.md)
- `release bundle`, `RootReleaseBundle`, or `ParentEvidenceBundle` -> [Runtime boundary and controller loop contract](runtime-boundary-and-controller-loop-contract.md), [Parent/root release and closure](../workflows/parent-root-release-and-closure.md), and [Artifact ref and storage contract](artifact-ref-and-storage-contract.md)
- `packetized completion`, completion bundle, or evidence bundle wording -> [Completion, checkpoint, and evidence](completion-checkpoint-and-evidence.md), [Criteria and parent verification](../workflows/criteria-and-parent-verification.md), and [Artifact ref and storage contract](artifact-ref-and-storage-contract.md)
- `OpenClaw session and continuity contract` -> [OpenClaw session lifecycle](openclaw-session-lifecycle.md), [OpenClaw continuity and send modes](openclaw-continuity-and-send-modes.md), and [OpenClaw worker and gateway contract](openclaw-worker-and-gateway-contract.md)
- `Gateway RPC subset`, `hello-ok`, `connect.challenge`, `agent.wait`, or `sessions.abort` -> [OpenClaw Gateway RPC subset](openclaw-gateway-rpc-subset.md)

## Start here

- [Design overview](design-overview.md)
- [Runtime records and lifecycle](runtime-records-and-lifecycle.md)
- [Runtime boundary and controller loop](runtime-boundary-and-controller-loop-contract.md)
- [Assignment contract](assignment-contract.md)
- [Checkpoint contract](checkpoint-contract.md)
- [Runtime database and object contract](runtime-database-and-object-contract.md)
- [Manifest contract](manifest-contract.md)
- [Worker context contract](worker-context-contract.md)
- [Task root layout and generated files](task-root-layout-and-generated-files.md)
- [Runtime lifecycle overview](runtime-lifecycle-overview.md)
- [Provider, worker, and operator boundary](provider-worker-and-operator-boundary.md)
- [OpenClaw Gateway RPC subset](openclaw-gateway-rpc-subset.md)
- [Runtime lane separation rationale](runtime-lane-separation-rationale.md)
- [Runtime monitoring and watchdog automation](runtime-monitoring-and-watchdog-automation.md)

## Surface rule

Use this surface for controller-owned runtime truth, the live assignment contract family, generated projections, observability separation, and adapter normalization.
