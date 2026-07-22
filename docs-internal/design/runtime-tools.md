# Built-in runtime tools target

Status: Target

Decision record: accepted 2026-07-22; revised 2026-07-23.

## Boundary

Banksia has two separate built-in agent tool catalogs:

- **Task-member tools** are controller operations used by a current Task Dispatch. Managed Codex and Claude turns receive them through a private Dispatch-scoped MCP binding. OpenClaw may use the explicit-ID compatibility projection of the same logical catalog.
- **Operator tools** act on user-facing Workflow and Task product services. They never inherit Task-member authority and are not injected into a Task Dispatch.

The deferred external-MCP decision does not remove either built-in catalog. It means a Workflow cannot add arbitrary MCP servers or tools, and Banksia has no external-MCP registry, credential, discovery, approval, replan, or UI shape in this baseline.

## Exact final Task-member catalog

The final catalog contains exactly nine logical operations:

```text
get_current_context
set_work_plan
checkpoint
delegate
add_child
update_child
remove_child
open_human_request       # capability-gated
start_command_run        # capability-gated
```

There is no separate file, note, generic file-reader, wait, finish, retry, release, continuation, child-result, or definition tool.

### Current-to-target disposition

| Current AutoClaw Node operation | Banksia disposition |
| --- | --- |
| `get_current_context` | Keep the name; replace the response with complete Assignment, optional exact Continuation, current Member/direct team, participation, Work Plan, legal actions, effective built-in grants, and `.banksia` paths. |
| `list_files` | Remove. Task members use provider-native filesystem tools in the shared workspace. |
| `read_file` | Remove for the same reason. |
| `set_work_plan` | Keep the name and the settled zero-to-nine-step replacement/clear contract; simplify model-visible readback by omitting private revisions and author IDs. |
| `record_checkpoint` | Rename and redesign as `checkpoint`. |
| `return_boundary` | Remove. `checkpoint(outcome=green|blocked|retry)` performs the terminal boundary atomically; `delegate` owns the former yield transfer. |
| `open_human_request` | Keep the name; simplify its request and preserve typed capability gating and stop-after-commit behavior. |
| `start_command_run` | Keep the name; simplify its request, use one combined log, and preserve stop-after-commit behavior. |
| `search_definitions` | Remove with Role, Policy, and generic Definition lookup. |
| `get_definition` | Remove with Role, Policy, and generic Definition lookup. |
| `assign_child` | Replace with atomic one-to-eight-member `delegate`. |
| `add_child` | Keep the name; replace the request, authority, result, and continuation semantics. |
| `update_child` | Keep the name; replace the request, authority, result, and continuation semantics. |
| `remove_child` | Keep the name; replace the request, authority, result, and continuation semantics. |
| `release_green` | Remove. Current direct-child participation and terminal Checkpoint admission own green completion. |
| `release_blocked` | Remove. A root terminal blocked Checkpoint is the exact blocked Result. |

The shipped source has no `write_note` Node operation. Any stale documentation, fixture, or compatibility alias using that name is deleted; no replacement is added.

## Exposure and legality

The managed binding exposes a stable ceiling for one exact Dispatch. Fresh controller state still decides whether a listed call is legal.

| Current Member condition | Tool ceiling |
| --- | --- |
| Every Member | `get_current_context`, `set_work_plan`, `checkpoint`, `add_child` |
| Member with current direct children | add `delegate`, `update_child`, `remove_child` |
| Effective Human Request grant contains at least one kind | add `open_human_request` |
| Effective managed Command Run grant is `allow` | add `start_command_run` |

`add_child` is deliberately available to a Contributor: adding its first child changes its next fresh context to Manager behavior. Task lead is a position, not a separate tool role, and receives no secret completion operation.

The tool ceiling is not completion authority. For example, `checkpoint` stays available for progress while the controller may reject a terminal green outcome until current direct-child participation is satisfied. A managed Human Request schema should narrow its `kind` enum to the exact granted kinds for that binding; the compatibility catalog may advertise the complete enum but must enforce the selected Dispatch's grant at call time.

An accepted structural replan closes its source Dispatch, so a change from Contributor to Manager, or the reverse, always receives a fresh binding and fresh tool ceiling on the successor.

## Shared semantic types

