from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from banksia.main import create_app
from banksia.operator import (
    OperatorConversationService,
    OperatorProviderAskUserResult,
    OperatorProviderMessageResult,
    OperatorTurnOutcome,
    OperatorTurnRunner,
    UnavailableOperatorTurnRunner,
)
from banksia.operator.contracts import (
    OperatorAssistantQuestionSetEntry,
    OperatorConversationView,
)
from banksia.persistence import OperatorConversationEntryModel
from banksia.persistence.session import RuntimeAsyncSession
from banksia.runtime.clock import utc_now
from tests.helpers.operator import (
    RecordingTurnRunner,
    create_operator_engine,
)


@asynccontextmanager
async def _operator_client(
    tmp_path: Path,
    *,
    runner: OperatorTurnRunner,
) -> AsyncIterator[
    tuple[
        httpx.AsyncClient,
        async_sessionmaker[RuntimeAsyncSession],
    ]
]:
    engine = await create_operator_engine(tmp_path)
    session_factory = async_sessionmaker(
        engine,
        class_=RuntimeAsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    app = create_app(should_enable_mcp_mounts=False)
    app.state.operator_conversation_service = OperatorConversationService(
        session_factory=session_factory,
        runner=runner,
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
            base_url="http://127.0.0.1:18125",
        ) as client:
            yield client, session_factory
    finally:
        await engine.dispose()


async def test_product_openapi_contains_exactly_six_operator_routes() -> None:
    app = create_app(should_enable_mcp_mounts=False)

    operator_routes = {path for path in app.openapi()["paths"] if path.startswith("/api/operator")}

    assert operator_routes == {
        "/api/operator/status",
        "/api/operator/conversations",
        "/api/operator/conversations/{conversation_id}",
        "/api/operator/conversations/{conversation_id}/messages",
        ("/api/operator/conversations/{conversation_id}/question-sets/{question_set_id}/answers"),
    }
    methods = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/operator")
        for method in operations
        if method != "parameters"
    }
    assert methods == {
        ("GET", "/api/operator/status"),
        ("GET", "/api/operator/conversations"),
        ("POST", "/api/operator/conversations"),
        ("GET", "/api/operator/conversations/{conversation_id}"),
        ("POST", "/api/operator/conversations/{conversation_id}/messages"),
        (
            "POST",
            "/api/operator/conversations/{conversation_id}/question-sets/{question_set_id}/answers",
        ),
    }
    create_responses = app.openapi()["paths"]["/api/operator/conversations"]["post"]["responses"]
    assert create_responses["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/OperationFailure"
    }
    openapi = app.openapi()
    operator_document = {
        "paths": {
            path: operations
            for path, operations in openapi["paths"].items()
            if path.startswith("/api/operator")
        },
        "schemas": {
            name: schema
            for name, schema in openapi["components"]["schemas"].items()
            if name.startswith("Operator")
        },
    }
    serialized = str(operator_document).casefold()
    for forbidden in (
        "operator/mcp",
        "operator sse",
        "operatorinvocation",
        "operatoreffect",
        "confirmation",
        "retryprovider",
    ):
        assert forbidden not in serialized


async def test_unconfigured_operator_surface_rejects_new_conversation(
    tmp_path: Path,
) -> None:
    async with _operator_client(
        tmp_path,
        runner=UnavailableOperatorTurnRunner(),
    ) as (client, _session_factory):
        status_response = await client.get("/api/operator/status")
        create_response = await client.post(
            "/api/operator/conversations",
            headers={"Idempotency-Key": "create-1"},
            json={},
        )

    assert status_response.status_code == 200
    assert status_response.json() == {
        "availability": "unconfigured",
        "configured_provider": None,
        "explanation": "Operator is not configured with a provider.",
        "setup_action": "Run `banksia operator setup`, then restart Banksia.",
    }
    assert create_response.status_code == 503


