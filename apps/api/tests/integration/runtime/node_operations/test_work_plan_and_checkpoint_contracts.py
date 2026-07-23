from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import banksia.runtime.work_plan.operations as work_plan_operations
import pytest
from banksia.runtime.contracts import CheckpointRequest
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.work_plan import SetWorkPlanRequest
from pydantic import ValidationError
from tests.helpers.executor_harness import seeded_executor


def test_work_plan_contract_enforces_exact_bounded_meaningful_text() -> None:
    request = SetWorkPlanRequest.model_validate(
        {
            "explanation": "e" * 1_024,
            "steps": [{"step": "s" * 512, "status": "pending"}],
        }
    )

    assert len(request.explanation or "") == 1_024
    assert len(request.steps[0].step) == 512
    schema = SetWorkPlanRequest.model_json_schema()
    explanation_schema = schema["properties"]["explanation"]["anyOf"][0]
    step_schema = schema["$defs"]["SetWorkPlanStep"]["properties"]["step"]
    assert explanation_schema["minLength"] == 1
    assert explanation_schema["maxLength"] == 1_024
    assert step_schema["minLength"] == 1
    assert step_schema["maxLength"] == 512

    invalid_payloads = (
        {"explanation": "e" * 1_025, "steps": []},
        {"steps": [{"step": "s" * 513, "status": "pending"}]},
        {"explanation": "   ", "steps": []},
        {"explanation": "T.B.D.", "steps": []},
        {"steps": [{"step": "...", "status": "pending"}]},
        {"steps": [{"step": "[TODO]", "status": "pending"}]},
    )
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            SetWorkPlanRequest.model_validate(payload)


def test_checkpoint_enforces_exact_bounded_meaningful_text() -> None:
    checkpoint = CheckpointRequest.model_validate(
        {
            "summary": "s" * 2_048,
            "details": "Complete teammate-facing details.",
            "files": [
                {
                    "path": ".banksia/t_example/artifacts/report.md",
                    "description": "Reviewable report.",
                }
            ],
            "outcome": "green",
        }
    )

    assert len(checkpoint.summary) == 2_048
    assert checkpoint.details == "Complete teammate-facing details."
    assert checkpoint.files[0].description == "Reviewable report."
    assert checkpoint.outcome == "green"

    invalid_checkpoints = (
        {"summary": "s" * 2_049},
        {"summary": "   "},
        {"summary": "Summary.", "details": "x" * 65_537},
        {"summary": "Summary.", "outcome": "unknown"},
        {"summary": "Summary.", "files": [{"path": "../escape"}]},
    )
    for payload in invalid_checkpoints:
        with pytest.raises(ValidationError):
            CheckpointRequest.model_validate(payload)


async def test_work_plan_commit_time_advances_only_for_changed_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_commit = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    second_commit = first_commit + timedelta(minutes=1)
    commit_times = iter((first_commit, second_commit))
    monkeypatch.setattr(work_plan_operations, "utc_now", lambda: next(commit_times))

    async with seeded_executor(tmp_path, suffix="plan-commit-time") as (
        executor,
        _session_factory,
        ids,
        _signals,
    ):
        scope = NodeOperationScope(task_id=ids.task_id, dispatch_id=ids.current_dispatch_id)
        first = await executor.execute(
            scope=scope,
            operation_name="set_work_plan",
            arguments={
                "explanation": "Bound the implementation.",
                "steps": [{"step": "Inspect controller truth", "status": "in_progress"}],
            },
        )
        repeated = await executor.execute(
            scope=scope,
            operation_name="set_work_plan",
            arguments={
                "explanation": "  Bound the implementation.  ",
                "steps": [{"step": "  Inspect controller truth  ", "status": "in_progress"}],
            },
        )
        replaced = await executor.execute(
            scope=scope,
            operation_name="set_work_plan",
            arguments={
                "explanation": "Record the result.",
                "steps": [{"step": "Record controller truth", "status": "completed"}],
            },
        )

    first_plan = first.model_dump()["plan"]
    repeated_plan = repeated.model_dump()["plan"]
    replaced_plan = replaced.model_dump()["plan"]
    assert first_plan is not None and repeated_plan is not None and replaced_plan is not None
    assert first.model_dump()["changed"] is True
    assert repeated.model_dump()["changed"] is False
    assert replaced.model_dump()["changed"] is True
    assert first_plan["revision"] == repeated_plan["revision"] == 1
    assert replaced_plan["revision"] == 2
    assert first_plan["updated_at"] == repeated_plan["updated_at"] == first_commit
    assert replaced_plan["updated_at"] == second_commit
