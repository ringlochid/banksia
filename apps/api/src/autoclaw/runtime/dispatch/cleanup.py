from __future__ import annotations

import os
import stat
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import (
    ArtifactPublicationModel,
    DispatchPromptRefsModel,
    DispatchTurnModel,
    TaskModel,
    TransientLocalizationModel,
)
from autoclaw.runtime.node_mcp import DispatchMcpBindingRegistry
from autoclaw.runtime.post_commit.signals import DispatchCleanupRequested
from autoclaw.runtime.startup_audit import (
    StartupAuditPage,
    audit_startup_source_family,
)

DISPATCH_REQUEST_CLEANUP_MINIMUM_AGE = timedelta(hours=24)

_DISPATCH_DIRECTORY_PREFIX = "dispatch."
_STAGING_DIRECTORY_PREFIX = ".dispatch-stage-"
_REQUEST_FILENAMES = frozenset(("instructions.md", "input.md"))

type AsyncSessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type DispatchBindingCleanupHandler = Callable[
    [AsyncSession, DispatchCleanupRequested], Awaitable[None]
]
type _CandidateKind = Literal["final", "staging"]
type _ReferenceState = Literal["referenced", "unreferenced", "task_changed"]


@dataclass(frozen=True, slots=True)
class DispatchRequestCleanupResult:
    """Bounded outcome of one startup request-directory cleanup pass."""

    task_count: int
    entry_count: int
    deleted_candidate_count: int
    deleted_staging_count: int
    young_count: int
    referenced_count: int
    rejected_count: int
    changed_count: int


@dataclass(frozen=True, slots=True)
class _TaskRootSource:
    task_id: str
    task_root_path: str


@dataclass(frozen=True, slots=True)
class _CleanupCandidate:
    name: str
    kind: _CandidateKind
    identity: tuple[int, int]


@dataclass(slots=True)
class _CleanupCounts:
    task_count: int = 0
    entry_count: int = 0
    deleted_candidate_count: int = 0
    deleted_staging_count: int = 0
    young_count: int = 0
    referenced_count: int = 0
    rejected_count: int = 0
    changed_count: int = 0

    def freeze(self) -> DispatchRequestCleanupResult:
        return DispatchRequestCleanupResult(
            task_count=self.task_count,
            entry_count=self.entry_count,
            deleted_candidate_count=self.deleted_candidate_count,
            deleted_staging_count=self.deleted_staging_count,
            young_count=self.young_count,
            referenced_count=self.referenced_count,
            rejected_count=self.rejected_count,
            changed_count=self.changed_count,
        )


def create_dispatch_binding_cleanup_handler(
    binding_registry: DispatchMcpBindingRegistry,
) -> DispatchBindingCleanupHandler:
    """Create exact closed-dispatch cleanup for process-local MCP authority."""

    async def revoke_closed_dispatch_binding(
        session: AsyncSession,
        signal: DispatchCleanupRequested,
    ) -> None:
        status = await session.scalar(
            select(DispatchTurnModel.status).where(
                DispatchTurnModel.dispatch_id == signal.dispatch_id
            )
        )
        if status == "closed":
            binding_registry.revoke_dispatch(signal.dispatch_id)

    return revoke_closed_dispatch_binding