`FileReference` is the only generic controller value for pointing another context to a loose file in the Task workspace:

```yaml
FileReference:
  path: workspace-relative regular-file path
  description: optional short purpose
```

The controller validates containment and stores the immutable value on its Assignment, Checkpoint, or Human Request. Task start seeds the root Assignment. Continuations, Result, Activity, context, and product views expose the exact values from those owners rather than persisting copies. Banksia does not allocate a generic file ID, copy bytes, hash or version content, create a current pointer, or promise that the mutable file still has its earlier bytes. The path may identify an ordinary project file, a working file under `.banksia/t_<id>/notes/`, a reviewable loose file under `.banksia/t_<id>/artifacts/`, or a Command Run log. Agents open referenced files with native tools and report a missing or changed file honestly.

Storage may normalize these values into owner-scoped ordered rows, but no row is a standalone file resource or receives an independently addressable ID, lifecycle, content body, or lookup API.

All semantic request and success objects are strict closed JSON objects. IDs, enums, text bounds, and nested schemas belong to the tool definition rather than the system prompt.

## Operation contracts

### `get_current_context`

Request:

```yaml
{}
```

Success is one coherent fresh observation:

```yaml
task:
  id: t_7m4k2d9x
  root_path: .banksia/t_7m4k2d9x
dispatch:
  id: controller Dispatch ID
attempt:
  id: controller Attempt ID
member:
  id: current Member ID
  title: optional string
  description: optional string
  instruction: >-
    optional string
  provider: optional nonsecret effective selection
  task_lead: boolean
  behavior: manager | contributor
assignment:
  id: controller Assignment ID
  prompt: complete exact string
  files:
    - path: .banksia/t_7m4k2d9x/notes/review.md
      description: optional string
continuation: optional complete typed Continuation
direct_team:
  - member: complete current Member configuration
    participation: required | satisfied
    availability: available | busy
work_plan: optional complete current plan
capabilities:
  human_request: [input, direction]
  command_run: deny
allowed_actions: [get_current_context, set_work_plan, checkpoint, ...]
paths:
  manifest: .banksia/t_7m4k2d9x/manifest.md
  workflow_note: optional path
  notes: .banksia/t_7m4k2d9x/notes
  artifacts: .banksia/t_7m4k2d9x/artifacts
  command_runs: .banksia/t_7m4k2d9x/command-runs
observed_at: RFC-3339 UTC timestamp
```

The exact implementation uses shared typed structures with Dispatch input; it does not duplicate a second vocabulary. Initial Dispatches omit Continuation entirely. A successor includes the exact trigger source and complete result, not a compact reason plus lookup reference. The response contains no Role, Policy, criteria, consume/produce, request-file ref, managed file operation, structural revision/hash, generic file ID/version, synthetic initial trigger, or permanently null placeholder.

### `set_work_plan`

```yaml
request:
  explanation: optional normalized string
  steps: # 0..9; [] clears
    - step: normalized string
      status: pending | in_progress | completed

success:
  changed: boolean
  plan: null | {explanation?, steps}
```

At most one step is in progress. An identical normalized request is a success with `changed: false`. Private revision, authoring Dispatch, and commit metadata remain support truth, not model-visible success fields.

### `checkpoint`

```yaml
request:
  summary: required nonblank teammate-facing string
  details: optional Markdown string
  files: optional ordered FileReference list
  outcome: optional green | blocked | retry

success:
  checkpoint: {summary, details?, files, outcome?}
  recorded_at: RFC-3339 UTC timestamp
  terminal: boolean
  must_stop: boolean
```

No outcome records progress, returns `terminal: false`, and leaves the Dispatch current. Every present outcome—`green`, `blocked`, or `retry`—commits a terminal Checkpoint and internal accepted boundary together, returns `terminal: true` and `must_stop: true`, and permits no later call or outer-response prose from that Dispatch. Green/blocked close the Assignment; retry closes only the current Dispatch and Attempt, keeps the exact Assignment open, and creates a fresh Attempt when budget remains. Root green/blocked is the exact user Result; root retry is not. There is no separate finish or retry operation.

### `delegate`

```yaml
request:
  assignments: # 1..8, unique current direct-child IDs
    - child_id: Member ID
      prompt: complete nonblank Assignment prompt
      files: optional ordered FileReference list

success:
  accepted: true
  members:
    - child_id: Member ID
  must_stop: true
```

