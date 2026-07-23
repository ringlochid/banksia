from __future__ import annotations

from pathlib import Path
from typing import cast

from banksia.persistence.models import (
    AssignmentModel,
    AttemptModel,
    FlowNodeModel,
    NodePlanRevisionModel,
)
from banksia.runtime import TaskComposeInput
from banksia.runtime.launch.persistence.runtime import (
    persist_bootstrap_runtime_from_precomputed,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from tests.helpers.launch_foundation import (
    build_launch_foundation_input,
    build_launch_foundation_workflow_revision,
    seed_launch_foundation_workflow,
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
            flow_node = await session.scalar(select(FlowNodeModel))
            node_plan = await session.scalar(select(NodePlanRevisionModel))
    finally:
        engine.dispose()

    assert assignment is not None
    assert assignment.child_assignment_limit == 20
    assert assignment.child_assignments_remaining == 20
    assert assignment.retry_limit == 1
    assert assignment.retries_remaining == 1
    assert attempt is not None and attempt.latest_checkpoint_id is None
    assert flow_node is not None and flow_node.provider_kind == "codex"
    assert node_plan is not None and node_plan.provider_kind == "codex"
