from __future__ import annotations

import asyncio
import logging
import os
import secrets
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import (
    AttemptModel,
    DispatchTurnModel,
    TaskModel,
    WorkspaceBindingModel,
)
from oh_my_subagents.platform.workspace_files import DirectoryLease
from oh_my_subagents.runtime.post_commit import DispatchStartDue
from oh_my_subagents.runtime.team import (
    InitialTaskTeam,
    render_current_team_manifest,
    render_initial_team_manifest,
)
from oh_my_subagents.runtime.team.currentness import dispatch_team_selection_is_current
from oh_my_subagents.runtime.workspace.availability import (
    is_workspace_unavailable_error,
    normalized_workspace_root,
    pause_task_for_unavailable_workspace,
)
from oh_my_subagents.runtime.workspace.storage import (
    LEGACY_TASK_CONTAINER_NAME,
    TASK_CONTAINER_NAME,
    TASK_CONTAINER_NAMES,
    WorkspaceIdentity,
    capture_workspace_identity,
    ensure_directory,
    is_real_directory,
    open_task_container,
    open_task_root,
    read_small_text,
    remove_task_tree,
    replace_text,
    reserve_task_root,
    task_root_names,
    unlink_entry,
    write_new_text,
)
from oh_my_subagents.workflows.catalog import read_published_workflow_revision
from oh_my_subagents.workflows.contracts import PublishedWorkflowRevision

TASK_ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
TASK_INITIALIZATION_MARKER = ".oms-initializing"
_MARKER_HEADER = "oms-task-initialization-v1"

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
    task_id: str
    workspace: Path
    task_root: Path
    workflow_key: str
    workflow_revision_no: int
    workflow_content_hash: str


async def allocate_task_id(
    session: AsyncSession,
    *,
    workspace: Path,
) -> str:
    """Allocate a collision-checked 40-bit product Task identifier."""

    for _ in range(128):
        candidate = _new_task_id()
        if await session.get(TaskModel, candidate) is not None:
            continue
        collisions = await asyncio.gather(
            *(
                asyncio.to_thread(os.path.lexists, workspace / container / candidate)
                for container in TASK_CONTAINER_NAMES
            )
        )
        if not any(collisions):
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
    task_container_path = workspace / TASK_CONTAINER_NAME
    task_path = task_container_path / task_id
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
    ) as (task_container, task_root):
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
                remove_task_tree(task_container, task_id, task_root)
            raise
    return admission


def accept_task_workspace(admission: TaskWorkspaceAdmission) -> None:
    """Clear the initialization marker after the Task transaction commits."""

    with open_task_container(
        admission.workspace,
        container_name=admission.task_root.parent.name,
        should_create=False,
        expected_workspace_identity=admission.workspace_identity,
    ) as task_container:
        if task_container is None:
            raise RuntimeError("Task workspace disappeared before acceptance")
        with open_task_root(task_container, admission.task_id) as task_root:
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
        workspace_tasks = tuple(task for task in committed.values() if task.workspace == workspace)
        expected_identity = (
            expected_workspace_identities.get(workspace)
            if expected_workspace_identities is not None
            else None
        )
        recovered.extend(
            await _recover_workspace_admissions(
                session,
                workspace=workspace,
                expected_workspace_identity=expected_identity,
                workspace_tasks=workspace_tasks,
                committed=committed,
                publish_recovered_provider_start=publish_recovered_provider_start,
            )
        )
    return tuple(recovered)


async def _recover_workspace_admissions(
    session: AsyncSession,
    *,
    workspace: Path,
    expected_workspace_identity: WorkspaceIdentity | None,
    workspace_tasks: tuple[_CommittedTaskWorkspace, ...],
    committed: Mapping[str, _CommittedTaskWorkspace],
    publish_recovered_provider_start: RecoveredProviderStartPublisher | None,
) -> tuple[Path, ...]:
    recovered: list[Path] = []
    for container_name in TASK_CONTAINER_NAMES:
        container_tasks = tuple(
            task for task in workspace_tasks if task.task_root.parent.name == container_name
        )
        recovered.extend(
            await _recover_task_container_admissions(
                session,
                workspace=workspace,
                container_name=container_name,
                expected_workspace_identity=expected_workspace_identity,
                workspace_tasks=container_tasks,
                committed=committed,
                publish_recovered_provider_start=publish_recovered_provider_start,
            )
        )
    return tuple(recovered)


async def _recover_task_container_admissions(
    session: AsyncSession,
    *,
    workspace: Path,
    container_name: str,
    expected_workspace_identity: WorkspaceIdentity | None,
    workspace_tasks: tuple[_CommittedTaskWorkspace, ...],
    committed: Mapping[str, _CommittedTaskWorkspace],
    publish_recovered_provider_start: RecoveredProviderStartPublisher | None,
) -> tuple[Path, ...]:
    stack = ExitStack()
    try:
        task_container = stack.enter_context(
            open_task_container(
                workspace,
                container_name=container_name,
                should_create=False,
                expected_workspace_identity=expected_workspace_identity,
            )
        )
    except OSError as exc:
        stack.close()
        if not is_workspace_unavailable_error(exc):
            raise
        await _pause_unavailable_workspace_tasks(
            session,
            workspace=workspace,
            tasks=workspace_tasks,
        )
        return ()
    with stack:
        if task_container is None:
            await _pause_unavailable_workspace_tasks(
                session,
                workspace=workspace,
                tasks=workspace_tasks,
            )
            return ()
        try:
            task_names = task_root_names(task_container)
        except OSError as exc:
            if not is_workspace_unavailable_error(exc):
                raise
            await _pause_unavailable_workspace_tasks(
                session,
                workspace=workspace,
                tasks=workspace_tasks,
            )
            return ()
        return await _recover_available_workspace(
            session,
            workspace=workspace,
            container_name=container_name,
            task_container=task_container,
            task_names=task_names,
            workspace_tasks=workspace_tasks,
            committed=committed,
            publish_recovered_provider_start=publish_recovered_provider_start,
        )