The success means every child Assignment/Attempt/first Dispatch and the parent Wave wait committed atomically; it does not mean providers started or children finished. No Wave ID, mode, schedule, dependency, output declaration, summary, details, criteria, or parent selector is model-visible. The source provider stops immediately. There is no `wait_for_wave` tool: the controller opens the one parent Continuation after the local collect-all join settles.

### Replan operations

Requests are the closed recursive contracts in [Runtime](runtime.md):

```yaml
add_child: {child: NewMember}
update_child: {id: existing descendant ID, patch: MemberPatch}
remove_child: {id: existing descendant ID}
```

No request accepts caller/parent ID, expected revision, hash, existing ID on a new Member, reparent/reorder directive, runtime work, arbitrary tool, or external-MCP field. Result families return the relevant created/updated/removed IDs plus fresh direct team, participation, derived behavior, capabilities, and legal actions. Every accepted result contains `must_stop: true`; a separate same-Attempt successor carries the complete committed result after manifest health is current.

### `open_human_request`

```yaml
request:
  request: HumanRequestOpenRequest # exact simplified contract in runtime.md

success:
  request_id: controller-issued product ID
  status: open
  must_stop: true
```

Success means the request, typed Attempt wait, and source-Dispatch close committed. It does not mean a human answered or a successor opened.

### `start_command_run`

```yaml
request:
  request: CommandRunStartRequest # exact simplified contract in runtime.md

success:
  command_id: c_q3m8y1ka
  status: pending_start
  output_path: .banksia/t_7m4k2d9x/command-runs/c_q3m8y1ka/output.log
  must_stop: true
```

Success means command intent, typed Attempt wait, and source-Dispatch close committed. Launch, output, terminal state, and successor opening remain later controller-owned effects. There is no Node command-status/log tool; the continuation carries typed terminal facts and the member reads the visible log with native filesystem tools when needed.

## Transfer boundary rule

The operation descriptor must state whether success:

- leaves the Dispatch current;
- always closes and transfers authority; or
- closes only for a terminal variant.

`delegate`, all three replan operations, `open_human_request`, and `start_command_run` always transfer. `checkpoint` transfers only when outcome is present. After a successful transfer, no further Node call or provider prose is accepted as controller work from that Dispatch.

This metadata belongs beside the operation contract and drives descriptions, prompt action teaching, provider cleanup, and tests. It does not replace the transaction's currentness checks.

## MCP projections and binding

Preserve one logical catalog with two Node projections:

- managed `/_internal/node/mcp`: semantic arguments only, direct loopback peer, Host/Origin checks, opaque bearer bound to exact Task, Dispatch, and provider-start revision, and a Dispatch-specific exposure ceiling;
- compatibility `/node/mcp`: the same semantic schemas prefixed with required full `task_id` and `dispatch_id`, complete static discovery, and fresh call-time legality. This remains the weaker user-configured OpenClaw lane.

Concurrent Attempt lanes receive independent bindings to the same application. The executor must validate Attempt-local current Dispatch authority; it must no longer consult a Flow-wide current pointer. Binding credentials, Task/Dispatch selectors, provider sessions, and controller revisions never enter managed model-visible schemas.

Rename implementation identities to `banksia_node`, `banksia-node-managed`, and `banksia-node` during the Banksia identity package. The endpoint paths may remain stable because they are descriptive rather than AutoClaw identity.

Every tool provides deterministic ordering, detailed bounded teaching, strict input and output schemas, structured content plus JSON text compatibility, and the shared structured execution failure. Set accurate `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint` values; treat them only as client hints, never authorization. Where the pinned SDK exposes MCP task support, mark every Banksia operation `forbidden`: Banksia's Dispatch, wait, Wave, Human Request, and Command Run records own resumability. Do not add MCP resources, prompts, elicitation, or protocol-task dependencies.

`tools/list` authenticates and reads fresh authority but does not refresh Node activity. Every admitted call, including reads, accepted no-ops, and normalized post-admission failures, refreshes the exact Dispatch activity revision once. Authentication, malformed schema, stale scope, exposure, and capability denial occur before activity. Every conditional mutation rereads currentness in its short commit transaction.

## Provider integration changes

