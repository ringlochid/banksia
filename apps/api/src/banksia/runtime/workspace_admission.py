from __future__ import annotations

import asyncio
import os
import secrets
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import TaskModel, WorkspaceBindingModel
from banksia.runtime.team import (
    InitialTaskTeam,
    render_current_team_manifest,
    render_initial_team_manifest,
)
from banksia.workflows.catalog import read_published_workflow_revision
from banksia.workflows.contracts import PublishedWorkflowRevision

TASK_ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
TASK_INITIALIZATION_MARKER = ".banksia-initializing"
_MARKER_HEADER = "banksia-task-initialization-v1"


@dataclass(frozen=True, slots=True)
class TaskWorkspaceAdmission:
    task_id: str
    workspace: Path
    task_root: Path
    manifest: Path
    workflow_note: Path | None
    marker: Path


@dataclass(slots=True)
class _WorkspaceAdmissionLock:
    lock: asyncio.Lock
    users: int = 0


class TaskWorkspaceAdmissionCoordinator:
    """Serialize admission recovery and commit for each workspace in one controller."""

    def __init__(self) -> None:
        self._entries_lock = asyncio.Lock()
        self._entries: dict[Path, _WorkspaceAdmissionLock] = {}

    @asynccontextmanager
    async def hold(self, workspace: Path) -> AsyncIterator[None]:
        """Hold one workspace admission lane without blocking unrelated workspaces."""

        entry = await self._register(workspace)
        try:
            async with entry.lock:
                yield
        finally:
            await self._unregister(workspace, entry)

    async def _register(self, workspace: Path) -> _WorkspaceAdmissionLock:
        async with self._entries_lock:
            entry = self._entries.get(workspace)
            if entry is None:
                entry = _WorkspaceAdmissionLock(lock=asyncio.Lock())
                self._entries[workspace] = entry
            entry.users += 1
            return entry

    async def _unregister(
        self,
        workspace: Path,
        entry: _WorkspaceAdmissionLock,
    ) -> None:
        async with self._entries_lock:
            entry.users -= 1
            if entry.users == 0 and self._entries.get(workspace) is entry:
                del self._entries[workspace]


async def allocate_task_id(
    session: AsyncSession,
    *,
    workspace: Path,
) -> str:
    """Allocate a collision-checked 40-bit product Task identifier."""

    task_parent = workspace / ".banksia"
    for _ in range(128):
        candidate = _new_task_id()
        if await session.get(TaskModel, candidate) is not None:
            continue
        if not await asyncio.to_thread(
            os.path.lexists,
            task_parent / candidate,
        ):
            return candidate
    raise RuntimeError("could not allocate a collision-free Task identifier")


def stage_task_workspace(
    *,
    workspace: Path,
    task_id: str,
    workflow_revision: PublishedWorkflowRevision,
    initial_team: InitialTaskTeam,
) -> TaskWorkspaceAdmission:
    """Create one exclusive marked Task directory and its initial projections."""

    banksia_root = workspace / ".banksia"
    banksia_root.mkdir(mode=0o700, exist_ok=True)
    if not banksia_root.is_dir():
        raise NotADirectoryError(f"Banksia workspace path is not a directory: {banksia_root}")

    task_root = banksia_root / task_id
    task_root.mkdir(mode=0o700)
    marker = task_root / TASK_INITIALIZATION_MARKER
    admission = TaskWorkspaceAdmission(
        task_id=task_id,
        workspace=workspace,
        task_root=task_root,
        manifest=task_root / "manifest.md",
        workflow_note=(
            task_root / "workflow-note.md" if workflow_revision.workflow.note is not None else None
        ),
        marker=marker,
    )
    marker_written = False
    try:
        _write_new_text(marker, _marker_body(task_id))
        marker_written = True
        (task_root / "notes").mkdir(mode=0o700)
        (task_root / "artifacts").mkdir(mode=0o700)
        (task_root / "command-runs").mkdir(mode=0o700)
        _write_new_text(
            admission.manifest,
            render_initial_team_manifest(
                task_id=task_id,
                workflow_revision=workflow_revision,
                initial_team=initial_team,
            ),
        )
        if admission.workflow_note is not None:
            assert workflow_revision.workflow.note is not None
            _write_new_text(admission.workflow_note, workflow_revision.workflow.note)
    except BaseException:
        if marker_written:
            cleanup_marked_task_workspace(admission)
        else:
            shutil.rmtree(task_root)
        raise
    return admission


def accept_task_workspace(admission: TaskWorkspaceAdmission) -> None:
    """Clear the initialization marker after the Task transaction commits."""

    if admission.marker.read_text(encoding="utf-8") != _marker_body(admission.task_id):
        raise RuntimeError("Task initialization marker changed before acceptance")
    admission.marker.unlink()


def cleanup_marked_task_workspace(admission: TaskWorkspaceAdmission) -> bool:
    """Remove only the exact marked directory owned by this failed admission."""

    return _remove_marked_directory(admission.task_root, task_id=admission.task_id)


