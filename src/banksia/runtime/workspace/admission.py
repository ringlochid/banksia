from __future__ import annotations

import asyncio
import logging
import os
import secrets
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    AttemptModel,
    DispatchTurnModel,
    TaskModel,
    WorkspaceBindingModel,
)
from banksia.platform.workspace_files import DirectoryLease
from banksia.runtime.post_commit import DispatchStartDue
from banksia.runtime.team import (
    InitialTaskTeam,
    render_current_team_manifest,
    render_initial_team_manifest,
)
from banksia.runtime.team.currentness import dispatch_team_selection_is_current
from banksia.runtime.workspace.storage import (
    WorkspaceIdentity,
    capture_workspace_identity,
    ensure_directory,
    is_real_directory,
    open_banksia_root,
    open_task_root,
    read_small_text,
    remove_task_tree,
    replace_text,
    reserve_task_root,
    task_root_names,
    unlink_entry,
    write_new_text,
)
from banksia.workflows.catalog import read_published_workflow_revision
from banksia.workflows.contracts import PublishedWorkflowRevision

TASK_ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
TASK_INITIALIZATION_MARKER = ".banksia-initializing"
_MARKER_HEADER = "banksia-task-initialization-v1"

logger = logging.getLogger(__name__)

type RecoveredProviderStartPublisher = Callable[[DispatchStartDue], bool]


@dataclass(frozen=True, slots=True)
class TaskWorkspaceAdmission:
    task_id: str
    workspace: Path
    task_root: Path
    manifest: Path
    workflow_note: Path | None
    marker: Path
    workspace_identity: WorkspaceIdentity


@dataclass(frozen=True, slots=True)
class _CommittedTaskWorkspace:
    task_root: Path
    workflow_key: str
    workflow_revision_no: int
    workflow_content_hash: str


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
    workspace_identity: WorkspaceIdentity | None = None,
) -> TaskWorkspaceAdmission:
    """Create one exclusive marked Task directory and its initial projections."""

    if workspace_identity is None:
        workspace_identity = capture_workspace_identity(workspace)
    banksia_path = workspace / ".banksia"
    task_path = banksia_path / task_id
    marker = task_path / TASK_INITIALIZATION_MARKER
    admission = TaskWorkspaceAdmission(
        task_id=task_id,
        workspace=workspace,
        task_root=task_path,
        manifest=task_path / "manifest.md",
        workflow_note=(
            task_path / "workflow-note.md" if workflow_revision.workflow.note is not None else None
        ),
        marker=marker,
        workspace_identity=workspace_identity,
    )
    marker_written = False
    with reserve_task_root(
        workspace,
        task_id,
        expected_workspace_identity=workspace_identity,
    ) as (banksia_root, task_root):
        try:
            write_new_text(
                task_root,
                TASK_INITIALIZATION_MARKER,
                _marker_body(task_id),
            )
            marker_written = True
            for name in ("notes", "artifacts", "command-runs"):
                ensure_directory(task_root, name)
            write_new_text(
                task_root,
                "manifest.md",
                render_initial_team_manifest(
                    task_id=task_id,
                    workflow_revision=workflow_revision,
                    initial_team=initial_team,
                ),
            )
            if admission.workflow_note is not None:
                assert workflow_revision.workflow.note is not None
                write_new_text(
                    task_root,
                    "workflow-note.md",
                    workflow_revision.workflow.note,
                )
        except BaseException:
            if not marker_written or read_small_text(
                task_root,
                TASK_INITIALIZATION_MARKER,
            ) == _marker_body(task_id):
                remove_task_tree(banksia_root, task_id, task_root)
            raise
    return admission


def accept_task_workspace(admission: TaskWorkspaceAdmission) -> None:
    """Clear the initialization marker after the Task transaction commits."""

    with open_banksia_root(
        admission.workspace,
        should_create=False,
        expected_workspace_identity=admission.workspace_identity,
    ) as banksia_root:
        if banksia_root is None:
            raise RuntimeError("Task workspace disappeared before acceptance")
        with open_task_root(banksia_root, admission.task_id) as task_root:
            if read_small_text(
                task_root,
                TASK_INITIALIZATION_MARKER,
            ) != _marker_body(admission.task_id):
                raise RuntimeError("Task initialization marker changed before acceptance")
            unlink_entry(task_root, TASK_INITIALIZATION_MARKER)


def cleanup_marked_task_workspace(admission: TaskWorkspaceAdmission) -> bool:
    """Remove only the exact marked directory owned by this failed admission."""

    return _remove_marked_directory(
        admission.workspace,
        task_id=admission.task_id,
        workspace_identity=admission.workspace_identity,
    )


