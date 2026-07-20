# Manifest Contract

Status: Target

This page defines the one canonical whole-workflow manifest for the frozen v1 runtime model.

The manifest is the controller-generated workflow contract that agents read. Controller/DB state remains the final authority.

## Core rule

V1 keeps one canonical agent-visible manifest family only:

- `_runtime/workflow-manifest.json`
- `_runtime/workflow-manifest.md`

Rules:

- There is no live flow/scope manifest split.
- There is no canonical scope-manifest, flow-manifest, flow-brief, or scope-brief dependency in the v1 agent model.
- The manifest is a derived workflow contract generated from current controller/DB truth.
- Agents read the manifest; they do not patch it, acknowledge it, or treat it as authored workflow YAML.
- Runtime structural CRUD adopts controller truth first, then regenerates the manifest in place.

## Manifest authority

- Controller/DB state owns runtime truth.
- `_runtime/workflow-manifest.*` is the durable shared workflow picture generated from that truth.
- If the manifest and controller/DB state disagree, controller/DB state wins.
- Monitoring files are not manifest truth and do not override workflow truth.
- This manifest family is rewritten through synchronous post-commit writers, not through a generic queued refresh contract.

## Exact distinctions

### Manifest versus workflow definition

- Authored workflow YAML is hidden source material.
- The manifest is the rendered effective workflow contract that agents see.
- Agents should not be told to inspect authored YAML directly to understand the current workflow.

### Manifest versus assignment

- The manifest explains the whole workflow, current node position, filesystem path bindings, dependency map, and currently surfaced refs.
- The assignment explains what the current node should do now.
- Current mission wording, selected must-read refs, and bounded transient carryover belong in `assignment.*`, not in the manifest.
- Exact assignment field ownership lives in [Assignment contract](assignment-contract.md).

### Manifest versus checkpoint

- The manifest is the durable workflow picture.
- The checkpoint is the durable attempt summary of what happened and what should happen next.
- Later agents should not infer attempt history from the manifest when `latest-checkpoint.*` is the correct surface.
- Exact checkpoint field ownership lives in [Checkpoint contract](checkpoint-contract.md).

### Manifest versus artifacts and transient files

- The manifest may point at durable or transient files through compact surfaced refs.
- It must not inline full artifact bodies, full criteria content, or full transient file bodies.
- Drilldown content lives in artifacts, criteria files, transient files, assignments, and checkpoints.

### Manifest versus monitoring

- The manifest is workflow context.
- `_runtime/dispatch/<dispatch_id>/delivery-state.json`, `continuity-state.json`, `watchdog-state.json`, and `provider-events.ndjson` are monitoring/support projections only.
- Monitoring files are not parent/root workflow truth and are not part of the manifest contract.

## Canonical file contract

The canonical agent-visible runtime layout for this surface is:

```text
_runtime/
  workflow-manifest.json
  workflow-manifest.md
  attempts/
    <attempt_id>/
      assignment.json
      assignment.md
      latest-checkpoint.json
      latest-checkpoint.md
      artifact-index.json
      transient-index.json
```

Rules:

- Keep the manifest at the stable whole-task path `_runtime/workflow-manifest.*`.
- Keep attempt-local files under `_runtime/attempts/<attempt_id>/`.
- Parent/root/worker prompts should point at the stable manifest plus the attempt-local assignment/checkpoint/index files needed now.
- The manifest, attempt, and dispatch projection writers are synchronous post-commit helpers; callers provide current projections and those helpers write the task-root files directly.
- Do not require agents to read `_runtime/views/`, scope-local manifest mirrors, or brief families as part of the canonical contract.

## Required top-level sections

Minimum required manifest sections:

1. `manifest_version`
2. `active_flow_revision_id`
3. `generated_at`
4. `task`
5. `workflow`
6. `filesystem_roots`
7. `structural_edit_palette`
8. `current_context`
9. `node_tree`
10. `dependency_index`

Use `consumes / produces / criteria`, not old input/output wording. Use `path` only for surfaced refs in v1. Use `transient` as the live public transient term, not `transfer`.

## `task`

Required fields:

- `task_id`
- `task_key`
- `title`
- `summary`
- `instruction` | optional

`title`, `summary`, and optional `instruction` come from task compose and project into prompt `task_identity`. They do not become provider-side static `instructions`.

## `workflow`

Required fields:

- `workflow_key`
- `description`

## `filesystem_roots`

Required fields:

- `workspace_path`
- `context_path`
- `outputs_path`
- `tmp_path`
- `runtime_path`

These path bindings tell the agent exactly where stable surfaces live so it does not infer from messy folders.

## `structural_edit_palette`

This top-level section carries the compact registry-backed role/policy names that parent/root structural edits may use now.

Required machine fields:

- `roles`
- `policies`

`roles` entries must include:

- `role`
- `allowed_node_kinds`
- `description`

`policies` entries must include:

- `policy`
- `applies_to`
- `description`

Rules:

- use this palette as the surfaced structural-edit naming surface instead of broad “anything mentioned elsewhere in the prompt or manifest” wording
- the machine payload keeps `structural_edit_palette` even when both lists are empty
- the markdown manifest may omit a rendered `Structural Edit Palette` section when both lists are empty
- structural-edit naming stays separate from current node role/policy guidance and from node-tree topology

## `current_context`

Required fields:

- `current_node_key`
- `owner_node_key`
- `active_attempt_id`
- `active_assignment_path`
- `latest_checkpoint_path`
- `latest_relevant_checkpoint_path`
- `current_relevant_paths`

`current_relevant_paths` entries must use this explicit path-only shape:

```yaml
current_relevant_ref:
    one_of:
        - node_runtime_file_ref
        - evidence_ref

node_runtime_file_ref:
    kind: checkpoint | artifact_index | transient_index
    path: string
    description: string

evidence_ref:
    kind: criteria | artifact | wiki | doc | transient
    slot: string | null
    path: string
    description: string
```

Rules:

- V1 surfaced refs are path-only.
- Runtime must localize any external resource into the task root before surfacing it to agents.
- `node_runtime_file_ref` is limited here to additional node-visible runtime drilldown files such as checkpoint and attempt-local indexes.
- `evidence_ref` points at durable or explicit transient material the current node may inspect now.
- for `kind: criteria`, surface only `kind`, `slot`, `path`, and `description`
- For `kind: artifact`, surface only the compact artifact ref shape agents need now: `slot`, `version`, `path`, and `description`.
- `vNN` is a derived filename or rendering convention from `version`; it is not a separate stored field.
- Do not inline currentness history, supersession lineage, or controller-only ids into ordinary manifest refs.
- `description` is required. The agent must not infer meaning from a filename.
- `latest_checkpoint_path` is the current node's own latest checkpoint when one exists.
- `latest_relevant_checkpoint_path` is optional and points at the surfaced checkpoint chosen for parent/root redispatch handoff when that handoff differs from the current node's own checkpoint.
- When `latest_relevant_checkpoint_path` is non-null, it must match a surfaced `kind: checkpoint` entry from `current_relevant_paths`.
- Parent/root redispatch chooses `latest_relevant_checkpoint_path` from surfaced checkpoint refs by controller checkpoint truth, not by list order.
- ordinary direct-child checkpoint auto surfacing may still appear in `current_relevant_paths` for orientation, but it does not by itself choose `latest_relevant_checkpoint_path`
- `current_relevant_paths` may point at current assignment/checkpoint/index, key durable artifact/criteria files, curated wiki material, or exact transient refs when those help orient the current node.
- when a parent/root decision depends on child durable publications, surface the exact current child artifact refs here as compact `kind: artifact` evidence refs resolved from controller-owned current-pointer truth
- when a parent/root release reread depends on descendant evidence beyond the direct-child set, surface the controller-staged descendant checkpoint and artifact refs for that release turn here instead of reconstructing them by direct-child discovery
- `transient` entries remain transient even when surfaced here.
- `current_relevant_paths` must not become a hidden replacement for assignment or checkpoint content.
- observability-only files such as `delivery-state.json`, `continuity-state.json`, `watchdog-state.json`, and `provider-events.ndjson` are not legal `current_relevant_paths` entries in ordinary node-visible context.

Worked example:

```yaml
current_context:
    current_node_key: review_findings
    owner_node_key: review_findings
    active_attempt_id: attempt.review_findings.02
    active_assignment_path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.review_findings.02/assignment.md
    latest_checkpoint_path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.review_findings.02/latest-checkpoint.md
    latest_relevant_checkpoint_path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.investigate_issue.02/latest-checkpoint.md
    current_relevant_paths:
        - kind: checkpoint
          path: C:/tasks/task_2026_0042/_runtime/attempts/attempt.investigate_issue.02/latest-checkpoint.md
          description: Upstream investigation checkpoint surfaced for the current review decision.
        - kind: criteria
          slot: review_findings_delivery_criteria
          path: C:/tasks/task_2026_0042/_runtime/criteria/review_findings_delivery_criteria.v01.md
          description: Delivery criteria the review node must validate now.
        - kind: artifact
          slot: findings_report
          version: 2
          path: C:/tasks/task_2026_0042/outputs/artifacts/review_findings/findings_report/findings_report.v02.md
          description: Current findings report surfaced for parent/root review.
```

This example is intentionally compact:

- assignment still owns the mission wording
- checkpoint still owns the latest "what happened / what next" summary
- the manifest only tells later readers which concrete files are current and relevant now

## `node_tree`

Each node entry should include at least:

- `node_key`
- `parent_node_key`
- `child_node_keys`
- `node_kind`
- `role`
- `policy` | optional
- `description`
- `consumes`
- `produces`
- `criteria`
- `depends_on_node_keys`
- `depended_on_by_node_keys`

Rules:

- `node_kind` must distinguish `root | parent | worker`.
- `description` is required for every node.
- `consumes` and `produces` must carry slot descriptions, not bare slot names.
- `criteria` must identify owner node, slot, description, and path when a criteria file is materialized.
- criteria ownership stays with the declaring node even when direct-parent `child_defaults.criteria` expanded that slot onto another node at compile time; ordinary prompt and worker-context criteria refs stay compact and do not widen with `owner_node_key`.

## `dependency_index`

The manifest must expose dependency relationships directly.

Each dependency entry should make explicit:

- consumer node
- provider node
- dependency kind
- slot
- description

This can be rendered as a flat edge list or an equivalent direct map, but the agent-visible manifest must answer "who depends on what?" without hidden scope logic.

## Suggested canonical skeleton

```yaml
workflow_manifest:
  manifest_version: 1
  active_flow_revision_id: string
  generated_at: timestamp
  task:
    task_id: string
    task_key: string
    title: string
    summary: string
    instruction: >-
      string | null
  workflow:
    workflow_key: string
    description: string
  filesystem_roots:
    workspace_path: string
    context_path: string
    outputs_path: string
    tmp_path: string
    runtime_path: string
  structural_edit_palette:
    roles:
      - role: string
        allowed_node_kinds: [parent | worker, ...]
        description: string
    policies:
      - policy: string
        applies_to: [parent | worker, ...]
        description: string
  current_context:
    current_node_key: string
    owner_node_key: string
    active_attempt_id: string | null
    active_assignment_path: string | null
    latest_checkpoint_path: string | null
    latest_relevant_checkpoint_path: string | null
    current_relevant_paths:
      - kind: assignment | checkpoint | artifact_index | transient_index | criteria | artifact | transient | wiki
        slot: string | null
        version: integer | null for `kind: artifact`, otherwise omitted
        path: string
        description: string
  node_tree:
    - node_key: string
      parent_node_key: string | null
      child_node_keys: [string, ...]
      node_kind: root | parent | worker
      role: string
      policy: string | null
      description: string
      node_instruction: string | null
      consumes:
        artifacts: [slot_entry, ...] | optional
        criteria: [slot_entry, ...] | optional
      produces:
        artifacts: [slot_entry, ...] | optional
      criteria:
        - owner_node_key: string
          slot: string
          description: string
          path: string | null
      depends_on_node_keys: [string, ...] | optional
      depended_on_by_node_keys: [string, ...] | optional
  dependency_index:
    - consumer_node_key: string
      provider_node_key: string
      kind: artifact | criteria
      slot: string
      description: string
```

## Prompt rule

Prompts should teach this read order:

1. `_runtime/workflow-manifest.*` for the whole-workflow picture
2. current `_runtime/attempts/<attempt_id>/assignment.*` for the current mission
3. `latest_relevant_checkpoint_path` when present, otherwise the current attempt-local `latest-checkpoint.*` for durable handoff
4. surfaced `consumed_durable_refs` for exact current criteria, artifacts, docs, and wiki refs
5. optional `transient_refs`

Every parent/root/worker dispatch should surface at least:

- the stable `workflow-manifest.md` path
- a short description saying this is the whole-workflow visible contract
- the current assignment/checkpoint paths separately when those exist

The markdown and JSON twins describe the same contract. Prompts do not need to inline both payloads.

Concrete parent/root read example after structural mutation:

1. parent/root successfully commits `update_child`
2. runtime adopts the new structural revision
3. runtime regenerates `_runtime/workflow-manifest.*`
4. tool success surfaces the manifest path plus a short description
5. the still-open parent/root dispatch rereads the manifest before deciding whether to stage one child assignment and close with `yield`

The manifest contract does not change across send modes.

If a later dispatch uses adapter-private `same_session_continue`, that transport wrapper may omit only the prompt's static inline sections. It does not remove manifest fields, relax path-only surfaced-ref rules, or turn delivery-state observability files into manifest truth.

## Markdown rendering rule

`workflow-manifest.md` should mirror the JSON contract in scan-first form.

Recommended markdown section order:

1. Task
2. Workflow
3. Current Context
4. Filesystem Roots
5. Node Tree
6. Dependency Map
7. Criteria And Produce Contracts
8. Read Next

Rules:

- The markdown file is a rendering of the same manifest truth, not a separate authored narrative.
- Keep summaries short and use explicit paths.
- Do not hide current node, attempt-local file refs, or the dependency map in prose only.

## Removed from the live v1 model

Do not treat any of the following as live manifest contract:

- `flow-manifest`
- `scope-manifest`
- `_runtime/views/`
- scope-local manifest mirrors
- `flow-brief.md`
- scope-brief families
- `scope_key`
- `parent_gate`
- `current_boundary_summary`
- flow/scope brief dependency

## Related contracts

- [Worker context contract](worker-context-contract.md)
- [Runtime records and lifecycle](runtime-records-and-lifecycle.md)
- [Runtime boundary and controller loop contract](runtime-boundary-and-controller-loop-contract.md)
- [Task root layout and generated files](task-root-layout-and-generated-files.md)
- [Prompt contract](../prompt-layer/contract.md)
