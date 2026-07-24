from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

import banksia.runtime.dispatch.ordinary_continuation as ordinary_continuation_module
import pytest
from banksia.config import CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    AttemptModel,
    AttemptWaitModel,
    DispatchRequestModel,
    DispatchTurnModel,
    FlowModel,
    HumanRequestModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.contracts import HumanRequestResolveRequest
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.flow.service import runtime_flow_read
from banksia.runtime.human_request.continuation import open_human_request_successor
from banksia.runtime.human_request.service import list_human_requests, resolve_human_request
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DispatchStartDue,
    HumanRequestTerminal,
    RuntimeEffectPublisher,
    RuntimeEffectSignal,
)
from banksia.runtime.prompt import parse_prompt_continuation
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds

_DIRECTION_A_ANSWER = {
    "direction": {
        "kind": "option",
        "option_id": "a",
    }
}


class _RaisingPublisher:
    def publish(self, signal: RuntimeEffectSignal) -> bool:
        del signal
        raise RuntimeError("post-commit publication unavailable")


async def test_terminal_human_source_opens_one_same_attempt_successor(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="human-continuation") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_and_resolve_human_request(executor, session_factory, ids)
        publisher = CapturedRuntimeEffectPublisher()
        dependencies = _opening_dependencies(publisher=publisher)

        async with session_factory() as session:
            pre_open = await runtime_flow_read(cast(AsyncSession, session), ids.task_id)
            unrelated_request_id = await _stage_unrelated_child_wait(
                cast(AsyncSession, session),
                ids,
            )
            initial_flow = await session.get(FlowModel, ids.flow_id)
            assert initial_flow is not None
            initial_control_revision = initial_flow.control_revision
            first = await open_human_request_successor(
                cast(AsyncSession, session),
                signal=HumanRequestTerminal(request_id),
                dependencies=dependencies,
            )
            duplicate = await open_human_request_successor(
                cast(AsyncSession, session),
                signal=HumanRequestTerminal(request_id),
                dependencies=dependencies,
            )
            source = await session.get(HumanRequestModel, request_id)
            request_page = await list_human_requests(
                cast(AsyncSession, session),
                task_id=ids.task_id,
            )
            flow = await session.get(FlowModel, ids.flow_id)
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            unrelated_attempt = await session.get(AttemptModel, ids.child_attempt_id)
            unrelated_wait = await session.scalar(
                select(AttemptWaitModel).where(
                    AttemptWaitModel.human_request_id == unrelated_request_id
                )
            )
            successor = await session.get(DispatchTurnModel, first.dispatch_id)
            dispatch_request = await session.get(DispatchRequestModel, first.dispatch_id)
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert first.outcome == "opened"
    assert pre_open.current_human_request is not None
    assert pre_open.current_human_request.request_id == request_id
    assert pre_open.current_human_request.status.value == "resolved"
    assert pre_open.current_dispatch is None
    assert duplicate.outcome == "skipped"
    assert first.dispatch_id is not None
    assert source is not None and source.successor_dispatch_id == first.dispatch_id
    assert request_page.items[0].request.successor_dispatch_id == first.dispatch_id
    assert attempt is not None
    assert attempt.current_dispatch_id == first.dispatch_id
    assert attempt.current_wait_id is None
    assert unrelated_attempt is not None and unrelated_wait is not None
    assert unrelated_attempt.current_wait_id == unrelated_wait.wait_id
    assert flow is not None and flow.control_revision == initial_control_revision
    assert successor is not None and successor.opened_reason == "human_result"
    assert successor.assignment_id == ids.root_assignment_id
    assert successor.attempt_id == ids.root_attempt_id
    assert dispatch_count == 4
    assert dispatch_request is not None
    continuation = parse_prompt_continuation(dispatch_request.input)
    assert continuation is not None
    trigger = continuation.trigger
    assert trigger.kind == "human_result"
    assert trigger.source.request_id == request_id
    assert trigger.result.request.items[0].prompt == "Which direction?"
    assert trigger.result.resolution.resolution_kind.value == "answered"
    assert trigger.result.resolution.model_dump(mode="json")["item_responses"] == (
        _DIRECTION_A_ANSWER
    )
    assert "policy_basis" not in trigger.result.resolution.model_dump(mode="json")
    assert len(publisher.signals) == 1
    signal = publisher.signals[0]
    assert isinstance(signal, DispatchStartDue)
    assert signal.dispatch_id == first.dispatch_id
    assert signal.provider_start_revision == 0


async def test_human_successor_commit_survives_start_publication_failure(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="human-publish-failure") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_and_resolve_human_request(executor, session_factory, ids)
        async with session_factory() as session:
            result = await open_human_request_successor(
                cast(AsyncSession, session),
                signal=HumanRequestTerminal(request_id),
                dependencies=_opening_dependencies(publisher=_RaisingPublisher()),
            )
            source = await session.get(HumanRequestModel, request_id)
            successor = await session.get(DispatchTurnModel, result.dispatch_id)

    assert result.outcome == "opened"
    assert source is not None and source.successor_dispatch_id == result.dispatch_id
    assert successor is not None and successor.status == "starting"


