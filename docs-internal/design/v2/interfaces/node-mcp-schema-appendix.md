# Node MCP schema appendix

Status: Target

This appendix owns the exact V2 model-visible projection rules and the request, response, validation, path, failure, and activity contract for `get_current_context`, `list_files`, `read_file`, and `set_work_plan`.

## Projection rule

AutoClaw defines each tool once from a semantic request schema.

The managed projection presents that schema unchanged:

```yaml
ManagedRequest:
  <semantic fields only>
```

The compatibility projection constructs a strict wrapper:

```yaml
CompatibilityRequest:
  task_id: nonempty full controller ID
  dispatch_id: nonempty full controller ID
  <the same semantic fields>
```

Additional properties are forbidden in both projections. The compatibility selectors are not part of the semantic operation and never appear in managed schemas or responses.

Managed scope comes from an authenticated `DispatchMcpBinding`. Compatibility scope comes only from the explicit selectors. Both paths then perform the same fresh controller read and require the exact current `starting` or `open` dispatch; a stale dispatch never redirects to another one.

## Success and failure results

Every tool returns its named success shape or:

```yaml
OperationFailure:
  ok: false
  code: OperationFailureCode
  summary: string
  retryable: boolean
  field_path: string | null
  suggested_next_step: string | null
```

Additional properties are forbidden. MCP marks failures with `isError: true` and may repeat the summary as text content. Successful payloads do not add an `ok` discriminator.

All timestamps are RFC 3339 UTC strings. All logical paths use `/` separators and are relative to the logical task namespace. Controller IDs are returned in full.

## Shared read types

```yaml
AssignmentContextRead:
  assignment_id: string
  node_key: string
  node_kind: worker | parent | root
  summary: string
  instruction: >-
    string | null
  criteria:
    - slot: string
      path: string
      description: string

AttemptContextRead:
  attempt_id: string
  assignment_id: string
  retry_of_attempt_id: string | null

WorkPlanStepRead:
  step: nonempty string
  status: pending | in_progress | completed

WorkPlanRead:
  assignment_id: string
  revision: integer >= 1
  explanation: string | null
  steps: [WorkPlanStepRead, ...] # 1..9
  authored_by_dispatch_id: string
  updated_at: timestamp

SlotContextRead:
  slot: string
  kind: artifact | criteria | checkpoint | transient | workspace
  description: string
  path: string | null
  version: integer >= 1 | null

RuntimeReadbackRefs:
  instructions: task-relative logical path
  input: task-relative logical path
  workflow_manifest: task-relative logical path

WorkflowNeighborRead:
  node_key: string
  node_kind: worker | parent | root
  relationship: string
  assignment_id: string | null

EffectiveCapabilitySet:
  dispatch_id: string
  provider_native_access:
    effective: full | restricted | denied
    source: default | policy_definition | task_policy | controller
  network_access:
    effective: allow | deny
    source: default | policy_definition | task_policy | controller
  human_request:
    direction: allow | deny
    approval: allow | deny
    input: allow | deny
    review: allow | deny
  command_run: allow | deny
```

Continuation types are discriminated by `kind` and embed the exact controller source owned by the human-request, command-run, watchdog, child-return, or retry contract. They never contain provider output or transport/session state.

For slot reads, `path` is the current logical task path when a body is materialized, an unmaterialized produce requirement has `path: null`, and `version` is present only for a versioned artifact.

## `get_current_context`

### Semantic request

```yaml
GetCurrentContextRequest: {}
```

### Success response

```yaml
GetCurrentContextResponse:
  task_id: string
  dispatch_id: string
  assignment: AssignmentContextRead
  attempt: AttemptContextRead
  trigger: CurrentContextTriggerRead
  plan: WorkPlanRead | null
  workflow_neighborhood: [WorkflowNeighborRead, ...]
  readback_refs: RuntimeReadbackRefs
  capabilities: EffectiveCapabilitySet
  allowed_actions: [string, ...]
  consume_slots: [SlotContextRead, ...]
  produce_slots: [SlotContextRead, ...]
  continuation: object | null
  checkpoint_to_resume_from: string | null
```

```yaml
CurrentContextTriggerRead:
  kind: root_start | accepted_boundary | child_return | human_result | command_result | watchdog_recovery | semantic_retry | operator_continue
  source_dispatch_id: string | null
```

`allowed_actions` contains provider-neutral logical operation names legal at read time. It can be narrower than the managed `tools/list` ceiling because state and capability remain dynamic.

`provider_native_access` and `network_access` resolve independently. Each object discloses the frozen effective value and the controlling source. Equally restrictive ties use `controller > task_policy > policy_definition > default`; adapter and local hard ceilings report `controller`. The result exposes neither provider configuration nor credentials and does not replace live authorization.