async def cleanup_aged_dispatch_request_directories(
    *,
    session_factory: AsyncSessionContextFactory,
    data_boundary: Path,
    now: datetime,
    minimum_age: timedelta = DISPATCH_REQUEST_CLEANUP_MINIMUM_AGE,
) -> DispatchRequestCleanupResult:
    """Delete only aged, unreferenced request publisher directories at startup.

    This is a finite maintenance pass over controller-owned task roots. It does
    not poll, infer controller truth from the filesystem, or use the exact
    dispatch resource-cleanup signal.
    """

    _validate_cleanup_inputs(data_boundary=data_boundary, now=now, minimum_age=minimum_age)
    _require_safe_directory_operations()
    counts = _CleanupCounts()
    cutoff_timestamp_ns = int((now - minimum_age).timestamp() * 1_000_000_000)

    async def cleanup_task(source: _TaskRootSource) -> None:
        counts.task_count += 1
        await _cleanup_task_dispatch_root(
            session_factory=session_factory,
            source=source,
            data_boundary=data_boundary,
            cutoff_timestamp_ns=cutoff_timestamp_ns,
            counts=counts,
        )

    await audit_startup_source_family(
        family_name="dispatch_request_cleanup",
        fetch_page=lambda cursor, size: _read_task_root_page(
            session_factory,
            cursor,
            size,
        ),
        route_source=cleanup_task,
        cursor_advances=lambda previous, candidate: candidate > previous,
    )
    return counts.freeze()


async def _read_task_root_page(
    session_factory: AsyncSessionContextFactory,
    cursor: str | None,
    page_size: int,
) -> StartupAuditPage[_TaskRootSource, str]:
    async with session_factory() as session:
        statement = (
            select(TaskModel.task_id, TaskModel.task_root_path)
            .order_by(TaskModel.task_id)
            .limit(page_size)
        )
        if cursor is not None:
            statement = statement.where(TaskModel.task_id > cursor)
        rows = tuple((await session.execute(statement)).all())
    sources = tuple(_TaskRootSource(task_id, task_root_path) for task_id, task_root_path in rows)
    return StartupAuditPage(
        sources,
        rows[-1][0] if len(rows) == page_size else None,
    )


async def _cleanup_task_dispatch_root(
    *,
    session_factory: AsyncSessionContextFactory,
    source: _TaskRootSource,
    data_boundary: Path,
    cutoff_timestamp_ns: int,
    counts: _CleanupCounts,
) -> None:
    try:
        dispatch_directory_fd = _open_canonical_dispatch_directory(
            task_root_path=Path(source.task_root_path),
            data_boundary=data_boundary,
        )
    except OSError:
        counts.rejected_count += 1
        return
    if dispatch_directory_fd is None:
        return

    try:
        with os.scandir(dispatch_directory_fd) as entries:
            entry_names = tuple(entry.name for entry in entries)
        for entry_name in entry_names:
            counts.entry_count += 1
            await _cleanup_dispatch_entry(
                session_factory=session_factory,
                source=source,
                dispatch_directory_fd=dispatch_directory_fd,
                entry_name=entry_name,
                cutoff_timestamp_ns=cutoff_timestamp_ns,
                counts=counts,
            )
    finally:
        os.close(dispatch_directory_fd)


async def _cleanup_dispatch_entry(
    *,
    session_factory: AsyncSessionContextFactory,
    source: _TaskRootSource,
    dispatch_directory_fd: int,
    entry_name: str,
    cutoff_timestamp_ns: int,
    counts: _CleanupCounts,
) -> None:
    candidate_kind = _classify_candidate_name(entry_name)
    if candidate_kind is None:
        counts.rejected_count += 1
        return
    candidate = _open_cleanup_candidate(
        dispatch_directory_fd=dispatch_directory_fd,
        entry_name=entry_name,
        kind=candidate_kind,
        cutoff_timestamp_ns=cutoff_timestamp_ns,
        counts=counts,
    )
    if candidate is None:
        return

    candidate_fd, cleanup_candidate = candidate
    try:
        if not _has_safe_candidate_contents(candidate_fd):
            counts.rejected_count += 1
            return
        reference_state = await _read_candidate_reference_state(
            session_factory=session_factory,
            source=source,
            candidate_name=cleanup_candidate.name,
        )
        if reference_state == "referenced":
            counts.referenced_count += 1
            return
        if reference_state == "task_changed":
            counts.changed_count += 1
            return
        if not _delete_unchanged_candidate(
            dispatch_directory_fd=dispatch_directory_fd,
            candidate_fd=candidate_fd,
            candidate=cleanup_candidate,
            cutoff_timestamp_ns=cutoff_timestamp_ns,
        ):
            counts.changed_count += 1
            return
    except OSError:
        counts.rejected_count += 1
        return
    finally:
        os.close(candidate_fd)

    if cleanup_candidate.kind == "staging":
        counts.deleted_staging_count += 1
    else:
        counts.deleted_candidate_count += 1


