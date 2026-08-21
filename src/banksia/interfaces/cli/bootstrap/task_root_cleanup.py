from __future__ import annotations

import errno
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from banksia.platform.workspace_files import (
    DirectoryLease,
    PrivatePathError,
    select_workspace_file_operations,
)


class UnsafeTaskRootError(ValueError):
    """Raised when reset cannot prove a task root is safe to delete."""


@dataclass(frozen=True, slots=True)
class _DeletionRootCandidate:
    path: Path
    relative_parts: tuple[str, ...]


@dataclass(slots=True)
class _RetainedDeletionRoot:
    candidate: _DeletionRootCandidate
    parent: DirectoryLease | None = None
    root: DirectoryLease | None = None
    is_parent_owned: bool = True

    def close(self) -> None:
        if self.root is not None:
            self.root.close()
            self.root = None
        if self.parent is not None and self.is_parent_owned:
            self.parent.close()
        self.parent = None


def delete_controller_task_roots(
    task_root_paths: Iterable[str],
    *,
    data_boundary: Path,
) -> tuple[Path, ...]:
    """Delete controller roots through the selected retained native filesystem owner."""

    candidates = _deletion_root_candidates(task_root_paths, data_boundary=data_boundary)
    if not candidates:
        return ()
    operations = select_workspace_file_operations()
    try:
        boundary = operations.open_workspace(data_boundary.expanduser().absolute())
    except FileNotFoundError:
        return ()

    retained: list[_RetainedDeletionRoot] = []
    try:
        for candidate in candidates:
            retained.append(_retain_deletion_root(boundary, candidate))
        deleted: list[Path] = []
        for deletion_root in retained:
            if deletion_root.parent is None or deletion_root.root is None:
                continue
            try:
                was_deleted = operations.remove_retained_tree(
                    deletion_root.parent,
                    deletion_root.candidate.relative_parts[-1],
                    deletion_root.root,
                )
            except OSError as exc:
                raise _unsafe_root_error(
                    deletion_root.candidate.path,
                    exc,
                    is_root=True,
                ) from exc
            if was_deleted:
                deleted.append(deletion_root.candidate.path)
        return tuple(deleted)
    finally:
        for deletion_root in reversed(retained):
            deletion_root.close()
        boundary.close()


def _retain_deletion_root(
    boundary: DirectoryLease,
    candidate: _DeletionRootCandidate,
) -> _RetainedDeletionRoot:
    operations = select_workspace_file_operations()
    try:
        parent = _open_directory_chain(boundary, candidate.relative_parts[:-1])
    except OSError as exc:
        raise _unsafe_root_error(candidate.path, exc, is_root=False) from exc
    if parent is None:
        return _RetainedDeletionRoot(candidate)
    is_parent_owned = bool(candidate.relative_parts[:-1])
    try:
        try:
            root = operations.open_child_directory(
                parent,
                candidate.relative_parts[-1],
                should_require_private=False,
            )
        except FileNotFoundError:
            if is_parent_owned:
                parent.close()
            return _RetainedDeletionRoot(candidate)
        return _RetainedDeletionRoot(
            candidate,
            parent=parent,
            root=root,
            is_parent_owned=is_parent_owned,
        )
    except OSError as exc:
        if is_parent_owned:
            parent.close()
        raise _unsafe_root_error(candidate.path, exc, is_root=True) from exc


def _open_directory_chain(
    boundary: DirectoryLease,
    components: tuple[str, ...],
) -> DirectoryLease | None:
    operations = select_workspace_file_operations()
    if not components:
        return boundary
    current: DirectoryLease | None = None
    try:
        for component in components:
            parent = boundary if current is None else current
            try:
                following = operations.open_child_directory(
                    parent,
                    component,
                    should_require_private=False,
                )
            except FileNotFoundError:
                if current is not None:
                    current.close()
                return None
            if current is not None:
                current.close()
            current = following
        assert current is not None
        return current
    except BaseException:
        if current is not None:
            current.close()
        raise


def _deletion_root_candidates(
    task_root_paths: Iterable[str],
    *,
    data_boundary: Path,
) -> tuple[_DeletionRootCandidate, ...]:
    boundary = Path(os.path.abspath(data_boundary.expanduser()))
    candidates_by_path: dict[Path, _DeletionRootCandidate] = {}
    for raw_task_root in task_root_paths:
        deletion_root = Path(raw_task_root).expanduser()
        if not deletion_root.is_absolute():
            raise UnsafeTaskRootError(f"controller task root must be absolute: {raw_task_root}")
        normalized_root = Path(os.path.abspath(deletion_root))
        if normalized_root == boundary or not normalized_root.is_relative_to(boundary):
            raise UnsafeTaskRootError(
                "controller task root escapes the configured Oh My Subagents data boundary: "
                f"{deletion_root}"
            )
        candidates_by_path.setdefault(
            normalized_root,
            _DeletionRootCandidate(
                path=normalized_root,
                relative_parts=normalized_root.relative_to(boundary).parts,
            ),
        )
    return tuple(
        sorted(
            candidates_by_path.values(),
            key=lambda candidate: (len(candidate.relative_parts), str(candidate.path)),
            reverse=True,
        )
    )


def _unsafe_root_error(
    path: Path,
    exc: OSError,
    *,
    is_root: bool,
) -> UnsafeTaskRootError:
    if exc.errno in {errno.ELOOP, errno.ENOTDIR} or isinstance(exc, PrivatePathError):
        subject = "controller task root" if is_root else "controller task-root ancestor"
        return UnsafeTaskRootError(f"refusing to traverse a linked or replaced {subject}: {path}")
    return UnsafeTaskRootError(f"cannot safely delete controller task root {path}: {exc}")


__all__ = ["UnsafeTaskRootError", "delete_controller_task_roots"]
