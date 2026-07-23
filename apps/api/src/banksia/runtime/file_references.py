from __future__ import annotations

from pathlib import Path

from banksia.runtime.contracts import FileReference
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError


def validate_file_references(
    workspace: Path,
    files: tuple[FileReference, ...],
) -> tuple[FileReference, ...]:
    """Validate the provisional WP-03 physical contract for ordered file references."""

    normalized_workspace = validate_workspace(workspace)
    seen: set[str] = set()
    validated: list[FileReference] = []
    for file in files:
        if file.path in seen:
            raise _invalid_file_reference(f"files contains duplicate normalized path {file.path!r}")
        seen.add(file.path)
        candidate = normalized_workspace.joinpath(*file.path.split("/"))
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise _invalid_file_reference(f"referenced file does not exist: {file.path}") from exc
        if not resolved.is_relative_to(normalized_workspace):
            raise _invalid_file_reference(
                f"referenced file escapes the Task workspace: {file.path}"
            )
        if not resolved.is_file():
            raise _invalid_file_reference(f"referenced path is not a regular file: {file.path}")
        validated.append(file)
    return tuple(validated)


def validate_workspace(workspace: Path) -> Path:
    """Return one normalized existing workspace or reject it semantically."""

    expanded = workspace.expanduser()
    if not expanded.is_absolute():
        raise _invalid_workspace("workspace must be an absolute path")
    try:
        normalized = expanded.resolve(strict=True)
    except FileNotFoundError as exc:
        raise _invalid_workspace(f"workspace does not exist: {expanded}") from exc
    if not normalized.is_dir():
        raise _invalid_workspace(f"workspace is not a directory: {normalized}")
    return normalized


def _invalid_workspace(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.INVALID_TASK_ROOT,
        summary=summary,
        is_retryable=False,
        suggested_next_step="Provide an existing absolute workspace directory and retry.",
        status_code_override=422,
    )


def _invalid_file_reference(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.INVALID_TASK_PATH,
        summary=summary,
        is_retryable=False,
        suggested_next_step=(
            "Provide a unique workspace-relative path to an existing regular file and retry."
        ),
        status_code_override=422,
    )


__all__ = ["validate_file_references", "validate_workspace"]
