from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from banksia.runtime.contracts.common import RuntimeSchemaText
from banksia.runtime.contracts.refs import (
    FileReference,
    reject_duplicate_file_references,
    validate_file_reference_limit,
)
from banksia.runtime.contracts.text import MAX_WORK_PROMPT_BYTES, normalize_exact_text


class DelegatedAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    child_id: RuntimeSchemaText
    prompt: str
    files: tuple[FileReference, ...] = ()

    @field_validator("prompt", mode="before")
    @classmethod
    def normalize_prompt(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="delegation prompt",
            max_utf8_bytes=MAX_WORK_PROMPT_BYTES,
            is_nonblank_required=True,
        )

    @field_validator("files")
    @classmethod
    def reject_duplicate_paths(
        cls,
        files: tuple[FileReference, ...],
    ) -> tuple[FileReference, ...]:
        validate_file_reference_limit(files, label="delegation assignment")
        return reject_duplicate_file_references(files, label="delegation assignment")


class DelegateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assignments: tuple[DelegatedAssignment, ...] = Field(min_length=1, max_length=8)

    @field_validator("assignments")
    @classmethod
    def reject_duplicate_children(
        cls,
        assignments: tuple[DelegatedAssignment, ...],
    ) -> tuple[DelegatedAssignment, ...]:
        child_ids = tuple(assignment.child_id for assignment in assignments)
        if len(set(child_ids)) != len(child_ids):
            raise ValueError("delegate assignments must target unique direct children")
        return assignments


class DelegatedMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    child_id: RuntimeSchemaText


class DelegateSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: Literal[True] = True
    members: tuple[DelegatedMember, ...]
    must_stop: Literal[True] = True


__all__ = [
    "DelegateRequest",
    "DelegateSuccess",
    "DelegatedAssignment",
    "DelegatedMember",
]