async def recover_task_workspace_admissions(
    session: AsyncSession,
    *,
    workspaces: tuple[Path, ...] = (),
    expected_workspace_identities: Mapping[Path, WorkspaceIdentity] | None = None,
    publish_recovered_provider_start: RecoveredProviderStartPublisher | None = None,
) -> tuple[Path, ...]:
    """Repair committed markers and remove only uncommitted marked directories."""

    committed, bound_workspaces = await _read_committed_task_workspaces(session)
    roots = await asyncio.to_thread(
        _normalized_workspace_roots,
        workspaces,
        bound_workspaces,
    )

    recovered: list[Path] = []
    for workspace in sorted(roots, key=str):
        expected_identity = (
            expected_workspace_identities.get(workspace)
            if expected_workspace_identities is not None
            else None
        )
        with open_banksia_root(
            workspace,
            should_create=False,
            expected_workspace_identity=expected_identity,
        ) as banksia_root:
            if banksia_root is None:
                continue
            for task_id in task_root_names(banksia_root):
                if not _is_task_id(task_id) or not is_real_directory(
                    banksia_root,
                    task_id,
                ):
                    continue
                with open_task_root(banksia_root, task_id) as task_root_authority:
                    if read_small_text(
                        task_root_authority,
                        TASK_INITIALIZATION_MARKER,
                    ) != _marker_body(task_id):
                        continue
                    task_root = workspace / ".banksia" / task_id
                    committed_row = committed.get(task_id)
                    if committed_row is None or committed_row.task_root != task_root:
                        should_remove = True
                    else:
                        should_remove = False
                        await _repair_committed_task_workspace(
                            session,
                            task_root=task_root_authority,
                            task_id=task_id,
                            workflow_key=committed_row.workflow_key,
                            workflow_revision_no=committed_row.workflow_revision_no,
                            workflow_content_hash=committed_row.workflow_content_hash,
                        )
                        provider_start = await _read_recovered_provider_start(
                            session,
                            task_id=task_id,
                        )
                        unlink_entry(task_root_authority, TASK_INITIALIZATION_MARKER)
                        if (
                            provider_start is not None
                            and publish_recovered_provider_start is not None
                        ):
                            await session.rollback()
                            _publish_recovered_provider_start(
                                provider_start,
                                publish=publish_recovered_provider_start,
                            )
                    if should_remove and remove_task_tree(
                        banksia_root,
                        task_id,
                        task_root_authority,
                    ):
                        recovered.append(task_root)
                if not should_remove:
                    recovered.append(task_root)
    return tuple(recovered)


async def _read_committed_task_workspaces(
    session: AsyncSession,
) -> tuple[dict[str, _CommittedTaskWorkspace], tuple[str, ...]]:
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
        task_id: _CommittedTaskWorkspace(
            task_root=Path(task_root_path),
            workflow_key=workflow_key,
            workflow_revision_no=workflow_revision_no,
            workflow_content_hash=workflow_content_hash,
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
    return committed, tuple(workspace for *_, workspace in rows)


async def _repair_committed_task_workspace(
    session: AsyncSession,
    *,
    task_root: DirectoryLease,
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
        ensure_directory(task_root, name)
    replace_text(
        task_root,
        "manifest.md",
        await render_current_team_manifest(session, task_id=task_id),
    )
    note = revision.workflow.note
    if note is not None:
        replace_text(task_root, "workflow-note.md", note)
        return
    try:
        unlink_entry(task_root, "workflow-note.md")
    except FileNotFoundError:
        pass


async def _read_recovered_provider_start(
    session: AsyncSession,
    *,
    task_id: str,
) -> DispatchStartDue | None:
    row = (
        await session.execute(
            select(
                DispatchTurnModel.dispatch_id,
                DispatchTurnModel.provider_start_revision,
                DispatchTurnModel.next_provider_start_at,
            )
            .join(
                AttemptModel,
                (AttemptModel.task_id == DispatchTurnModel.task_id)
                & (AttemptModel.assignment_id == DispatchTurnModel.assignment_id)
                & (AttemptModel.attempt_id == DispatchTurnModel.attempt_id)
                & (AttemptModel.current_dispatch_id == DispatchTurnModel.dispatch_id),
            )
            .join(TaskModel, TaskModel.task_id == DispatchTurnModel.task_id)
            .where(
                DispatchTurnModel.task_id == task_id,
                DispatchTurnModel.status == "starting",
                AttemptModel.status == "running",
                AttemptModel.current_wait_id.is_(None),
                TaskModel.status == "running",
                dispatch_team_selection_is_current(),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    dispatch_id, provider_start_revision, due_at = row
    if due_at is None:
        raise RuntimeError(f"committed Task {task_id!r} has a starting Dispatch without a due time")
    return DispatchStartDue(
        dispatch_id=dispatch_id,
        provider_start_revision=provider_start_revision,
        due_at=due_at,
    )


def _publish_recovered_provider_start(
    signal: DispatchStartDue,
    *,
    publish: RecoveredProviderStartPublisher,
) -> None:
    try:
        is_published = publish(signal)
    except Exception:
        logger.exception(
            "failed to publish recovered Task provider-start hint",
            extra={"dispatch_id": signal.dispatch_id},
        )
        return
    if not is_published:
        logger.warning(
            "recovered Task provider-start hint was not accepted",
            extra={"dispatch_id": signal.dispatch_id},
        )


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


def _remove_marked_directory(
    workspace: Path,
    *,
    task_id: str,
    workspace_identity: WorkspaceIdentity | None = None,
) -> bool:
    with open_banksia_root(
        workspace,
        should_create=False,
        expected_workspace_identity=workspace_identity,
    ) as banksia_root:
        if banksia_root is None or not is_real_directory(
            banksia_root,
            task_id,
        ):
            return False
        try:
            with open_task_root(banksia_root, task_id) as task_root:
                if read_small_text(
                    task_root,
                    TASK_INITIALIZATION_MARKER,
                ) != _marker_body(task_id):
                    return False
                return remove_task_tree(banksia_root, task_id, task_root)
        except OSError:
            return False


def _normalized_workspace_roots(
    configured: tuple[Path, ...],
    committed: tuple[str, ...],
) -> set[Path]:
    roots = {Path(os.path.abspath(os.fspath(workspace.expanduser()))) for workspace in configured}
    roots.update(
        Path(os.path.abspath(os.fspath(Path(workspace).expanduser()))) for workspace in committed
    )
    return roots


__all__ = [
    "TASK_ID_ALPHABET",
    "TASK_INITIALIZATION_MARKER",
    "RecoveredProviderStartPublisher",
    "TaskWorkspaceAdmission",
    "TaskWorkspaceAdmissionCoordinator",
    "accept_task_workspace",
    "allocate_task_id",
    "cleanup_marked_task_workspace",
    "recover_task_workspace_admissions",
    "stage_task_workspace",
]
