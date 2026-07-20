from __future__ import annotations

from datetime import UTC, datetime

import pytest
from autoclaw.runtime.contracts import (
    COMMAND_RUN_TERMINAL_EVENT_TYPES,
    TERMINAL_COMMAND_RUN_STATES,
    CommandRunRecord,
    CommandRunState,
    CommandRunTerminalSource,
    PromptCommandOutcome,
    PromptCommandResult,
    PromptCommandTerminalSource,
    TaskEventType,
)
from pydantic import ValidationError

NOW = datetime(2026, 7, 18, tzinfo=UTC)


def test_abandoned_is_a_terminal_command_state_with_its_own_event() -> None:
    assert CommandRunState.ABANDONED in TERMINAL_COMMAND_RUN_STATES
    assert (
        COMMAND_RUN_TERMINAL_EVENT_TYPES[CommandRunState.ABANDONED]
        == TaskEventType.COMMAND_RUN_ABANDONED
    )


def test_abandoned_command_record_requires_ownership_lost_diagnostic() -> None:
    payload = {
        "run_id": "command-run.target",
        "task_id": "task.target",
        "flow_id": "flow.target",
        "assignment_id": "assignment.target",
        "attempt_id": "attempt.target",
        "source_dispatch_id": "dispatch.target",
        "request": {
            "command": {"kind": "argv", "argv": ["true"]},
            "summary": "Run a target command.",
        },
        "state": CommandRunState.ABANDONED,
        "ownership_revision": 2,
        "created_at": NOW,
        "started_at": NOW,
        "ended_at": NOW,
        "stdout_log_ref": "_runtime/command-runs/command-run.target/stdout.log",
        "stderr_log_ref": "_runtime/command-runs/command-run.target/stderr.log",
        "successor_dispatch_id": "dispatch.successor",
        "terminal_result": {
            "state": CommandRunState.ABANDONED,
            "summary": "Command ownership was lost during restart.",
            "started_at": NOW,
            "ended_at": NOW,
            "stdout_log_ref": "_runtime/command-runs/command-run.target/stdout.log",
            "stderr_log_ref": "_runtime/command-runs/command-run.target/stderr.log",
            "failure_code": "command_ownership_lost",
            "terminal_event_source": CommandRunTerminalSource.PROCESS_OWNER,
        },
    }

    record = CommandRunRecord.model_validate(payload)

    assert record.state == CommandRunState.ABANDONED
    assert record.source_dispatch_id == "dispatch.target"
    assert record.successor_dispatch_id == "dispatch.successor"
    assert record.request.command.kind == "argv"
    assert record.terminal_result is not None
    assert record.terminal_result.state == CommandRunState.ABANDONED
    assert record.terminal_result.stdout_log_ref == record.stdout_log_ref
    assert record.terminal_result.failure_code == "command_ownership_lost"

    terminal_result = payload["terminal_result"]
    assert isinstance(terminal_result, dict)
    payload["terminal_result"] = {**terminal_result, "failure_code": "process_not_found"}
    with pytest.raises(ValidationError, match="command_ownership_lost"):
        CommandRunRecord.model_validate(payload)


def test_command_record_rejects_terminal_result_source_mismatches() -> None:
    payload = {
        "run_id": "command-run.target",
        "task_id": "task.target",
        "flow_id": "flow.target",
        "assignment_id": "assignment.target",
        "attempt_id": "attempt.target",
        "source_dispatch_id": "dispatch.target",
        "request": {
            "command": {"kind": "argv", "argv": ["true"]},
            "summary": "Run a target command.",
        },
        "state": CommandRunState.SUCCEEDED,
        "ownership_revision": 2,
        "created_at": NOW,
        "started_at": NOW,
        "ended_at": NOW,
        "stdout_log_ref": "_runtime/command-runs/command-run.target/stdout.log",
        "terminal_result": {
            "state": CommandRunState.SUCCEEDED,
            "summary": "Command completed.",
            "started_at": NOW,
            "ended_at": NOW,
            "stdout_log_ref": "_runtime/command-runs/other/stdout.log",
            "terminal_event_source": CommandRunTerminalSource.PROCESS_OWNER,
        },
    }

    with pytest.raises(ValidationError, match="stdout_log_ref must match"):
        CommandRunRecord.model_validate(payload)


def test_abandoned_prompt_result_requires_ownership_lost_diagnostic() -> None:
    result = PromptCommandResult(
        state=PromptCommandOutcome.ABANDONED,
        summary="Command ownership was lost during restart.",
        started_at=NOW,
        ended_at=NOW,
        failure_code="command_ownership_lost",
        terminal_event_source=PromptCommandTerminalSource.CONTROLLER,
    )

    assert result.failure_code == "command_ownership_lost"

    with pytest.raises(ValidationError, match="command_ownership_lost"):
        PromptCommandResult(
            state=PromptCommandOutcome.ABANDONED,
            summary="Command ownership was lost during restart.",
            started_at=NOW,
            ended_at=NOW,
            failure_code="process_not_found",
            terminal_event_source=PromptCommandTerminalSource.CONTROLLER,
        )
