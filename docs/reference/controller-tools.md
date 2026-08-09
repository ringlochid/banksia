# Controller tools

Banksia has two distinct typed operation catalogs:

- **Task-member operations** act inside one exact current provider Dispatch and advance that Member's work.
- **Operator operations** act on semantic Workflow and Task product services from a separate control-plane agent.

They are not interchangeable. Operator is not a Workflow Member, and the Task-member catalog grants no Operator or support authority.

## Task-member scope and currentness

Every Task-member call is authorized against the current controller state for one Task and one Dispatch. Managed Codex and Claude bindings carry that scope implicitly. The model does not submit a Task ID, Dispatch ID, capability token, or parent selector in the operation body.

`get_current_context.available_actions` is the exact current action ceiling. Operations are exposed only when runtime legality permits:

- direct-team operations require a current direct team;
- Human Request and Command Run also require the current Member's effective authored grant; and
- controller/deployment policy may narrow, but never widen, those grants.

## Nine Task-member operations

| Operation | Main input | Commit and continuation behavior |
| --- | --- | --- |
| `get_current_context` | Empty object | Reads one coherent controller snapshot and does not mutate. |
| `set_work_plan` | Optional explanation and up to nine distinct `{step, status}` values; an empty step list clears | Replaces or clears the current Assignment's advisory plan; the Dispatch stays current. |
| `checkpoint` | Required `summary`; optional `details`, `files`, and `outcome` | Omitted outcome records progress. `green`, `blocked`, or `retry` closes the Dispatch; response `must_stop` tells the provider to stop. |
| `delegate` | One to eight unique direct-child `{child_id, prompt, files}` Assignments | Atomically creates one ordered Wave and parent wait. Success always closes the Dispatch; stop and await the collect-all continuation. |
| `add_child` | One new direct child with optional recursive subtree | Creates a new current team revision. Success closes the Dispatch; the controller opens a fresh same-Attempt continuation after manifest projection. |
| `update_child` | Existing descendant ID plus a nonempty typed patch | Updates the selected descendant and optional listed descendants without changing existing IDs or order. Success transfers to a fresh continuation. |
| `remove_child` | Existing descendant ID | Removes that descendant subtree from future team revisions without erasing history. Success transfers to a fresh continuation. |
| `open_human_request` | One granted kind, summary, one to three typed items, optional files and timeout | Commits the typed wait and closes the Dispatch. A later continuation carries the exact resolution. |
| `start_command_run` | `argv` or shell command, summary, optional relative cwd and timeout | Commits the managed command wait and output path before launch. A later continuation carries the exact terminal result. |

### `get_current_context`

The response contains:

- Task and current Dispatch context;
- the current Member and immutable Assignment;
- the exact Continuation source, when present;
- current direct-team readback;
- the current advisory Work Plan;
- currently available actions; and
- workspace, Task directory, manifest, optional Workflow note, notes, artifacts, and Command Run paths.

This typed readback is the recovery surface. It does not rely on hidden conversation history or projected Assignment files.

### `set_work_plan`

Step statuses are `pending`, `in_progress`, and `completed`, with at most one step in progress. A Work Plan remains advisory: it does not schedule work, satisfy participation, settle a Wave, or prove completion.

### `checkpoint`

The exact outcomes are:

- omitted: progress only; the Dispatch stays current;
- `green`: current execution and Assignment complete;
- `blocked`: current execution and Assignment end blocked; and
- `retry`: current Attempt ends and the exact Assignment receives a fresh Attempt when budget remains.

`green` and `blocked` may settle a Wave member or select the root Result. `retry` does neither. Review-driven repair belongs in a fresh Assignment, not `retry`.

A Manager's `green` outcome is legal only after every current direct child configuration has an accepted green return on its current branch basis. A blocked child settles its Wave position but does not satisfy participation; retry settles neither. A Manager that intends to take over substantive execution must first remove every direct child and continue under fresh Contributor context.

### `delegate`

Each prompt must be complete and nonblank. Targets must be unique, current, available direct children. The runtime configuration may narrow the schema ceiling of eight and the parent Assignment also has a cumulative child-Assignment budget.

The parent receives every terminal `green` or `blocked` child Checkpoint in request order after the local Wave joins. There is no separate child-result or wait-for-Wave operation.

### Replan operations

