from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy import desc, select

from banksia.config import get_settings
from banksia.main import create_app
from banksia.operator.contracts import (
    OperatorProviderAskUserResult,
    OperatorProviderMessageResult,
    OperatorProviderQuestion,
    OperatorProviderQuestionOption,
    OperatorProviderResult,
)
from banksia.operator.operations import (
    OperatorOperationExecutor,
    OperatorOperationScope,
)
from banksia.operator.provider import (
    OperatorProviderAvailability,
    OperatorProviderError,
    OperatorProviderInvocation,
    OperatorProviderOutcome,
)
from banksia.operator.service import OperatorServices, create_operator_services
from banksia.persistence.models import OperatorInvocationModel
from tests.helpers.product_surface import product_dispatch_dependencies
from tests.helpers.workflow_runtime import AsyncSessionFactory, initialized_workflow_database


class HttpContractRunner:
    availability = OperatorProviderAvailability(
        availability="available",
        configured_provider="test",
        problem_code=None,
        explanation="The hermetic Operator provider is available.",
        setup_action=None,
        resolved_model="test-model",
        resolved_effort="high",
    )

    async def invoke(
        self,
        invocation: OperatorProviderInvocation,
        operations: OperatorOperationExecutor,
    ) -> OperatorProviderOutcome:
        result: OperatorProviderResult
        if invocation.provider_input == "fail":
            raise OperatorProviderError("transient", is_retry_safe=True)
        if invocation.provider_input == "proposal":
            proposal = await operations.execute(
                scope=OperatorOperationScope(
                    conversation_id=invocation.conversation_id,
                    invocation_id=invocation.invocation_id,
                    claim_generation=invocation.claim_generation,
                ),
                provider_call_id="http-task-start",
                operation_name="task_start",
                arguments={
                    "workflow": "reviewed-delivery",
                    "prompt": "Start through the HTTP confirmation route.",
                },
            )
            assert proposal.kind == "proposal"
            result = OperatorProviderMessageResult(
                kind="message",
                text="The HTTP proposal is ready.",
            )
        elif invocation.provider_input.startswith("<operator_return"):
            result = OperatorProviderMessageResult(
                kind="message",
                text="The HTTP answer is recorded.",
            )
        else:
            result = OperatorProviderAskUserResult(
                kind="ask_user",
                questions=(
                    OperatorProviderQuestion(
                        header="Direction",
                        question="Which HTTP direction should be used?",
                        options=(
                            OperatorProviderQuestionOption(
                                label="First",
                                consequence="Use the first direction.",
                            ),
                            OperatorProviderQuestionOption(
                                label="Second",
                                consequence="Use the second direction.",
                            ),
                        ),
                    ),
                ),
            )
        return OperatorProviderOutcome(
            result=result,
            provider_thread_id=f"thread-{invocation.conversation_id}",
        )


@dataclass(frozen=True)
class _QuestionRouteProof:
    conversation_id: str
    create: httpx.Response
    create_replay: httpx.Response
    detail: httpx.Response
    message: httpx.Response
    message_replay: httpx.Response
    message_conflict: httpx.Response
    invalid_answers: httpx.Response
    answers: httpx.Response
    answers_replay: httpx.Response
    answers_conflict: httpx.Response


@dataclass(frozen=True)
class _OperatorRouteProof:
    status: httpx.Response
    listing: httpx.Response
    questions: _QuestionRouteProof
    confirmation: httpx.Response
    confirmation_replay: httpx.Response
    retry: httpx.Response
    retry_replay: httpx.Response


