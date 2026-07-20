# Workflow Definition Schema

Status: Target

This page defines the canonical authored workflow schema for live v1.

The authored workflow has exactly two concerns:

- structural ownership through `root` and `children`
- durable authored contracts through `consumes`, `produces`, and `criteria`

Runtime later resolves that authored source into relational graph rows and generated projections. Authored YAML does not own runtime currentness, dispatch state, checkpoints, manifests, or monitoring.

Each node's baseline durable contract comes from that node's authored `consumes`, `produces`, and local `criteria`, plus any legal direct-parent `child_defaults` expansion. Runtime may later surface supplemental durable sharing for one attempt, but it does not rewrite that authored baseline.

## Core rule

The only authored durable contract families are:

- `consumes`
- `produces`
- `criteria`

Everything else that agents read later is runtime projection:

- assignment `criteria`, `summary`, and `instruction`
- checkpoint history
- pinned consumed refs
- durable artifact current pointers
- transient refs
- manifest and monitoring files

There are no authored workflow `inputs`, `outputs.handoffs`, handoff packets, review gates, or closure gates in v1.

## Concept glossary for authored workflows

Use these terms consistently in workflow definitions and prompt-facing docs:

- `purpose` is the reason the task or node exists and what success means; author it through task summary/instruction and node `description`
- `mode` is the current process shape such as planning, research, implementation, review, verification, failure analysis, replan, or release; author it through node `instruction`, role, and policy wording rather than a separate schema field
- `role` is the reusable capability profile attached to a node
- `policy` is the reusable behavioral guardrail, budget, and capability profile attached to a node
- `workflow` is the authored tree and durable contract source that compiles into runtime graph truth
- `assignment` is runtime-projected current mission prose for one node attempt; workflow YAML only supplies baseline purpose and guidance
- `criteria` are hard acceptance or guardrail requirements, not optional advice
- `consumes` declare durable artifact or criteria slots the node needs before work can proceed
- `produces` declare required artifact slots the node must publish before successful completion
- `checkpoint` is not authored in workflow YAML; it is runtime handoff memory written during execution
- `boundary` is not authored in workflow YAML; dispatch, yield, green, retry, and blocked are runtime control-flow events

## Public workflow definition routes

Guarded definition upload accepts the exact authored workflow payload through:

- `POST /definitions`

## Exact authored body

The guarded definition-upload API accepts the exact authored workflow body.

## Canonical authored shape

```yaml
workflow_definition:
  id: string
  description: string
  root: RootNodeDefinition

RootNodeDefinition:
  id: root
  role: string
  policy: string | optional
  description: string
  instruction: >-
    string | optional
  produces:
    artifacts: [produce_slot, ...] | optional
  criteria: [criteria_declaration, ...] | optional
  child_defaults:
    consumes:
      artifacts: [consume_selector, ...] | optional
      criteria: [consume_selector, ...] | optional
    criteria: [slot_id, ...] | optional
  children: [NodeDefinition, ...] | optional

NodeDefinition:
  id: string
  role: string
  policy: string | optional
  description: string
  instruction: >-
    string | optional
  consumes:
    artifacts: [consume_selector, ...] | optional
    criteria: [consume_selector, ...] | optional
  produces:
    artifacts: [produce_slot, ...] | optional
  criteria: [criteria_declaration, ...] | optional
  child_defaults:
    consumes:
      artifacts: [consume_selector, ...] | optional
      criteria: [consume_selector, ...] | optional
    criteria: [slot_id, ...] | optional
  children: [NodeDefinition, ...] | optional
```

Node kind is structural:

- the authored `root` object is always kind `root`
- any non-root node with `children` is kind `parent`
- any leaf without `children` is kind `worker`

Review, QA, compliance, release, and closure work are all authored as ordinary `worker` leaves or subtrees.

## Canonical file form for CLI scan/import

When stored as a canonical definition file for CLI import, add the required top-level `kind` field to that authored body:

```yaml
kind: workflow
id: string
description: string
root: RootNodeDefinition
```

In this repo, packaged seeds under `apps/api/src/autoclaw/definitions/seeds/workflows/*.yaml` are the committed authored and shipped seed source for this canonical file form. A caller may select an explicit `definitions_root` override tree for import or seed work, but no repo-root workflow fixture mirror is required by shipped paths. After seed or upload, launch and later runtime paths read registry current revisions instead of rereading seed or override files as live authority.

## Concrete authored example

The canonical file form stays small. It describes structure plus durable contracts only.

