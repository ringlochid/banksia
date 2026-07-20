from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


class UnsafeTaskRootError(ValueError):
    """Raised when reset cannot prove a task root is safe to delete."""


@dataclass(frozen=True, slots=True)
class _DeletionRootCandidate:
    path: Path
    relative_parts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ValidatedDeletionRoot:
    candidate: _DeletionRootCandidate
    identity: tuple[int, int] | None


def delete_controller_task_roots(
    task_root_paths: Iterable[str],
    *,
    data_boundary: Path,
) -> tuple[Path, ...]:
    """Delete controller task roots without traversing symlinks."""

    candidates = _deletion_root_candidates(
        task_root_paths,
        data_boundary=data_boundary,
    )
    if not candidates:
        return ()
    _require_symlink_safe_deletion_support()

    resolved_boundary = data_boundary.expanduser().resolve(strict=False)
    boundary_fd = _open_data_boundary(resolved_boundary)
    if boundary_fd is None:
        return ()
    try:
        deletion_roots = tuple(
            _validate_deletion_root(boundary_fd, candidate) for candidate in candidates
        )
        deleted_roots: list[Path] = []
        for deletion_root in deletion_roots:
            if _delete_validated_root(boundary_fd, deletion_root):
                deleted_roots.append(deletion_root.candidate.path)
        return tuple(deleted_roots)
    finally:
        os.close(boundary_fd)


def _deletion_root_candidates(
    task_root_paths: Iterable[str],
    *,
    data_boundary: Path,
) -> tuple[_DeletionRootCandidate, ...]:
    resolved_boundary = data_boundary.expanduser().resolve(strict=False)
    candidates_by_path: dict[Path, _DeletionRootCandidate] = {}

    for raw_task_root in task_root_paths:
        deletion_root = Path(raw_task_root).expanduser()
        if not deletion_root.is_absolute():
            raise UnsafeTaskRootError(f"controller task root must be absolute: {raw_task_root}")
        normalized_root = Path(os.path.normpath(deletion_root))
        if normalized_root == resolved_boundary or not normalized_root.is_relative_to(
            resolved_boundary
        ):
            raise UnsafeTaskRootError(
                "controller task root escapes the configured AutoClaw data boundary: "
                f"{deletion_root}"
            )
        candidates_by_path.setdefault(
            normalized_root,
            _DeletionRootCandidate(
                path=normalized_root,
                relative_parts=normalized_root.relative_to(resolved_boundary).parts,
            ),
        )

    return tuple(
        sorted(
            candidates_by_path.values(),
            key=lambda candidate: (len(candidate.relative_parts), str(candidate.path)),
            reverse=True,
        )
    )


def _validate_deletion_root(
    boundary_fd: int,
    candidate: _DeletionRootCandidate,
) -> _ValidatedDeletionRoot:
    parent_fd = _open_candidate_parent(boundary_fd, candidate)
    if parent_fd is None:
        return _ValidatedDeletionRoot(candidate=candidate, identity=None)
    try:
        root_stat = _entry_stat(parent_fd, candidate.relative_parts[-1])
        if root_stat is None:
            return _ValidatedDeletionRoot(candidate=candidate, identity=None)
        _require_directory_entry(root_stat, candidate.path, is_root=True)
        root_fd = _open_verified_directory(
            parent_fd,
            candidate.relative_parts[-1],
            root_stat,
            candidate.path,
        )
        os.close(root_fd)
        return _ValidatedDeletionRoot(
            candidate=candidate,
            identity=_file_identity(root_stat),
        )
    finally:
        os.close(parent_fd)


def _delete_validated_root(
    boundary_fd: int,
    deletion_root: _ValidatedDeletionRoot,
) -> bool:
    expected_identity = deletion_root.identity
    if expected_identity is None:
        return False

    candidate = deletion_root.candidate
    parent_fd = _open_candidate_parent(boundary_fd, candidate)
    if parent_fd is None:
        return False
    try:
        root_name = candidate.relative_parts[-1]
        root_stat = _entry_stat(parent_fd, root_name)
        if root_stat is None:
            return False
        _require_directory_entry(root_stat, candidate.path, is_root=True)
        _require_expected_identity(root_stat, expected_identity, candidate.path)
        root_fd = _open_verified_directory(
            parent_fd,
            root_name,
            root_stat,
            candidate.path,
        )
        try:
            _clear_pinned_directory(root_fd, candidate.path)
            current_stat = _entry_stat(parent_fd, root_name)
            if current_stat is None:
                raise UnsafeTaskRootError(
                    f"controller task root changed during deletion: {candidate.path}"
                )
            _require_directory_entry(current_stat, candidate.path, is_root=True)
            _require_expected_identity(current_stat, expected_identity, candidate.path)
            os.rmdir(root_name, dir_fd=parent_fd)
        finally:
            os.close(root_fd)
        return True
    finally:
        os.close(parent_fd)


