from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import oh_my_subagents.runtime.replan.continuation as replan_continuation
from oh_my_subagents.config import CodexSettings, RuntimeSettings, Settings
from oh_my_subagents.persistence.models import (
    AttemptModel,
    DispatchTurnModel,
    ReplanTransitionModel,
    TaskModel,
)
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.node_operations import NodeOperationScope
from oh_my_subagents.runtime.post_commit import (
    CapturedRuntimeEffectPublisher,
    ReplanCommitted,
    RuntimeEffectSignal,
)
from oh_my_subagents.runtime.post_commit.dispatch_startup import read_replan_continuation_page
from oh_my_subagents.runtime.replan.continuation import continue_committed_replan
from oh_my_subagents.runtime.task_control.service import (
    cancel_runtime_task,
    continue_runtime_task,
    pause_runtime_task,
)
from tests.helpers.executor_harness import (
    SessionFactory,
    make_seed_child_terminal,
    seeded_executor,
    seeded_task_root,
)
from tests.helpers.lineage_seed import RuntimeIds


@dataclass(frozen=True, slots=True)
class _ManifestFailureObservation:
    opening_outcome: str
    manifest_state: str
    successor_state: str
    successor_dispatch_id: str | None
    discovered_sources: tuple[RuntimeEffectSignal, ...]


@dataclass(frozen=True, slots=True)
class _ManifestRepairObservation:
    opening_outcome: str
    successor_dispatch_id: str | None
    repeated_opening_outcome: str
    manifest_state: str
    successor_state: str
    persisted_successor_dispatch_id: str | None
    successor_count: int


async def test_pause_after_replan_resumes_the_exact_transition_once(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-pause-resume") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Reviewer"}},
        )
        dependencies = _opening_dependencies()
        async with session_factory() as session:
            transition = await session.scalar(select(ReplanTransitionModel))
            task = await session.get(TaskModel, ids.task_id)
            assert transition is not None and task is not None
            paused = await pause_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=transition.successor_team_revision_id,
                expected_control_revision=task.control_revision,
            )
            startup_while_paused = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=transition.replan_transition_id,
                dependencies=dependencies,
            )
            resumed = await continue_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=transition.successor_team_revision_id,
                expected_control_revision=paused.task.control_revision,
                dependencies=dependencies,
            )
            duplicate = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=transition.replan_transition_id,
                dependencies=dependencies,
            )
            current_transition = await session.get(
                ReplanTransitionModel,
                transition.replan_transition_id,
            )
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            successor_count = await session.scalar(
                select(func.count())
                .select_from(DispatchTurnModel)
                .where(
                    DispatchTurnModel.predecessor_dispatch_id == ids.current_dispatch_id,
                )
            )

    assert startup_while_paused.outcome == "skipped"
    assert resumed.status.value == "running"
    assert duplicate.outcome == "skipped"
    assert current_transition is not None
    assert current_transition.successor_state == "opened"
    assert attempt is not None
    assert attempt.current_dispatch_id == current_transition.successor_dispatch_id
    assert successor_count == 1


async def test_cancel_after_replan_settles_and_hides_the_transition_from_startup(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="recursive-cancel") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            await make_seed_child_terminal(session, ids)
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Reviewer"}},
        )
        async with session_factory() as session:
            transition = await session.scalar(select(ReplanTransitionModel))
            task = await session.get(TaskModel, ids.task_id)
            assert transition is not None and task is not None
            cancelled = await cancel_runtime_task(
                cast(AsyncSession, session),
                ids.task_id,
                expected_team_revision_id=transition.successor_team_revision_id,
                expected_control_revision=task.control_revision,
            )
            current_transition = await session.get(
                ReplanTransitionModel,
                transition.replan_transition_id,
            )
        page = await read_replan_continuation_page(
            lambda: cast(
                AbstractAsyncContextManager[AsyncSession],
                session_factory(),
            ),
            cursor=None,
            page_size=10,
        )

    assert cancelled.status.value == "cancelled"
    assert current_transition is not None
    assert current_transition.successor_state == "cancelled"
    assert current_transition.successor_dispatch_id is None
    assert page.sources == ()


