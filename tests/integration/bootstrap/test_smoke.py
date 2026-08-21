from __future__ import annotations

from pathlib import Path
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from oh_my_subagents.persistence.models import (
    AssignmentModel,
    AttemptModel,
    MemberConfigurationModel,
    TaskStartSourceModel,
)
from oh_my_subagents.runtime import TaskStartRequest
from oh_my_subagents.runtime.launch.persistence.runtime import (
    persist_bootstrap_runtime_from_precomputed,
)
from tests.helpers.launch_foundation import (
    build_launch_foundation_input,
    build_launch_foundation_workflow_revision,
    seed_launch_foundation_workflow,
)
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)


def test_task_start_payload_smoke() -> None:
    payload = TaskStartRequest.model_validate(
        {
            "workflow": "bounded-change",
            "prompt": "Make one scoped settings-loader change and publish evidence.",
        }
    )

    assert payload.workflow == "bounded-change"
    assert payload.prompt == "Make one scoped settings-loader change and publish evidence."


async def test_launch_persists_provider_budget_and_empty_checkpoint_pointer(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="launch-foundation.sqlite")
    workflow_revision = build_launch_foundation_workflow_revision()
    bootstrap_input = build_launch_foundation_input(
        tmp_path,
        workflow_revision=workflow_revision,
    )
    with engine.begin() as connection:
        seed_launch_foundation_workflow(
            connection,
            workflow_revision=workflow_revision,
        )

    sync_factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with SyncSessionAdapter(sync_factory) as session:
            await persist_bootstrap_runtime_from_precomputed(
                cast(AsyncSession, session),
                bootstrap_input,
            )
            assignment = await session.scalar(select(AssignmentModel))
            attempt = await session.scalar(select(AttemptModel))
            member_configuration = await session.scalar(select(MemberConfigurationModel))
            task_start_source = await session.scalar(select(TaskStartSourceModel))
    finally:
        engine.dispose()

    assert assignment is not None
    assert assignment.child_assignment_limit == 20
    assert assignment.child_assignments_remaining == 20
    assert assignment.retry_limit == 1
    assert assignment.retries_remaining == 1
    assert attempt is not None and attempt.latest_checkpoint_id is None
    assert member_configuration is not None
    assert member_configuration.requested_provider_json == {"kind": "codex"}
    assert task_start_source is not None
    assert task_start_source.root_assignment_id == assignment.assignment_id
    assert task_start_source.root_attempt_id == attempt.attempt_id