def _open_candidate_parent(
    boundary_fd: int,
    candidate: _DeletionRootCandidate,
) -> int | None:
    current_fd = os.dup(boundary_fd)
    try:
        for index, component in enumerate(candidate.relative_parts[:-1], start=1):
            component_path = candidate.path.parents[len(candidate.relative_parts) - index - 1]
            component_stat = _entry_stat(current_fd, component)
            if component_stat is None:
                os.close(current_fd)
                return None
            _require_directory_entry(component_stat, component_path, is_root=False)
            next_fd = _open_verified_directory(
                current_fd,
                component,
                component_stat,
                component_path,
            )
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _clear_pinned_directory(directory_fd: int, display_path: Path) -> None:
    with os.scandir(directory_fd) as entries:
        children = list(entries)
    for child in children:
        child_path = display_path / child.name
        try:
            is_directory = child.is_dir(follow_symlinks=False)
        except OSError as exc:
            raise UnsafeTaskRootError(
                f"cannot safely inspect controller task-root entry: {child_path}"
            ) from exc
        if is_directory:
            shutil.rmtree(child.name, dir_fd=directory_fd)
        else:
            os.unlink(child.name, dir_fd=directory_fd)


def _open_data_boundary(resolved_boundary: Path) -> int | None:
    try:
        return os.open(resolved_boundary, _directory_open_flags())
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise UnsafeTaskRootError(
            f"cannot safely open the AutoClaw data boundary: {resolved_boundary}"
        ) from exc


def _open_verified_directory(
    parent_fd: int,
    name: str,
    expected_stat: os.stat_result,
    display_path: Path,
) -> int:
    try:
        directory_fd = os.open(name, _directory_open_flags(), dir_fd=parent_fd)
    except OSError as exc:
        raise UnsafeTaskRootError(
            f"controller task-root component changed during safety validation: {display_path}"
        ) from exc
    if os.path.samestat(expected_stat, os.fstat(directory_fd)):
        return directory_fd
    os.close(directory_fd)
    raise UnsafeTaskRootError(
        f"controller task-root component changed during safety validation: {display_path}"
    )


def _entry_stat(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _require_directory_entry(
    entry_stat: os.stat_result,
    display_path: Path,
    *,
    is_root: bool,
) -> None:
    if stat.S_ISLNK(entry_stat.st_mode):
        if is_root:
            raise UnsafeTaskRootError(
                f"refusing to delete symlinked controller task root: {display_path}"
            )
        raise UnsafeTaskRootError(
            f"refusing to traverse symlinked controller task-root ancestor: {display_path}"
        )
    if stat.S_ISDIR(entry_stat.st_mode):
        return
    if is_root:
        raise UnsafeTaskRootError(f"controller task root is not a directory: {display_path}")
    raise UnsafeTaskRootError(f"controller task-root ancestor is not a directory: {display_path}")


def _require_expected_identity(
    entry_stat: os.stat_result,
    expected_identity: tuple[int, int],
    display_path: Path,
) -> None:
    if _file_identity(entry_stat) != expected_identity:
        raise UnsafeTaskRootError(
            f"controller task root changed after safety validation: {display_path}"
        )


def _file_identity(entry_stat: os.stat_result) -> tuple[int, int]:
    return entry_stat.st_dev, entry_stat.st_ino


def _directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _require_symlink_safe_deletion_support() -> None:
    required_attributes = ("O_DIRECTORY", "O_NOFOLLOW")
    required_dir_fd_functions = (os.open, os.stat, os.unlink, os.rmdir)
    if (
        not shutil.rmtree.avoids_symlink_attacks
        or any(not hasattr(os, attribute) for attribute in required_attributes)
        or any(function not in os.supports_dir_fd for function in required_dir_fd_functions)
        or os.stat not in os.supports_follow_symlinks
        or os.scandir not in os.supports_fd
    ):
        raise UnsafeTaskRootError(
            "safe controller task-root deletion is unsupported on this platform"
        )


__all__ = ["UnsafeTaskRootError", "delete_controller_task_roots"]
