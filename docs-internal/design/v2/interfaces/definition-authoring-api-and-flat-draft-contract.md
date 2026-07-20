# Definition authoring API and flat draft contract

Status: Target

This page defines the V2 backend and state contract for definition authoring.

## Core rule

Current registry revisions remain controller-owned reusable truth.

Definition drafts are backend-owned local pending authoring state over that truth. They are not a second registry, browser-owned state, or a hidden runtime lane.

The authoring lane stores one draft per `(kind, key)`. There is no bundle-level draft object.

Publishing a draft is the only authoring-draft path that changes current reusable definition truth. Saving, reading, validating, discarding, and replacing a draft only mutate backend-owned draft files under AutoClaw's configured data dir.

## Draft model

Canonical saved draft paths:

```text
<data_dir>/drafts/definitions/
  roles/
    <key>.yaml
  policies/
    <key>.yaml
  workflows/
    <key>.yaml
  _metadata/
    roles/
      <key>.json
    policies/
      <key>.json
    workflows/
      <key>.json
  _normalized/
    roles/
      <key>.json
    policies/
      <key>.json
    workflows/
      <key>.json
```

Rules:

- one saved draft exists for at most one `(kind, key)`
- create drafts use `mode=create` and must not collide with current registry truth or another saved draft
- update drafts use `mode=update` and capture `based_on.revision_no`, `based_on.content_hash`, and optional `based_on.source_path`
- saved YAML bodies are the editable truth for draft content
- normalized JSON shadows are backend-owned read models, not a second editable truth
- metadata owns baseline body, normalized baseline, mode, timestamps, status inputs, and stale-publish guards
- a YAML body file under `roles/`, `policies/`, or `workflows/` remains a saved draft even when metadata is missing; readback may synthesize metadata until the next save rewrites canonical metadata
- browser state may hold unsaved textarea edits, but saved draft state belongs to the backend

## Canonical API families

V2 authoring uses an explicit authoring lane rather than overloading the current `/definitions` registry routes.

Canonical route families are:

- `GET /authoring/definition-drafts`
- `POST /authoring/definition-drafts`
- `GET /authoring/definitions/{kind}/{key}/draft`
- `PUT /authoring/definitions/{kind}/{key}/draft`
- `DELETE /authoring/definitions/{kind}/{key}/draft`
- `POST /authoring/definitions/{kind}/{key}/draft/replace-current`
- `POST /authoring/definitions/{kind}/{key}/draft/validate`
- `POST /authoring/definitions/{kind}/{key}/draft/publish`
- `POST /authoring/task-compose/preview`

Rules:

- `/authoring` names local pending authoring state, not runtime control truth
- current registry reads and uploads remain under `/definitions`
- `kind` accepts only `role`, `policy`, or `workflow`
- `DELETE` returns `204 No Content`
- `GET /authoring/definitions/{kind}/{key}/draft` may return a transient unsaved update draft over current registry truth when no saved draft exists
- `PUT` saves a YAML body and creates a saved draft if one does not already exist
- resetting a draft to its baseline is a `PUT` of the captured `baseline_body`; it keeps the saved draft
- `POST /authoring/definitions/{kind}/{key}/draft/replace-current` refreshes a saved update draft from current registry truth and keeps the saved draft
- `POST /authoring/definition-drafts` creates explicit `create` or `update` drafts and fails on saved-draft or registry name collisions
- validation and publish read saved draft state; clients should save local edits first
- task-compose preview accepts the exact `TaskStartRequest` body and reads current registry truth rather than saved draft state
- stale publish and name collisions return structured non-published results or 409 operation failures depending on when the conflict is detected
- operator MCP is not the draft authoring lane; draft authoring remains on trusted HTTP `/authoring`

## Canonical envelopes

