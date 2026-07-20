# API Schema Appendix

Status: Target

This appendix is the schema companion for the frozen design interface surface.

Primary contract pages still own route meaning and behavioral semantics. This page freezes the named request and response objects, shared ref families, and the route-carried payload shapes that must stay aligned with the canonical lane map.

## Shared object ownership

- runtime truth and projection/currentness rules are owned by [Runtime Database And Object Contract](../architecture/runtime-database-and-object-contract.md) and [Runtime Records And Lifecycle](../architecture/runtime-records-and-lifecycle.md).
- surfaced ref taxonomy is owned by [Manifest Contract](../architecture/manifest-contract.md) and [Artifact Ref And Storage Contract](../architecture/artifact-ref-and-storage-contract.md).
- authored workflow input semantics are owned by [Workflow Definition Schema](../workflows/workflow-definition-schema.md).
- `TaskStartRequest` semantics are owned by [Task Compose Schema](../workflows/task-compose-schema.md).
- role and policy definition bodies are owned by [Role And Policy Definition Schema](role-and-policy-definition-schema.md).
- callback write bodies are semantic submissions only. Callers do not author runtime-minted ids, materialized runtime-file refs, or durable publication currentness through these schemas.

## Shared enums

### `DefinitionKind`

- `role`
- `policy`
- `workflow`

### `FlowStatus`

- `pending`
- `running`
- `blocked`
- `paused`
- `succeeded`
- `cancelled`

### `IngressBoundary`

- `dispatch`

### `EgressBoundary`

- `yield`
- `green`
- `retry`
- `blocked`

### `CheckpointKind`

- `progress`
- `terminal`

### `AttemptOutcome`

- `green`
- `retry`
- `blocked`

### `ParentRootToolName`

- `assign_child`
- `add_child`
- `update_child`
- `remove_child`
- `release_green`
- `release_blocked`

### `DispatchSendMode`

- `full_prompt`

### `DispatchDeliveryStatus`

This is the normalized observability-facing delivery projection used on operator and observability surfaces.

It is the shared vocabulary for operator-trace `delivery_status` and observability `delivery-state.json.transport_state`; it does not include legacy `callback_progressed` wording.

- `prepared`
- `accepted`
- `provider_signal_seen`
- `provider_completed`
- `provider_failed`
- `transport_failed`
- `transport_ambiguous`
- `superseded`

### `OperationFailureCode`

- `invalid_request_shape`
- `illegal_caller`
- `illegal_target_relation`
- `illegal_state`
- `stale_dispatch`
- `stale_flow_revision`
- `stale_assignment`
- `stale_checkpoint`
- `missing_resource`
- `missing_required_publication`
- `budget_exhausted`
- `conflicting_continuation`
- `boundary_precondition_failed`
- `removed_surface`
- `internal_error`

## Shared ref families

Alias convention:

- the shared family names below define the canonical ref taxonomy
- when a carrier fixes one exact kind, the alias may omit the fixed `kind` field in the rendered shape
- when a carrier unions multiple ref kinds, the rendered shape carries `kind` explicitly

### `node_runtime_file_ref`

Use this family for node-visible runtime projections.

- `kind` as `manifest | assignment | checkpoint | artifact_index | transient_index`
- `path`
- `description`

Rules:

- these refs are controller-generated reread surfaces
- callback write payloads do not author `node_runtime_file_ref` values directly

### `support_runtime_file_ref`

Use this family for observability-only runtime projections.

- `kind` as `delivery_state | continuity_state | watchdog_state | provider_events`
- `path`
- `description`

`support_runtime_file_ref` remains the shared family name for delivery, continuity, watchdog, and provider-event refs.

### `evidence_ref`

Use this family for read-side durable or explicitly surfaced reading material.

Variant rules:

- `artifact`
    - exact ordinary fields: `slot`, `version`, `path`, `description`
- `criteria`
    - exact ordinary fields: `slot`, `path`, `description`
- `doc`
    - exact ordinary fields: `path`, `description`
- `wiki`
    - exact ordinary fields: `path`, `description`
- `transient`
    - exact ordinary fields: `path`, `description`

Shared evidence-ref rules:

