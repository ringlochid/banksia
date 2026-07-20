# Workflow schema appendix

Status: Target

This appendix is the exhaustive authored-shape companion for the live v1 workflow model.

Primary behavioral semantics still live in [Workflow Definition Schema](workflow-definition-schema.md). This page collects the exact authored shapes, child-default expansion rules, and runtime structural-edit cross-checks that implementers repeatedly need while building the launch compiler and runtime validator.

## Ownership map

- [Workflow Definition Schema](workflow-definition-schema.md) owns the core authored model and hard validation rules
- [Typed Dependency Selectors And Produce Slots](typed-dependency-selectors-and-produce-slots.md) owns selector semantics and deterministic consumed-ref pinning
- [Criteria And Parent Verification](criteria-and-parent-verification.md) owns criteria delivery and parent/root verification semantics
- [Runtime Structural Replan](runtime-structural-replan.md) owns runtime structural CRUD semantics after launch

## Authored launch shapes

Task-start shapes live in [Task Compose Schema](task-compose-schema.md).

## Authored workflow shapes

### `WorkflowDefinitionInput`

- `id`
- `description`
- `root` as `RootNodeDefinition`

### `RootNodeDefinition`

- `id` fixed to `root`
- `role`
- `policy` | optional
- `description`
- `produces.artifacts` as `[produce_slot, ...]` | optional
- `criteria` as `[criteria_declaration, ...]` | optional
- `child_defaults` as `ChildDefaults` | optional
- `children` as `[NodeDefinitionInput, ...]` | optional

### `NodeDefinitionInput`

- `id`
- `role`
- `policy` | optional
- `description`
- `consumes.artifacts` as `[consume_selector, ...]` | optional
- `consumes.criteria` as `[consume_selector, ...]` | optional
- `produces.artifacts` as `[produce_slot, ...]` | optional
- `criteria` as `[criteria_declaration, ...]` | optional
- `child_defaults` as `ChildDefaults` | optional
- `children` as `[NodeDefinitionInput, ...]` | optional

Ordinary node type is structural:

- node with `children` = parent/root coordinator node
- node without `children` = worker/reviewer/release leaf

### `ChildDefaults`

- `consumes.artifacts` as `[consume_selector, ...]` | optional
- `consumes.criteria` as `[consume_selector, ...]` | optional
- `criteria` as `[slot_id, ...]` | optional

### `produce_slot`

- `slot`
- `description`
- `file_hint` | optional

### `criteria_declaration`

- `slot`
- `description`
- `criteria` as `[string, ...]`

## Hard validation inventory

- `root.id` is fixed to `root`
- node ids are unique across the whole tree
- artifact produce slots are unique across all nodes
- criteria slots are unique across all declarations
- non-root nodes may declare authored `consumes`
- `root.consumes` is illegal
- authored `inputs`, `outputs.handoffs`, bundle families, and gate fields are illegal
- authored `review`, `closure`, and `activation` are illegal
- authored `skill_refs`, `provider_preference`, and transport/mode fields are illegal
- typed dependency resolution must remain acyclic

## `ChildDefaultsExpansionRule`

- expansion touches only direct children
- expansion is additive by bucket
- expansion dedupes by slot id while preserving first-authored order
- expansion never rewrites a child's authored local `consumes`
- expansion never rewrites a child's authored local `criteria`

## Worked child-default expansion

This is the most common authored shorthand in v1.

Authored input:

```yaml
id: implementation_subtree
criteria:
    - slot: subtree_rules
      description: Shared subtree rules.
      criteria:
          - every child stays inside the current subtree
child_defaults:
    criteria:
        - subtree_rules
children:
    - id: investigate_issue
      role: researcher
    - id: implement_change
      role: engineer
      criteria:
          - slot: implement_change_delivery_criteria
            description: Local engineering criteria.
            criteria:
                - patch matches the assigned scope
```

Expansion consequence:

- `investigate_issue` receives `subtree_rules`
- `implement_change` receives both `subtree_rules` and its own `implement_change_delivery_criteria`
- grandchildren would not receive `subtree_rules` unless a nearer parent authored another `child_defaults`