```yaml
kind: workflow
id: auth-refresh-bugfix
description: Fix the auth refresh regression and close only after current review evidence is sufficient.
root:
    id: root
    role: root_planning_lead
    policy: standard-root
    description: Coordinate the whole flow and decide final closure.
    instruction: >-
      Keep final closure tied to current surfaced evidence.
    criteria:
        - slot: root_closure_criteria
          description: Final root acceptance criteria.
          criteria:
              - all required review evidence is current
              - root closes only after current closure evidence is sufficient
    children:
        - id: implementation_subtree
          role: planning_lead
          policy: standard-parent
          description: Coordinate investigation, implementation, and review.
          instruction: >-
            Assign only the next bounded child step needed for this subtree.
          criteria:
              - slot: subtree_delivery_rules
                description: Shared delivery rules for direct children.
                criteria:
                    - implementation stays inside the approved subtree
                    - downstream review addresses the current patch
              - slot: implementation_review_criteria
                description: Review criteria for downstream verification.
                criteria:
                    - review addresses the current patch and verification evidence
                    - open risks are either closed or explicitly documented
          child_defaults:
              criteria:
                  - subtree_delivery_rules
          children:
              - id: investigate_issue
                role: researcher
                description: Gather findings for downstream implementation.
                instruction: >-
                  Publish only findings needed by downstream implementation.
                produces:
                    artifacts:
                        - slot: findings_report
                          description: Findings for downstream implementation.
                          file_hint: findings_report.md
              - id: implement_change
                role: engineer
                description: Implement the scoped fix.
                instruction: >-
                  Read current criteria before editing and keep the patch scoped.
                consumes:
                    artifacts:
                        - slot: findings_report
                criteria:
                    - slot: implementation_delivery_criteria
                      description: Delivery criteria for the implementation leaf.
                      criteria:
                          - the patch addresses the current findings report
                          - the verification report covers the changed behavior
                produces:
                    artifacts:
                        - slot: change_patch
                          description: Patch for the scoped fix.
                          file_hint: change_patch.diff
                        - slot: verification_report
                          description: Verification evidence for the scoped fix.
                          file_hint: verification_report.md
              - id: review_change
                role: reviewer
                description: Review the patch against current criteria and evidence.
                instruction: >-
                  Review the current patch and verification evidence only.
                consumes:
                    artifacts:
                        - slot: change_patch
                        - slot: verification_report
                    criteria:
                        - slot: implementation_review_criteria
                produces:
                    artifacts:
                        - slot: review_report
                          description: Current review result for parent and root verification.
                          file_hint: review_report.md
```

This one authored tree implies all of the following:

- `implementation_subtree` is kind `parent`
- `investigate_issue`, `implement_change`, and `review_change` are kind `worker`
- `implement_change` depends on `investigate_issue` through `findings_report`
- `review_change` depends on `implement_change` through `change_patch` and `verification_report`, and on `implementation_subtree` through `implementation_review_criteria`

The producer node ids are not authored directly. The compiler resolves them from globally unique slot ids.

## Structural tree versus dependency graph

The authored workflow owns only the structural tree through `children`.

Typed dependency edges are derived from authored selectors:

- `consumes.artifacts` resolves against authored artifact `produces`
- `consumes.criteria` resolves against authored `criteria`
- preview, start, and runtime structural adopt all validate the resulting dependency graph with the same deterministic Kahn topological-sort rule

Runtime then stores the adopted graph relationally:

- launch-time normalized graph rows such as `compiled_plan_nodes` and `compiled_plan_edges`
- runtime adopted graph rows such as `flow_nodes` and `flow_edges`

Neither authored YAML nor generated manifest files own runtime graph truth.

## Forbidden authored fields

The frozen v1 authored workflow input must not carry:

- authored `edges`
- authored `review`, `closure`, or `activation` blocks
- authored `inputs`, `outputs.handoffs`, or handoff-packet families
- generic `skill_refs`
- authored provider-selection or transport fields
- workflow-level free-form prompt fragments
- authored runtime boundaries such as `dispatch`, `yield`, `green`, `retry`, or `blocked`
- authored release verbs such as `release_green` or `release_blocked`
- authored `parent_gate`
- authored manifest/runtime readback fields such as `depends_on_node_keys`, `current_relevant_paths`, `dispatch_id`, or checkpoint refs
- authored `root.consumes`

## Schema atoms

The owned schema atoms live in [Typed dependency selectors and produce slots](typed-dependency-selectors-and-produce-slots.md).

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

## `ChildDefaultsRule`

`child_defaults` is compile-time shorthand only.

Rules:

- it expands only onto direct children
- it is additive by bucket
- it dedupes by slot id while preserving first-authored order
- it never reaches grandchildren
- it never rewrites a child's authored local `consumes`
- it never rewrites a child's authored local `criteria`
- every `child_defaults.criteria` entry must resolve to a criteria slot declared on that same parent/root node

`child_defaults` is not runtime inheritance and not hidden ancestor magic.

## `BaselineChildDurableContractRule`