async def recover_task_workspace_admissions(
    session: AsyncSession,
    *,
    workspaces: tuple[Path, ...] = (),
) -> tuple[Path, ...]:
    """Repair committed markers and remove only uncommitted marked directories."""

    rows = tuple(
        (
            await session.execute(
                select(
                    TaskModel.task_id,
                    TaskModel.task_root_path,
                    TaskModel.workflow_key,
                    TaskModel.workflow_revision_no,
                    TaskModel.workflow_content_hash,
                    WorkspaceBindingModel.normalized_root_path,
                ).join(
                    WorkspaceBindingModel,
                    WorkspaceBindingModel.task_id == TaskModel.task_id,
                )
            )
        ).all()
    )
    committed = {
        task_id: (
            Path(task_root_path),
            workflow_key,
            workflow_revision_no,
            workflow_content_hash,
        )
        for (
            task_id,
            task_root_path,
            workflow_key,
            workflow_revision_no,
            workflow_content_hash,
            _workspace,
        ) in rows
    }
    roots = await asyncio.to_thread(
        _normalized_workspace_roots,
        workspaces,
        tuple(workspace for *_, workspace in rows),
    )

    recovered: list[Path] = []
    for workspace in sorted(roots, key=str):
        banksia_root = workspace / ".banksia"
        if not banksia_root.is_dir():
            continue
        for task_root in banksia_root.iterdir():
            task_id = task_root.name
            if not _is_task_id(task_id) or not task_root.is_dir():
                continue
            marker = task_root / TASK_INITIALIZATION_MARKER
            if not marker.is_file():
                continue
            if marker.read_text(encoding="utf-8") != _marker_body(task_id):
                continue
            committed_row = committed.get(task_id)
            if committed_row is None or committed_row[0] != task_root:
                if _remove_marked_directory(task_root, task_id=task_id):
                    recovered.append(task_root)
                continue
            await _repair_committed_task_workspace(
                session,
                task_root=task_root,
                task_id=task_id,
                workflow_key=committed_row[1],
                workflow_revision_no=committed_row[2],
                workflow_content_hash=committed_row[3],
            )
            marker.unlink()
            recovered.append(task_root)
    return tuple(recovered)


async def _repair_committed_task_workspace(
    session: AsyncSession,
    *,
    task_root: Path,
    task_id: str,
    workflow_key: str,
    workflow_revision_no: int,
    workflow_content_hash: str,
) -> None:
    revision = await read_published_workflow_revision(
        session,
        workflow_id=workflow_key,
        revision_no=workflow_revision_no,
    )
    if revision.content_hash != workflow_content_hash:
        raise RuntimeError(f"Task {task_id!r} has an inconsistent Workflow pin")
    for name in ("notes", "artifacts", "command-runs"):
        (task_root / name).mkdir(mode=0o700, exist_ok=True)
    manifest = task_root / "manifest.md"
    _replace_manifest(
        manifest,
        await render_current_team_manifest(session, task_id=task_id),
    )
    note = revision.workflow.note
    note_path = task_root / "workflow-note.md"
    if note is not None and not note_path.is_file():
        _write_new_text(note_path, note)


def _new_task_id() -> str:
    value = int.from_bytes(secrets.token_bytes(5), "big")
    encoded = "".join(TASK_ID_ALPHABET[(value >> shift) & 0x1F] for shift in range(35, -1, -5))
    return f"t_{encoded}"


def _is_task_id(value: str) -> bool:
    return (
        len(value) == 10
        and value.startswith("t_")
        and all(character in TASK_ID_ALPHABET for character in value[2:])
    )


def _marker_body(task_id: str) -> str:
    return f"{_MARKER_HEADER}\n{task_id}\n"


def _write_new_text(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_manifest(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.repair")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _remove_marked_directory(task_root: Path, *, task_id: str) -> bool:
    marker = task_root / TASK_INITIALIZATION_MARKER
    try:
        body = marker.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, UnicodeError):
        return False
    if body != _marker_body(task_id):
        return False
    with suppress(FileNotFoundError):
        shutil.rmtree(task_root)
    return True


def _normalized_workspace_roots(
    configured: tuple[Path, ...],
    committed: tuple[str, ...],
) -> set[Path]:
    roots = {workspace.expanduser().resolve(strict=False) for workspace in configured}
    roots.update(Path(workspace).expanduser().resolve(strict=False) for workspace in committed)
    return roots


__all__ = [
    "TASK_ID_ALPHABET",
    "TASK_INITIALIZATION_MARKER",
    "TaskWorkspaceAdmission",
    "TaskWorkspaceAdmissionCoordinator",
    "accept_task_workspace",
    "allocate_task_id",
    "cleanup_marked_task_workspace",
    "recover_task_workspace_admissions",
    "stage_task_workspace",
]
