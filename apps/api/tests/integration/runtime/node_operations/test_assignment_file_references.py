from __future__ import annotations

from pathlib import Path

import pytest
from banksia.persistence.models import AssignmentModel, DispatchTurnModel, FlowNodeModel
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import NodeOperationScope
from sqlalchemy import func, select
from tests.helpers.executor_harness import seeded_executor


async def test_assign_child_rejects_invalid_file_before_staging_any_child_work(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="assign-invalid-file") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            assert parent is not None and child is not None
            parent.child_assignments_remaining = 1
            child.current_assignment_id = None
            child.state = "ready"
            before_count = await session.scalar(select(func.count()).select_from(AssignmentModel))
            await session.commit()

        with pytest.raises(RuntimeOperationError, match="referenced file does not exist"):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="assign_child",
                arguments={
                    "expected_structural_revision_id": ids.flow_revision_id,
                    "payload": {
                        "child_node_key": "child",
                        "assignment": {
                            "prompt": "Inspect a missing file.",
                            "files": [{"path": "missing.md"}],
                        },
                    },
                },
            )

        async with session_factory() as session:
            parent = await session.get(AssignmentModel, ids.root_assignment_id)
            child = await session.get(FlowNodeModel, ids.child_node_id)
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)
            after_count = await session.scalar(select(func.count()).select_from(AssignmentModel))

        assert before_count == after_count
        assert parent is not None and parent.child_assignments_remaining == 1
        assert child is not None and child.current_assignment_id is None
        assert dispatch is not None and dispatch.status == "open"