- ordinary artifact refs do not surface `owner_node_key`
- ordinary refs do not surface `producer_node_key`
- ordinary refs do not surface `uri` or `url`
- artifact example paths must include the publishing node namespace: `outputs/artifacts/<owner_node_key>/<slot>/...`
- durable evidence refs are surfaced by runtime-managed read projections
- explicit transient surfaces may still be authored directly on assignment or checkpoint writes

### Fixed-kind aliases

The following aliases reuse the shared family names above.

#### Node-runtime aliases

- `workflow_manifest_ref`
    - `path`
    - `description`
- `assignment_file_ref`
    - `path`
    - `description`
- `checkpoint_file_ref`
    - `path`
    - `description`
- `artifact_index_ref`
    - `path`
    - `description`
- `transient_index_ref`
    - `path`
    - `description`

#### Observability aliases

- `delivery_state_ref`
    - `path`
    - `description`
- `continuity_state_ref`
    - `path`
    - `description`
- `watchdog_state_ref`
    - `path`
    - `description`
- `provider_events_ref`
    - `path`
    - `description`

#### Evidence aliases

- `artifact_ref`
    - `slot`
    - `version`
    - `path`
    - `description`
- `criteria_ref`
    - `slot`
    - `path`
    - `description`
- `doc_ref`
    - `path`
    - `description`
- `wiki_ref`
    - `path`
    - `description`
- `transient_ref`
    - `path`
    - `description`

Example durable artifact ref:

```yaml
slot: findings_report
version: 2
path: C:/tasks/task_2026_0042/outputs/artifacts/review_node/findings_report/findings_report.v02.md
description: Current durable findings report for the review node.
```

### Mixed-carrier aliases

#### `assignment_consume_ref`

This is one of:

- `checkpoint_file_ref`
- `artifact_ref`
- `criteria_ref`
- `doc_ref`
- `wiki_ref`

Rules:

- `checkpoint` is the only node-runtime file ref legal in `consumes`
- `transient` does not appear here and stays in `transient_refs`

#### `assignment_transient_ref`

This is `transient_ref`.

#### `checkpoint_transient_ref`

This is `transient_ref`.

#### `operator_support_surface_ref`

Use this mixed ref only on `/operator/...` and `/observability/...` carriers.

- `kind` as `manifest | assignment | checkpoint | artifact_index | transient_index | delivery_state | continuity_state | watchdog_state | provider_events | artifact | criteria | doc | wiki | transient`
- `slot` as `string | null`
- `version` as `integer | null`
- `path`
- `description`

Rules:

- `operator_support_surface_ref` is forbidden on `/runtime/...` and `/callback/...` schemas
- observability-only refs remain observability/operator-only even when they are path-based files

## Assignment and checkpoint bodies

### `assignment_intent`

- `summary`
- `instruction` as `string | null`

### `supplemental_durable_context`

- `artifact_slots` as `[{ slot }, ...] | optional`
- `criteria_slots` as `[{ slot }, ...] | optional`

Rules:

- this field is semantic slot-based durable context sharing only
- callers do not submit final durable `path`, `version`, `description`, or currentness claims here
- callers must not pass a child its own produced artifact slot through `artifact_slots`; use explicit `transient_surfaces` for previous same-node material

### `assignment_produce_requirement`

- `slot`
- `description`
- `file_hint` as `string | null`

### `assignment_body`

- `summary`
- `instruction` as `string | null`
- `criteria` as `[criteria_ref, ...]`
- `consumes` as `[assignment_consume_ref, ...]`
- `produces` as `[assignment_produce_requirement, ...]`
- `transient_refs` as `[assignment_transient_ref, ...] | optional`

Rules:

- `assignment_body` is the runtime-projected read shape
- `assignment_body` is not the parent-authored `assign_child` write shape

### `checkpoint_handoff`

- `summary`
- `next_step`
- `blockers` as `[string, ...] | optional`
- `risks` as `[string, ...] | optional`

### `produced_artifact_claim`

- `kind` as `artifact`
- `slot`
- `path`

Rules:

- this is a reduced durable claim only
- callers do not author `version`, final surfaced `description`, `owner_node_key`, `assignment_key`, `attempt_id`, or currentness here

### `transient_surface_write`

- `path`
- `description`

### `checkpoint_write_body`

- `checkpoint_kind` as `CheckpointKind`
- `outcome` as `AttemptOutcome | null`
- `handoff` as `checkpoint_handoff`
- `produced_artifacts` as `[produced_artifact_claim, ...] | optional`
- `transient_surfaces` as `[transient_surface_write, ...] | optional`

