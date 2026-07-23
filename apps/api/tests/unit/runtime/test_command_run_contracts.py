from __future__ import annotations

from datetime import UTC, datetime

import pytest
from banksia.runtime.contracts import (
    COMMAND_RUN_TERMINAL_EVENT_TYPES,
    TERMINAL_COMMAND_RUN_STATES,
    CommandArgvSpec,
    CommandRunRecord,
    CommandRunStartRequest,
    CommandRunState,
    CommandRunTerminalSource,
    CommandShellSpec,
    PromptCommandOutcome,
    PromptCommandResult,
    PromptCommandTerminalSource,
    TaskEventType,
)
from pydantic import ValidationError

NOW = datetime(2026, 7, 18, tzinfo=UTC)


def test_command_request_preserves_argument_and_summary_semantics() -> None:
    request = CommandRunStartRequest.model_validate(
        {
            "command": {
                "kind": "argv",
                "argv": ["  executable  ", "", "line\r\nvalue", "\tkept\t"],
            },
            "summary": "  preserve this purpose\r\n  ",
        }
    )

    assert isinstance(request.command, CommandArgvSpec)
    assert request.command.argv == (
        "  executable  ",
        "",
        "line\nvalue",
        "\tkept\t",
    )
    assert request.summary == "  preserve this purpose\n  "


def test_command_argv_applies_exact_item_bounds_and_rejects_illegal_text() -> None:
    accepted = CommandRunStartRequest.model_validate(
        {
            "command": {"kind": "argv", "argv": ["x" * 4_096]},
            "summary": "Boundary.",
        }
    )
    assert isinstance(accepted.command, CommandArgvSpec)
    assert accepted.command.argv == ("x" * 4_096,)

    with pytest.raises(ValidationError, match="argv item exceeds"):
        CommandRunStartRequest.model_validate(
            {
                "command": {"kind": "argv", "argv": ["x" * 4_097]},
                "summary": "Over boundary.",
            }
        )
    with pytest.raises(ValidationError, match="executable must not be empty"):
        CommandRunStartRequest.model_validate(
            {
                "command": {"kind": "argv", "argv": ["", "legal-empty-later", ""]},
                "summary": "Empty executable.",
            }
        )
    with pytest.raises(ValidationError, match="illegal text character"):
        CommandRunStartRequest.model_validate(
            {
                "command": {"kind": "argv", "argv": ["ok", "bad\u0001"]},
                "summary": "Illegal argument.",
            }
        )