The caller is implicit and may change only its own subtree:

- add allocates controller Member IDs for the new direct child and descendants;
- update preserves existing IDs, parentage, and sibling order, while omission preserves unlisted descendants; and
- remove is the only deletion signal.

Accepted structural changes preserve earlier team and execution history. Reparenting, reordering, arbitrary work fields, and mutation of busy affected subtrees are rejected.

### Human Request

The four request kinds are `input`, `direction`, `approval`, and `review`. Each item uses either:

- a bounded Draft 2020-12 JSON response schema; or
- two or three stable-ID options, optionally allowing an Other answer or skip.

Labels are not option identity. Opening a request is a wait, not completion. After success the provider must stop.

### Command Run

The command is either:

```json
{"kind": "argv", "argv": ["make", "test-backend-unit"]}
```

or:

```json
{"kind": "shell", "command": "make test-backend-unit"}
```

`cwd`, when supplied, is relative to the Task workspace. Timeout is between 1 and 86,400 seconds. Full observed output goes to the Task's `command-runs/c_<id>/output.log`; product reads are bounded. Banksia does not capture unrelated provider-native shell activity.

## Seventeen Operator operations

Operator operations use closed JSON inputs and the same product services as the Console and HTTP API.

### Workflow operations

| Operation | Exact purpose and currentness |
| --- | --- |
| `workflow_search` | Search ID/description with optional `query`, opaque `cursor`, and `limit` 1–100. Continue only with the returned cursor. |
| `workflow_get` | Read compact catalog/history truth, one exact published revision and optional Member, or one exact draft ETag and optional Member. |
| `workflow_authoring_options` | Read accepted fields, providers, effort values, sandbox pairs, capabilities, and configured defaults. |
| `workflow_draft_create` | Import one complete structured Workflow. Replacing an existing active draft requires its current ETag. |
| `workflow_draft_edit` | Apply one typed edit using the exact draft ID and ETag; controller-issued Member IDs are returned. |
| `workflow_draft_validate` | Validate the current draft and return current reference plus issues; it does not publish. |
| `workflow_draft_undo` | Consume one single-use Undo receipt against the exact current ETag. |
| `workflow_draft_discard` | Remove only the mutable draft using its current ETag; publications remain. |
| `workflow_draft_publish` | Publish the exact current draft using its ETag and remove the draft. |

`workflow_get` catalog history uses `revision_cursor` and `revision_limit` 1–100. Published selection uses an exact positive `revision_no`. Draft selection is valid only when the Workflow ID, draft ID, and ETag still agree.

### Task and attention operations

| Operation | Exact purpose and currentness |
| --- | --- |
| `task_search` | Search Task ID, Workflow, prompt, or semantic status using an opaque cursor and `limit` 1–100. |
| `task_get` | Read an overview or exactly one Member, Result, Activity item, Human Request, or Human Request file set. |
| `task_start` | Start one published Workflow with exact prompt, optional absolute workspace, and loose file references. |
| `task_control` | Apply the current pause, resume, or cancel action using the opaque `action_id` returned by `task_get`. |
| `human_request_respond` | Answer or cancel one open request using its current `action_id` and exact response shape. |
| `command_run_get` | Read current semantic state, outcome, output link, and cancellation action. |
| `command_run_output_read` | Read one sanitized output page with optional opaque cursor and byte limit 1–65,536. |
| `command_run_cancel` | Request cancellation using the current opaque `action_id` returned by `command_run_get`. |

Opaque action IDs are currentness capabilities, not predictable commands. Operator must reread product truth after a conflict instead of guessing or reusing a stale action.

## Transport and authority limits

Managed Codex and Claude Dispatches receive a short-lived scoped MCP connection at `/_internal/node/mcp`. Banksia does not persist that endpoint in provider configuration.

These endpoints are transport for Banksia-owned operations. Workflow definitions cannot add arbitrary external MCP servers, resources, prompts, elicitation, Skills, plugins, or tools.

Neither Banksia catalog contains generic file listing/reading/writing, note writing, managed Artifact operations, support traces, database operations, or host shell/network operations. This catalog boundary does not remove a managed Task Member's independent provider-native filesystem, search, editor, shell, or network access under the Dispatch's effective sandbox. Operator sees only semantic product readbacks and their owning file references; it receives no generic host authority.
