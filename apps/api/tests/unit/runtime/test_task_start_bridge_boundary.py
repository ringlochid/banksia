from __future__ import annotations

from banksia.interfaces.http.router import api_router
from banksia.runtime.contracts import TaskStartRequest
from banksia.runtime.task_start import TASK_COMPOSE_START_BRIDGE_DELETE_AFTER
from fastapi import FastAPI
from pydantic import ValidationError


def test_task_compose_start_bridge_is_explicitly_bounded_to_wp03() -> None:
    assert TASK_COMPOSE_START_BRIDGE_DELETE_AFTER == "WP-03"


def test_task_start_bridge_accepts_only_the_existing_workflow_launch_body() -> None:
    schema = TaskStartRequest.model_json_schema()

    assert tuple(schema["properties"]) == ("task", "workflow", "roots")
    assert set(schema["required"]) == {"task", "workflow"}
    assert "preview" not in str(schema).casefold()
    assert "role" not in str(schema).casefold()
    assert "policy" not in str(schema).casefold()

    try:
        TaskStartRequest.model_validate(
            {
                "task": {
                    "key": "bounded-bridge",
                    "title": "Bounded bridge",
                    "summary": "Reject deleted generic Definition authority.",
                },
                "workflow": {"key": "reviewed-delivery"},
                "role": "deleted",
            }
        )
    except ValidationError:
        pass
    else:  # pragma: no cover - gap guard
        raise AssertionError("Task start accepted a deleted Role field")


def test_task_start_http_contract_exists_without_preview_or_generic_definition_routes() -> None:
    app = FastAPI()
    app.include_router(api_router)
    openapi = app.openapi()

    assert "/tasks/start" in openapi["paths"]
    assert "TaskStartRequest" in openapi["components"]["schemas"]
    assert "TaskStartResponse" in openapi["components"]["schemas"]
    serialized = str(openapi).casefold()
    assert "/authoring/task-compose/preview" not in serialized
    assert "/definitions" not in serialized
    assert "taskcomposepreview" not in serialized
