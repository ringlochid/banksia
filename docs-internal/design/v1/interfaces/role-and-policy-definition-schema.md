# Role And Policy Definition Schema

Status: Target

This page defines the exact v1 role and policy definition input schemas.

These schemas are canonical for:

- guarded definition uploads
- registry reads used before structural edits
- launch-time compiler validation
- runtime structural-edit validation of role/policy references
- prompt-layer role and policy source provenance

In this repo, packaged seeds under `apps/api/src/autoclaw/definitions/seeds/{roles,policies}/**` are the committed authored and shipped seed source for these file forms. A caller may select an explicit `definitions_root` override tree for import or seed work, but no repo-root definitions mirror is required by shipped paths. After seed or guarded upload, registry current revisions remain the only live definition authority.

## `RoleDefinitionInput`

Role definitions use this exact authored body:

```yaml
id: string
title: string
description: string
allowed_node_kinds:
    - root | parent | worker
labels:
    - string
instruction: >-
  string | optional
```

Canonical file form for CLI scan/import:

```yaml
kind: role
id: string
title: string
description: string
allowed_node_kinds:
    - root | parent | worker
labels:
    - string
instruction: >-
  string | optional
```

Field meaning:

- `id` is the stable logical role key
- `title` is the human display name used by authoring and control surfaces
- `description` is reusable descriptive metadata; in prompt use, it should express role purpose rather than detailed execution procedure
- `allowed_node_kinds` is the compatibility set for workflow nodes
- `labels` are optional portable tags for search, grouping, and UI routing
- `instruction` is reusable role guidance; use it to explain expected mode, evidence posture, criteria posture, and checkpoint expectations
- `description` and `instruction` are rendered into the assembled static provider-side instruction layer for the current node

Role guidance should not assume the model already knows AutoClaw concepts. When a role depends on purpose, mode, criteria, consumes, produces, checkpoints, refs, or boundaries, restate the meaning in ordinary language.

Custom role ids are legal in v1 when they are defined in stored registry content and their `allowed_node_kinds` are valid.

Review, QA, release, compliance, and audit workers are all ordinary `worker` roles.

Authored body example:

```yaml
id: review-role
title: Review Role
description: Parent review role for structured review against current criteria.
allowed_node_kinds:
    - parent
instruction: >-
  Read current criteria first, then inspect the latest checkpoint and surfaced durable refs.
```

Canonical file example:

```yaml
kind: role
id: review-role
title: Review Role
description: Parent review role for structured review against current criteria.
allowed_node_kinds:
    - parent
instruction: >-
  Read current criteria first, then inspect the latest checkpoint and surfaced durable refs.
```

## `PolicyDefinitionInput`

Policy definitions use this exact authored body:

```yaml
id: string
title: string
description: string
applies_to:
    - root | parent | worker
budget_spec:
    child_assignment_limit: integer | optional
    retry_limit: integer | optional
capabilities:
    human_request:
        mode: deny | allow
        allowed_kinds:
            - direction | approval | input | review
    command_run: deny | allow
labels:
    - string
instruction: >-
  string | optional
```

Canonical file form for CLI scan/import:

```yaml
kind: policy
id: string
title: string
description: string
applies_to:
    - root | parent | worker
budget_spec:
    child_assignment_limit: integer | optional
    retry_limit: integer | optional
capabilities:
    human_request:
        mode: deny | allow
        allowed_kinds:
            - direction | approval | input | review
    command_run: deny | allow
labels:
    - string
instruction: >-
  string | optional
```

Field meaning:

- `id` is the stable logical policy key
- `title` is the human display name used by authoring and control surfaces
- `description` is reusable descriptive metadata; in prompt use, it should summarize policy purpose
- `applies_to` selects which structural node kinds may use this policy
- `budget_spec` is the only live authored policy control object in v1 and configures minimal controller-side limits only
- `capabilities.human_request` and `capabilities.command_run` are portable V2 capability inputs and default to deny
- `labels` are optional portable tags for search, grouping, and UI routing
- `instruction` is reusable policy guidance; use it to explain constraints, evidence gates, allowed posture, and checkpoint expectations
- `description` and `instruction` are rendered into the assembled static provider-side instruction layer for the current node
- parent/root policies may author `child_assignment_limit` only
- worker policies may author `retry_limit` only
- continuity, same-attempt redispatch, and same-session reuse belong to runtime recovery/continuity logic rather than authored policy grammar
- `budget_spec` does not expose runtime counters, remaining counts, or any wider tool, boundary, recovery, provider, or session grammar

The live top-level docs do not freeze any richer authored policy grammar beyond these fields, the two named `budget_spec` keys, and the two V2 capability families. If an implementation later supports deeper authored policy controls, those fields must be locked separately before they become canonical.

Authored body example:

```yaml
id: review-policy
title: Review Policy
description: Restrict review nodes to current v1 review and closure powers.
applies_to:
    - parent
budget_spec:
    child_assignment_limit: 4
instruction: >-
  Keep review grounded in current criteria, latest checkpoint, and surfaced durable refs.
```

Canonical file example:

```yaml
kind: policy
id: review-policy
title: Review Policy
description: Restrict review nodes to current v1 review and closure powers.
applies_to:
    - parent
budget_spec:
    child_assignment_limit: 4
instruction: >-
  Keep review grounded in current criteria, latest checkpoint, and surfaced durable refs.
```

Worker retry example:

```yaml
id: implement-fix-policy
title: Implement Fix Policy
description: Allow bounded worker retry while preserving controller-owned continuity rules.
applies_to:
    - worker
budget_spec:
    retry_limit: 2
instruction: >-
  Retry only when the current assignment still applies and the latest checkpoint names the next narrow step.
```

## Validation rules

Validation must enforce:

- logical key comes from `RoleDefinitionInput.id` or `PolicyDefinitionInput.id`
- any enclosing transport `kind` or file-level `kind` matches the authored body
- `title` is optional display metadata for roles and policies
- `allowed_node_kinds` is non-empty
- `applies_to` is non-empty
- `labels`, when present, must not contain duplicates
- when `budget_spec` is present, it may contain only:
    - `child_assignment_limit`
    - `retry_limit`
- when a `budget_spec` limit is present, its value is an integer
- `child_assignment_limit` is legal only when `applies_to` contains `root` and/or `parent`
- `retry_limit` is legal only when `applies_to` contains `worker`
- one authored policy must not mix root/parent assignment budgeting with worker retry budgeting
- omitted `capabilities.human_request` defaults to `mode: deny`
- omitted `capabilities.command_run` defaults to `deny`
- `capabilities.human_request.mode: allow` requires non-empty `allowed_kinds`
- `capabilities.human_request.mode: deny` grants no portable human-request permission
- richer-than-live policy grammar is rejected, not silently ignored

Canonical richer-grammar rejects include:

- `default_policy`
- `defaults`
- `defaults.retry_budget`
- `rules`
- `rules.allowed_tools`
- `rules.allowed_boundaries`
- `same_attempt_redispatch_limit`
- `budget_spec.same_attempt_redispatch_limit`
- `budget_spec.same_attempt_continue_limit`
- top-level `same_attempt_continue_limit`
- top-level `same_attempt_redispatch_limit`
- authored same-session or continue-session preferences
- provider/plugin-specific authored behavior fields

## Effective policy resolution

Effective node policy resolves exactly as:

1. explicit authored node `policy`, if present
2. otherwise no policy resolves

Then validate:

1. the current role id exists in current registry truth
2. the node kind is included in role `allowed_node_kinds`
3. if explicit `policy` is present, the resolved policy id exists in current registry truth
4. if explicit `policy` is present, the node kind is included in policy `applies_to`

There is no workflow-level default policy in v1. There is no role-level default policy in v1. There is no hidden runtime-injected fallback in v1.

The effective policy output available to later surfaces is only:

- resolved `policy_id | null`
- resolved policy `title | null`
- resolved policy `description | null`
- resolved policy `instruction | null`
- resolved policy `applies_to | null`
- resolved policy `budget_spec | null`
- resolved policy `capabilities | null`
- resolved policy `labels | null`

That output may drive compatibility validation, descriptive instruction assembly, and controller-side budget initialization. It does not create a richer machine-control grammar.

Pinned-runtime rule:

- registry read resolves the current role and policy revisions at the moment of launch or runtime structural adopt
- compiled plan and runtime node truth then pin those exact role/policy revisions
- later registry uploads do not change already-launched or already-adopted runtime nodes
- a later runtime structural edit may choose a newer current role/policy revision, but only by committing a new structural revision that pins the newly chosen revision numbers

## Instruction authority rule

Role and policy `description` and `instruction` fields:

- contribute only to the assembled stable instruction block
- do not replace assignment `instruction`
- do not introduce provider-specific authored instruction fields
- do not create a second controller-truth surface

`budget_spec` contributes only controller-side configured limit inputs. It does not render as provider-specific instruction and it does not surface runtime counters, recovery counters, or session-reuse preferences as authored truth.

## Runtime structural-edit rule

Parent/root structural edits must not assume a separate callback-side registry read lane.

Instead:

- parent/root uses role/policy names already surfaced in current prompt or manifest context, or other controller-provided naming context already in the current dispatch
- runtime still revalidates those references on commit against controller-owned definition registry truth
- validator is commit authority
- pinned compiled/runtime revision truth is execution authority after commit

Concrete structural-edit example:

1. parent rereads the current manifest and current assignment
2. parent chooses `review-role` plus `review-policy` from already surfaced controller context
3. parent calls `add_child` or `update_child`
4. runtime revalidates those references during structural adoption
5. runtime validator confirms those ids still resolve and pins the exact current role/policy revision numbers before commit

## Removed from the live v1 schema

Do not keep these as live role/policy schema concepts:

- `default_policy`
- workflow-level default policy
- role-level default policy
- `allowed_kinds`
- `target_kind`
- `allowed_parent_outcomes`
- `allowed_result_outcomes`
- `defaults`
- unfrozen authored policy grammars such as `defaults.retry_budget`, `rules.allowed_tools`, or `rules.allowed_boundaries`
- `rules`
- `same_attempt_redispatch_limit`
- `same_attempt_continue_limit`
- `budget_spec.same_attempt_redispatch_limit`
- `budget_spec.same_attempt_continue_limit`
- `parent_gate`-specific policy contracts
- provider/plugin-specific authored behavior fields
- `instruction_text`

## Related contracts

- [Workflow definition schema](../workflows/workflow-definition-schema.md)
- [Mode contract and legality matrix](../workflows/mode-contract-and-legality-matrix.md)
- [Definition registry and upload contract](definition-registry-and-upload-contract.md)
- [Role and policy example definitions](../workflows/role-and-policy-example-definitions.md)
