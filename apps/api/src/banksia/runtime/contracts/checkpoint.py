from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from banksia.runtime.contracts.primitives import CheckpointOutcome
from banksia.runtime.contracts.refs import FileReference, validate_file_reference_limit
from banksia.runtime.contracts.text import (
    MAX_WORK_PROMPT_BYTES,
    normalize_exact_text,
)

_CHECKPOINT_SUMMARY_MAX_CHARACTERS = 2_048


class CheckpointRecord(BaseModel):
    """One exact teammate-facing Checkpoint message."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    summary: str
    details: str | None = None
    files: tuple[FileReference, ...] = ()
    outcome: CheckpointOutcome | None = None

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_summary(cls, value: object) -> str:
        normalized = normalize_exact_text(
            value,
            label="checkpoint summary",
            is_nonblank_required=True,
        )
        if len(normalized) > _CHECKPOINT_SUMMARY_MAX_CHARACTERS:
            raise ValueError("checkpoint summary exceeds the controller text limit")
        return normalized

    @field_validator("details", mode="before")
    @classmethod
    def normalize_details(cls, value: object | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_exact_text(
            value,
            label="checkpoint details",
            max_utf8_bytes=MAX_WORK_PROMPT_BYTES,
        )
        return normalized if normalized.strip() else None

    @field_validator("files")
    @classmethod
    def validate_files(
        cls,
        files: tuple[FileReference, ...],
    ) -> tuple[FileReference, ...]:
        return validate_file_reference_limit(files, label="checkpoint")


class CheckpointRequest(CheckpointRecord):
    """Strict public request for the unified Checkpoint operation."""


class CheckpointResponse(BaseModel):
    """Committed Checkpoint readback without internal controller identities."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    checkpoint: CheckpointRecord
    recorded_at: datetime
    terminal: bool
    must_stop: bool


class TaskResult(BaseModel):
    """Exact accepted terminal Checkpoint selected as the Task result."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    outcome: Literal["green", "blocked"]
    summary: str
    details: str | None = None
    files: tuple[FileReference, ...] = ()
    completed_at: datetime


__all__ = [
    "CheckpointRecord",
    "CheckpointRequest",
    "CheckpointResponse",
    "TaskResult",
]