## Slot uniqueness and legality matrix

| Slot kind              | Uniqueness scope                             | Consumers                                                                          |
| ---------------------- | -------------------------------------------- | ---------------------------------------------------------------------------------- |
| artifact produce slots | globally unique across all nodes             | `consumes.artifacts`, `child_defaults.consumes.artifacts`                          |
| criteria slots         | globally unique across all authored criteria | `consumes.criteria`, `child_defaults.criteria`, `child_defaults.consumes.criteria` |

## Criteria ownership and projection summary

- root-owned criteria define top-level delivery requirements
- parent-owned local criteria define subtree acceptance requirements
- worker-owned local criteria define delivery requirements
- normalized compiler output carries `owner_node_key` on each normalized criteria entry so direct-parent `child_defaults.criteria` expansion keeps the declaring node as owner instead of rewriting ownership to the child node
- workers pin exact criteria refs they consumed through runtime assignment `criteria` and durable checkpoint/evidence surfaces
- parent/root may sharpen the current assignment wording, but must not mutate authored criteria silently

## Runtime structural change cross-check

Runtime structural change is not an authored YAML patch block.

After launch, parent/root may change current structure only through:

- `add_child`
- `update_child`
- `remove_child`

Cross-checks:

- a runtime `add_child` draft is a runtime structural child draft, not a full authored `NodeDefinitionInput` wrapper
- the runtime draft uses semantic `node_key`, not authored `id`
- the runtime draft may reuse the authored node buckets where relevant: `role`, `policy`, `description`, `consumes`, `produces`, `criteria`, `child_defaults`, and `children`
- the runtime validator resolves changed role/policy ids against controller-owned definition registry truth during validation; do not assume a separate callback-side registry-read lane
- the runtime validator builds the candidate adopted graph and validates it with Kahn's topological sort
- successful structural change adopts one new structural revision and then regenerates `_runtime/workflow-manifest.*`

Do not treat runtime structural CRUD as whole-subtree replacement by default.

## Worked runtime structural edit cross-check

Suppose the current parent/root owns a subtree whose immediate children are:

- `investigate_issue`
- `implement_change`
- `review_change`

and decides it needs one more child under that owned subtree:

```yaml
node_key: qa_sweep
role: architect
description: Run a bounded QA sweep over current implementation evidence.
consumes:
    artifacts:
        - slot: change_patch
        - slot: verification_report
        - slot: review_report
produces:
    artifacts:
        - slot: qa_report
          description: QA findings for the subtree.
          file_hint: qa_report.md
```

Runtime must validate:

1. the current caller still owns the target parent node inside its subtree
2. no continuation outcome is already staged
3. `qa_sweep` is a new semantic runtime `node_key`
4. `architect` resolves through the definition registry
5. the candidate adopted dependency graph is still acyclic
6. the new subtree still has all required consume selectors resolved

Only after those checks pass may runtime adopt one new structural revision and regenerate `_runtime/workflow-manifest.*`.

## Example cross-reference matrix

| Example                        | Main teaching purpose               | Key features                                                                                 |
| ------------------------------ | ----------------------------------- | -------------------------------------------------------------------------------------------- |
| [Bounded change](examples/bounded-change.md)                   | smallest runnable authored flow     | one worker leaf, simple produce slot, root verification                                      |
| [Reviewed change release](examples/reviewed-change-release.md) | ordinary parent-review-release flow | parent subtree, root criteria, ordinary release child, consumes/produces only                |
| [Staged delivery release](examples/staged-delivery-release.md) | richer staged flow                  | multiple parents, child defaults, typed consumes, ordinary reviewer, QA, and release workers |

## Related contracts

- [Task compose schema](task-compose-schema.md)
- [Workflow definition schema](workflow-definition-schema.md)
- [Typed dependency selectors and produce slots](typed-dependency-selectors-and-produce-slots.md)
- [Criteria and parent verification](criteria-and-parent-verification.md)
- [Runtime structural replan](runtime-structural-replan.md)