Rules:

- `checkpoint_write_body` is the semantic `record_checkpoint` write body, not the materialized checkpoint file
- `produced_artifacts` are reduced durable claims only; callers do not author surfaced `artifact_ref` path/version tuples here
- runtime later resolves any durable reread refs and checkpoint projections from committed truth
- `transient_surfaces` remain explicit node-authored carryover surfaces only
- terminal `green` checkpoints must include one `produced_artifacts` claim for every declared produce slot and satisfy the non-pointer preflight needed by the matching `green` boundary before they are accepted

## Parent/root tool payloads

### `AssignChildPayload`

- `child_node_key`
- `assignment_intent`
- `supplemental_durable_context` as `supplemental_durable_context | optional`
- `transient_surfaces` as `[transient_surface_write, ...] | optional`

Rules:

- callers do not submit runtime-minted `assignment_key` or `attempt_id`, materialized `assignment.*` file content, or guessed child checkpoint refs
- runtime derives the baseline durable child contract from the child node definition
- callers may add only semantic mission wording, supplemental durable slot sharing, and explicit transient carryover
- controller commits the fresh child assignment/attempt lineage and then surfaces reread refs through success/read models

### `AddChildPayload`

- `child` as `ChildNodeDraft`
- `target_parent_node_key` | optional

Rules:

- omitted `target_parent_node_key` adds under the current parent/root node
- explicit `target_parent_node_key` must name the current node or a descendant parent inside the caller's owned subtree

### `UpdateChildPayload`

- `child_node_key`
- `patch` as `ChildNodePatch`

Rules:

- `child_node_key` must name an explicit descendant node inside the caller's owned subtree

### `RemoveChildPayload`

- `child_node_key`

Rules:

- `child_node_key` must name an explicit descendant node inside the caller's owned subtree

### `ReleaseGreenPayload`

- empty object

### `ReleaseBlockedPayload`

- empty object

## Public route request and response coverage

### `DefinitionSummaryRead`

- `key`
- `title` as `string | null`
- `description` as `string | null`
- `current_revision_no`
- `allowed_node_kinds` as `[root | parent | worker, ...] | null`
- `applies_to` as `[root | parent | worker, ...] | null`
- `budget_spec` as `{ child_assignment_limit as integer | null, retry_limit as integer | null } | null`
- `labels` as `[string, ...]`
- `updated_at`

Rules:

- `title` is populated for role and policy summaries
- `description` is the discovery description surfaced from the current revision body
- `labels` is populated from role or policy definition labels and is empty for workflows
- `allowed_node_kinds` is populated for role summaries only
- `applies_to` and `budget_spec` are populated for policy summaries only
- workflow summaries keep those compatibility-only fields null

### `DefinitionListQuery`

- `q` as `string` | optional
- `limit` as `integer` in `1..200` | optional; defaults to `50`
- `cursor` as `string | null`
- `sort` as `updated_at_desc | updated_at_asc | key_asc | key_desc` | optional; defaults to `updated_at_desc`
- `allowed_node_kind` as `root | parent | worker | null`
- `applies_to` as `root | parent | worker | null`

Rules:

- `q` is free-text search over definition key, description, and instruction
- `allowed_node_kind` is legal only on the roles list route
- `applies_to` is legal only on the policies list route
- list routes do not accept both route-specific node-kind filters at once because each route fixes one definition kind already

### `DefinitionSummaryListResponse`

- `kind` as `DefinitionKind`
- `items` as `[DefinitionSummaryRead, ...]`
- `next_cursor` as `string | null`

### `DefinitionRevisionHistoryEntry`

- `revision_no`
- `recorded_by` as `string | null`
- `updated_at`

### `DefinitionRevisionHistoryQuery`

- `limit` as `integer` in `1..200` | optional; defaults to `50`
- `cursor` as `string | null`
- `sort` as `revision_no_desc | revision_no_asc | updated_at_desc | updated_at_asc` | optional; defaults to `revision_no_desc`

### `DefinitionRevisionHistoryResponse`

- `key`
- `kind` as `DefinitionKind`
- `current_revision_no`
- `items` as `[DefinitionRevisionHistoryEntry, ...]`
- `next_cursor` as `string | null`

### `DefinitionUploadRequest`

