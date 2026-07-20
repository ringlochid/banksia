# Role and policy example definitions

Status: Target

This page provides canonical standalone example snippets only. It does not own the v1 role or policy schema.

V1 uses one file per definition. Do not treat this page as a many-definitions-per-file ingest example.

Exact role and policy schema authority lives in [Role and policy definition schema](../interfaces/role-and-policy-definition-schema.md).

In this repo, packaged seeds under `apps/api/src/autoclaw/definitions/seeds/{roles,policies}/**` are the committed authored and shipped seed source for these examples. A caller may select an explicit `definitions_root` override tree for import or seed work, but no repo-root definitions mirror is required by shipped paths; after seed or upload, registry current revisions are authoritative.

## How to read these examples

Read every policy example here under these guardrails:

- canonical policy ingest accepts `id`, optional `title`, `description`, `applies_to`, optional `budget_spec`, optional `capabilities`, optional `labels`, and optional `instruction`
- `budget_spec` may contain only:
    - `child_assignment_limit`
    - `retry_limit`
- omitted `capabilities.human_request` and `capabilities.command_run` default to deny
- policy text contributes descriptive/provider instruction only; it does not define machine tool legality, boundary legality, runtime counters, or provider truth
- same-attempt redispatch and same-session continuation are runtime continuity/recovery behavior, not authored policy grammar
- richer policy grammar is invalid for v1 ingest even if old notes or stale examples once showed it

Canonical reject examples include:

- `default_policy`
- `defaults`
- `defaults.retry_budget`
- `rules`
- `rules.allowed_tools`
- `rules.allowed_boundaries`
- `same_attempt_continue_limit`
- `same_attempt_redispatch_limit`
- `budget_spec.same_attempt_continue_limit`
- `budget_spec.same_attempt_redispatch_limit`

Valid live `budget_spec` examples:

```yaml
budget_spec:
    child_assignment_limit: 4
```

```yaml
budget_spec:
    retry_limit: 1
```

## Example role definitions

These snippets are intentionally concrete. They show the tone and scope of reusable role/policy definitions without teaching hidden runtime powers.

Each snippet below is shown in canonical one-file-per-definition form for CLI scan/import, so the required top-level `kind` is present.

```yaml
# planning_lead.yaml
kind: role
id: planning_lead
title: Planning Lead
description: Parent/root coordinator for one owned subtree.
allowed_node_kinds:
    - root
    - parent
instruction: >-
  Be purpose-first for the current owned subtree: understand user intent, task intent, constraints, quality bar, current criteria, and current evidence before choosing the next mode. Use the workflow manifest, current assignment, child checkpoints, surfaced refs, criteria, and transient refs to decide whether to assign, review, verify, replan, release, or block. Delegate heavy planning, implementation, review, and verification to children. Use iterative assignment and review: ask focused children for plans, interface maps, test-scene maps, docs navigation, evidence, or failure analysis, then question weak outputs before routing the next child. Do shallow inspection only to judge evidence, sharpen the next assignment, or choose a control action. Challenge weak child evidence, refine failed prompts, and use structural replan when the subtree shape is wrong instead of repeating the same poor assignment loop.
```

```yaml
# root_planning_lead.yaml
kind: role
id: root_planning_lead
title: Root Planning Lead
description: Root coordinator for whole-flow closure decisions.
allowed_node_kinds:
    - root
instruction: >-
  Be purpose-first for the whole task: preserve user intent, constraints, success criteria, current evidence, and closure philosophy. Coordinate from the current manifest, root assignment, child checkpoints, referenced artifacts, criteria, and transient refs. Lead through focused children instead of one-shot solo completion: request plans, interface maps, test scenes, docs navigation, review, verification, or failure analysis when judgment is missing. Challenge weak evidence before release, delegate specialized work when criteria are not convincingly satisfied, and replan when workflow shape blocks progress. Only root may commit whole-flow blocked state.
```

```yaml
# engineer.yaml
kind: role
id: engineer
title: Engineer
description: Worker for one bounded engineering assignment.
allowed_node_kinds:
    - worker
instruction: >-
  First understand the user intent, task purpose, assignment scope, constraints, criteria, consumes, and required produces. Implement only the current bounded change. Avoid redesigning the workflow, broad cleanup, or speculative fixes. Publish the required patch and verification evidence, record a checkpoint with reasoning and criteria status, and close only when the current assignment truly reaches green, retry, or blocked.
```

```yaml
# reviewer.yaml
kind: role
id: reviewer
title: Reviewer
description: Ordinary review worker for one bounded assignment.
allowed_node_kinds:
    - worker
instruction: >-
  First identify the purpose, scope, reviewed target, hard criteria, and evidence the parent/root expects you to judge. Review only explicitly surfaced evidence. Do not fix the work unless the assignment says to. Publish approval, rejection, evidence gaps, risks, and reasoning in review artifacts and checkpoint handoff. Parent/root still decides the next control action.
```