async def test_unconfigured_operator_status_and_admission_failure_are_truthful(
    tmp_path: Path,
) -> None:
    async with initialized_workflow_database(tmp_path) as session_factory:
        dependencies = product_dispatch_dependencies(tmp_path)
        services = create_operator_services(
            session_factory=session_factory,
            settings=dependencies.settings,
            dispatch_dependencies=dependencies,
            runtime_effect_publisher=None,
        )
        app = create_app(should_enable_mcp_mounts=False)
        app.state.operator_conversation_service = services.conversations
        settings = get_settings()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
            base_url=f"http://127.0.0.1:{settings.api_port}",
        ) as client:
            status_response = await client.get("/api/operator/status")
            create_response = await client.post(
                "/api/operator/conversations",
                headers={"Idempotency-Key": "create"},
                json={},
            )
            invalid_header_response = await client.post(
                "/api/operator/conversations",
                headers={"Idempotency-Key": " "},
                json={},
            )
            invalid_body_response = await client.post(
                "/api/operator/conversations",
                headers={"Idempotency-Key": "invalid-body"},
                json={"unexpected": True},
            )
            missing_body_response = await client.post(
                "/api/operator/conversations",
                headers={"Idempotency-Key": "missing-body"},
            )

    assert status_response.status_code == 200
    assert status_response.json()["availability"] == "unconfigured"
    assert create_response.status_code == 503
    assert create_response.json()["problem"]["code"] == "operator_provider_unavailable"
    assert invalid_header_response.status_code == 422
    assert invalid_header_response.json()["problem"]["code"] == "invalid_operator_request"
    assert invalid_body_response.status_code == 422
    assert invalid_body_response.json()["problem"]["code"] == "invalid_operator_request"
    assert missing_body_response.status_code == 422
    assert missing_body_response.json()["problem"]["code"] == "invalid_operator_request"


async def test_all_eight_operator_routes_have_real_success_replay_and_conflict_proof(
    tmp_path: Path,
) -> None:
    proof = await _exercise_all_operator_routes(tmp_path)
    _assert_route_statuses(proof)
    _assert_route_replays_and_conflicts(proof)


async def _exercise_all_operator_routes(tmp_path: Path) -> _OperatorRouteProof:
    async with initialized_workflow_database(tmp_path) as session_factory:
        dependencies = product_dispatch_dependencies(tmp_path)
        services = create_operator_services(
            session_factory=session_factory,
            settings=dependencies.settings,
            dispatch_dependencies=dependencies,
            runtime_effect_publisher=None,
            provider_runner=HttpContractRunner(),
        )
        app = create_app(should_enable_mcp_mounts=False)
        app.state.operator_conversation_service = services.conversations
        settings = get_settings()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
            base_url=f"http://127.0.0.1:{settings.api_port}",
        ) as client:
            status_response = await client.get("/api/operator/status")
            list_response = await client.get("/api/operator/conversations")
            question_proof = await _exercise_question_routes(
                client,
                services=services,
                session_factory=session_factory,
            )
            confirmation_response, confirmation_replay = await _exercise_confirmation_route(
                client,
                services=services,
                session_factory=session_factory,
            )
            retry_response, retry_replay = await _exercise_retry_route(
                client,
                services=services,
                session_factory=session_factory,
            )
    return _OperatorRouteProof(
        status=status_response,
        listing=list_response,
        questions=question_proof,
        confirmation=confirmation_response,
        confirmation_replay=confirmation_replay,
        retry=retry_response,
        retry_replay=retry_replay,
    )


def _assert_route_statuses(proof: _OperatorRouteProof) -> None:
    matrix = {
        ("GET", "/operator/status"): proof.status.status_code,
        ("GET", "/operator/conversations"): proof.listing.status_code,
        ("POST", "/operator/conversations"): proof.questions.create.status_code,
        ("GET", "/operator/conversations/{id}"): proof.questions.detail.status_code,
        ("POST", "/operator/conversations/{id}/messages"): proof.questions.message.status_code,
        ("POST", "/operator/conversations/{id}/question-sets/{id}/answers"): (
            proof.questions.answers.status_code
        ),
        ("POST", "/operator/conversations/{id}/confirmations/{id}"): (
            proof.confirmation.status_code
        ),
        ("POST", "/operator/conversations/{id}/retries"): proof.retry.status_code,
    }
    assert matrix == {
        ("GET", "/operator/status"): 200,
        ("GET", "/operator/conversations"): 200,
        ("POST", "/operator/conversations"): 201,
        ("GET", "/operator/conversations/{id}"): 200,
        ("POST", "/operator/conversations/{id}/messages"): 202,
        ("POST", "/operator/conversations/{id}/question-sets/{id}/answers"): 202,
        ("POST", "/operator/conversations/{id}/confirmations/{id}"): 200,
        ("POST", "/operator/conversations/{id}/retries"): 202,
    }


