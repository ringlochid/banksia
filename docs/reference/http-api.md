# HTTP API reference

Oh My Subagents serves three deliberately separate HTTP surfaces:

- a loopback product API under `/api`;
- operational health reads at `/healthz` and `/readyz`; and
- an optional bearer-protected, nonbrowser support API under `/support`.

Generated OpenAPI is the exact field-level contract:

- [`openapi/product.json`](../../openapi/product.json)
- [`openapi/support.json`](../../openapi/support.json)

The product document intentionally excludes support records and internal runtime IDs. Health routes are intentionally excluded from both generated documents.

## Local admission

The shipped product binds to a configured loopback host. Requests must use an exact configured loopback `Host` authority. Browser requests must also use one of the configured absolute loopback `Origin` values.

There is no current general remote-deployment, multi-user authentication, or cross-machine browser contract. Do not expose the product API directly to another machine.

## Health

| Route | Meaning |
| --- | --- |
| `GET /healthz` | Process liveness; returns `200` while the application responds. |
| `GET /readyz` | Database connectivity; returns `200` when ready or `503` with `database_unavailable`. |

Application startup also fails closed when exact schema validation or mandatory startup recovery cannot complete.

## Product routes

### Workflow library and authoring

| Method and path | Input and semantic result |
| --- | --- |
| `GET /api/workflows` | Search with `q`, opaque `cursor`, and `limit`; returns library items and `next_cursor`. |
| `GET /api/workflows/authoring-options` | Returns accepted fields, provider choices, sandbox pairs, capabilities, and configured default. |
| `GET /api/workflows/{workflow_id}` | Reads catalog/current publication and optional draft. Optional `revision_no`, `include_revisions`, `revision_cursor`, and `revision_limit` select publication/history detail. |
| `POST /api/workflow-drafts` | Opens an existing draft or creates one from a discriminated `open`/`create` JSON body. Returns `ETag`; creation returns `201` and `Location`. |
| `GET /api/workflow-drafts/{draft_id}` | Reads the current draft and returns its `ETag`. |
| `PATCH /api/workflow-drafts/{draft_id}` | Applies one typed draft edit using required `If-Match`. |
| `DELETE /api/workflow-drafts/{draft_id}` | Discards only the draft using required `If-Match`. |
| `POST /api/workflow-drafts/{draft_id}/validate` | Returns semantic validation and the current draft; does not publish. |
| `POST /api/workflow-drafts/{draft_id}/undo` | Consumes one `receipt_id` using required `If-Match`; returns the new `ETag`. |
| `POST /api/workflow-drafts/{draft_id}/publish` | Publishes the exact current draft using required `If-Match`; returns the immutable revision. |

Draft create, patch, and undo bodies must use `Content-Type: application/json`. A missing `If-Match` returns `428`; a stale ETag returns `412` with current draft truth. Refetch and reconcile instead of retrying a guessed mutation.

### Tasks, attention, and managed actions

| Method and path | Input and semantic result |
| --- | --- |
| `GET /api/tasks` | Search by `q`, semantic `status`, opaque `cursor`, and `limit`. |
| `POST /api/tasks` | Starts one Task asynchronously; returns `202` accepted receipt. |
| `GET /api/tasks/{task_id}` | Returns semantic status, team work, current plan, attention, legal actions, exact Result, and bounded recent Activity/Human Request/Command Run history. |
| `POST /api/tasks/{task_id}/members/{member_id}/steers` | Sends one exact message through a current Member's returned `steer_action`; confirmed delivery returns current Task truth and records visible Activity. |
| `GET /api/tasks/{task_id}/activities` | Returns a cursor page of semantic Activity. |
| `GET /api/tasks/{task_id}/activities/stream` | Streams `activity` and invalidating `task_changed` server-sent events. |
| `POST /api/tasks/{task_id}/controls/{action_id}` | Applies one current pause, resume, or cancel action with a `confirmed` body when required. |
| `GET /api/tasks/{task_id}/human-requests/{request_id}` | Reads one Human Request and its current action/resolution. |
| `POST /api/tasks/{task_id}/human-requests/{request_id}/responses` | Uses the current `action_id` to answer typed items or confirm cancellation. |
| `GET /api/tasks/{task_id}/command-runs/{command_id}` | Reads semantic Action state, output link, and current cancel action. |
| `GET /api/tasks/{task_id}/command-runs/{command_id}/output` | Reads one bounded sanitized output page. |
| `POST /api/tasks/{task_id}/command-runs/{command_id}/cancel` | Uses the current `action_id` and `confirmed: true` to request cancellation. |

Task detail is a semantic product readback. It does not expose Assignments, Attempts, provider-turn IDs, Waves, bindings, watchdogs, or raw events as an alternate control protocol.

### Operator conversations

