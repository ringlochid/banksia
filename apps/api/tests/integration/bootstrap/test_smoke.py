from __future__ import annotations

from pathlib import Path
from typing import cast

from autoclaw.persistence.models import (
    AssignmentModel,
    AttemptModel,
    FlowNodeModel,
    NodePlanRevisionModel,
)
from autoclaw.runtime import TaskComposeInput
from autoclaw.runtime.launch.persistence.runtime import (
    persist_bootstrap_runtime_from_precomputed,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from tests.helpers.launch_foundation import (
    build_launch_foundation_definitions,
    build_launch_foundation_input,
    seed_launch_foundation_catalog,
)
from tests.helpers.sqlite_runtime import (
    SyncSessionAdapter,
    create_runtime_schema_engine,
)


def test_task_compose_payload_smoke() -> None:
    payload = TaskComposeInput.model_validate(
        {
            "task": {
                "key": "settings-loader-cleanup",
                "title": "Clean up settings loader",
                "summary": "Make one scoped settings-loader change and publish evidence.",
                "instruction": "Stay scoped to the settings-loader path only.",
            },
            "workflow": {"key": "bounded-change"},
        }
    )

    assert payload.workflow.key == "bounded-change"
    assert payload.task.key == "settings-loader-cleanup"


async def test_launch_persists_provider_budget_and_empty_checkpoint_pointer(
    tmp_path: Path,
) -> None:
    engine = create_runtime_schema_engine(tmp_path, name="launch-foundation.sqlite")
    role, policy, workflow = build_launch_foundation_definitions()
    bootstrap_input = build_launch_foundation_input(
        tmp_path,
        role=role,
        policy=policy,
        workflow=workflow,
    )
    with engine.begin() as connection:
        seed_launch_foundation_catalog(
            connection,
            role=role,
            policy=policy,
            workflow=workflow,
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
            flow_node = await session.scalar(select(FlowNodeModel))
            node_plan = await session.scalar(select(NodePlanRevisionModel))
    finally:
        engine.dispose()

    assert assignment is not None
    assert assignment.child_assignment_limit == 3
    assert assignment.child_assignments_remaining == 3
    assert assignment.retry_limit is None
    assert assignment.retries_remaining is None
    assert attempt is not None and attempt.latest_checkpoint_id is None
    assert flow_node is not None and flow_node.provider_kind == "codex"
    assert node_plan is not None and node_plan.provider_kind == "codex"