- `kind` as `DefinitionKind`
- `content` as exactly one of:
    - `RoleDefinitionInput`
    - `PolicyDefinitionInput`
    - `WorkflowDefinitionInput`

Rules:

- logical key comes from `content.id`
- callers do not submit a second path key for guarded upload
- `kind` must agree with `content`
- identical canonical content for the same `kind` plus logical key is a no-op, not a new revision
- concurrent uploads are serialized in DB and may both succeed as distinct new revisions
- the current revision pointer advances in commit order

### `DefinitionRevisionDetailResponse`

- `key`
- `revision_no`
- `content` as exactly one of:
    - `RoleDefinitionInput`
    - `PolicyDefinitionInput`
    - `WorkflowDefinitionInput`
- `recorded_by` as `string | null`
- `updated_at`

### `TaskStartRequest`

`POST /tasks/start` accepts the authored task-start body from [Task Compose Schema](../workflows/task-compose-schema.md).

Rules:

- `task.title`, `task.summary`, and optional `task.instruction` are task-wide identity inputs visible to every node
- the first/root assignment is generated at launch from task identity plus launch-selected current node purpose, node instruction, and static role/policy instruction assembly
- callers do not author a separate `initial_assignment` object in workflow YAML or in `TaskStartRequest`

### `TaskStartResponse`

- `task_id`
- `compiled_plan_id`
- `active_flow_revision_id`
- `flow_status` as `FlowStatus`
- `workflow_manifest_ref` as `workflow_manifest_ref`

Rules:

- `TaskStartResponse` does not expose a public `dispatch_id`
- `TaskStartResponse` does not require or surface a public `flow_id`

### `RuntimeFlowSummary`

- `task_id`
- `task_title`
- `task_summary`
- `workflow_key` as `string | null`
- `status` as `FlowStatus`
- `active_flow_revision_id`
- `workflow_manifest_ref` as `workflow_manifest_ref`
- `current_node_key` as `string | null`
- `active_attempt_id` as `string | null`
- `updated_at`

### `RuntimeTaskListQuery`

- `q` as `string` | optional
- `limit` as `integer` in `1..200` | optional; defaults to `50`
- `cursor` as `string | null`
- `sort` as `updated_at_desc | updated_at_asc | task_title_asc | task_title_desc` | optional; defaults to `updated_at_desc`
- `status` as `any | pending | running | blocked | paused | succeeded | cancelled` | optional; defaults to `any`

Rules:

- `q` is free-text search over `task_id`, `task_title`, `task_summary`, `workflow_key`, and `current_node_key`

### `RuntimeFlowSummaryListResponse`

- `items` as `[RuntimeFlowSummary, ...]`
- `next_cursor` as `string | null`

### `RuntimeFlowRead`

- `task_id`
- `task_title`
- `task_summary`
- `workflow_key` as `string | null`
- `status` as `FlowStatus`
- `active_flow_revision_id`
- `workflow_manifest_ref` as `workflow_manifest_ref`
- `current_node_key` as `string | null`
- `active_attempt_id` as `string | null`
- `updated_at`

### `RuntimeFlowControlQuery`

- `expected_active_flow_revision_id`

### `RuntimeFlowPauseResponse`

- `flow` as `RuntimeFlowRead`

### `top_actionable_item`

- `summary`
- `node_key` as `string | null`
- `current_paths` as `[operator_support_surface_ref, ...]`
- `suggested_action` as `string | null`

Rule:

- `current_paths` are support/readback refs only and do not define semantic currentness, resume target, or flow-control truth
- `suggested_action` is advisory only and is not core runtime truth

### `OperatorFlowSnapshotResponse`

- `flow` as `RuntimeFlowRead`
- `top_actionable_items` as `[top_actionable_item, ...]`
- `current_paths` as `[operator_support_surface_ref, ...]`

Rule:

- `current_paths` are support/readback refs only and do not define semantic currentness, resume target, or flow-control truth

### `OperatorFlowTraceQuery`

- `scope` as `current | whole` | optional; defaults to `current`
- `q` as `string` | optional
- `limit` as `integer` in `1..200` | optional; defaults to `50`
- `cursor` as `string | null`
- `sort` as `occurred_at_desc | occurred_at_asc` | optional; defaults to `occurred_at_desc`

Rules:

- `q` is free-text search over checkpoint summaries, node keys, boundary names, and normalized delivery history

