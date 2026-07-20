# Typed Dependency Selectors And Produce Slots

Status: Target

This page owns authored selector shape, produce-slot declarations, slot identity, deterministic dependency legality expectations, and runtime surfaced ref semantics for those authored contracts.

## Canonical authored selector and slot shapes

```yaml
consume_selector:
    slot: slot_id
    required: true | false # optional; defaults to true

produce_slot:
    slot: slot_id
    description: string
    file_hint: string | optional

criteria_declaration:
    slot: slot_id
    description: string
    criteria:
        - string
```

`required` meaning is intentionally narrow:

- `required: false` does not make authored selector resolution optional during preview, task start, or runtime structural adopt
- the selected slot must still exist and still contributes a real dependency edge
- the flag is preserved into normalized compiled nodes and later manifest or assignment projections so runtime can distinguish optional publication absence from hard-missing publication

## Authored dependency buckets

The authored dependency buckets are:

- `consumes.artifacts`
- `consumes.criteria`
- `produces.artifacts`
- local `criteria` declarations, which create criteria slots other nodes may later consume

There is no authored handoff-slot family, no authored packet family, and no legacy workflow `inputs` or `outputs` dependency family in v1.

Runtime assignment `consumes` may later surface checkpoints, docs, wiki pages, or transient refs when helpful, but those are runtime read projections, not authored dependency edges.

## Baseline durable contract versus runtime supplements

For any node, the baseline durable contract comes from the node definition that owns that work, plus legal direct-parent `child_defaults` expansion:

- authored local `consumes.*` selectors
- authored local `produces.artifacts` slots
- authored local criteria declarations
- direct-parent `child_defaults` entries that compile onto that node

Parent/root dispatch-time behavior does not rewrite that baseline. Runtime may still merge supplemental current durable sharing for one attempt:

- supplemental artifact sharing appears only as additional exact `artifact` refs in assignment `consumes`
- supplemental criteria sharing appears only as additional exact criteria refs in assignment `criteria`
- those supplements do not mutate authored `consume_selector`, `produce_slot`, or criteria ownership

## Global slot identity per bucket

Slot ids are globally unique within their bucket across one workflow:

- artifact `produce_slot.slot` is globally unique across the artifact bucket
- criteria `criteria_declaration.slot` is globally unique across the criteria bucket

Because slot ids are globally unique per bucket:

- authored consume selectors do not carry a producer node id
- ordinary surfaced artifact refs do not need `producer_node_key` or `owner_node_key` as agent-visible fields
- if two nodes would need the same artifact or criteria slot id, the authored workflow is invalid

## `ConsumeSelectorResolutionRule`

Producer identity is inferred from slot id within the matching bucket.

Selectors are legal only when:

- an artifact consume selector matches one declared artifact produce slot
- a criteria consume selector matches one declared criteria slot
- the resulting dependency graph is legal under the deterministic Kahn rule

### Worked selector example

Authored producer:

```yaml
produces:
    artifacts:
        - slot: findings_report
          description: Findings for downstream implementation.
          file_hint: findings_report.md
```

Authored consumer:

```yaml
consumes:
    artifacts:
        - slot: findings_report
```

Resolution meaning:

- the consumer does not name the producer node directly
- the compiler resolves `findings_report` by slot within the artifact bucket
- the resolved dependency edge becomes explicit in normalized/runtime graph rows
- if no current `findings_report` publication exists yet, the consumer is not runnable
- when the consumer does run, the exact current ref is pinned into the attempt's evidence basis

## Authored slot identity versus runtime storage identity

Authored dependency identity and runtime durable currentness are intentionally different:

| Layer                                        | Identity                 |
| -------------------------------------------- | ------------------------ |
| authored selector identity                   | `slot`                   |
| runtime durable storage/currentness identity | `(owner_node_key, slot)` |

Rules:

- authored selectors and authored `produces` use only `slot`
- runtime resolves which node owns that slot
- durable artifact publication history and currentness are tracked by `(owner_node_key, slot)`
- durable artifact paths live under `outputs/artifacts/<owner_node_key>/<slot>/...`
- ordinary surfaced artifact refs stay compact because authored slot ids are already globally unique

Worked runtime example:

```yaml
# controller-owned durable storage/currentness truth
owner_node_key: implement_change
slot: change_patch
version: 2
path: C:/tasks/task_2026_0042/outputs/artifacts/implement_change/change_patch/change_patch.v02.diff
```

The ordinary surfaced artifact ref for that same publication is:

```yaml
kind: artifact
slot: change_patch
version: 2
path: C:/tasks/task_2026_0042/outputs/artifacts/implement_change/change_patch/change_patch.v02.diff
  description: Patch for the scoped fix.
```

