# Definition ingest and task-start file contract

Status: Target

This page defines the frozen file-based entry contracts for definition content and task-compose start input.

There is no separate task-file upload surface in v1.

## Separation rule

Definition ingest and task start are different surfaces.

They serve different goals:

- definition ingest changes stored authoring and launch material
- task start loads one authored task compose document and launches runtime materialization

## Definition file contract

Each canonical definition file contains exactly one authored definition body plus one top-level `kind` field:

```yaml
kind: role | policy | workflow
id: string
...
```

Rules:

- `kind` is required in the file
- `id` remains the logical key inside the authored body
- the remaining top-level fields must match exactly one of:
    - `RoleDefinitionInput`
    - `PolicyDefinitionInput`
    - `WorkflowDefinitionInput`
- file import strips the transport-only top-level `kind` before calling the guarded registry lifecycle
- if `kind` and body shape disagree, import rejects

The frozen public write surface for those files remains:

- guarded definition upload

Request granularity:

- each guarded upload request carries exactly one definition file or one definition body
- guarded upload does not recursively ingest referenced roles, policies, or workflows
- upload each referenced definition explicitly before starting a task that depends on it

Import and guarded upload use the same canonical schema validation. That means:

- `RoleDefinitionInput` and `PolicyDefinitionInput` must match the exact owned schemas in [Role And Policy Definition Schema](role-and-policy-definition-schema.md)
- `PolicyDefinitionInput` may author only the optional `budget_spec` keys `child_assignment_limit` and `retry_limit`, plus the V2 `human_request` and `command_run` capability families
- parent/root policies may author `child_assignment_limit` only; worker policies may author `retry_limit` only
- same-attempt redispatch and same-session continuation remain runtime continuity/recovery behavior, not authored definition grammar
- richer policy grammar such as `default_policy`, `defaults`, `defaults.retry_budget`, `rules`, or `same_attempt_continue_limit` is rejected rather than silently dropped
- guarded upload validates the workflow definition internally before current registry truth moves

## Compatibility-only bundle helper

If implementation retains explicit bundle-manifest import, it is a compatibility/helper surface only. It is not the canonical v1 batch import front door.

Retained helper shape:

```yaml
bundle_version: 1
definitions:
    - kind: role | policy | workflow
      key: string
      path: relative/path/from/manifest.yaml
```

If retained, bundle rules are:

- `bundle_version` is required and fixed to `1`
- `definitions` must be non-empty
- each `path` is relative to the bundle-manifest directory
- each file must contain exactly one definition body of the declared `kind`
- duplicate logical ids across the resolved bundle are validation errors
- any referenced policy body must satisfy the minimal live `PolicyDefinitionInput` schema, including the exact `budget_spec` key set

Worked example:

```yaml
bundle_version: 1
definitions:
    - kind: role
      key: review-role
      path: roles/review-role.yaml
    - kind: policy
      key: parent-review-policy
      path: policies/parent-review-policy.yaml
    - kind: workflow
      key: retry-review
      path: workflows/retry-review.yaml
```

## Root CLI import surface

The root CLI exposes a definition-import front door over the same guarded upload service.

Its rules are:

- `autoclaw definitions import --file <definition_path> [--overwrite reject|allow_new_revision]` is the explicit target wrapper shape
- zero-arg `autoclaw definitions import` is the canonical shallow current-working-directory scan/import path for the root CLI wrapper
- `--file` is the explicit import path
- zero-arg import is a shallow current-working-directory scan/import path
- zero-arg import scans only top-level `*.yaml` files in the current working directory
- zero-arg import does not recurse
- zero-arg import does not scan a configured root and does not scan a package-bundled root
- `--kind` is not part of the target CLI because file content already carries top-level `kind`
- `--overwrite` defaults to `reject`

Removed from live canon:

- legacy directory/recursive definition-import variants

Overwrite semantics:

- `reject` refuses a changed import when a current stored revision already exists for that `kind` plus logical key with different content
- `allow_new_revision` creates a new revision and lets DB commit order decide which concurrent upload becomes current
- current revisions are never mutated in place by import
- identical canonical content for the same `kind` plus logical key is a no-op, not a new revision