async def _recover_available_workspace(
    session: AsyncSession,
    *,
    workspace: Path,
    container_name: str,
    task_container: DirectoryLease,
    task_names: tuple[str, ...],
    workspace_tasks: tuple[_CommittedTaskWorkspace, ...],
    committed: Mapping[str, _CommittedTaskWorkspace],
    publish_recovered_provider_start: RecoveredProviderStartPublisher | None,
) -> tuple[Path, ...]:
    for task in workspace_tasks:
        if not is_real_directory(task_container, task.task_id):
            await pause_task_for_unavailable_workspace(
                session,
                task_id=task.task_id,
                workspace=workspace,
            )
    recovered: list[Path] = []
    for task_id in task_names:
        if not _is_task_id(task_id) or not is_real_directory(task_container, task_id):
            continue
        committed_row = committed.get(task_id)
        stack = ExitStack()
        try:
            task_root_authority = stack.enter_context(open_task_root(task_container, task_id))
        except OSError as exc:
            stack.close()
            if committed_row is None or not is_workspace_unavailable_error(exc):
                raise
            await pause_task_for_unavailable_workspace(
                session,
                task_id=task_id,
                workspace=workspace,
            )
            continue
        with stack:
            task_root = await _recover_marked_task_root(
                session,
                workspace=workspace,
                container_name=container_name,
                task_container=task_container,
                task_root_authority=task_root_authority,
                task_id=task_id,
                committed_row=committed_row,
                publish_recovered_provider_start=publish_recovered_provider_start,
            )
        if task_root is not None:
            recovered.append(task_root)
    return tuple(recovered)


async def _recover_marked_task_root(
    session: AsyncSession,
    *,
    workspace: Path,
    container_name: str,
    task_container: DirectoryLease,
    task_root_authority: DirectoryLease,
    task_id: str,
    committed_row: _CommittedTaskWorkspace | None,
    publish_recovered_provider_start: RecoveredProviderStartPublisher | None,
) -> Path | None:
    marker_name = _initialization_marker(container_name)
    if read_small_text(task_root_authority, marker_name) != _marker_body(
        task_id,
        container_name=container_name,
    ):
        return None
    task_root = workspace / container_name / task_id
    if committed_row is None or committed_row.task_root != task_root:
        return (
            task_root
            if remove_task_tree(
                task_container,
                task_id,
                task_root_authority,
            )
            else None
        )
    await _repair_committed_task_workspace(
        session,
        task_root=task_root_authority,
        task_id=task_id,
        workflow_key=committed_row.workflow_key,
        workflow_revision_no=committed_row.workflow_revision_no,
        workflow_content_hash=committed_row.workflow_content_hash,
    )
    provider_start = await _read_recovered_provider_start(session, task_id=task_id)
    unlink_entry(task_root_authority, marker_name)
    if provider_start is not None and publish_recovered_provider_start is not None:
        await session.rollback()
        _publish_recovered_provider_start(
            provider_start,
            publish=publish_recovered_provider_start,
        )
    return task_root


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
            task_id=task_id,
            workspace=normalized_workspace_root(workspace),
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
            workspace,
        ) in rows
    }
    return committed, tuple(workspace for *_, workspace in rows)


async def _pause_unavailable_workspace_tasks(
    session: AsyncSession,
    *,
    workspace: Path,
    tasks: tuple[_CommittedTaskWorkspace, ...],
) -> None:
    for task in tasks:
        await pause_task_for_unavailable_workspace(
            session,
            task_id=task.task_id,
            workspace=workspace,
        )


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


def _marker_body(
    task_id: str,
    *,
    container_name: str = TASK_CONTAINER_NAME,
) -> str:
    header = (
        "banksia-task-initialization-v1"
        if container_name == LEGACY_TASK_CONTAINER_NAME
        else _MARKER_HEADER
    )
    return f"{header}\n{task_id}\n"


def _initialization_marker(container_name: str) -> str:
    if container_name == LEGACY_TASK_CONTAINER_NAME:
        return ".banksia-initializing"
    return TASK_INITIALIZATION_MARKER


def _remove_marked_directory(
    workspace: Path,
    *,
    task_id: str,
    workspace_identity: WorkspaceIdentity | None = None,
) -> bool:
    with open_task_container(
        workspace,
        container_name=TASK_CONTAINER_NAME,
        should_create=False,
        expected_workspace_identity=workspace_identity,
    ) as task_container:
        if task_container is None or not is_real_directory(
            task_container,
            task_id,
        ):
            return False
        try:
            with open_task_root(task_container, task_id) as task_root:
                if read_small_text(
                    task_root,
                    TASK_INITIALIZATION_MARKER,
                ) != _marker_body(task_id):
                    return False
                return remove_task_tree(task_container, task_id, task_root)
        except OSError:
            return False


def _normalized_workspace_roots(
    configured: tuple[Path, ...],
    committed: tuple[str, ...],
) -> set[Path]:
    roots = {normalized_workspace_root(workspace) for workspace in configured}
    roots.update(normalized_workspace_root(Path(workspace)) for workspace in committed)
    return roots


__all__ = [
    "TASK_ID_ALPHABET",
    "TASK_INITIALIZATION_MARKER",
    "RecoveredProviderStartPublisher",
    "TaskWorkspaceAdmission",
    "accept_task_workspace",
    "allocate_task_id",
    "cleanup_marked_task_workspace",
    "recover_task_workspace_admissions",
    "stage_task_workspace",
]
