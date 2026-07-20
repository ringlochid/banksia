from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from autoclaw.runtime.contracts.common import RuntimeSchemaText
from autoclaw.runtime.contracts.primitives import (
    CommandRunState,
    CommandRunTerminalSource,
    TaskEventType,
    TaskIdentifier,
)

TERMINAL_COMMAND_RUN_STATES = frozenset(
    {
        CommandRunState.SUCCEEDED,
        CommandRunState.FAILED,
        CommandRunState.TIMED_OUT,
        CommandRunState.CANCELLED,
        CommandRunState.ABANDONED,
    }
)

type CommandRunTerminalState = Literal[
    CommandRunState.SUCCEEDED,
    CommandRunState.FAILED,
    CommandRunState.TIMED_OUT,
    CommandRunState.CANCELLED,
    CommandRunState.ABANDONED,
]

COMMAND_RUN_TERMINAL_EVENT_TYPES = {
    CommandRunState.SUCCEEDED: TaskEventType.COMMAND_RUN_SUCCEEDED,
    CommandRunState.FAILED: TaskEventType.COMMAND_RUN_FAILED,
    CommandRunState.TIMED_OUT: TaskEventType.COMMAND_RUN_TIMED_OUT,
    CommandRunState.CANCELLED: TaskEventType.COMMAND_RUN_CANCELLED,
    CommandRunState.ABANDONED: TaskEventType.COMMAND_RUN_ABANDONED,
}


type CommandEnvironmentRef = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
    ),
]


class CommandArgvSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["argv"]
    argv: tuple[RuntimeSchemaText, ...] = Field(min_length=1, max_length=256)

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any("\x00" in argument for argument in value):
            raise ValueError("command argv must not contain NUL bytes")
        return value


class CommandShellSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["shell"]
    command: RuntimeSchemaText

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("shell command must not contain NUL bytes")
        return value


type CommandSpec = Annotated[
    CommandArgvSpec | CommandShellSpec,
    Field(discriminator="kind"),
]


class CommandExpectedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: RuntimeSchemaText
    description: RuntimeSchemaText


class CommandRunStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command: CommandSpec
    cwd: RuntimeSchemaText | None = None
    environment: tuple[CommandEnvironmentRef, ...] = Field(default=(), max_length=32)
    timeout_seconds: int | None = Field(default=None, ge=1)
    summary: RuntimeSchemaText
    expected_outputs: tuple[CommandExpectedOutput, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def validate_unique_references(self) -> CommandRunStartRequest:
        if len(self.environment) != len(set(self.environment)):
            raise ValueError("command environment references must be unique")
        output_paths = [output.path for output in self.expected_outputs]
        if len(output_paths) != len(set(output_paths)):
            raise ValueError("command expected output paths must be unique")
        return self


class CommandRunStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    run_id: RuntimeSchemaText
    task_id: TaskIdentifier
    state: Literal[CommandRunState.PENDING_START, CommandRunState.RUNNING]


class CommandRunTerminalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    state: CommandRunTerminalState
    summary: RuntimeSchemaText
    exit_code: int | None = None
    started_at: datetime | None = None
    ended_at: datetime
    stdout_log_ref: RuntimeSchemaText | None = None
    stderr_log_ref: RuntimeSchemaText | None = None
    failure_code: RuntimeSchemaText | None = None
    terminal_event_source: CommandRunTerminalSource
    terminal_actor_ref: RuntimeSchemaText | None = None

    @model_validator(mode="after")
    def validate_abandoned_failure(self) -> CommandRunTerminalResult:
        _validate_abandoned_failure_code(self.state, self.failure_code)
        return self


class CommandRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    run_id: RuntimeSchemaText
    task_id: TaskIdentifier
    flow_id: RuntimeSchemaText
    assignment_id: RuntimeSchemaText
    attempt_id: RuntimeSchemaText
    source_dispatch_id: RuntimeSchemaText
    request: CommandRunStartRequest
    state: CommandRunState
    ownership_revision: int = Field(ge=0)
    created_at: datetime
    started_at: datetime | None = None
    due_at: datetime | None = None
    ended_at: datetime | None = None
    stdout_log_ref: RuntimeSchemaText | None = None
    stderr_log_ref: RuntimeSchemaText | None = None
    cancellation_requested_at: datetime | None = None
    cancellation_requested_by_actor_ref: RuntimeSchemaText | None = None
    terminal_result: CommandRunTerminalResult | None = None
    successor_dispatch_id: RuntimeSchemaText | None = None

    @model_validator(mode="after")
    def validate_terminal_result(self) -> CommandRunRecord:
        if self.state in TERMINAL_COMMAND_RUN_STATES:
            if self.terminal_result is None:
                raise ValueError("terminal command run states require terminal_result")
            if self.ended_at is None:
                raise ValueError("terminal command run states require ended_at")
            if self.terminal_result.state != self.state:
                raise ValueError("command run state must match terminal_result.state")
            if self.terminal_result.started_at != self.started_at:
                raise ValueError("command run started_at must match terminal_result.started_at")
            if self.terminal_result.ended_at != self.ended_at:
                raise ValueError("command run ended_at must match terminal_result.ended_at")
            if self.terminal_result.stdout_log_ref != self.stdout_log_ref:
                raise ValueError(
                    "command run stdout_log_ref must match terminal_result.stdout_log_ref"
                )
            if self.terminal_result.stderr_log_ref != self.stderr_log_ref:
                raise ValueError(
                    "command run stderr_log_ref must match terminal_result.stderr_log_ref"
                )
            return self
        if self.terminal_result is not None:
            raise ValueError("non-terminal command run states must not set terminal_result")
        return self


class CommandRunProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    run_id: RuntimeSchemaText
    summary: RuntimeSchemaText
    log_ref: RuntimeSchemaText | None = None
    owned_process_pid: int | None = Field(default=None, ge=1)
    occurred_at: datetime


class CommandRunListItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    run_id: RuntimeSchemaText
    state: CommandRunState
    command: RuntimeSchemaText
    description: RuntimeSchemaText | None = None
    workdir: RuntimeSchemaText | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    summary: RuntimeSchemaText | None = None
    exit_code: int | None = None
    signal: RuntimeSchemaText | None = None
    log_ref: RuntimeSchemaText | None = None
    failure_code: RuntimeSchemaText | None = None

    @model_validator(mode="after")
    def validate_abandoned_failure(self) -> CommandRunListItem:
        _validate_abandoned_failure_code(self.state, self.failure_code)
        return self


class CommandRunListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: TaskIdentifier
    items: tuple[CommandRunListItem, ...]
    next_cursor: RuntimeSchemaText | None = None


class CommandRunCancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: TaskIdentifier
    run: CommandRunListItem


class CommandRunLogReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    task_id: TaskIdentifier
    run_id: RuntimeSchemaText
    log_ref: RuntimeSchemaText
    content: str


def _validate_abandoned_failure_code(
    state: CommandRunState,
    failure_code: str | None,
) -> None:
    if state == CommandRunState.ABANDONED and failure_code != "command_ownership_lost":
        raise ValueError("abandoned command runs require command_ownership_lost")


for _command_run_contract in (
    CommandArgvSpec,
    CommandShellSpec,
    CommandExpectedOutput,
    CommandRunStartRequest,
    CommandRunStartResponse,
    CommandRunTerminalResult,
    CommandRunRecord,
    CommandRunProgressUpdate,
    CommandRunListItem,
    CommandRunListResponse,
    CommandRunCancelResponse,
    CommandRunLogReadResponse,
):
    _command_run_contract.model_rebuild(_types_namespace=globals())


__all__ = [
    "COMMAND_RUN_TERMINAL_EVENT_TYPES",
    "TERMINAL_COMMAND_RUN_STATES",
    "CommandArgvSpec",
    "CommandEnvironmentRef",
    "CommandExpectedOutput",
    "CommandRunCancelResponse",
    "CommandRunListItem",
    "CommandRunListResponse",
    "CommandRunLogReadResponse",
    "CommandRunProgressUpdate",
    "CommandRunRecord",
    "CommandRunStartRequest",
    "CommandRunStartResponse",
    "CommandRunTerminalResult",
    "CommandRunTerminalState",
    "CommandShellSpec",
    "CommandSpec",
]