The provider-start request continues to carry an ephemeral managed connection for Codex/Claude or the compatibility endpoint for OpenClaw. Update:

- provider-side enabled-tool lists to the exact current target ceiling;
- Claude names from `mcp__autoclaw_node__*` to `mcp__banksia_node__*`;
- Codex MCP server key from `autoclaw_node` to `banksia_node`;
- direct Dispatch request strings instead of `instructions.md`/`input.md` file reads; and
- Attempt-local authority and cleanup for multiple concurrent bindings.

Do not persist the binding or write it into user/provider configuration. A same-Dispatch provider-start retry receives a fresh credential and the same committed request/tool ceiling. Closing a Dispatch invalidates its old binding even when provider stop is delayed or unsupported.

## Operator runtime-tool contraction

The complete target Operator catalog is defined by [Interfaces, Console, and Operator](interfaces-console-and-operator.md) and the curated Operator proposal. It is exactly:

```text
workflow_search
workflow_get
workflow_authoring_options
workflow_draft_create
workflow_draft_edit
workflow_draft_validate
workflow_draft_undo
workflow_draft_discard
workflow_draft_publish
task_search
task_get
task_start
task_control
human_request_respond
command_run_get
command_run_output_read
command_run_cancel
```

Its runtime-facing subset is exactly:

```text
task_search
task_get
task_start
task_control
human_request_respond
command_run_get
command_run_output_read
command_run_cancel
```

`workflow_draft_undo` accepts only an opaque, controller-issued, single-use receipt bound to the exact draft and accepted ETag; neither Operator nor the browser computes an inverse mutation. `workflow_draft_discard` removes only a mutable draft. Published Workflow revisions are immutable and have no delete tool in this baseline.

Current runtime-oriented Operator tools change as follows:

| Current Operator tool | Target disposition |
| --- | --- |
| `search_definitions` | Replace with Workflow-only `workflow_search`; remove Role/Policy/generic-kind input. |
| `get_definition` | Replace with `workflow_get`, which reads the current/published Workflow, bounded revision history, and active mutable draft plus ETag when one exists. |
| `list_definition_versions` | Fold bounded immutable Workflow history into `workflow_get`. |
| `upload_definition(path)` | Delete. Use structured-JSON `workflow_draft_create`; validate and publish through separate operations. |
| `start_task(task_compose_path)` | Replace with structured `task_start(TaskStartRequest)`. |
| `list_runtime_tasks` | Replace with semantic `task_search`. |
| `get_runtime_task` | Replace with semantic `task_get`. |
| `get_operator_snapshot` | Fold useful product facts into `task_get`; delete its Flow/runtime response. |
| `get_operator_trace` | Remove from the Operator agent; support/audit API may retain technical inspection. |
| `get_task_events` | Remove from the Operator agent; `task_get` returns bounded semantic Activity and canonical current state. |
| `get_human_requests` | Fold current request/attention facts into `task_get`. |
| `resolve_human_request` | Replace with action-bound `human_request_respond`, including answer and cancel. |
| `get_command_runs` | Fold bounded summaries/attention into `task_get`. |
| `get_command_run` | Replace with semantic `command_run_get`. |
| `get_command_run_log` | Replace with bounded cursor-based `command_run_output_read`. |
| `cancel_command_run` | Replace with action-bound `command_run_cancel`. |
| `pause_task`, `continue_task`, `cancel_task` | Replace with one `task_control` over a controller-returned opaque legal-action ID. |

There is no `artifact_get` or generic `file_get`. `task_get` returns loose `FileReference` values sourced from Assignments, Checkpoints, and Human Requests, embedded in the relevant product message rather than as a standalone file catalog. The Operator receives no arbitrary host-file access or generic file CRUD/content retrieval. UI-specific file opening, if retained, is an authorized product route rather than an Operator agent tool.

The complete Operator catalog has seventeen operations after this removal: three Workflow reads, six draft actions, four Task actions, one Human Request action, and three Command Run actions.

## Explicitly absent tools

Do not add:

- `capture_artifact`, `artifact_get`, `file_get`, legacy Artifact list/version/publish/promote, or generic file/reference CRUD;
- `list_files`, `read_file`, `write_file`, `write_note`, directory search, or remote-resource access;
- `wait_for_wave`, `wait_for_attempt`, `get_child_result`, or mutable completion counters;
- `return_boundary`, `yield`, `finish`, `retry`, `release_green`, or `release_blocked`;
- `continue`, `resume`, or provider-output completion tools for Task members;
- Role, Policy, Skill, generic Definition, tool-registry, or external-MCP lookup/mutation;
- provider configuration or capability mutation outside `add_child` and `update_child` Member configuration; or
- one generic `execute_action(any)` escape hatch.

## Implementation ownership

| Package | Tool-surface responsibility |
| --- | --- |
| WP-01 | Rename MCP server/config identities from AutoClaw to Banksia without changing operation semantics. |
| WP-02 | Delete Role/Policy/generic Definition Node lookup and replace Operator definition tools with Workflow product services. |
| WP-03 | Land owning-message `FileReference` values and `checkpoint`; absorb progress plus the green/blocked/retry terminal boundary variants and release actions; delete the complete legacy Artifact resource/publication/capture/version/current-pointer domain. Keep only the temporary single-child `assign_child` plus yield transfer until WP-08. |
| WP-04 | Prove provider-native workspace access, create the physical notes/artifacts/command-runs tree, bind the final physical path validator, remove Node file/note tools, separate Command logs, and recheck that WP-03's Artifact-domain deletion remains complete. |
| WP-05 | Redesign `get_current_context`, action teaching, direct Dispatch requests, common schemas/results, Human Request/Command Run requests, and provider allowlists. |
| WP-06 | Replace all three replan schemas/transactions/results, remove model-visible revisions, and enforce stop/fresh-successor behavior. |
| WP-07 | Move Node authority, activity, waits, binding currentness, and external-wait continuation from Flow to Attempt lanes. |
| WP-08 | Add `delegate`, Wave settlement/join/recovery, remove temporary `assign_child` and yield, and freeze the exact nine-operation Node catalog. |
| WP-09 | Freeze semantic Task/product services and remove Flow/runtime payloads used by Operator tools. |
| WP-11 | Implement the exact seventeen-operation Operator catalog and scoped SDK/MCP projections; do not add `artifact_get` or `file_get`. |
| WP-12 | Rewrite final Banksia docs and delete every old tool/schema/name/test/readback. |
| WP-13 | Independently audit exact inventories, schemas, exposure, races, provider injection, negative searches, and UI/Operator parity. |

The temporary WP-03-to-WP-07 catalog is an implementation bridge, not public target canon: `assign_child` and a yield-only transfer remain paired only until one-member Wave parity is live. They never appear in target prompts, examples, or final discovery. WP-08 atomically activates `delegate` plus controller-owned Attempt waits and removes both old operations. No package may remove one while leaving the other unusable or advertise `delegate` before it executes.

## Required proof

- exact final Node inventory equals the nine names above, in deterministic order, with no stale alias;
- exact final Operator inventory equals its seventeen approved names and has no `artifact_get`;
- managed and compatibility Node projections share semantic schemas/results, differing only by hidden versus explicit Task/Dispatch scope;
- Contributor, Manager, capability-granted, denied, stale, and post-replan discovery/call matrices are correct;
- every transfer operation commits authority loss before success returns and duplicate/stale calls cannot mutate a successor;
- nested parallel Attempt bindings cannot cross Task, Attempt, Dispatch, tool ceiling, or provider-start generation;
- provider allowlists and Claude/Codex prefixed names match the catalog exactly;
- no MCP protocol Task, elicitation, resource, prompt, or dynamic external-MCP behavior becomes runtime authority;
- native filesystem conformance passes before file-tool removal;
- loose `FileReference` values preserve exact path/description order across project files, notes, artifacts, and command logs but create no generic file ID, body copy, digest, version, current pointer, or Operator content tool; the physical `artifacts/` convention never becomes an Artifact resource; and
- broad searches find no Role/Policy lookup, release/yield, Flow current pointer, request-file ref, managed file tool, old server identity, or raw runtime Operator surface in the final package.

## Protocol basis

The target uses the stable MCP tool primitives: JSON Schema inputs, optional output schemas, structured results with text compatibility, annotations as untrusted hints, and Streamable HTTP with Origin validation, local binding, and authentication. These protocol features describe transport and teaching only; Banksia controller currentness remains the authority.
