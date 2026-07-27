from __future__ import annotations

import errno
import os
from pathlib import Path

from banksia.runtime.contracts import FileReference
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.workspace.regular_files import validate_workspace_regular_file
from banksia.runtime.workspace.storage import capture_workspace_identity


def validate_file_references(
    workspace: Path,
    files: tuple[FileReference, ...],
) -> tuple[FileReference, ...]:
    """Validate ordered loose-file navigation values at their owning boundary."""

    if not workspace.is_absolute():
        raise _invalid_workspace("workspace must be an absolute path")
    seen: set[str] = set()
    validated: list[FileReference] = []
    for file in files:
        if file.path in seen:
            raise _invalid_file_reference(f"files contains duplicate normalized path {file.path!r}")
        seen.add(file.path)
        try:
            validate_workspace_regular_file(workspace, file.path)
        except FileNotFoundError as exc:
            raise _invalid_file_reference(f"referenced file does not exist: {file.path}") from exc
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _invalid_file_reference(
                    f"referenced path contains a symbolic link: {file.path}"
                ) from exc
            raise _invalid_file_reference(
                f"referenced path is not a regular file: {file.path}"
            ) from exc
        validated.append(file)
    return tuple(validated)


def validate_workspace(workspace: Path) -> Path:
    """Return one normalized existing workspace or reject it semantically."""

    expanded = workspace.expanduser()
    if not expanded.is_absolute():
        raise _invalid_workspace("workspace must be an absolute path")
    normalized = Path(os.path.abspath(os.fspath(expanded)))
    try:
        capture_workspace_identity(normalized)
    except FileNotFoundError as exc:
        raise _invalid_workspace(f"workspace does not exist: {normalized}") from exc
    except OSError as exc:
        raise _invalid_workspace(f"workspace is not a safe real directory: {normalized}") from exc
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