The root CLI wrapper remains a local authoring/import front door over the registry lifecycle. It does not become a second source of truth beside the guarded definitions API.

Concrete translation:

- the front doors are guarded upload through `POST /definitions` or `upload_definition(...)`, plus the local root CLI wrapper `autoclaw definitions import ...`
- each `POST /definitions` request body or `upload_definition(...)` call carries exactly one definition file/body
- the root CLI wrapper reads one local file or shallow-scans the current working directory for top-level `*.yaml`
- the shipped CLI wrapper accepts only files that match the canonical definition-file shape
- the shipped CLI wrapper ignores non-importable files and reports them with reasons
- the shipped CLI wrapper extracts top-level `kind`, parses the remaining body into the exact canonical definition input body, and then calls the guarded registry lifecycle
- the front door does not widen the schema or bypass guarded-write validation or DB serialization rules
- successful upload changes stored registry truth, not the source file itself

Example file contents:

```yaml
# roles/reviewer.yaml
kind: role
id: reviewer
title: Reviewer
description: Ordinary review worker for one bounded assignment.
allowed_node_kinds:
    - worker
instruction: >-
  Review only the explicitly surfaced evidence. Publish ordinary review artifacts and a checkpoint. Parent/root still decides the next control action.
```

```yaml
# policies/standard-worker.yaml
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
# workflows/auth-refresh-bugfix.yaml
kind: workflow
id: auth-refresh-bugfix
description: Fix the auth refresh regression and release only after review.
root:
    id: root
    role: root_planning_lead
    policy: standard-root
    description: Coordinate the flow and decide final closure.
    children:
        - id: implementation_subtree
          role: planning_lead
          policy: standard-parent
          description: Coordinate investigation, implementation, and review.
          children:
              - id: investigate_issue
                role: researcher
                description: Gather findings.
                produces:
                    artifacts:
                        - slot: findings_report
                          description: Findings for downstream implementation.
              - id: implement_change
                role: engineer
                description: Implement the scoped fix.
                consumes:
                    artifacts:
                        - slot: findings_report
                produces:
                    artifacts:
                        - slot: change_patch
                          description: Patch for the scoped fix.
```

Current shipped upload expectations:

- one guarded upload request does not auto-import referenced definitions from a workflow body
- readers should upload each referenced role, policy, and workflow definition explicitly unless they are using a separate batch helper
- partial success is legal only when the selected operator flow batches multiple files
- result output must distinguish:
    - imported definitions
    - unchanged no-op definitions
    - rejected invalid definitions
- imported and unchanged entries should be grouped by `role`, `policy`, and `workflow` keys when a batch helper is used

## `TaskStartEntrypointFileContract`

The canonical HTTP task-start route is:

- `POST /tasks/start`

The canonical external `operator MCP` parity entrypoint is:

- `start_task(task_compose_path)`

The canonical local root CLI parity entrypoint is:

- `autoclaw task-compose start --file <task_compose_path>`

Entry-point rules:

- the file at `task_compose_path` must parse exactly as `TaskStartRequest`
- the current shipped `operator MCP` surface loads that local file and submits the resulting body to the same canonical backend task-start handler behind `POST /tasks/start`
- the shipped root CLI wrapper does the same thing over the same handler
- there is no separate task-file upload, staged task upload, or multipart task content lane in v1
- supporting task content enters only through:
    - `task.instruction`
    - the bound `workspace` root
    - the bound `context` root

Worked example:

`operator MCP` or one OpenClaw package or parity wrapper over that surface does the current shipped local-file handoff:

```text
start_task("C:/tasks/bugfix/task-compose.yaml")
```

Neither surface uploads an arbitrary archive or multipart payload in v1.

## Related contracts

- [Definition registry and upload contract](definition-registry-and-upload-contract.md)
- [API schema appendix](api-schema-appendix.md)
- [Task compose schema](../workflows/task-compose-schema.md)
- [CLI surface and operator workflows](cli-surface-and-operator-workflows.md)