```yaml
definition_draft_baseline_read:
    revision_no: integer | null
    content_hash: string | null
    source_path: string | null

definition_draft_summary:
    kind: role | policy | workflow
    key: string
    mode: create | update
    draft_path: string
    normalized_path: string
    body_format: yaml
    content_hash: string
    based_on: definition_draft_baseline_read
    status: clean | modified | new | stale | invalid
    updated_at: timestamp

definition_draft_detail:
    <<: definition_draft_summary
    body: string
    normalized_content: object | null
    baseline_body: string | null
    baseline_normalized_content: object | null
    is_saved: boolean

definition_draft_list_query:
    cursor: string | null
    limit: integer

definition_draft_list_response:
    items:
        - definition_draft_summary
    next_cursor: string | null

definition_draft_create_request:
    kind: role | policy | workflow
    key: string
    mode: create | update
    body: string | null
    body_format: yaml

definition_draft_write_request:
    body: string
    body_format: yaml

definition_draft_detail_response:
    draft: definition_draft_detail
```

Validation uses:

```yaml
definition_draft_validation_issue:
    code: string
    message: string
    path: string | null
    kind: schema | cross_reference | stale | collision

definition_draft_validation_response:
    kind: role | policy | workflow
    key: string
    status: valid | invalid | stale | name_collision
    errors:
        - definition_draft_validation_issue
    warnings:
        - definition_draft_validation_issue
```

Task-compose preview is a separate read-only operation. It does not overload draft validation:

```yaml
task_compose_preview_issue:
    code: string
    message: string
    path: string | null
    kind: schema | cross_reference | provider | path

task_compose_preview_provider_resolution:
    requested_provider: codex | claude | openclaw
    resolved_provider: codex | claude | openclaw
    selection_basis: explicit | default

task_compose_node_preview:
    node_key: string
    provider_resolution: task_compose_preview_provider_resolution
    provider_native_access:
        effective: full | restricted | denied
        source: default | policy_definition | task_policy | controller
    network_access:
        effective: allow | deny
        source: default | policy_definition | task_policy | controller

task_compose_preview_response:
    status: ready | invalid
    nodes:
        - task_compose_node_preview
    errors:
        - task_compose_preview_issue
    warnings:
        - task_compose_preview_issue
```

Preview rules:

- the request body parses exactly as `TaskStartRequest`
- resolution uses the current workflow, role, and policy revisions plus current provider routing and controller ceilings
- every ready node reports both capability axes with the same effective-value and source shape used by runtime, API, CLI/status, current-context, and console readbacks
- the baseline `TaskStartRequest` has no task-policy override, so `task_policy` cannot be the winning source in this preview unless a later task-compose contract explicitly adds that input
- preview performs no provider or model I/O and creates no task, root, path lease, compiled plan, runtime row, dispatch, or external side effect
- preview is not a reservation or launch authorization; task start rereads current truth and recomputes provider and capability resolution
- saved draft changes are invisible to preview until they are published into current registry truth

Publish uses:

```yaml
definition_draft_published_revision:
    kind: role | policy | workflow
    key: string
    revision_no: integer
    content_hash: string

definition_draft_publish_response:
    kind: role | policy | workflow
    key: string
    status: published | invalid | stale | name_collision
    published_revision: definition_draft_published_revision | null
    validation: definition_draft_validation_response
```

## Collision and stale rules

Create mode:

- creating a draft for an existing current registry key returns `409 name_collision`
- creating a second saved draft for the same `(kind, key)` returns `409 name_collision`
- publishing rechecks current registry truth and returns `name_collision` if another writer published the key first

Update mode:

- the saved draft captures the current revision number and content hash when the draft is created or first saved
- publish compares the saved baseline to current registry truth before writing
- if the current revision moved, publish returns `stale` and does not overwrite current truth
- no-op update publish may return `published` with `published_revision=null` only when validation succeeded and content already matches current truth

## Validation scope

Validation is per draft. Workflow cross-reference validation uses:

- candidate workflow content from the saved draft
- current registry truth for referenced roles and policies

If a workflow needs a new role or policy, publish that role or policy first, then validate and publish the workflow draft.

Flat drafts intentionally do not provide bundle validation across several definitions. A future proposal/workspace feature may add multi-definition review, but it must not reintroduce hidden bundle coupling into the baseline authoring lane.