`trigger` is intentionally compact. It normalizes the dispatch opening reason to the prompt trigger vocabulary and includes the predecessor dispatch when one exists. The immutable `input` readback owns the complete exact trigger payload.

`checkpoint_to_resume_from`, when present, is one controller-selected task-relative logical path. The current implementation returns it only when an exact accepted-boundary row identifies the current dispatch as its successor and owns a checkpoint. Its support projection may still be missing or unreadable; the immutable `input` readback retains the exact dispatch-start checkpoint summary. The agent never chooses a recovery checkpoint by scanning filenames, timestamps, or provider history.

`workflow_neighborhood` is the live direct-child read from the active flow revision. `readback_refs.instructions` and `readback_refs.input` come from the current dispatch's committed refs row. `readback_refs.workflow_manifest` is a stable path to a support projection that may be missing or stale and never overrides the live neighborhood.

`continuation` and `checkpoint_to_resume_from` are optional current projections, not promises that every continuation dispatch has a non-null value. The current handler leaves `continuation` as `null`. The immutable `input` readback remains the complete dispatch-start projection when either current field is absent.

This is one coherent current database read. It returns refs and summaries rather than file bodies.

## `list_files`

### Semantic request

```yaml
ListFilesRequest:
  directory: string = "."
```

### Success response

```yaml
FileEntryRead:
  name: string
  path: string
  kind: file | directory | symlink | other
  size_bytes: integer >= 0 | null

ListFilesResponse:
  directory: string
  entries: [FileEntryRead, ...]
```

The listing is exactly one level, sorted by Unicode code point of `name`, and never partial. `size_bytes` is present only for regular files. If the configured entry ceiling would be exceeded, the call fails with `directory_limit_exceeded`.

## `read_file`

### Semantic request

```yaml
ReadFileRequest:
  path: string
  start_line: integer >= 1 = 1
  max_lines: integer >= 1 = 400
```

The schema freezes the 400-line default, not a universal hard maximum. Deployments may configure requested-line and response-byte ceilings.

### Success response

```yaml
ReadFileResponse:
  path: string
  start_line: integer >= 1
  max_lines: integer >= 1
  content: string
  lines_returned: integer >= 0
  has_more: boolean
  next_start_line: integer >= 1 | null
```

The server accepts UTF-8 text from a regular file or a contained symlink resolving to one. It preserves selected newline characters. A start beyond end of file returns empty content, zero lines, `has_more: false`, and no next line.

## `set_work_plan`

### Semantic request

```yaml
SetWorkPlanStep:
  step: string # 1..512 normalized Unicode characters
  status: pending | in_progress | completed

SetWorkPlanRequest:
  explanation: string | null = null # 1..1,024 normalized Unicode characters when present
  steps: [SetWorkPlanStep, ...] # 0..9
```

Rules:

- root, parent, and worker assignments may call the operation when it is exposed;
- `steps: []` clears the current plan;
- no more than one step may be `in_progress`;
- zero in-progress steps is legal, including when pending steps remain;
- all steps may be completed;
- ordered normalized steps replace the previous assignment-owned snapshot;
- repeated or vague filler steps fail validation; and
- explanation, when present, uses the same narrow meaningful-text validation as a step.

Normalization, placeholder recognition, and exact limits are owned by the work-plan and checkpoint contract. The schema exposes the limits as `minLength` and `maxLength`; the ordered steps expose `maxItems: 9`.

### Success response

```yaml
SetWorkPlanResponse:
  changed: boolean
  plan: WorkPlanRead | null
```

Clearing an existing plan returns `changed: true` and `plan: null`. Clearing an absent plan or submitting an identical normalized snapshot returns `changed: false` without a new revision or plan event. Every admitted call still refreshes Node activity once.

## Other catalog operations

The projection rule applies unchanged to checkpoint, boundary, external-wait, definition, child-assignment, and release operations. Their retained semantic top-level fields are fixed here so transport migration cannot invent a generic wrapper:

| Operation | Semantic top-level fields |
| --- | --- |
| `record_checkpoint` | `checkpoint` |
| `return_boundary` | `boundary` |
| `open_human_request` | `request` |
| `start_command_run` | `request` |
| `search_definitions` | its current strict search fields |
| `get_definition` | its current strict kind/key fields |
| `assign_child` | `expected_structural_revision_id`, `payload` |
| `add_child` | `expected_structural_revision_id`, `payload` |
| `update_child` | `expected_structural_revision_id`, `payload` |
| `remove_child` | `expected_structural_revision_id`, `payload` |
| `release_green` | `expected_structural_revision_id` |
| `release_blocked` | `expected_structural_revision_id` |

