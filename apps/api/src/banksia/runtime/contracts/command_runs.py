from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from banksia.runtime.contracts.common import RuntimeSchemaText
from banksia.runtime.contracts.primitives import (
    CommandRunState,
    CommandRunTerminalSource,
    TaskEventType,
    TaskIdentifier,
)
from banksia.runtime.contracts.text import normalize_exact_text

_COMMAND_ARG_MAX_CHARACTERS = 4_096
_COMMAND_SHELL_MAX_UTF8_BYTES = 16 * 1_024
_COMMAND_SUMMARY_MAX_CHARACTERS = 2_048
_COMMAND_TIMEOUT_MAX_SECONDS = 86_400

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


class CommandArgvSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["argv"]
    argv: tuple[str, ...] = Field(min_length=1, max_length=256)

    @field_validator("argv", mode="before")
    @classmethod
    def normalize_argv(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            raise ValueError("command argv must be an array")
        normalized: list[str] = []
        for index, argument in enumerate(value):
            text = normalize_exact_text(
                argument,
                label=f"command argv item {index}",
            )
            if len(text) > _COMMAND_ARG_MAX_CHARACTERS:
                raise ValueError("command argv item exceeds the controller text limit")
            normalized.append(text)
        if normalized and not normalized[0]:
            raise ValueError("command executable must not be empty")
        return tuple(normalized)


class CommandShellSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["shell"]
    command: str

    @field_validator("command", mode="before")
    @classmethod
    def normalize_command(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="shell command",
            max_utf8_bytes=_COMMAND_SHELL_MAX_UTF8_BYTES,
            is_nonblank_required=True,
        )


type CommandSpec = Annotated[
    CommandArgvSpec | CommandShellSpec,
    Field(discriminator="kind"),
]


class CommandRunStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command: CommandSpec
    cwd: RuntimeSchemaText | None = None
    timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        le=_COMMAND_TIMEOUT_MAX_SECONDS,
    )
    summary: str

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_summary(cls, value: object) -> str:
        normalized = normalize_exact_text(
            value,
            label="command summary",
            is_nonblank_required=True,
        )
        if len(normalized) > _COMMAND_SUMMARY_MAX_CHARACTERS:
            raise ValueError("command summary exceeds the controller text limit")
        return normalized


class CommandRunStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    run_id: RuntimeSchemaText
    task_id: TaskIdentifier
    state: Literal[CommandRunState.PENDING_START, CommandRunState.RUNNING]
    output_path: RuntimeSchemaText


class CommandRunTerminalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    state: CommandRunTerminalState
    summary: RuntimeSchemaText
    exit_code: int | None = None
    started_at: datetime | None = None
    ended_at: datetime
    output_path: RuntimeSchemaText
    output_observed_bytes: int = Field(ge=0)
    output_written_bytes: int = Field(ge=0)
    output_complete: bool
    output_encoding: Literal["raw_bytes"]
    failure_code: RuntimeSchemaText | None = None
    terminal_event_source: CommandRunTerminalSource
    terminal_actor_ref: RuntimeSchemaText | None = None

    @model_validator(mode="after")
    def validate_abandoned_failure(self) -> CommandRunTerminalResult:
        _validate_abandoned_failure_code(self.state, self.failure_code)
        _validate_output_byte_counts(
            self.output_observed_bytes,
            self.output_written_bytes,
            self.output_complete,
        )
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
    output_path: RuntimeSchemaText
    output_observed_bytes: int = Field(ge=0)
    output_written_bytes: int = Field(ge=0)
    output_complete: bool
    output_encoding: Literal["raw_bytes"]
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
            if self.terminal_result.output_path != self.output_path:
                raise ValueError("command run output_path must match terminal_result.output_path")
            if (
                self.terminal_result.output_observed_bytes != self.output_observed_bytes
                or self.terminal_result.output_written_bytes != self.output_written_bytes
                or self.terminal_result.output_complete != self.output_complete
                or self.terminal_result.output_encoding != self.output_encoding
            ):
                raise ValueError("command run output facts must match terminal_result")
            return self
        if self.terminal_result is not None:
            raise ValueError("non-terminal command run states must not set terminal_result")
        _validate_output_byte_counts(
            self.output_observed_bytes,
            self.output_written_bytes,
            self.output_complete,
        )
        return self


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
    output_path: RuntimeSchemaText
    output_observed_bytes: int = Field(ge=0)
    output_written_bytes: int = Field(ge=0)
    output_complete: bool
    output_encoding: Literal["raw_bytes"]
    failure_code: RuntimeSchemaText | None = None

    @model_validator(mode="after")
    def validate_abandoned_failure(self) -> CommandRunListItem:
        _validate_abandoned_failure_code(self.state, self.failure_code)
        _validate_output_byte_counts(
            self.output_observed_bytes,
            self.output_written_bytes,
            self.output_complete,
        )
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
    output_path: RuntimeSchemaText
    content: str
    offset: int = Field(ge=0)
    bytes_read: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    file_size: int | None = Field(default=None, ge=0)
    is_missing: bool
    is_changed: bool
    output_complete: bool
    output_encoding: Literal["raw_bytes"]
    read_encoding: Literal["utf-8-replacement"] = "utf-8-replacement"


def _validate_abandoned_failure_code(
    state: CommandRunState,
    failure_code: str | None,
) -> None:
    if state == CommandRunState.ABANDONED and failure_code != "command_ownership_lost":
        raise ValueError("abandoned command runs require command_ownership_lost")


def _validate_output_byte_counts(
    observed_bytes: int,
    written_bytes: int,
    output_complete: bool,
) -> None:
    if written_bytes > observed_bytes:
        raise ValueError("command output written bytes cannot exceed observed bytes")
    if output_complete and written_bytes != observed_bytes:
        raise ValueError("complete command output requires every observed byte to be written")


for _command_run_contract in (
    CommandArgvSpec,
    CommandShellSpec,
    CommandRunStartRequest,
    CommandRunStartResponse,
    CommandRunTerminalResult,
    CommandRunRecord,
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
    "CommandRunCancelResponse",
    "CommandRunListItem",
    "CommandRunListResponse",
    "CommandRunLogReadResponse",
    "CommandRunRecord",
    "CommandRunStartRequest",
    "CommandRunStartResponse",
    "CommandRunTerminalResult",
    "CommandRunTerminalState",
    "CommandShellSpec",
    "CommandSpec",
]
