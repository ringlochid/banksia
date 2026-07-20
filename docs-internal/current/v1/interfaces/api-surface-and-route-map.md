# Current API surface and route map

Status: Current

Last verified: 2026-07-19

AutoClaw ships one loopback FastAPI application with HTTP, same-origin console, operator MCP, and Node MCP surfaces.

## Local admission

Network requests must come directly from loopback and use one exact configured loopback Host authority. Unsafe browser requests and preflight requests must use an exact allowed Origin. CORS does not allow credentials.

There is no global API key and no provider callback route. The packaged console receives only `apiBaseUrl` from `GET /console/config`; the response is `no-store`.

## Health and definitions

- `GET /healthz`
- `GET /readyz`
- `GET /definitions/roles`
- `GET /definitions/policies`
- `GET /definitions/workflows`
- `GET /definitions/{kind}/{key}`
- `GET /definitions/{kind}/{key}/versions`
- `POST /definitions`
- `POST /tasks/start`

`/readyz` checks database connectivity. Definition list and history routes support their typed query contracts. Uploading a definition creates an immutable revision or returns the existing identical revision.

## Authoring

- `POST /authoring/task-compose/preview`
- `GET /authoring/definition-drafts`
- `POST /authoring/definition-drafts`
- `GET /authoring/definitions/{kind}/{key}/draft`
- `PUT /authoring/definitions/{kind}/{key}/draft`
- `DELETE /authoring/definitions/{kind}/{key}/draft`
- `POST /authoring/definitions/{kind}/{key}/draft/replace-current`
- `POST /authoring/definitions/{kind}/{key}/draft/validate`
- `POST /authoring/definitions/{kind}/{key}/draft/publish`

Drafts are controller-managed authoring state. Preview validates a task compose request without reserving or starting a task.

## Runtime and control

- `GET /runtime/tasks`
- `GET /control/tasks/{task_id}`
- `POST /control/tasks/{task_id}/pause`
- `POST /control/tasks/{task_id}/continue`
- `POST /control/tasks/{task_id}/cancel`
- `GET /control/tasks/{task_id}/snapshot`
- `GET /control/tasks/{task_id}/trace`
- `GET /control/tasks/{task_id}/human-requests`
- `POST /control/tasks/{task_id}/human-requests/{request_id}/resolve`
- `GET /control/tasks/{task_id}/command-runs`
- `GET /control/tasks/{task_id}/command-runs/{run_id}`
- `GET /control/tasks/{task_id}/command-runs/{run_id}/log`
- `POST /control/tasks/{task_id}/command-runs/{run_id}/cancel`
- `GET /control/tasks/{task_id}/events`
- `GET /control/tasks/{task_id}/events/stream`

Pause, continue, and cancel use expected flow and control revisions. The event stream is server-sent events and accepts either a cursor or `Last-Event-ID`.

## Packaged console

The same-origin console serves:

- `GET /console/config`
- `GET /`
- `GET /tasks` and task subpaths
- `GET /definitions` and definition subpaths
- `GET /task-start`
- packaged assets

These shell routes are not part of generated OpenAPI.

## Operator MCP

The operator server is mounted at `/operator/mcp`. It exposes definition search, definition reads and uploads, task start and list, task readbacks and events, human-request resolution, command-run inspection and cancellation, and pause, continue, and cancel controls.

The exact tool names are `search_definitions`, `get_definition`, `list_definition_versions`, `upload_definition`, `start_task`, `list_runtime_tasks`, `get_runtime_task`, `get_operator_snapshot`, `get_operator_trace`, `get_task_events`, `get_human_requests`, `resolve_human_request`, `get_command_runs`, `get_command_run`, `get_command_run_log`, `cancel_command_run`, `pause_task`, `continue_task`, and `cancel_task`.

## Node MCP

Both Node MCP surfaces use the same operation catalog and controller checks:

- managed dispatches use `/_internal/node/mcp`; a short-lived bearer binding supplies task, dispatch, provider-start revision, and the maximum exposed tool set
- compatibility providers use `/node/mcp`; every call supplies the full `task_id` and `dispatch_id`

The executor always rereads current dispatch authority, state legality, role, and capabilities. The compatibility identifiers do not bypass those checks.

All node kinds may receive current context, contained file reads, work plans, checkpoints, boundary return, and policy-enabled human-request or command-run operations. Parent and root nodes may also receive definition search, definition read, child assignment and structural edits, and green release. Only the root may receive blocked release.

The exact operation names are `get_current_context`, `list_files`, `read_file`, `set_work_plan`, `record_checkpoint`, `return_boundary`, `open_human_request`, `start_command_run`, `search_definitions`, `get_definition`, `assign_child`, `add_child`, `update_child`, `remove_child`, `release_green`, and `release_blocked`.

`get_current_context` currently returns the exact dispatch-request readback refs, the support-only workflow-manifest ref, and the live direct-child neighborhood from controller rows. Its typed trigger normalizes the bounded dispatch reason and predecessor source. When the current dispatch is the exact successor of an accepted boundary with a checkpoint, `checkpoint_to_resume_from` returns that controller-selected task-relative path. `continuation` remains reserved and `null`; the richer immutable dispatch input remains available through its committed `input` readback ref.

## Evidence

- `apps/api/src/autoclaw/interfaces/http/`
- `apps/api/src/autoclaw/interfaces/web_console/`
- `apps/api/src/autoclaw/interfaces/mcp/operator/`
- `apps/api/src/autoclaw/interfaces/mcp/node/`
- `apps/api/src/autoclaw/runtime/node_operations/catalog.py`
- `apps/api/src/autoclaw/main.py`
- `apps/api/tests/integration/public_surfaces/`
- `apps/api/tests/integration/mcp/`