For any child, the baseline durable contract used by preview, compile, and runtime structural adopt is derived from:

- the child's authored local `consumes`
- the child's authored local `produces`
- the child's authored local `criteria`
- any direct-parent `child_defaults` entries that legally expand onto that child

Runtime assignment may later surface supplemental durable sharing as additional exact refs, but it does not rewrite the child's authored `consume_selector`, `produce_slot`, or criteria declarations.

## Validation rules

- `id` is the workflow identity and must match the guarded definition-upload logical key
- exactly one authored `root` object must exist, and its `id` must be `root`
- node ids are unique across the whole authored tree
- artifact produce slots are globally unique across the workflow artifact bucket
- criteria slots are globally unique across the workflow criteria bucket
- node kind is inferred structurally as `root | parent | worker`
- the authored `role` id must resolve and its `allowed_node_kinds` must include the inferred node kind
- if explicit `policy` is present, it must resolve and its `applies_to` must include the inferred node kind
- if explicit `policy` is absent, effective policy is `null`
- there is no workflow-level or role-level default policy fallback
- `root.consumes` is illegal in frozen v1
- consume selectors are legal only when the selected slot exists in the matching bucket
- the candidate dependency graph built from resolved selectors must pass the deterministic Kahn legality rule:
    - missing selector targets reject immediately
    - the zero-in-degree queue is ordered by canonical node order, then authored `id`
    - emitted node count must equal candidate node count or the graph is cyclic and illegal
- authored workflow YAML does not carry retry budgets, runtime replan state, active dispatch state, or watchdog/provider state

## Workflow versus role versus policy

- workflow `description` is local authored purpose text for the whole workflow
- node `description` is local authored purpose text for one ordinary node
- node `instruction` is optional node-local prompt guidance and renders as source-disambiguated node instruction
- role is reusable compatibility plus descriptive instruction
- policy is optional reusable descriptive instruction plus optional `budget_spec`

Workflow and node descriptions render into prompt surfaces, but they do not replace node, role, policy, task, or assignment instruction layers and they do not create new machine control grammar.

## How authored workflow becomes runtime truth

The authored workflow does not directly contain:

- the current dispatch
- the current assignment
- the latest checkpoint
- the current artifact pointer
- the current structural revision

Instead:

1. authored `consumes`, `produces`, `criteria`, role refs, and explicit policy refs are validated
2. selector resolution builds the candidate dependency graph
3. deterministic legality runs before launch or structural adopt commits
4. the compiler normalizes one plan and runtime stores relational graph rows
5. manifest, assignment, checkpoint, and artifact refs are regenerated from committed controller truth only; assignment materialization resolves selectors to exact current refs and projects `produces` as requirement-only

## Parent-owned artifact publication rule

Parent and root nodes may declare ordinary durable artifact `produces` slots in v1.

Typical parent/root publications include:

- curated review summaries
- bounded planning summaries
- root-visible release notes or final reports

Those are ordinary authored artifact slots, not hidden gate bundles.

## Review and release rule

V1 has no authored review gate or closure gate block.

If a workflow needs review, QA, compliance, release, or closure work:

- author that work as ordinary child nodes or subtrees
- wire the evidence flow through authored `consumes`
- publish ordinary durable artifacts through declared `produces`
- let the owning parent/root consume that evidence during its ordinary open dispatch

No child may force final `green` by itself.

## Final closure rule

Task closure is a runtime root decision, not an authored gate.

Root reaches final `green` only after the runtime controller has surfaced the current whole-flow evidence, root publishes its terminal `green` checkpoint, and root commits `release_green` during its ordinary dispatch.

## Criteria ownership rule

- the node that declares a criteria slot owns that durable contract
- a parent/root node's local criteria are subtree or whole-flow acceptance contracts
- a worker leaf's local criteria are delivery criteria for that node
- downstream consumers reference owned criteria slots; they do not redefine them
- nodes receive criteria only through authored local `criteria`, `child_defaults.criteria`, authored `consumes.criteria`, and runtime assignment `criteria`
- runtime may sharpen assignment wording, but it must not silently rewrite the underlying authored criteria contract

## Runtime structural change rule

Runtime local replan is not an authored YAML block.

During execution, parent/root may structurally edit the current tree through:

- `add_child`
- `update_child`
- `remove_child`

Those are runtime CRUD actions validated against current truth, adopted as a new structural revision, and then materialized into a new manifest.

## Related contracts

- [Workflow schema appendix](workflow-schema-appendix.md)
- [Compiler contract and launch materialization](compiler-contract-and-launch-materialization.md)
- [Typed dependency selectors and produce slots](typed-dependency-selectors-and-produce-slots.md)
- [Runtime structural replan](runtime-structural-replan.md)
- [Parent/root release and closure](parent-root-release-and-closure.md)
