# Assignment Contract

Status: Target

This page defines the canonical assignment write/read contract for the frozen v1 runtime.

It owns:

- the semantic boundary between child definition truth and parent assignment staging
- the canonical assignment projection fields
- the split between durable requirement selectors and explicit transient surfacing
- the assignment materialization order from semantic facts to controller truth to generated projections

It does not own:

- whole-workflow orientation, which belongs to the manifest
- attempt history or durable handoff, which belongs to the checkpoint contract
- durable artifact publication truth or currentness, which belongs to runtime rows and artifact storage contracts

## Core rule

An assignment is the current node's forward-looking mission contract.

The baseline durable contract comes from the current node definition.

That node definition owns:

- the semantic meaning of its `criteria` slots
- the semantic meaning of its `consumes` selectors
- the semantic meaning of its `produces` slots

The parent/root may stage one assignment instance for a child, but it does not redefine those durable meanings.

The parent/root may add only:

- assignment-specific `summary` and `instruction` wording
- supplemental durable context sharing by semantic slot selector for `artifact` and `criteria` only
- explicit `transient_refs`

The runtime then resolves the durable requirements into controller-owned truth and projects the assignment files from that truth.

For the first/root assignment there is no parent-authored `assignment_intent`. At launch, runtime/system generates the first assignment `summary` and `instruction` from:

- task-wide identity (`task.title`, `task.summary`, optional `task.instruction`)
- the launch-selected current node purpose and node-definition semantics
- optional node instruction from the selected workflow node
- resolved role description and optional role instruction
- resolved policy description and optional policy instruction

That launch-generated first assignment is still an ordinary assignment projection. It is not a special authored YAML object.

## Durable versus transient split

Freeze this split:

- durable assignment facts are `criteria`, resolved `consumes`, and required `produces`
- transient assignment facts are explicit `transient_refs` only

Rules:

- parent/root supplemental durable context must use semantic selectors such as artifact slot or criteria slot, not final durable ref metadata
- parent/root may not author `version`, `owner_node_key`, `path`, or other final publication metadata for durable artifact inputs
- runtime resolves authored `consumes` selectors to exact concrete durable refs during assignment materialization
- runtime projects `produces` as requirements only; assignments do not invent final durable ref metadata for outputs that do not exist yet
- transient surfacing is explicit and optional
- there is no transient current-pointer family
- an omitted `transient_refs` set means no transient carryover is surfaced for this assignment

## Semantic sources

### Child definition truth

The current node definition is the durable semantic home for:

- node role and description
- authored `criteria` slot meanings
- authored `consumes` selector meanings
- authored `produces` slot meanings

That is why root launch, child assignments, consumers, parent nodes, and checkpoints all inherit the same slot meaning without re-authoring it per attempt.

### Parent/root staging authority

The parent/root may stage one child assignment instance by specifying:

- which child node should run now
- the assignment-local `summary`
- optional bounded `instruction`
- which additional authored artifact slots or criteria slots should be shared durably for this assignment
- which transient files should be surfaced explicitly, if any

The parent/root does not get to redefine:

- what a child produce slot means
- what a child consume selector means
- what a durable artifact's final version/path/currentness is

This staging authority applies only to parent/root -> child assignment creation. It does not describe how the initial/root assignment is created at launch.

## Assignment materialization order

The assignment sequence is closed:

1. semantic facts exist in the child definition plus any parent/root supplemental slot selectors and transient surfacing
    - for the first/root assignment, semantic facts start from task identity plus the launch-selected current node purpose, optional node instruction, and node-definition semantics
    - for later child assignments, semantic facts start from the child node definition plus parent/root staging
2. the controller validates authority, currentness, dependency legality, and selector legality
3. the controller resolves concrete durable `consumes` refs from runtime truth
4. the controller persists assignment rows and related consumed-ref truth
5. the runtime generates `_runtime/attempts/<attempt_id>/assignment.*`

Do not invert that order.

The generated assignment is never the source of truth for durable inputs or outputs.

## Canonical assignment projection

Assignments are projected at:

- `_runtime/attempts/<attempt_id>/assignment.json`
- `_runtime/attempts/<attempt_id>/assignment.md`

Minimum canonical projection fields:

- `assignment_key`
- `node_key`
- `summary`
- `instruction` | optional
- `criteria`
- `consumes`
- `produces`
- `transient_refs` | optional

Recommended shape:

```yaml
assignment:
    assignment_key: string
    node_key: string
    summary: string
    instruction: >-
      string | null
    criteria:
        - kind: criteria
          slot: string
          path: string
          description: string
    consumes:
        - kind: artifact | doc | wiki
          slot: string | null
          version: integer | null
          path: string
          description: string
    produces:
        - slot: string
          description: string
    transient_refs:
        - kind: transient
          slot: null
          path: string
          description: string
```

Rules:

- `criteria` and `consumes` are concrete read-now surfaces
- `produces` is a requirement list only
- `produces.description` comes from the authored child produce-slot meaning
- any consumed artifact `description` also comes from the producing node's authored produce-slot meaning
- `transient_refs` stays outside the durable requirement model

## Parent supplemental durable context

When a parent/root shares additional durable context with a child, that supplemental context must stay semantic.

Allowed durable selectors:

- artifact slot selectors
- criteria slot selectors

Disallowed parent-authored durable fields:

- artifact `version`
- artifact `path`
- artifact `owner_node_key`
- artifact `assignment_key`
- artifact `attempt_id`
- artifact currentness claims

The controller resolves those durable details after validation.

Illustrative staging input:

```yaml
assign_child:
    child_node_key: implement_fix
    assignment_intent:
        summary: Implement the approved fix for the auth refresh failure.
        instruction: >-
          Keep the patch small and preserve retry-safe behavior.
    supplemental_durable_context:
        artifact_slots:
            - slot: findings_report
        criteria_slots:
            - slot: implement_fix_delivery_criteria
    transient_surfaces:
        - path: <task_root>/tmp/transfers/auth-refresh-repro-steps.md
          description: Optional transient repro notes surfaced for this assignment.
        - path: <task_root>/tmp/transfers/auth-refresh-open-question.md
          description: Temporary parent note about the unresolved token-expiry proof lane.
```

Exact semantic payload shape:

```yaml
assign_child:
    child_node_key: string
    assignment_intent:
        summary: string
        instruction: >-
          string | null
    supplemental_durable_context:
        artifact_slots:
            - slot: string
        criteria_slots:
            - slot: string
    transient_surfaces:
        - path: string
          description: string
```

Rules:

- `assignment_intent` is semantic mission staging only
- `assignment_intent` is for parent/root -> child staging only; it is not the launch-time root-assignment source
- `supplemental_durable_context` is slot-based durable context sharing only
- `supplemental_durable_context.artifact_slots` must not target a slot produced by the same child node; pass previous same-node material through explicit `transient_surfaces` instead
- `transient_surfaces` is a JSON array/YAML sequence of `{ path, description }` objects for explicit non-durable carryover only
- the parent/root does not submit materialized `criteria`, concrete durable `consumes`, or projected `produces`
- runtime resolves concrete durable refs and then projects the final `assignment.*`

Resulting projected durable inputs are runtime-resolved, not parent-authored:

```yaml
assignment:
    assignment_key: implement_fix.assign-01
    node_key: implement_fix
    summary: Implement the approved fix for the auth refresh failure.
    instruction: >-
      Keep the patch small and preserve retry-safe behavior.
    criteria:
        - kind: criteria
          slot: implement_fix_delivery_criteria
          path: <task_root>/_runtime/criteria/implement_fix_delivery_criteria.v01.md
          description: Delivery criteria for the implement-fix node.
    consumes:
        - kind: artifact
          slot: findings_report
          version: 2
          path: <task_root>/outputs/artifacts/investigate_issue/findings_report/findings_report.v02.md
          description: Findings for downstream implementation.
    produces:
        - slot: code_patch
          description: Code patch implementing the approved fix.
          file_hint: change_patch.diff
    transient_refs:
        - kind: transient
          slot: null
          version: null
          path: <task_root>/tmp/transfers/auth-refresh-repro-steps.md
          description: Optional transient repro notes surfaced for this assignment.
        - kind: transient
          slot: null
          version: null
          path: <task_root>/tmp/transfers/auth-refresh-open-question.md
          description: Temporary parent note about the unresolved token-expiry proof lane.
```

## Read rule

Workers, parents, and roots read the projected assignment.

They do not reconstruct the assignment from:

- authored workflow YAML
- parent tool call memory
- artifact folder scans
- transient directory scans

If assignment projection and controller truth disagree, controller truth wins and the assignment projection must be regenerated.

## Related contracts

- [Worker context contract](worker-context-contract.md)
- [Manifest contract](manifest-contract.md)
- [Checkpoint contract](checkpoint-contract.md)
- [Runtime boundary and controller loop contract](runtime-boundary-and-controller-loop-contract.md)
- [Runtime database and object contract](runtime-database-and-object-contract.md)
