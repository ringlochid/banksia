from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, field_validator

from oh_my_subagents.runtime.contracts.text import (
    MAX_FILE_REFERENCES,
    normalize_exact_text,
    normalize_optional_text,
)


class FileReference(BaseModel):
    """An ordered navigation value to one ordinary workspace file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    description: str | None = None

    @field_validator("path", mode="before")
    @classmethod
    def normalize_path(cls, value: object) -> str:
        value = normalize_exact_text(
            value,
            label="file reference path",
            max_utf8_bytes=4_096,
        )
        if (
            not value
            or "\\" in value
            or value.startswith("/")
            or any(character in value for character in ("*", "?", "[", "]"))
        ):
            raise ValueError("file reference path must be a workspace-relative regular-file path")
        raw_parts = value.split("/")
        if ".." in raw_parts:
            raise ValueError("file reference path must not contain '..'")
        normalized = str(PurePosixPath(value))
        if normalized in {"", "."}:
            raise ValueError("file reference path must name a file")
        first_part = PurePosixPath(normalized).parts[0]
        if ":" in first_part:
            raise ValueError("file reference path must not use a drive or URI scheme")
        return normalized

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> str | None:
        return normalize_optional_text(
            value,
            label="file reference description",
            max_characters=1_024,
        )


def validate_file_reference_limit(
    files: tuple[FileReference, ...],
    *,
    label: str,
) -> tuple[FileReference, ...]:
    """Apply the controller's hidden defensive bound without publishing it."""

    if len(files) > MAX_FILE_REFERENCES:
        raise ValueError(f"{label} files exceed the controller entry limit")
    return files


def reject_duplicate_file_references(
    files: tuple[FileReference, ...],
    *,
    label: str,
) -> tuple[FileReference, ...]:
    """Reject duplicate normalized paths where no workspace check follows."""

    paths = [file.path for file in files]
    if len(paths) != len(set(paths)):
        raise ValueError(f"{label} files contain a duplicate normalized path")
    return files


__all__ = [
    "FileReference",
    "reject_duplicate_file_references",
    "validate_file_reference_limit",
]