def test_shell_command_uses_utf8_bound_without_stripping() -> None:
    exact_boundary = "é" * (16 * 1_024 // 2)
    accepted = CommandRunStartRequest.model_validate(
        {
            "command": {"kind": "shell", "command": exact_boundary},
            "summary": "Boundary.",
        }
    )
    assert isinstance(accepted.command, CommandShellSpec)
    assert accepted.command.command == exact_boundary

    preserved = CommandRunStartRequest.model_validate(
        {
            "command": {"kind": "shell", "command": "  printf value\r\n  "},
            "summary": "Whitespace.",
        }
    )
    assert isinstance(preserved.command, CommandShellSpec)
    assert preserved.command.command == "  printf value\n  "

    with pytest.raises(ValidationError, match="shell command exceeds"):
        CommandRunStartRequest.model_validate(
            {
                "command": {"kind": "shell", "command": exact_boundary + "x"},
                "summary": "Over boundary.",
            }
        )
    with pytest.raises(ValidationError, match="shell command must not be blank"):
        CommandRunStartRequest.model_validate(
            {
                "command": {"kind": "shell", "command": " \t\r\n "},
                "summary": "Blank command.",
            }
        )


def test_command_summary_and_timeout_apply_exact_boundaries() -> None:
    accepted = CommandRunStartRequest.model_validate(
        {
            "command": {"kind": "argv", "argv": ["true"]},
            "summary": "s" * 2_048,
            "timeout_seconds": 86_400,
        }
    )
    assert accepted.summary == "s" * 2_048
    assert accepted.timeout_seconds == 86_400

    with pytest.raises(ValidationError, match="summary exceeds"):
        CommandRunStartRequest.model_validate(
            {
                "command": {"kind": "argv", "argv": ["true"]},
                "summary": "s" * 2_049,
            }
        )
    with pytest.raises(ValidationError, match="less than or equal to 86400"):
        CommandRunStartRequest.model_validate(
            {
                "command": {"kind": "argv", "argv": ["true"]},
                "summary": "Timeout.",
                "timeout_seconds": 86_401,
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("environment", ["python.safe"]),
        (
            "expected_outputs",
            [{"path": "artifacts/result.txt", "description": "Result."}],
        ),
    ),
)
def test_command_request_rejects_removed_orchestration_fields(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CommandRunStartRequest.model_validate(
            {
                "command": {"kind": "argv", "argv": ["true"]},
                "summary": "Run one command.",
                field: value,
            }
        )


def test_abandoned_is_a_terminal_command_state_with_its_own_event() -> None:
    assert CommandRunState.ABANDONED in TERMINAL_COMMAND_RUN_STATES
    assert (
        COMMAND_RUN_TERMINAL_EVENT_TYPES[CommandRunState.ABANDONED]
        == TaskEventType.COMMAND_RUN_ABANDONED
    )


def test_abandoned_command_record_requires_ownership_lost_diagnostic() -> None:
    payload = {
        "run_id": "c_01234567",
        "task_id": "t_01234567",
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
        "output_path": ".banksia/t_01234567/command-runs/c_01234567/output.log",
        "output_observed_bytes": 42,
        "output_written_bytes": 42,
        "output_complete": True,
        "output_encoding": "raw_bytes",
        "successor_dispatch_id": "dispatch.successor",
        "terminal_result": {
            "state": CommandRunState.ABANDONED,
            "summary": "Command ownership was lost during restart.",
            "started_at": NOW,
            "ended_at": NOW,
            "output_path": ".banksia/t_01234567/command-runs/c_01234567/output.log",
            "output_observed_bytes": 42,
            "output_written_bytes": 42,
            "output_complete": True,
            "output_encoding": "raw_bytes",
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
    assert record.terminal_result.output_path == record.output_path
    assert record.terminal_result.failure_code == "command_ownership_lost"

    terminal_result = payload["terminal_result"]
    assert isinstance(terminal_result, dict)
    payload["terminal_result"] = {**terminal_result, "failure_code": "process_not_found"}
    with pytest.raises(ValidationError, match="command_ownership_lost"):
        CommandRunRecord.model_validate(payload)


def test_command_record_rejects_terminal_result_source_mismatches() -> None:
    payload = {
        "run_id": "c_01234567",
        "task_id": "t_01234567",
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
        "output_path": ".banksia/t_01234567/command-runs/c_01234567/output.log",
        "output_observed_bytes": 42,
        "output_written_bytes": 42,
        "output_complete": True,
        "output_encoding": "raw_bytes",
        "terminal_result": {
            "state": CommandRunState.SUCCEEDED,
            "summary": "Command completed.",
            "started_at": NOW,
            "ended_at": NOW,
            "output_path": ".banksia/t_01234567/command-runs/c_76543210/output.log",
            "output_observed_bytes": 42,
            "output_written_bytes": 42,
            "output_complete": True,
            "output_encoding": "raw_bytes",
            "terminal_event_source": CommandRunTerminalSource.PROCESS_OWNER,
        },
    }

    with pytest.raises(ValidationError, match="output_path must match"):
        CommandRunRecord.model_validate(payload)


def test_abandoned_prompt_result_requires_ownership_lost_diagnostic() -> None:
    result = PromptCommandResult(
        state=PromptCommandOutcome.ABANDONED,
        summary="Command ownership was lost during restart.",
        started_at=NOW,
        ended_at=NOW,
        output_path=".banksia/t_01234567/command-runs/c_01234567/output.log",
        output_observed_bytes=0,
        output_written_bytes=0,
        output_complete=False,
        output_encoding="raw_bytes",
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
            output_path=".banksia/t_01234567/command-runs/c_01234567/output.log",
            output_observed_bytes=0,
            output_written_bytes=0,
            output_complete=False,
            output_encoding="raw_bytes",
            failure_code="process_not_found",
            terminal_event_source=PromptCommandTerminalSource.CONTROLLER,
        )
