from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import autoclaw.runtime.work_plan.operations as work_plan_operations
import pytest
from autoclaw.runtime.contracts import CheckpointHandoffRead
from autoclaw.runtime.node_operations import NodeOperationScope
from autoclaw.runtime.work_plan import SetWorkPlanRequest
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


def test_checkpoint_handoff_enforces_exact_bounded_meaningful_text() -> None:
    handoff = CheckpointHandoffRead.model_validate(
        {
            "summary": "s" * 2_048,
            "next_step": "n" * 1_024,
            "blockers": ["b" * 1_024] * 16,
            "risks": ["r"],
        }
    )

    assert len(handoff.summary) == 2_048
    assert len(handoff.next_step) == 1_024
    assert len(handoff.blockers) == 16
    schema = CheckpointHandoffRead.model_json_schema()["properties"]
    assert schema["summary"]["minLength"] == 1
    assert schema["summary"]["maxLength"] == 2_048
    assert schema["next_step"]["minLength"] == 1
    assert schema["next_step"]["maxLength"] == 1_024
    assert schema["blockers"]["maxItems"] == 16
    assert schema["blockers"]["items"]["minLength"] == 1
    assert schema["blockers"]["items"]["maxLength"] == 1_024
    assert schema["risks"]["maxItems"] == 16
    assert schema["risks"]["items"]["minLength"] == 1
    assert schema["risks"]["items"]["maxLength"] == 1_024

    valid_base = {"summary": "Summary.", "next_step": "Continue."}
    invalid_handoffs = (
        {**valid_base, "summary": "s" * 2_049},
        {**valid_base, "next_step": "n" * 1_025},
        {**valid_base, "blockers": ["b"] * 17},
        {**valid_base, "risks": ["r" * 1_025]},
        {**valid_base, "summary": "   "},
        {**valid_base, "next_step": "T.B.D."},
        {**valid_base, "blockers": ["…"]},
        {**valid_base, "risks": ["[TODO]"]},
    )
    for payload in invalid_handoffs:
        with pytest.raises(ValidationError):
            CheckpointHandoffRead.model_validate(payload)


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