def _assert_route_replays_and_conflicts(proof: _OperatorRouteProof) -> None:
    questions = proof.questions
    assert questions.create_replay.status_code == 201
    assert questions.create_replay.json()["id"] == questions.conversation_id
    assert questions.message_replay.status_code == 202
    assert questions.message_replay.json()["entries"] == questions.message.json()["entries"]
    assert questions.answers_replay.status_code == 202
    assert questions.answers_replay.json()["entries"] == questions.answers.json()["entries"]
    assert proof.confirmation_replay.status_code == 200
    assert proof.retry_replay.status_code == 202
    assert questions.invalid_answers.status_code == 422
    invalid_problem = questions.invalid_answers.json()["problem"]
    assert invalid_problem["code"] == "invalid_operator_request"
    assert invalid_problem["message"] == "The Operator answers are invalid."
    assert invalid_problem["field_errors"]
    assert "not-a-current-option" not in questions.invalid_answers.text
    for conflict in (questions.message_conflict, questions.answers_conflict):
        assert conflict.status_code == 409
        assert conflict.json()["problem"]["code"] == "idempotency_conflict"


def test_operator_openapi_declares_only_route_specific_problem_responses() -> None:
    schema = create_app(should_enable_mcp_mounts=False).openapi()
    paths = schema["paths"]
    declared = {
        ("get", "/api/operator/status"): {"200"},
        ("get", "/api/operator/conversations"): {"200", "422"},
        ("post", "/api/operator/conversations"): {"201", "422", "503"},
        ("get", "/api/operator/conversations/{conversation_id}"): {
            "200",
            "404",
            "422",
        },
        ("post", "/api/operator/conversations/{conversation_id}/messages"): {
            "202",
            "404",
            "409",
            "422",
            "503",
        },
        (
            "post",
            (
                "/api/operator/conversations/{conversation_id}/question-sets/"
                "{question_set_id}/answers"
            ),
        ): {"202", "404", "409", "422", "503"},
        (
            "post",
            ("/api/operator/conversations/{conversation_id}/confirmations/{confirmation_id}"),
        ): {"200", "404", "409", "422"},
        ("post", "/api/operator/conversations/{conversation_id}/retries"): {
            "202",
            "404",
            "409",
            "422",
            "503",
        },
    }

    assert {key: set(paths[key[1]][key[0]]["responses"]) for key in declared} == declared


async def _exercise_question_routes(
    client: httpx.AsyncClient,
    *,
    services: OperatorServices,
    session_factory: AsyncSessionFactory,
) -> _QuestionRouteProof:
    conversation_id, create, create_replay, detail = await _exercise_conversation_routes(client)
    message, message_replay, message_conflict = await _exercise_message_routes(
        client,
        conversation_id,
    )
    await services.coordinator.execute_provider_invocation(
        await _queued_invocation_id(session_factory, conversation_id)
    )
    asked = (await client.get(f"/api/operator/conversations/{conversation_id}")).json()
    question_set = asked["entries"][-1]
    question = question_set["questions"][0]
    answer_url = (
        f"/api/operator/conversations/{conversation_id}/question-sets/{question_set['id']}/answers"
    )
    invalid_answers, answers, answers_replay, answers_conflict = await _exercise_answer_routes(
        client,
        answer_url=answer_url,
        question=question,
    )
    await services.coordinator.execute_provider_invocation(
        await _queued_invocation_id(session_factory, conversation_id)
    )
    return _QuestionRouteProof(
        conversation_id=conversation_id,
        create=create,
        create_replay=create_replay,
        detail=detail,
        message=message,
        message_replay=message_replay,
        message_conflict=message_conflict,
        invalid_answers=invalid_answers,
        answers=answers,
        answers_replay=answers_replay,
        answers_conflict=answers_conflict,
    )


async def _exercise_conversation_routes(
    client: httpx.AsyncClient,
) -> tuple[str, httpx.Response, httpx.Response, httpx.Response]:
    create = await client.post(
        "/api/operator/conversations",
        headers={"Idempotency-Key": "http-create"},
        json={},
    )
    assert create.status_code == 201, create.text
    conversation_id = str(create.json()["id"])
    create_replay = await client.post(
        "/api/operator/conversations",
        headers={"Idempotency-Key": "http-create"},
        json={},
    )
    detail = await client.get(f"/api/operator/conversations/{conversation_id}")
    return conversation_id, create, create_replay, detail


async def _exercise_message_routes(
    client: httpx.AsyncClient,
    conversation_id: str,
) -> tuple[httpx.Response, httpx.Response, httpx.Response]:
    message_url = f"/api/operator/conversations/{conversation_id}/messages"
    message = await client.post(
        message_url,
        headers={"Idempotency-Key": "http-message"},
        json={"text": "ask"},
    )
    message_replay = await client.post(
        message_url,
        headers={"Idempotency-Key": "http-message"},
        json={"text": "ask"},
    )
    message_conflict = await client.post(
        message_url,
        headers={"Idempotency-Key": "http-message"},
        json={"text": "different"},
    )
    return message, message_replay, message_conflict


