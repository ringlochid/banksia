# Controller tools

Banksia has two separate typed operation catalogs. Task Members use runtime operations inside one exact Dispatch. The Operator uses product operations over the controller.

## Task-member operations

The complete logical catalog has nine operations:

| Operation | Purpose |
| --- | --- |
| `get_current_context` | Read the complete current Assignment, continuation, team, Work Plan, legal actions, capabilities, and Task paths. |
| `set_work_plan` | Set, update, or clear a small advisory plan. |
| `checkpoint` | Record progress or finish with `green`, `blocked`, or `retry`. |
| `delegate` | Atomically assign one Wave of complete prompts to direct children. |
| `add_child` | Add one direct child, optionally with a nested subtree. |
| `update_child` | Patch an existing descendant without changing its ID. |
| `remove_child` | Remove an existing descendant from future team revisions. |
| `open_human_request` | Open a typed external decision wait when granted. |
| `start_command_run` | Start one controller-managed command wait when granted. |

Operations are exposed only when current runtime legality permits them. Human Request and Command Run additionally require the Member's effective authored grant.

`delegate`, every accepted replan, `open_human_request`, and `start_command_run` transfer authority and require the provider turn to stop. A terminal Checkpoint does the same. There is no finish, retry, yield, wait-for-wave, child-result, generic file, note, artifact, or definition operation.

Managed Codex and Claude Dispatches receive an ephemeral scoped connection at `/_internal/node/mcp`. Banksia does not persist it in provider configuration.

OpenClaw uses the compatibility projection at `/node/mcp`. It exposes the same semantic operations but requires full `task_id` and `dispatch_id` selectors on every call and rereads current controller authority. This endpoint is provider transport compatibility, not an authorable external MCP extension.

## Operator operations

The complete Operator product catalog has seventeen operations:

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

These operations call the same product services as the Console and HTTP routes. The Operator does not receive Task-member operations or arbitrary host authority. There is no `artifact_get` or generic `file_get`; Task reads include relevant loose file references in their owning Assignment, Checkpoint, or Human Request.

## MCP scope

Banksia currently uses MCP as a transport for controller-owned Task-member operations. It does not make arbitrary external MCP servers, resources, prompts, elicitation, Skills, or Plugins part of Workflow definitions. Those extension systems are deferred.