| Method and path | Input and semantic result |
| --- | --- |
| `GET /api/operator/status` | Reads Operator availability and setup action. |
| `GET /api/operator/conversations` | Lists conversations with opaque `cursor` and `limit`. |
| `POST /api/operator/conversations` | Creates one conversation from an empty JSON object. |
| `GET /api/operator/conversations/{conversation_id}` | Reads one bounded entry page using optional `cursor` and `limit`. |
| `POST /api/operator/conversations/{conversation_id}/messages` | Submits one nonblank `text` message. |
| `POST /api/operator/conversations/{conversation_id}/question-sets/{question_set_id}/answers` | Submits one to three option, custom, or skip answers for the current question set. |

Every Operator POST requires an `Idempotency-Key` header from 1 to 200 characters. Reusing the same key for the same accepted request converges; reusing it for different content conflicts. A question set is a two-turn interaction: read the typed questions, submit one explicit `Continue` answer request, then refetch conversation truth.

## Task start

`POST /api/tasks` accepts the closed `TaskStartRequest`:

```json
{
  "workflow": "production-feature-delivery",
  "prompt": "Implement and independently review the requested change.",
  "workspace": "/absolute/path/to/project",
  "files": [
    {
      "path": "docs/accepted-scope.md",
      "description": "Accepted scope"
    }
  ]
}
```

`workflow` and nonblank `prompt` are required. `workspace` may be omitted only when `paths.workspace` is configured. `files` defaults to an empty ordered list and every path must be an existing regular workspace-relative file with no symbolic-link component.

The `202` receipt includes a receipt ID, Task ID, Workflow ID and revision, workspace, manifest path, `accepted` status, and a reminder that work starts asynchronously and may need attention. A repeated POST is a new Task request; the Task-start route has no generic idempotency-key contract.

## Currentness and legal actions

Product mutations use current controller readbacks:

- Workflow draft mutations use opaque ETags and `If-Match`.
- Task controls use the opaque `action_id` returned in the current Task view.
- Human Request response and Command Run cancellation use the opaque `action_id` returned by their current readback.
- Operator conversation POSTs use `Idempotency-Key`, and question answers also identify the current question set.

Action IDs encode current legal action, not a stable button name. After `409`, `412`, or another currentness failure, refetch and use the actions currently offered. Do not synthesize IDs or replay stale confirmations.

## Pagination

All cursors are opaque and scoped to their owning route/query. Start without a cursor, follow only the returned cursor, and restart the read after a cursor reset. Do not parse, alter, or carry a cursor between resources.

| Read | Default / maximum |
| --- | --- |
| Workflow library | `limit=50`, maximum `100` |
| Workflow revision history | `revision_limit=20`, maximum `100` |
| Task search | `limit=50`, maximum `100` |
| Task Activity page | `limit=50`, maximum `200` |
| Command Run output | `limit=65536` bytes, maximum `65536` |
| Operator conversation list | `limit=50`, maximum `100` |
| Operator conversation entries | `limit=100`, maximum `100` |
| Support Task search | `limit=50`, maximum `200` |
| Support event page | `limit=100`, maximum `500` |
| Support trace | `limit=50`, maximum `200` |

Command output pages also report `output_complete`, `is_missing`, `is_changed`, and `is_bounded`. A later file mutation can therefore be disclosed rather than hidden behind the cursor.

## Activity stream

Use the Activity page for bounded backfill and the SSE stream as a live invalidation channel. Each SSE frame has an opaque `id`. Reconnect with `Last-Event-ID`; on the product stream it is authoritative when both it and a query `cursor` are present.

With no cursor, the stream begins at the current head and emits future changes; it does not replay all history. The stream has no separate heartbeat contract. Clients should refetch Task truth after an event, reconnect, cursor reset, or uncertain connection state rather than reconstructing the Task solely from frames.

## Failure contract

Ordinary product failures use:

```json
{
  "ok": false,
  "code": "invalid_request",
  "summary": "The request contains an unsupported or invalid field.",
  "retryable": false,
  "field_path": "files.0.path",
  "suggested_next_step": "Correct the highlighted field and resend the request."
}
```

The closed product-safe codes are:

- `invalid_request`;
- `not_found`;
- `conflict`;
- `cursor_reset_required`;
- `access_denied`;
- `unavailable`; and
- `internal_error`.

Use the HTTP status, `retryable`, current controller readback, and suggested next step together. Do not turn every failure into an unconditional retry.

## Support API

The read-only support routes are:

```text
GET /support/openapi.json
GET /support/tasks
GET /support/tasks/{task_id}
GET /support/tasks/{task_id}/events
GET /support/tasks/{task_id}/events/stream
GET /support/tasks/{task_id}/trace
```

They require:

```http
Authorization: Bearer <OMS_SUPPORT_BEARER_TOKEN>
```

The configured token must contain at least 32 characters. Any browser `Origin` header is rejected.

Support Task search accepts `q`, `status`, cursor, and limit. Trace accepts `q`, cursor, limit, and `sort=occurred_at_desc|occurred_at_asc`. Event pages and streams expose raw controller audit records. For the support SSE stream, query `cursor` and `Last-Event-ID` must identify the same position when both are supplied.

Support snapshots, traces, and events are derived readbacks. They never mutate runtime state, select a successor, clear a wait, or override product truth. There is no generic HTTP file CRUD, managed Artifact API, or public raw-runtime mutation route.