async def _exercise_answer_routes(
    client: httpx.AsyncClient,
    *,
    answer_url: str,
    question: dict[str, object],
) -> tuple[httpx.Response, httpx.Response, httpx.Response, httpx.Response]:
    answer_payload = _answer_payload(question, option_index=0)
    invalid_answers = await client.post(
        answer_url,
        headers={"Idempotency-Key": "http-invalid-answer"},
        json={
            "answers": [
                {
                    "question_id": question["id"],
                    "answer": {
                        "kind": "option",
                        "option_id": "not-a-current-option",
                    },
                }
            ]
        },
    )
    answers = await client.post(
        answer_url,
        headers={"Idempotency-Key": "http-answer"},
        json=answer_payload,
    )
    answers_replay = await client.post(
        answer_url,
        headers={"Idempotency-Key": "http-answer"},
        json=answer_payload,
    )
    answers_conflict = await client.post(
        answer_url,
        headers={"Idempotency-Key": "http-answer"},
        json=_answer_payload(question, option_index=1),
    )
    return invalid_answers, answers, answers_replay, answers_conflict


async def _exercise_confirmation_route(
    client: httpx.AsyncClient,
    *,
    services: OperatorServices,
    session_factory: AsyncSessionFactory,
) -> tuple[httpx.Response, httpx.Response]:
    conversation_id = await _create_http_conversation(client, "proposal-create")
    await client.post(
        f"/api/operator/conversations/{conversation_id}/messages",
        headers={"Idempotency-Key": "proposal-message"},
        json={"text": "proposal"},
    )
    await services.coordinator.execute_provider_invocation(
        await _queued_invocation_id(session_factory, conversation_id)
    )
    view = (await client.get(f"/api/operator/conversations/{conversation_id}")).json()
    confirmation_id = next(
        action["confirmation_id"]
        for action in view["legal_actions"]
        if action["kind"] == "confirm_effect"
    )
    url = f"/api/operator/conversations/{conversation_id}/confirmations/{confirmation_id}"
    confirmation = await client.post(
        url,
        headers={"Idempotency-Key": "http-confirm"},
        json={},
    )
    replay = await client.post(
        url,
        headers={"Idempotency-Key": "http-confirm"},
        json={},
    )
    return confirmation, replay


async def _exercise_retry_route(
    client: httpx.AsyncClient,
    *,
    services: OperatorServices,
    session_factory: AsyncSessionFactory,
) -> tuple[httpx.Response, httpx.Response]:
    conversation_id = await _create_http_conversation(client, "retry-create")
    await client.post(
        f"/api/operator/conversations/{conversation_id}/messages",
        headers={"Idempotency-Key": "retry-message"},
        json={"text": "fail"},
    )
    await services.coordinator.execute_provider_invocation(
        await _queued_invocation_id(session_factory, conversation_id)
    )
    url = f"/api/operator/conversations/{conversation_id}/retries"
    retry = await client.post(
        url,
        headers={"Idempotency-Key": "http-retry"},
        json={},
    )
    replay = await client.post(
        url,
        headers={"Idempotency-Key": "http-retry"},
        json={},
    )
    return retry, replay


def _answer_payload(question: dict[str, object], *, option_index: int) -> dict[str, object]:
    options = question["options"]
    assert isinstance(options, list)
    option = options[option_index]
    assert isinstance(option, dict)
    return {
        "answers": [
            {
                "question_id": question["id"],
                "answer": {
                    "kind": "option",
                    "option_id": option["id"],
                },
            }
        ]
    }


async def _create_http_conversation(
    client: httpx.AsyncClient,
    idempotency_key: str,
) -> str:
    response = await client.post(
        "/api/operator/conversations",
        headers={"Idempotency-Key": idempotency_key},
        json={},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


async def _queued_invocation_id(
    session_factory: AsyncSessionFactory,
    conversation_id: str,
) -> str:
    async with session_factory() as session:
        invocation_id = await session.scalar(
            select(OperatorInvocationModel.invocation_id)
            .where(
                OperatorInvocationModel.conversation_id == conversation_id,
                OperatorInvocationModel.state == "queued",
            )
            .order_by(desc(OperatorInvocationModel.created_at))
            .limit(1)
        )
    assert invocation_id is not None
    return invocation_id
