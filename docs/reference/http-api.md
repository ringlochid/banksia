# HTTP API reference

Banksia serves a local product API and a separately protected support API. Generated OpenAPI documents are the exact field-level contract:

- [`openapi/product.json`](../../openapi/product.json)
- [`openapi/support.json`](../../openapi/support.json)

## Product API

The product API is mounted under `/api` and used by the Console and Operator HTTP surfaces.

| Area | Routes |
| --- | --- |
| Workflow library | `GET /api/workflows`, `GET /api/workflows/{workflow_id}` |
| Authoring options | `GET /api/workflows/authoring-options` |
| Draft lifecycle | `POST /api/workflow-drafts`, `GET/PATCH/DELETE /api/workflow-drafts/{draft_id}` |
| Draft actions | `POST .../validate`, `POST .../undo`, `POST .../publish` |
| Tasks | `GET/POST /api/tasks`, `GET /api/tasks/{task_id}` |
| Activity | `GET .../activities`, `GET .../activities/stream` |
| Controls | `POST /api/tasks/{task_id}/controls/{action_id}` |
| Human Requests | `GET .../human-requests/{request_id}`, `POST .../responses` |
| Command Runs | `GET .../command-runs/{command_id}`, `GET .../output`, `POST .../cancel` |
| Operator | conversation list/create, detail, message, question-answer, and status routes |

The Activity stream is server-sent events. Clients should treat the event as an invalidation hint and refetch controller truth instead of reconstructing the Task solely from stream messages.

Draft mutations use opaque ETags for optimistic concurrency. A stale client must refetch and reconcile rather than retrying a mutation against guessed state.

## Task start request

`POST /api/tasks` accepts:

```json
{
  "workflow": "reviewed-code-change",
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

`workspace` may be omitted when `paths.workspace` is configured. `prompt` remains the one required authored work message; there is no Task key, title, summary, or instruction quartet.

## Local admission

The shipped product surface binds to loopback. It validates exact configured loopback `Host` authorities and allowed browser `Origin` values. It has no general remote deployment or multi-user authentication contract. Do not expose the product API directly to another machine.

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

They require `Authorization: Bearer <BANKSIA_SUPPORT_BEARER_TOKEN>`. Browser `Origin` requests are rejected. Support projections and traces help diagnose controller behavior but never become runtime authority.