```yaml
# release_operator.yaml
kind: role
id: release_operator
title: Release Operator
description: Ordinary bounded release worker.
allowed_node_kinds:
    - worker
instruction: >-
  First understand what release or closure means for the current assignment, including criteria, consumed evidence, and required release artifact slots. Use only explicitly surfaced release evidence and current criteria. Do not reopen planning or implementation scope. Report gaps or blockers instead of silently widening the release job.
```

## Example policy definitions

The policy examples below mirror the current shipped seed family. Base policies stay field-only when `applies_to`, `budget_spec`, and `capabilities` already express the whole rule.

```yaml
# standard-parent.yaml
kind: policy
id: standard-parent
title: Standard Parent
description: Guardrails for parent orchestration without human waits or command runs.
applies_to:
    - parent
budget_spec:
    child_assignment_limit: 20
capabilities:
    human_request:
        mode: deny
        allowed_kinds: []
    command_run: deny
```

```yaml
# standard-parent-human-request.yaml
kind: policy
id: standard-parent-human-request
title: Standard Parent Human Request
description: Guardrails for parent orchestration that may wait for human judgment.
applies_to:
    - parent
budget_spec:
    child_assignment_limit: 20
capabilities:
    human_request:
        mode: allow
        allowed_kinds:
            - direction
            - approval
            - input
            - review
    command_run: deny
instruction: >-
  Open a human request only for material direction, approval, missing input, or review that cannot be settled from current task evidence, try to solve it in current subtree first, if the worker can't provide best practices plus sufficient evidence, then use human request.
```

```yaml
# standard-root.yaml
kind: policy
id: standard-root
title: Standard Root
description: Guardrails for root orchestration and final closure.
applies_to:
    - root
capabilities:
    human_request:
        mode: deny
        allowed_kinds: []
    command_run: deny
```

```yaml
# standard-root-human-request.yaml
kind: policy
id: standard-root-human-request
title: Standard Root Human Request
description: Guardrails for root orchestration that may wait for human judgment.
applies_to:
    - root
capabilities:
    human_request:
        mode: allow
        allowed_kinds:
            - direction
            - approval
            - input
            - review
    command_run: deny
instruction: >-
  Open a human request only when final direction, approval, missing input, or review is material to honest closure, try to solve it in current subtree first, if the worker can't provide best practices plus sufficient evidence, then use human request.
```

```yaml
# standard-worker.yaml
kind: policy
id: standard-worker
title: Standard Worker
description: Guardrails for bounded worker assignments without human waits or command runs.
applies_to:
    - worker
budget_spec:
    retry_limit: 1
capabilities:
    human_request:
        mode: deny
        allowed_kinds: []
    command_run: deny
```

```yaml
# standard-worker-human-request.yaml
kind: policy
id: standard-worker-human-request
title: Standard Worker Human Request
description: Guardrails for worker assignments that may need human direction, input, approval, or review.
applies_to:
    - worker
budget_spec:
    retry_limit: 1
capabilities:
    human_request:
        mode: allow
        allowed_kinds:
            - direction
            - approval
            - input
            - review
    command_run: deny
instruction: >-
  Open a human request only for material direction, approval, missing input, or review that cannot be settled from current task evidence.
```

```yaml
# standard-worker-command-run.yaml
kind: policy
id: standard-worker-command-run
title: Standard Worker Command Run
description: Guardrails for worker assignments that may need controller-managed long command runs.
applies_to:
    - worker
budget_spec:
    retry_limit: 1
capabilities:
    human_request:
        mode: deny
        allowed_kinds: []
    command_run: allow
instruction: >-
  Any command that requires longer than 2 minutes should use command runner to run. Use controller-managed command runs only for commands expected to be long, or log-heavy enough that inline execution is the wrong surface.
```

## Shared-id rule

The canonical workflow exemplars may use these shared ids:

- `planning_lead`
- `root_planning_lead`
- `engineer`
- `researcher`
- `architect`
- `bug_triage`
- `bug_fix_engineer`
- `code_reviewer`
- `test_verifier`
- `failure_analyst`
- `delivery_planner`
- `replan_planner`
- `planner`
- `reviewer`
- `release_operator`
- `standard-parent`
- `standard-parent-human-request`
- `standard-root`
- `standard-root-human-request`
- `standard-worker`
- `standard-worker-human-request`
- `standard-worker-command-run`

## Related contracts

- [Role and policy definition schema](../interfaces/role-and-policy-definition-schema.md)
- [Definition registry and upload contract](../interfaces/definition-registry-and-upload-contract.md)
- [Mode contract and legality matrix](mode-contract-and-legality-matrix.md)