async def test_manifest_repair_is_restart_discoverable_and_opens_one_exact_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    dependencies = _opening_dependencies()
    async with seeded_executor(
        tmp_path,
        suffix="replan-manifest-repair",
        runtime_effect_publisher=publisher,
    ) as (executor, session_factory, ids, _signals):
        await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="add_child",
            arguments={"child": {"title": "Recovery reviewer"}},
        )
        signal = publisher.signals[0]
        assert isinstance(signal, ReplanCommitted)
        failure = await _damage_manifest_and_read_recovery_source(
            monkeypatch,
            session_factory,
            signal,
            dependencies,
        )
        repaired = await _repair_manifest_and_read_successor(
            session_factory,
            ids,
            signal,
            dependencies,
        )

    assert failure.opening_outcome == "paused"
    assert failure.manifest_state == "repair_required"
    assert failure.successor_state == "blocked"
    assert failure.successor_dispatch_id is None
    assert failure.discovered_sources == (ReplanCommitted(signal.transition_id),)
    assert repaired.opening_outcome == "opened"
    assert repaired.successor_dispatch_id is not None
    assert repaired.repeated_opening_outcome == "skipped"
    assert repaired.manifest_state == "current"
    assert repaired.successor_state == "opened"
    assert repaired.persisted_successor_dispatch_id == repaired.successor_dispatch_id
    assert repaired.successor_count == 1
    manifest = seeded_task_root(
        tmp_path,
        "replan-manifest-repair",
    ).joinpath("manifest.md")
    assert "Recovery reviewer" in manifest.read_text(encoding="utf-8")


async def _damage_manifest_and_read_recovery_source(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: SessionFactory,
    signal: ReplanCommitted,
    dependencies: DispatchOpeningDependencies,
) -> _ManifestFailureObservation:
    async def fail_projection(*_args: object, **_kwargs: object) -> bool:
        raise OSError("manifest storage is temporarily unavailable")

    with monkeypatch.context() as scoped:
        scoped.setattr(
            replan_continuation,
            "project_workflow_manifest",
            fail_projection,
        )
        async with session_factory() as session:
            opening = await continue_committed_replan(
                cast(AsyncSession, session),
                transition_id=signal.transition_id,
                dependencies=dependencies,
            )
            transition = await session.get(ReplanTransitionModel, signal.transition_id)
        page = await read_replan_continuation_page(
            lambda: cast(
                AbstractAsyncContextManager[AsyncSession],
                session_factory(),
            ),
            cursor=None,
            page_size=10,
        )
    assert transition is not None
    return _ManifestFailureObservation(
        opening_outcome=opening.outcome,
        manifest_state=transition.manifest_state,
        successor_state=transition.successor_state,
        successor_dispatch_id=transition.successor_dispatch_id,
        discovered_sources=page.sources,
    )


async def _repair_manifest_and_read_successor(
    session_factory: SessionFactory,
    ids: RuntimeIds,
    signal: ReplanCommitted,
    dependencies: DispatchOpeningDependencies,
) -> _ManifestRepairObservation:
    async with session_factory() as session:
        opening = await continue_committed_replan(
            cast(AsyncSession, session),
            transition_id=signal.transition_id,
            dependencies=dependencies,
        )
        repeated = await continue_committed_replan(
            cast(AsyncSession, session),
            transition_id=signal.transition_id,
            dependencies=dependencies,
        )
        transition = await session.get(ReplanTransitionModel, signal.transition_id)
        successor_count = int(
            await session.scalar(
                select(func.count())
                .select_from(DispatchTurnModel)
                .where(DispatchTurnModel.predecessor_dispatch_id == ids.current_dispatch_id)
            )
            or 0
        )
    assert transition is not None
    return _ManifestRepairObservation(
        opening_outcome=opening.outcome,
        successor_dispatch_id=opening.dispatch_id,
        repeated_opening_outcome=repeated.outcome,
        manifest_state=transition.manifest_state,
        successor_state=transition.successor_state,
        persisted_successor_dispatch_id=transition.successor_dispatch_id,
        successor_count=successor_count,
    )


def _opening_dependencies() -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )
