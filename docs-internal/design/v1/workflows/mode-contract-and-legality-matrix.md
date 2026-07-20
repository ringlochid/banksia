# Mode contract and legality matrix

Status: Target

This page freezes the simplified v1 structural node-kind model and the explicit-policy-only legality rule.

V1 does not use an authored ordinary node `mode` field. Ordinary node kind is inferred from structure. Review, QA, compliance, release, and closure work are authored as ordinary worker leaves or worker-owned subtrees, not as special gate config.

## `NodeKindModel`

| Structural position           | Inferred kind |
| ----------------------------- | ------------- |
| `root`                        | `root`        |
| non-root node with `children` | `parent`      |
| leaf node without `children`  | `worker`      |

`root` stays distinct from `parent` in the live model. Both coordinate children, but only `root` owns whole-flow closure and the root-only `release_blocked` path.

## `RoleCompatibilityRule`

Roles are registry-defined and validate against `allowed_node_kinds`. This page does not own a hardcoded role catalog.

Illustrative examples:

| Example role id      | Allowed kind     |
| -------------------- | ---------------- |
| `root_planning_lead` | `root`           |
| `planning_lead`      | `root`, `parent` |
| `engineer`           | `worker`         |
| `researcher`         | `worker`         |
| `reviewer`           | `worker`         |
| `release_operator`   | `worker`         |

Illustrative role rows do not freeze one role to one structural kind. The canonical `planning_lead` example role is legal on both `root` and `parent` when the stored definition includes both kinds.

If a non-root node has `children`, it is structurally `parent` even when the node is performing review, QA, or release-oriented work.

## `EffectivePolicyResolutionRule`

Policy resolution is explicit-only.

| Authored node field   | Resolved `policy_id` | Validation consequence                                                                       |
| --------------------- | -------------------- | -------------------------------------------------------------------------------------------- |
| `policy: some_policy` | `some_policy`        | The policy id must exist and the inferred node kind must be included in policy `applies_to`. |
| `policy` omitted      | `null`               | Legal. There is no workflow default, role default, or hidden runtime fallback.               |

When `policy` is omitted, the resolved policy surface is:

```yaml
policy_id: null
description: null
instruction: null
applies_to: null
budget_spec: null
```

Compile preview, task start, and runtime structural adopt all use this same resolution rule.

## Structural legality rule

Compiler/runtime validate in this order:

1. infer ordinary node kind from structure
2. resolve the authored role id and validate the inferred node kind through role `allowed_node_kinds`
3. resolve effective policy exactly:
    - explicit authored `policy`, if present
    - otherwise `null`
4. if explicit policy is present, validate policy applicability through policy `applies_to`
5. validate typed dependency legality

Validation fails when:

- the role id does not resolve
- the inferred node kind is not legal for the resolved role
- an explicit policy id does not resolve
- an explicit policy is incompatible with the inferred node kind

Validation does not fail merely because `policy` is omitted.

## Worked compatibility examples

### Valid leaf with omitted policy

```yaml
id: implement_change
role: engineer
description: Implement the scoped fix.
consumes:
    artifacts:
        - slot: findings_report
    criteria:
        - slot: implementation_delivery_criteria
produces:
    artifacts:
        - slot: change_patch
          description: Patch for the scoped fix.
        - slot: verification_report
          description: Verification evidence for the scoped fix.
```

Why it is valid:

- `implement_change` has no children, so it is structurally `worker`
- `engineer` is legal on `worker`
- `policy` is omitted, so effective policy resolves to `null`
- `consumes`, `criteria`, and `produces` remain ordinary workflow contract surfaces and do not depend on policy fallback

### Valid parent with explicit policy

```yaml
id: implementation_subtree
role: planning_lead
policy: standard-parent
description: Coordinate implementation and review.
child_defaults:
    criteria:
        - subtree_delivery_rules
children:
    - id: implement_change
      role: engineer
```

Why it is valid:

- `implementation_subtree` has children, so it is structurally `parent`
- `planning_lead` is legal on `parent`
- explicit policy resolution is allowed because `policy` is present
- validation then checks that `standard-parent` exists and applies to `parent`

### Invalid parent/role pairing

```yaml
id: review_parent
role: reviewer
children:
    - id: child
      role: engineer
```

Why it fails:

- `review_parent` is structurally `parent`
- `reviewer` is legal only on `worker`
- validation fails before launch or structural adopt
- omitting `policy` does not rescue the node because role compatibility fails first

## Related contracts

- [Workflow definition schema](workflow-definition-schema.md)
- [Role and policy definition schema](../interfaces/role-and-policy-definition-schema.md)
- [Compiler contract and launch materialization](compiler-contract-and-launch-materialization.md)
- [Parent review and replan](parent-review-and-replan.md)
- [Review findings contract](review-findings-contract.md)