async def test_operator_create_route_is_strict_and_idempotent(
    tmp_path: Path,
) -> None:
    runner = RecordingTurnRunner(())

    async with _operator_client(tmp_path, runner=runner) as (client, _session_factory):
        status = await client.get("/api/operator/status")
        missing_key = await client.post("/api/operator/conversations", json={})
        unknown_field = await client.post(
            "/api/operator/conversations",
            headers={"Idempotency-Key": "create-unknown"},
            json={"unexpected": True},
        )
        created = await client.post(
            "/api/operator/conversations",
            headers={"Idempotency-Key": "create-1"},
            json={},
        )
        duplicate_create = await client.post(
            "/api/operator/conversations",
            headers={"Idempotency-Key": "create-1"},
            json={},
        )
        vendor_json = await client.post(
            "/api/operator/conversations",
            headers={
                "Content-Type": "application/vnd.banksia.operator+json",
                "Idempotency-Key": "create-vendor-json",
            },
            content=b"{}",
        )
        invalid_cursor = await client.get(
            "/api/operator/conversations",
            params={"cursor": "not-an-opaque-cursor"},
        )
        blank_key = await client.post(
            "/api/operator/conversations",
            headers={"Idempotency-Key": "   "},
            json={},
        )

    assert status.status_code == 200
    assert status.json()["availability"] == "available"
    assert missing_key.status_code == 400
    assert unknown_field.status_code == 400
    assert created.status_code == 201
    assert duplicate_create.status_code == 201
    assert duplicate_create.json() == created.json()
    assert vendor_json.status_code == 201
    assert invalid_cursor.status_code == 400
    assert blank_key.status_code == 400
    assert runner.requests == []


async def test_operator_message_and_answer_routes_return_committed_readback(
    tmp_path: Path,
) -> None:
    runner = RecordingTurnRunner(
        (
            OperatorTurnOutcome(
                provider_thread_id="thread-http",
                result=OperatorProviderAskUserResult.model_validate(
                    {
                        "kind": "ask_user",
                        "questions": [
                            {
                                "header": "Audience",
                                "question": "Who is this for?",
                                "options": [
                                    {
                                        "label": "Developers",
                                        "description": "Optimize for implementation.",
                                    },
                                    {
                                        "label": "Researchers",
                                        "description": "Optimize for evidence review.",
                                    },
                                ],
                            }
                        ],
                    }
                ),
            ),
            OperatorTurnOutcome(
                provider_thread_id="thread-http",
                result=OperatorProviderMessageResult(
                    kind="message",
                    text="The draft is ready.",
                ),
            ),
        )
    )

    async with _operator_client(tmp_path, runner=runner) as (client, _session_factory):
        created = await client.post(
            "/api/operator/conversations",
            headers={"Idempotency-Key": "create-1"},
            json={},
        )
        conversation_id = created.json()["id"]
        awaiting_response = await client.post(
            f"/api/operator/conversations/{conversation_id}/messages",
            headers={"Idempotency-Key": "message-1"},
            json={"text": "Create a Workflow."},
        )
        awaiting = OperatorConversationView.model_validate(awaiting_response.json())
        question_set = awaiting.entries[-1]
        assert isinstance(question_set, OperatorAssistantQuestionSetEntry)
        answer_response = await client.post(
            (
                f"/api/operator/conversations/{conversation_id}/question-sets/"
                f"{question_set.id}/answers"
            ),
            headers={"Idempotency-Key": "answer-1"},
            json={
                "answers": [
                    {
                        "question_id": question_set.questions[0].id,
                        "answer": {
                            "kind": "option",
                            "option_id": question_set.questions[0].options[0].id,
                        },
                    }
                ]
            },
        )
        readback = await client.get(f"/api/operator/conversations/{conversation_id}")
        listing = await client.get("/api/operator/conversations")

    assert created.status_code == 201
    assert awaiting_response.status_code == 200
    assert answer_response.status_code == 200
    assert answer_response.json()["state"] == "ready"
    assert readback.json() == answer_response.json()
    assert [item["id"] for item in listing.json()["items"]] == [conversation_id]
    assert len(runner.requests) == 2


async def test_malformed_stored_entry_is_a_safe_internal_error(
    tmp_path: Path,
) -> None:
    runner = RecordingTurnRunner(())

    async with _operator_client(tmp_path, runner=runner) as (client, session_factory):
        created = await client.post(
            "/api/operator/conversations",
            headers={"Idempotency-Key": "create-1"},
            json={},
        )
        conversation_id = created.json()["id"]
        async with session_factory() as session:
            session.add(
                OperatorConversationEntryModel(
                    entry_id="operator-entry.malformed",
                    conversation_id=conversation_id,
                    sequence=1,
                    kind="assistant_message",
                    body_json={"text": None},
                    request_idempotency_key=None,
                    request_digest=None,
                    created_at=utc_now(),
                )
            )
            await session.commit()
        response = await client.get(f"/api/operator/conversations/{conversation_id}")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "validation" not in str(response.json()).casefold()