def _open_cleanup_candidate(
    *,
    dispatch_directory_fd: int,
    entry_name: str,
    kind: _CandidateKind,
    cutoff_timestamp_ns: int,
    counts: _CleanupCounts,
) -> tuple[int, _CleanupCandidate] | None:
    try:
        entry_stat = os.stat(
            entry_name,
            dir_fd=dispatch_directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        counts.changed_count += 1
        return None
    if not stat.S_ISDIR(entry_stat.st_mode):
        counts.rejected_count += 1
        return None
    if entry_stat.st_mtime_ns > cutoff_timestamp_ns:
        counts.young_count += 1
        return None

    try:
        candidate_fd = os.open(
            entry_name,
            _directory_open_flags(),
            dir_fd=dispatch_directory_fd,
        )
    except FileNotFoundError:
        counts.changed_count += 1
        return None
    opened_stat = os.fstat(candidate_fd)
    if not os.path.samestat(entry_stat, opened_stat):
        os.close(candidate_fd)
        counts.changed_count += 1
        return None
    return candidate_fd, _CleanupCandidate(
        name=entry_name,
        kind=kind,
        identity=(entry_stat.st_dev, entry_stat.st_ino),
    )


async def _read_candidate_reference_state(
    *,
    session_factory: AsyncSessionContextFactory,
    source: _TaskRootSource,
    candidate_name: str,
) -> _ReferenceState:
    logical_prefix = f"_runtime/dispatch/{candidate_name}/"
    async with session_factory() as session:
        task_is_current = await session.scalar(
            select(
                exists().where(
                    TaskModel.task_id == source.task_id,
                    TaskModel.task_root_path == source.task_root_path,
                )
            )
        )
        if not task_is_current:
            return "task_changed"

        references = (
            await session.execute(
                select(
                    exists().where(
                        DispatchTurnModel.task_id == source.task_id,
                        DispatchTurnModel.dispatch_id == candidate_name,
                    ),
                    exists().where(
                        DispatchPromptRefsModel.dispatch_id == DispatchTurnModel.dispatch_id,
                        DispatchTurnModel.task_id == source.task_id,
                        or_(
                            DispatchPromptRefsModel.instructions_logical_path.startswith(
                                logical_prefix,
                                autoescape=True,
                            ),
                            DispatchPromptRefsModel.input_logical_path.startswith(
                                logical_prefix,
                                autoescape=True,
                            ),
                        ),
                    ),
                    exists().where(
                        ArtifactPublicationModel.task_id == source.task_id,
                        ArtifactPublicationModel.logical_path.startswith(
                            logical_prefix,
                            autoescape=True,
                        ),
                    ),
                    exists().where(
                        TransientLocalizationModel.task_id == source.task_id,
                        or_(
                            TransientLocalizationModel.source_logical_path.startswith(
                                logical_prefix,
                                autoescape=True,
                            ),
                            TransientLocalizationModel.localized_logical_path.startswith(
                                logical_prefix,
                                autoescape=True,
                            ),
                        ),
                    ),
                )
            )
        ).one()
    return "referenced" if any(references) else "unreferenced"


def _delete_unchanged_candidate(
    *,
    dispatch_directory_fd: int,
    candidate_fd: int,
    candidate: _CleanupCandidate,
    cutoff_timestamp_ns: int,
) -> bool:
    current_stat = os.stat(
        candidate.name,
        dir_fd=dispatch_directory_fd,
        follow_symlinks=False,
    )
    if (
        (current_stat.st_dev, current_stat.st_ino) != candidate.identity
        or current_stat.st_mtime_ns > cutoff_timestamp_ns
        or not _has_safe_candidate_contents(candidate_fd)
    ):
        return False

    with os.scandir(candidate_fd) as entries:
        filenames = tuple(entry.name for entry in entries)
    for filename in filenames:
        os.unlink(filename, dir_fd=candidate_fd)
    with os.scandir(candidate_fd) as remaining_entries:
        if next(remaining_entries, None) is not None:
            return False
    os.rmdir(candidate.name, dir_fd=dispatch_directory_fd)
    os.fsync(dispatch_directory_fd)
    return True


def _has_safe_candidate_contents(candidate_fd: int) -> bool:
    with os.scandir(candidate_fd) as entries:
        for entry in entries:
            if entry.name not in _REQUEST_FILENAMES:
                return False
            entry_stat = os.stat(
                entry.name,
                dir_fd=candidate_fd,
                follow_symlinks=False,
            )
            if not stat.S_ISREG(entry_stat.st_mode):
                return False
    return True


def _classify_candidate_name(entry_name: str) -> _CandidateKind | None:
    if entry_name.startswith(_STAGING_DIRECTORY_PREFIX):
        suffix = entry_name.removeprefix(_STAGING_DIRECTORY_PREFIX)
        return "staging" if suffix and _is_safe_path_segment(entry_name) else None
    if entry_name.startswith(_DISPATCH_DIRECTORY_PREFIX) and _is_safe_path_segment(entry_name):
        return "final"
    return None


def _is_safe_path_segment(value: str) -> bool:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return bool(
        value
        and len(encoded) <= 255
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
    )


def _open_canonical_dispatch_directory(
    *,
    task_root_path: Path,
    data_boundary: Path,
) -> int | None:
    if not task_root_path.is_absolute() or not data_boundary.is_absolute():
        raise ValueError("cleanup task and data roots must be absolute")
    lexical_boundary = Path(os.path.normpath(data_boundary))
    lexical_task_root = Path(os.path.normpath(task_root_path))
    if lexical_task_root == lexical_boundary or not lexical_task_root.is_relative_to(
        lexical_boundary
    ):
        raise ValueError("controller task root escapes the configured data boundary")

    relative_parts = lexical_task_root.relative_to(lexical_boundary).parts
    current_fd = os.open(lexical_boundary, _directory_open_flags())
    try:
        for component in (*relative_parts, "_runtime", "dispatch"):
            try:
                next_fd = os.open(component, _directory_open_flags(), dir_fd=current_fd)
            except FileNotFoundError:
                os.close(current_fd)
                return None
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _validate_cleanup_inputs(
    *,
    data_boundary: Path,
    now: datetime,
    minimum_age: timedelta,
) -> None:
    if not data_boundary.is_absolute():
        raise ValueError("data_boundary must be absolute")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if minimum_age < DISPATCH_REQUEST_CLEANUP_MINIMUM_AGE:
        raise ValueError("dispatch request cleanup must retain candidates for at least 24 hours")


def _directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _require_safe_directory_operations() -> None:
    required_attributes = ("O_DIRECTORY", "O_NOFOLLOW")
    required_dir_fd_functions = (os.open, os.stat, os.unlink, os.rmdir)
    if (
        any(not hasattr(os, attribute) for attribute in required_attributes)
        or any(function not in os.supports_dir_fd for function in required_dir_fd_functions)
        or os.stat not in os.supports_follow_symlinks
        or os.scandir not in os.supports_fd
    ):
        raise RuntimeError("safe dispatch request cleanup is unavailable on this platform")


__all__ = [
    "DISPATCH_REQUEST_CLEANUP_MINIMUM_AGE",
    "DispatchBindingCleanupHandler",
    "DispatchRequestCleanupResult",
    "cleanup_aged_dispatch_request_directories",
    "create_dispatch_binding_cleanup_handler",
]