async def test_human_preparation_failure_pauses_without_consuming_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with seeded_executor(tmp_path, suffix="human-preparation-failure") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_and_resolve_human_request(executor, session_factory, ids)

        def fail_preparation(**_kwargs: object) -> None:
            raise ValueError("request preparation failed")

        monkeypatch.setattr(
            ordinary_continuation_module,
            "prepare_dispatch_request",
            fail_preparation,
        )

        dependencies = DispatchOpeningDependencies.create(
            settings=_provider_settings(),
            available_adapter_kinds={ProviderKind.CODEX},
            post_commit_publisher=CapturedRuntimeEffectPublisher(),
        )
        async with session_factory() as session:
            result = await open_human_request_successor(
                cast(AsyncSession, session),
                signal=HumanRequestTerminal(request_id),
                dependencies=dependencies,
            )
            source = await session.get(HumanRequestModel, request_id)
            flow = await session.get(FlowModel, ids.flow_id)
            readback = await runtime_flow_read(cast(AsyncSession, session), ids.task_id)
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert result.outcome == "paused"
    assert source is not None and source.successor_dispatch_id is None
    assert flow is not None and flow.status == "paused"
    assert flow.pause_reason == "runtime_transition_failed"
    assert readback.current_human_request is not None
    assert readback.current_human_request.request_id == request_id
    assert readback.current_human_request.status.value == "resolved"
    assert dispatch_count == 3


async def test_human_source_change_during_preparation_loses_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = "human-preparation-race"
    database_path = tmp_path / f"{suffix}.sqlite"
    async with seeded_executor(tmp_path, suffix=suffix) as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_and_resolve_human_request(executor, session_factory, ids)

        real_prepare = ordinary_continuation_module.prepare_dispatch_request

        def prepare_then_pause(**kwargs: object) -> object:
            prepared = real_prepare(**kwargs)  # type: ignore[arg-type]
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    "UPDATE flows SET status = 'paused', pause_reason = 'operator_test', "
                    "paused_at = CURRENT_TIMESTAMP, paused_by_actor_ref = 'local_operator', "
                    "control_revision = control_revision + 1 WHERE flow_id = ?",
                    (ids.flow_id,),
                )
                connection.commit()
            return prepared

        monkeypatch.setattr(
            ordinary_continuation_module,
            "prepare_dispatch_request",
            prepare_then_pause,
        )

        dependencies = DispatchOpeningDependencies.create(
            settings=_provider_settings(),
            available_adapter_kinds={ProviderKind.CODEX},
            post_commit_publisher=CapturedRuntimeEffectPublisher(),
        )
        async with session_factory() as session:
            result = await open_human_request_successor(
                cast(AsyncSession, session),
                signal=HumanRequestTerminal(request_id),
                dependencies=dependencies,
            )
            source = await session.get(HumanRequestModel, request_id)
            dispatch_count = await session.scalar(
                select(func.count()).select_from(DispatchTurnModel)
            )

    assert result.outcome == "skipped"
    assert source is not None and source.successor_dispatch_id is None
    assert dispatch_count == 3


async def _open_and_resolve_human_request(
    executor: NodeOperationExecutor,
    session_factory: SessionFactory,
    ids: RuntimeIds,
) -> str:
    opened = await executor.execute(
        scope=NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id),
        operation_name="open_human_request",
        arguments={
            "request": {
                "kind": "direction",
                "summary": "Choose one exact direction.",
                "items": [
                    {
                        "id": "direction",
                        "prompt": "Which direction?",
                        "options": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
                    }
                ],
            }
        },
    )
    request_id = cast(str, opened.model_dump()["request_id"])
    async with session_factory() as session:
        await resolve_human_request(
            cast(AsyncSession, session),
            task_id=ids.task_id,
            request_id=request_id,
            request=HumanRequestResolveRequest.model_validate(
                {"item_responses": _DIRECTION_A_ANSWER}
            ),
        )
    return request_id


async def _stage_unrelated_child_wait(
    session: AsyncSession,
    ids: RuntimeIds,
) -> str:
    request_id = f"human-request.{ids.task_id}.unrelated-child"
    wait_id = f"attempt-wait.{ids.task_id}.unrelated-child"
    session.add(
        HumanRequestModel(
            request_id=request_id,
            task_id=ids.task_id,
            flow_id=ids.flow_id,
            assignment_id=ids.child_assignment_id,
            attempt_id=ids.child_attempt_id,
            source_dispatch_id=ids.child_dispatch_id,
            request_kind="input",
            request_summary="Synthetic unrelated child wait.",
            request_items_json=[
                {
                    "id": "detail",
                    "prompt": "Provide the detail.",
                    "response_schema": {"type": "string"},
                    "allow_skip": False,
                }
            ],
            capability_basis_json={"decision": "allow", "kind": "input"},
            status="open",
        )
    )
    session.add(
        AttemptWaitModel(
            wait_id=wait_id,
            task_id=ids.task_id,
            flow_id=ids.flow_id,
            assignment_id=ids.child_assignment_id,
            attempt_id=ids.child_attempt_id,
            source_dispatch_id=ids.child_dispatch_id,
            human_request_id=request_id,
        )
    )
    child_attempt = await session.get(AttemptModel, ids.child_attempt_id)
    assert child_attempt is not None
    child_attempt.current_wait_id = wait_id
    await session.commit()
    return request_id


def _provider_settings() -> Settings:
    return Settings(
        runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
        codex=CodexSettings(enabled=True),
    )


def _opening_dependencies(
    *,
    publisher: RuntimeEffectPublisher,
) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=_provider_settings(),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=publisher,
    )


__all__ = []