`checkpoint`, `boundary`, `request`, and `payload` are semantic fields owned by their strict Pydantic concept contracts; they are not session, callback, or transport envelopes. Managed schemas contain exactly these semantic fields. Compatibility schemas add only full `task_id` and `dispatch_id`. Both forbid additional properties at every owned model boundary. Operation-specific nested fields and success results remain owned by their concept pages and runtime contracts.

`add_child.payload.child` uses the portable node's optional strict `provider` object. `update_child.payload.patch.provider` is tri-state: omitted preserves the current authored selection, an object replaces it, and explicit `null` clears it so the configured default will be resolved for later dispatches. This field never accepts machine-local route details.

For example, managed `open_human_request` contains only the typed request fields, while compatibility `open_human_request` contains `task_id`, `dispatch_id`, and those same request fields. Neither transport projection may reinterpret the human-request transaction or timeout policy.

## Path normalization and containment

`list_files` and `read_file` share this behavior:

1. accept `/` as the logical separator;
2. reject empty paths except the listing default `.`;
3. reject NUL bytes, POSIX absolute paths, Windows drive paths, UNC paths, backslash-rooted paths, and every `..` segment;
4. normalize removable `.` segments;
5. accept only `workspace`, `outputs`, `tmp`, or `_runtime` as the first segment;
6. map the selected root through persisted task-root or workspace-binding truth; and
7. resolve symlinks and require the result to remain inside that selected physical root.

The logical root listing `.` returns the four logical roots and never their physical parents. A contained symlink is listed as a symlink; each later read repeats containment validation.

## Failure codes

Common codes include:

| Code | Meaning | Retryable |
| --- | --- | --- |
| `invalid_request_shape` | strict schema or operation invariant failed | no |
| `authentication_failed` | managed binding credential was absent or invalid | no |
| `scope_mismatch` | compatibility task and dispatch selectors do not identify one dispatch | no |
| `stale_dispatch` | dispatch is no longer exact current authority | no |
| `illegal_caller` | current role ceiling does not expose the operation | no |
| `capability_rejected` | current controller capability denies the operation | no |
| `illegal_state` | operation is not legal in the current source state | depends on operation |
| `missing_resource` | exact controller row or logical path is absent | no |
| `conflict` | another legal transition won the conditional write | no |

File operations additionally use:

| Code | Meaning | Retryable |
| --- | --- | --- |
| `invalid_task_path` | malformed, absolute, NUL-containing, or traversing logical path | no |
| `invalid_task_root` | logical root or persisted root mapping is unavailable | no |
| `path_escape` | resolved target leaves the selected physical root | no |
| `not_a_directory` | listing target is not a directory | no |
| `not_a_file` | read target is not a supported regular file | no |
| `binary_file` | target is not supported UTF-8 text | no |
| `file_read_limit_exceeded` | configured read ceiling would be exceeded | no |
| `directory_limit_exceeded` | configured listing ceiling would be exceeded | no |

Recognition and currentness fail before path-existence details are returned. `field_path` identifies the exact semantic field when safe and applicable.

## Admission and activity matrix

| Outcome | Admitted | Refreshes Node activity | Domain mutation |
| --- | --- | --- | --- |
| successful read | yes | once | none |
| changed semantic write | yes | once | exact owned mutation |
| accepted no-op | yes | once | none |
| normalized domain failure after admission | yes | once | none |
| malformed strict schema | no | no | none |
| failed binding authentication | no | no | none |
| wrong/stale task or dispatch | no | no | none |
| role, exposure, or capability denial | no | no | none |

Provider events, MCP ping/progress notifications, and transport traffic create no invocation and no activity.

## Transaction rules

- admission transaction A refreshes the exact current dispatch activity revision once and commits;
- the requested operation opens a fresh session and owns transaction B for its read or short conditional mutation;
- a changed plan snapshot and its bounded plan event commit together;
- boundary and external-wait sources close D1 in their own synchronous operation transaction;
- post-commit runtime signals are explicit and never hidden in session commit hooks;
- request/response bodies, file content, provider output, and binding credentials are not copied into invocation audit; and
- pre-admission failure creates no admitted invocation audit row.

## Related contracts

- [ADR-0010: dispatch-scoped managed Node MCP authority](../../../adr/ADR-0010-dispatch-scoped-managed-node-mcp-authority.md)
- [Node and Operator MCP surface](node-and-operator-mcp-surface-contract.md)
- [Managed Node MCP binding](../architecture/managed-node-mcp-binding.md)
- [Task root and file access](../architecture/task-root-and-file-access.md)
- [Work plan and checkpoint](../architecture/work-plan-and-checkpoint-contract.md)
- [Capability, security, and audit](capability-security-and-audit.md)
- [Human request and approval](human-request-and-approval-contract.md)
- [Command run and external wait](../architecture/command-run-and-external-wait.md)