### `DispatchHistoryEntry`

- `attempt_id`
- `assignment_key` as `string | null`
- `node_key`
- `send_mode` as `DispatchSendMode` | current/debt observability field only
- `delivery_status` as `DispatchDeliveryStatus`
- `rendered_at`

Rule:

- `delivery_status` is an observability-facing delivery projection only
- `send_mode` is current/debt readback only and may disappear when the remaining wrapper residue is removed

### `CheckpointHistoryEntry`

- `checkpoint_id`
- `attempt_id`
- `checkpoint_kind` as `CheckpointKind`
- `outcome` as `AttemptOutcome | null`
- `summary`
- `recorded_at`

### `BoundaryHistoryEntry`

- `node_key`
- `boundary` as `EgressBoundary`
- `occurred_at`

### `OperatorFlowTraceResponse`

- `task_id`
- `scope`
- `dispatch_history` as `[DispatchHistoryEntry, ...]`
- `checkpoint_history` as `[CheckpointHistoryEntry, ...]`
- `boundary_history` as `[BoundaryHistoryEntry, ...]`
- `current_paths` as `[operator_support_surface_ref, ...]`
- `next_cursor` as `string | null`

Rule:

- `current_paths` are support/readback refs only and do not define semantic currentness, resume target, or flow-control truth

## Callback route request and response coverage

### `DispatchContextRead`

Removed from the canonical live v1 callback lane.

Rules:

- canonical v1 callback is write-only
- worker reread happens through surfaced filesystem projections and prompt-visible paths instead
- if implementation retains any helper read envelope during migration, treat it as compatibility only rather than canonical callback contract

## Static node and callback call context

The v1 node/callback semantic contract uses explicit call context instead of hidden binding authority as target truth.

### `node_tool_context`

- `session_key`
- `task_id`

Rules:

- `session_key` is the primary v1 node-tool authority input
- `task_id` is also required and must match controller truth for that `session_key`
- callers do not author `dispatch_id`, `attempt_id`, callback-binding ids, or transport headers through this context
- this context belongs to static `node MCP` tool calls and the shared node/callback semantic authority model; callback HTTP may still carry it through transport-local shapes during migration

### `node_definition_lookup_call`

- `session_key`
- `task_id`
- `kind` as `role | policy`
- `query` | nullable
- `limit` | nullable
- `cursor` | nullable
- `sort` | nullable
- `allowed_node_kind` | nullable
- `applies_to` | nullable

### `node_definition_detail_call`

- `session_key`
- `task_id`
- `kind` as `role | policy`
- `key`

### `node_checkpoint_call`

- `session_key`
- `task_id`
- `checkpoint` as `checkpoint_write_body`

### `node_boundary_call`

- `session_key`
- `task_id`
- `boundary` as `EgressBoundary`

### `node_parent_tool_call`

- `session_key`
- `task_id`
- `tool_name` as `ParentRootToolName`
- `payload` as one exact payload shape matching `tool_name`
- `expected_structural_revision_id` as `string | null`

Rules:

- static `node MCP` wrappers preserve this exact discriminated request shape
- wrappers must not widen `payload` to a generic object contract divorced from `tool_name`

### `CheckpointWrite`

- `checkpoint` as `checkpoint_write_body`

Rules:

- this is the semantic `record_checkpoint` handoff write only
- callback authority remains an internal concern for HTTP callback transport and is not authored in this body
- callers do not author `checkpoint_id`, `checkpoint_ref`, `latest_checkpoint_ref`, or materialized durable reread refs here
- `produced_artifacts` are reduced durable claims only; surfaced durable refs are runtime-managed read projections
- `transient_surfaces` are the explicit surfaced carryover lane when non-durable context must survive reread

### `CheckpointRead`

- `attempt_id`
- `checkpoint_id`
- `checkpoint_ref` as `checkpoint_file_ref`
- `latest_checkpoint_ref` as `checkpoint_file_ref`

Rules:

- these refs are runtime-managed reread surfaces for the committed checkpoint state
- `CheckpointRead` does not inline surfaced durable refs; callers reread the checkpoint projection and current assignment/manifest surfaces instead
- static `node MCP` wrappers preserve this typed read model rather than flattening it into an untyped generic object contract

### `BoundaryWrite`

- `boundary` as `EgressBoundary`

