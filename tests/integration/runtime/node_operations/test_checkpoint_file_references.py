from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from banksia.persistence.models import AttemptCheckpointModel, AttemptModel, DispatchTurnModel
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations import NodeOperationScope
from tests.helpers.executor_harness import seeded_executor


async def test_checkpoint_rejects_invalid_file_without_persisting_message(
    tmp_path: Path,
) -> None:
    async with seeded_executor(tmp_path, suffix="checkpoint-invalid-file") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        with pytest.raises(RuntimeOperationError, match="referenced file does not exist"):
            await executor.execute(
                scope=NodeOperationScope(
                    task_id=ids.task_id,
                    dispatch_id=ids.current_dispatch_id,
                ),
                operation_name="checkpoint",
                arguments={
                    "summary": "This message must roll back.",
                    "files": [{"path": "missing.md"}],
                },
            )

        async with session_factory() as session:
            checkpoint = await session.scalar(
                select(AttemptCheckpointModel).where(
                    AttemptCheckpointModel.authoring_dispatch_id == ids.current_dispatch_id
                )
            )
            attempt = await session.get(AttemptModel, ids.root_attempt_id)
            dispatch = await session.get(DispatchTurnModel, ids.current_dispatch_id)

        assert checkpoint is None
        assert attempt is not None and attempt.latest_checkpoint_id is None
        assert dispatch is not None and dispatch.status == "open"
