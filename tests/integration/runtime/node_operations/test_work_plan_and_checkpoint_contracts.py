from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from oh_my_subagents.runtime.contracts import CheckpointRequest
from oh_my_subagents.runtime.node_operations import NodeOperationScope
from oh_my_subagents.runtime.work_plan import SetWorkPlanRequest
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


async def test_work_plan_replace_and_noop_return_only_model_visible_plan(
    tmp_path: Path,
) -> None:
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

    first_plan = first.model_dump(mode="json")["plan"]
    repeated_plan = repeated.model_dump(mode="json")["plan"]
    replaced_plan = replaced.model_dump(mode="json")["plan"]
    assert first_plan is not None and repeated_plan is not None and replaced_plan is not None
    assert first.model_dump()["changed"] is True
    assert repeated.model_dump()["changed"] is False
    assert replaced.model_dump()["changed"] is True
    assert first_plan == repeated_plan
    assert first_plan == {
        "explanation": "Bound the implementation.",
        "steps": [{"step": "Inspect controller truth", "status": "in_progress"}],
    }
    assert replaced_plan == {
        "explanation": "Record the result.",
        "steps": [{"step": "Record controller truth", "status": "completed"}],
    }
    assert "revision" not in replaced_plan
    assert "authored_by_dispatch_id" not in replaced_plan
    assert "updated_at" not in replaced_plan