### `BoundaryRead`

- `accepted_boundary` as `EgressBoundary`
- `flow` as `RuntimeFlowRead`
- `latest_checkpoint_ref` as `checkpoint_file_ref | null`

Rules:

- `latest_checkpoint_ref` is required for `green`, `retry`, and `blocked`
- `latest_checkpoint_ref` may be `null` for `yield`
- static `node MCP` wrappers preserve this typed read model rather than flattening it into an untyped generic object contract

### `ParentToolCall`

- `tool_name` as `ParentRootToolName`
- `payload` as one exact payload shape matching `tool_name`
- `expected_structural_revision_id` as `string | null`

Rules:

- caller identity for HTTP callback transport remains implicit from the bound current execution context
- callback write carriers remain write-only and do not double as worker read envelopes
- callback request bodies do not surface callback binding fields

### `AssignChildSuccess`

- `tool_name` as `assign_child`
- `summary` as `string | null`
- `target_node_key`
- `target_assignment_key`
- `target_attempt_id`
- `child_assignment_ref` as `assignment_file_ref | null`
- `flow` as `RuntimeFlowRead`
- `workflow_manifest_ref` as `workflow_manifest_ref | null`
- `latest_checkpoint_ref` as `checkpoint_file_ref | null`

### `ParentToolMutationSuccess`

- `tool_name` as `add_child | update_child | remove_child | release_green | release_blocked`
- `summary` as `string | null`
- `target_node_key` as `string | null`
- `flow` as `RuntimeFlowRead`
- `workflow_manifest_ref` as `workflow_manifest_ref | null`
- `latest_checkpoint_ref` as `checkpoint_file_ref | null`

### `ParentToolSuccess`

`ParentToolSuccess` is the internal typed union helper for the callback structural-mutation family, not the primary tool-facing contract.

The callback structural-mutation family returns exact per-tool success carriers:

- `AssignChildSuccess`
- `AddChildSuccess`
- `UpdateChildSuccess`
- `RemoveChildSuccess`
- `ReleaseGreenSuccess`
- `ReleaseBlockedSuccess`

Rules:

- the structural tool success carriers do not expose callback transport-binding fields
- the structural tool success carriers do not expose success-side `suggested_next_step`
- `AssignChildSuccess` does not expose a child `dispatch_id`
- static `node MCP` wrappers preserve these exact per-tool success shapes rather than widening them to a generic object map

## Observability route response coverage

Observability routes surface fixed-kind `support_runtime_file_ref` aliases such as:

- `delivery_state_ref`
- `continuity_state_ref`
- `watchdog_state_ref`
- `provider_events_ref`

Rules:

- operator/support read surfaces use `task_id`; internal dispatch chronology stays hidden behind controller resolution
- these refs remain observability-only readback
- they do not become ordinary callback or public-runtime context
- watchdog recovery is internal controller behavior rather than a canonical observability response family
- non-behavioral fields retained inside those readbacks are current/debt residue only and are not frozen by this appendix

## Error and status semantics

Transport/status mapping:

- `400` = invalid route, query, or body shape
- `404` = missing target definition, flow, revision, or dispatch
- `409` = stale-write or optimistic-currentness conflict
- `422` = semantically invalid but successfully evaluated request
- `500` = unexpected controller/internal failure

### `operation_failure`

- `ok` as `false`
- `code` as `OperationFailureCode`
- `summary`
- `retryable` as `boolean`
- `field_path` as `string | null`
- `suggested_next_step` as `string | null`

Rules:

- this is the canonical semantic failure body for definition, runtime, callback, operator, node MCP, and observability rejects
- the envelope does not widen with sibling `message`, `reason`, `expected`, or `received` fields

## Removed from the live schema appendix

Do not keep these as live appendix shapes:

- preview success `valid`
- `runtime_surface_ref`
- `artifact_runtime_ref`
- callback binding fields such as `manifest_id`, `manifest_hash`, `node_session_key`, and `ack_checkpoint_id`
- callback-era worker callback envelopes
- `BoundaryKind`
- `BoundarySubtype`
- `BoundaryAction`

## Related contracts

- [API surface and trust-lane map](api-surface-and-trust-lane-map.md)
- [Definition registry and upload contract](definition-registry-and-upload-contract.md)
- [Plugin tool reference](plugin-tool-reference.md)