The path includes the publishing node namespace. The surfaced ref still does not grow a top-level `owner_node_key` field.

## `CurrentValidResolutionRule`

Runtime resolves authored selectors to exact current refs:

- artifact selectors resolve to current `artifact` evidence refs
- criteria selectors resolve to current `criteria` evidence refs
- assignment `consumes` surfaces resolved artifact refs and assignment `criteria` surfaces resolved criteria refs; no dispatched attempt receives unresolved slot-only selectors

If no current required ref exists:

- the consumer is not runnable
- the worker is not dispatched just to discover that absence
- the controller surfaces the problem to the currently dispatched parent/root

## `DeterministicDependencyLegalityRule`

Preview, task start, and runtime structural adopt must all use the same deterministic Kahn topological-sort legality rule.

Algorithm:

1. resolve authored selectors into candidate dependency edges
2. reject immediately if any selector target is missing
3. initialize the zero-in-degree queue by canonical node order, then authored `id`
4. pop eligible nodes in that deterministic order
5. emit successors into the queue using the same order
6. accept only when emitted node count equals candidate node count

Consequences:

- cycle legality is deterministic, not "any topological sort"
- the same authored workflow yields the same legality result in preview, start, and runtime structural edits
- tree ownership still comes from `children`, but dependency legality is checked against explicit relational edge rows after resolution

## Runtime surfaced ref taxonomy

Runtime surfaces authored contracts through explicit ref families.

```yaml
node_runtime_file_ref:
    kind: manifest | assignment | checkpoint | artifact_index | transient_index
    path: string
    description: string

support_runtime_file_ref:
    kind: delivery_state | continuity_state | watchdog_state | provider_events
    path: string
    description: string

evidence_ref:
    kind: artifact | criteria | doc | wiki | transient
    slot: string | null
    version: integer | null
    path: string
    description: string
```

Rules:

- authored artifact and criteria dependencies resolve into `evidence_ref` entries
- `artifact` is the only ordinary evidence kind that carries `version`
- `criteria` carries `slot`, `path`, and `description`, but no ordinary `version` field in v1
- surfaced checkpoints are `node_runtime_file_ref`, not `artifact`
- delivery, continuity, watchdog, and provider-event files are `support_runtime_file_ref` and are observability-only, not ordinary worker evidence
- `file_hint` is authored `produce_slot` metadata only; it is not a surfaced runtime ref field
- assignment `produces` is requirement-only; it is derived from authored `produce_slot` contract and does not surface `path`, `version`, or realized refs

### Worked assignment consume example

```yaml
consumes:
    - kind: checkpoint
      path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.review_change.01/latest-checkpoint.md
      description: Latest child checkpoint relevant to this parent decision.
    - kind: artifact
      slot: review_report
      version: 1
      path: C:/tasks/task_2026_0042/outputs/artifacts/review_change/review_report/review_report.v01.md
      description: Current review report surfaced for parent verification.
    - kind: criteria
      slot: root_closure_criteria
      path: C:/tasks/task_2026_0042/_runtime/criteria/root_closure_criteria.md
      description: Root closure criteria in force for the current decision.
```

### Worked assignment produce requirement example

```yaml
produces:
    - slot: review_report
      description: Required review findings report for parent/root verification.
```

`Assignment produces` says what the attempt must publish before it can close green. It is not a realized ref surface and does not predeclare `path` or `version`.

## `DeterministicMaterializationRule`

All surfaced refs must point at localized task-directory paths.

Rules:

- runtime must localize any external resource into the task root before surfacing it
- surfaced refs do not use `url`, `uri`, or remote-only pointers
- artifact refs stay compact as `slot`, `version`, `path`, and `description`
- criteria refs stay compact as `slot`, `path`, and `description`
- runtime file refs stay compact as `kind`, `path`, and `description`

## `ConsumedRefPinningRule`

When a consumer attempt runs, it pins the exact resolved refs it consumed.

At minimum, that includes:

- artifact evidence refs resolved from authored `consumes.artifacts`
- criteria evidence refs resolved from authored `consumes.criteria`

When runtime intentionally surfaces additional refs for the same attempt, it pins those exact refs too:

- checkpoint `node_runtime_file_ref`
- curated `doc` or `wiki` evidence refs
- explicit `transient` carryover refs

Those pinned refs become part of the attempt's durable evidence basis. Later artifact republishes, criteria changes, structural changes, or assignment-basis changes can make older evidence stale.

## Related contracts

- [Workflow definition schema](workflow-definition-schema.md)
- [Manifest contract](../architecture/manifest-contract.md)
- [Worker context contract](../architecture/worker-context-contract.md)
