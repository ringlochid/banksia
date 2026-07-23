from pydantic import BaseModel, ConfigDict, field_validator

from banksia.runtime.contracts.refs import (
    FileReference,
    reject_duplicate_file_references,
    validate_file_reference_limit,
)
from banksia.runtime.contracts.text import (
    MAX_WORK_PROMPT_BYTES,
    normalize_exact_text,
)


class AssignmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: str
    files: tuple[FileReference, ...] = ()

    @field_validator("prompt", mode="before")
    @classmethod
    def normalize_prompt(cls, value: object) -> str:
        return normalize_exact_text(
            value,
            label="assignment prompt",
            max_utf8_bytes=MAX_WORK_PROMPT_BYTES,
            is_nonblank_required=True,
        )

    @field_validator("files")
    @classmethod
    def reject_duplicate_paths(
        cls,
        files: tuple[FileReference, ...],
    ) -> tuple[FileReference, ...]:
        validate_file_reference_limit(files, label="assignment")
        return reject_duplicate_file_references(files, label="assignment")


__all__ = ["AssignmentBody"]
