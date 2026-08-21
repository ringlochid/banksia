from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from oh_my_subagents.runtime.contracts.refs import (
    FileReference,
    reject_duplicate_file_references,
    validate_file_reference_limit,
)
from oh_my_subagents.runtime.contracts.text import (
    MAX_WORK_PROMPT_BYTES,
    normalize_exact_text,
)
from oh_my_subagents.workflows.contracts import Identifier


class TaskStartRequest(BaseModel):
    """The one transient request accepted by every Task-start transport."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow: Identifier
    prompt: str
    workspace: Path | None = None
    files: tuple[FileReference, ...] = ()

    @field_validator("prompt", mode="before")
    @classmethod
    def normalize_prompt(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="task prompt",
            max_utf8_bytes=MAX_WORK_PROMPT_BYTES,
            is_nonblank_required=True,
        )

    @field_validator("files")
    @classmethod
    def reject_duplicate_paths(
        cls,
        files: tuple[FileReference, ...],
    ) -> tuple[FileReference, ...]:
        validate_file_reference_limit(files, label="task")
        return reject_duplicate_file_references(files, label="task")


class TaskStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    status: Literal["accepted"] = "accepted"
    task_id: str
    workflow: Identifier
    workflow_revision: int = Field(ge=1)
    workspace: Path
    manifest: str


__all__ = ["TaskStartRequest", "TaskStartResponse"]
