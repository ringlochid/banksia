from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

import pytest
from autoclaw.config import CodexSettings, RuntimeSettings, Settings
from autoclaw.definitions.contracts.registry import PolicyDefinitionInput
from autoclaw.definitions.contracts.workflow import NodeKind, ProviderKind
from autoclaw.persistence.models import (
    CommandRunModel,
    DispatchPromptRefsModel,
    DispatchTurnModel,
    FlowModel,
    HumanRequestModel,
    PolicyRevisionModel,
)
from autoclaw.runtime.clock import utc_now
from autoclaw.runtime.contracts import HumanRequestResolveRequest, TaskRootPaths
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.dispatch.request_pair import DispatchRequestPairRefs
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.flow.service import runtime_flow_read
from autoclaw.runtime.human_request.continuation import open_human_request_successor
from autoclaw.runtime.human_request.service import list_human_requests, resolve_human_request
from autoclaw.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from autoclaw.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    DispatchStartDue,
    HumanRequestTerminal,
    RuntimeEffectPublisher,
    RuntimeEffectSignal,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    SessionFactory,
    seeded_executor,
)
from tests.helpers.lineage_seed import RuntimeIds


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
        await _enable_target_policy(session_factory)
        publisher = CapturedRuntimeEffectPublisher()
        dependencies = _opening_dependencies(publisher=publisher)

        async with session_factory() as session:
            pre_open = await runtime_flow_read(cast(AsyncSession, session), ids.task_id)
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
            successor = await session.get(DispatchTurnModel, first.dispatch_id)
            refs = await session.get(DispatchPromptRefsModel, first.dispatch_id)
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
    assert flow is not None and flow.current_dispatch_id == first.dispatch_id
    assert successor is not None and successor.opened_reason == "human_result"
    assert successor.assignment_id == ids.root_assignment_id
    assert successor.attempt_id == ids.root_attempt_id
    assert dispatch_count == 4
    assert refs is not None
    input_text = (tmp_path / "task-human-continuation" / refs.input_logical_path).read_text(
        encoding="utf-8"
    )
    assert '"kind": "human_result"' in input_text
    assert f'"request_id": "{request_id}"' in input_text
    assert '"prompt": "Which direction?"' in input_text
    assert '"resolution_kind": "answered"' in input_text
    assert '"direction": "a"' in input_text
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
        await _enable_target_policy(session_factory)
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
) -> None:
    async with seeded_executor(tmp_path, suffix="human-preparation-failure") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_and_resolve_human_request(executor, session_factory, ids)
        await _enable_target_policy(session_factory)

        def fail_request_pair(
            *,
            paths: TaskRootPaths,
            dispatch_id: str,
            instructions_bytes: bytes,
            input_bytes: bytes,
        ) -> DispatchRequestPairRefs:
            del paths, dispatch_id, instructions_bytes, input_bytes
            raise OSError("request publication failed")

        dependencies = DispatchOpeningDependencies.create(
            settings=_provider_settings(),
            available_adapter_kinds={ProviderKind.CODEX},
            post_commit_publisher=CapturedRuntimeEffectPublisher(),
            request_pair_publisher=fail_request_pair,
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


async def test_human_source_change_during_materialization_loses_cleanly(
    tmp_path: Path,
) -> None:
    suffix = "human-materialization-race"
    database_path = tmp_path / f"{suffix}.sqlite"
    async with seeded_executor(tmp_path, suffix=suffix) as (
        executor,
        session_factory,
        ids,
        _,
    ):
        request_id = await _open_and_resolve_human_request(executor, session_factory, ids)
        await _enable_target_policy(session_factory)

        def publish_then_pause(
            *,
            paths: TaskRootPaths,
            dispatch_id: str,
            instructions_bytes: bytes,
            input_bytes: bytes,
        ) -> DispatchRequestPairRefs:
            from autoclaw.runtime.dispatch.request_pair import publish_dispatch_request_pair

            refs = publish_dispatch_request_pair(
                paths=paths,
                dispatch_id=dispatch_id,
                instructions_bytes=instructions_bytes,
                input_bytes=input_bytes,
            )
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    "UPDATE flows SET status = 'paused', pause_reason = 'operator_test', "
                    "paused_at = CURRENT_TIMESTAMP, paused_by_actor_ref = 'local_operator', "
                    "control_revision = control_revision + 1 WHERE flow_id = ?",
                    (ids.flow_id,),
                )
                connection.commit()
            return refs

        dependencies = DispatchOpeningDependencies.create(
            settings=_provider_settings(),
            available_adapter_kinds={ProviderKind.CODEX},
            post_commit_publisher=CapturedRuntimeEffectPublisher(),
            request_pair_publisher=publish_then_pause,
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


async def test_flow_read_rejects_multiple_retained_continuation_sources(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="ambiguous-retained-sources") as (
        executor,
        session_factory,
        ids,
        _,
    ):
        await _open_and_resolve_human_request(executor, session_factory, ids)
        now = utc_now()
        async with session_factory() as session:
            session.add(
                CommandRunModel(
                    run_id=f"command-run.{ids.task_id}.ambiguous",
                    task_id=ids.task_id,
                    flow_id=ids.flow_id,
                    assignment_id=ids.root_assignment_id,
                    attempt_id=ids.root_attempt_id,
                    source_dispatch_id=ids.root_dispatch_id,
                    command_spec_json={"kind": "argv", "argv": ["true"]},
                    summary="Synthetic conflicting retained source.",
                    state="succeeded",
                    started_at=now,
                    ended_at=now,
                    terminal_summary="Synthetic command completed.",
                    terminal_exit_code=0,
                    terminal_event_source="process_owner",
                    created_at=now,
                )
            )
            await session.commit()
            with pytest.raises(RuntimeOperationError) as ambiguous:
                await runtime_flow_read(cast(AsyncSession, session), ids.task_id)

    assert ambiguous.value.code == OperationFailureCode.ILLEGAL_STATE


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
            request=HumanRequestResolveRequest(item_responses={"direction": "a"}),
        )
    return request_id


async def _enable_target_policy(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        policy = await session.get(PolicyRevisionModel, "policy-revision.target.1")
        assert policy is not None
        policy.content_json = PolicyDefinitionInput(
            id="policy.target",
            description="Allow exact-source continuation in the integration fixture.",
            applies_to=[NodeKind.ROOT, NodeKind.WORKER],
        ).model_dump(mode="json")
        await session.commit()


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
