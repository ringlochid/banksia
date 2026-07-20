# API surface and route map

AutoClaw serves one FastAPI application on loopback. It includes the HTTP API, the packaged console, operator MCP, and two Node MCP projections.

## Local admission

Every network request must come directly from loopback and use an exact loopback `Host` authority for the configured API port. Unsafe browser requests and CORS preflights must also use an exact allowed `Origin`. Requests without an `Origin`, such as local CLI and `curl` calls, remain valid when the peer and Host checks pass.

There is no global API key. CORS does not allow credentials. Provider callbacks are not part of the API.

## Health and launch

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/healthz` | Process health. |
| `GET` | `/readyz` | Database connectivity and readiness. |
| `POST` | `/tasks/start` | Compile a task compose and commit task bootstrap truth. |

Task start returns after the bootstrap transaction commits. Root dispatch opening and provider start happen independently after return.

## Definitions

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/definitions/roles` | List current roles. |
| `GET` | `/definitions/policies` | List current policies. |
| `GET` | `/definitions/workflows` | List current workflows. |
| `GET` | `/definitions/{kind}/{key}` | Read one current definition. |
| `GET` | `/definitions/{kind}/{key}/versions` | List immutable revisions. |
| `POST` | `/definitions` | Publish a definition revision. |

An identical upload reuses the existing revision. A changed upload needs the explicit new-revision policy.

## Authoring

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/authoring/task-compose/preview` | Validate and compile a preview without starting a task. |
| `GET`, `POST` | `/authoring/definition-drafts` | List or create drafts. |
| `GET`, `PUT`, `DELETE` | `/authoring/definitions/{kind}/{key}/draft` | Read, save, or delete one draft. |
| `POST` | `/authoring/definitions/{kind}/{key}/draft/replace-current` | Replace a draft from current published truth. |
| `POST` | `/authoring/definitions/{kind}/{key}/draft/validate` | Validate a draft. |
| `POST` | `/authoring/definitions/{kind}/{key}/draft/publish` | Publish a valid draft. |

Drafts are editable authoring state. Published definitions are immutable controller records.

## Runtime and control

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/runtime/tasks` | List runtime tasks. |
| `GET` | `/control/tasks/{task_id}` | Read current flow state and control revisions. |
| `POST` | `/control/tasks/{task_id}/pause` | Pause one current flow. |
| `POST` | `/control/tasks/{task_id}/continue` | Resume one paused flow. |
| `POST` | `/control/tasks/{task_id}/cancel` | Cancel one current flow. |
| `GET` | `/control/tasks/{task_id}/snapshot` | Read the current operator snapshot. |
| `GET` | `/control/tasks/{task_id}/trace` | Read a bounded operator trace. |
| `GET` | `/control/tasks/{task_id}/human-requests` | List human requests. |
| `POST` | `/control/tasks/{task_id}/human-requests/{request_id}/resolve` | Resolve one current request. |
| `GET` | `/control/tasks/{task_id}/command-runs` | List command runs. |
| `GET` | `/control/tasks/{task_id}/command-runs/{run_id}` | Read one command run. |
| `GET` | `/control/tasks/{task_id}/command-runs/{run_id}/log` | Read its bounded log. |
| `POST` | `/control/tasks/{task_id}/command-runs/{run_id}/cancel` | Request cancellation. |
| `GET` | `/control/tasks/{task_id}/events` | Read chronological task events. |
| `GET` | `/control/tasks/{task_id}/events/stream` | Stream task events with SSE. |

Pause, continue, and cancel require the fresh active-flow and control revisions returned by a current read. Human-request resolution and command-run cancellation use their dedicated routes.

## Event cursors

Event cursors are exclusive and task-bound: a page or stream starts after the referenced event. A list request may use `through_event_id` as a fixed upper bound for a stable backfill. The SSE route accepts either the `cursor` query field or `Last-Event-ID`, but not conflicting values. Without either value, the stream starts after the current head and emits only later events. Events are ordered by per-task sequence and may be deduplicated by `event_id`.

If the server returns `410 cursor_reset_required`, reread current task state, discard the old chronology cursor, and start a new backfill. Events explain changes; they do not replace current state.

## Console and MCP mounts

The packaged console serves its shell, assets, and `GET /console/config` from the same application. The config response contains only `apiBaseUrl` and uses `Cache-Control: no-store`. Console shell routes are not in OpenAPI.

MCP mounts are also outside OpenAPI:

- `/operator/mcp` exposes trusted local operator reads and controls.
- `/_internal/node/mcp` exposes a private dispatch-scoped managed projection for Codex and Claude.
- `/node/mcp` exposes the static compatibility projection for user-configured OpenClaw. Every tool call includes full `task_id` and `dispatch_id` selectors.

See [API trust lanes](api-trust-lanes.md) for the authority split and [Operator reference](../operator/README.md) for tool names.
