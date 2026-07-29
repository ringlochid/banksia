from __future__ import annotations

import base64
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Literal, NamedTuple, cast

from sqlalchemy import and_, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import CompoundSelect, Subquery

from banksia.persistence.models import (
    AcceptedBoundaryModel,
    AssignmentModel,
    AttemptCheckpointModel,
    CheckpointFileReferenceModel,
    DispatchCapabilitySetModel,
    DispatchTurnModel,
    MemberConfigurationModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from banksia.providers import ManagedExtensionMode
from banksia.runtime.contracts import CheckpointOutcome, FileReference
from banksia.runtime.contracts.capabilities import (
    EffectiveNetworkAccess,
    EffectiveProviderNativeAccess,
)
from banksia.runtime.contracts.provider_resolution import ExtensionModeResolutionSource
from banksia.runtime.contracts.support import (
    SupportActionableItem,
    SupportBoundaryTraceEntry,
    SupportCheckpointTraceEntry,
    SupportDispatchTraceEntry,
    SupportEffectiveCapabilityReadback,
    SupportTaskSnapshot,
    SupportTaskTracePage,
    SupportTeamMemberEntry,
    SupportTraceEntry,
)
from banksia.runtime.contracts.team_read import MemberBehavior
from banksia.runtime.errors import illegal_state_error, invalid_request_shape_error
from banksia.runtime.providers.contracts import ProviderExtensionInventory
from banksia.runtime.task_control.contracts import ControllerTaskState
from banksia.runtime.task_control.reads import read_runtime_task
from banksia.runtime.task_events import latest_task_event

_TRACE_CURSOR_PREFIX = "support-trace."
type _TraceSort = Literal["occurred_at_desc", "occurred_at_asc"]


class _TracePosition(NamedTuple):
    occurred_at: datetime
    kind: str
    entry_id: str


class _TraceIndexRow(NamedTuple):
    kind: str
    entry_id: str
    occurred_at: datetime


async def support_task_snapshot(
    session: AsyncSession,
    task_id: str,
) -> SupportTaskSnapshot:
    task = await read_runtime_task(session, task_id)
    latest_event = await latest_task_event(session, task_id=task_id)
    current_paths = (_manifest_file_reference(task),)
    return SupportTaskSnapshot(
        task=task,
        top_actionable_items=_actionable_items(task, current_paths),
        current_paths=current_paths,
        stream_head_event_id=latest_event.event_id if latest_event is not None else None,
    )


async def support_task_trace(
    session: AsyncSession,
    task_id: str,
    *,
    q: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
    sort: str = "occurred_at_desc",
) -> SupportTaskTracePage:
    resolved_sort = _validate_trace_query(limit=limit, sort=sort)
    normalized_q = (q or "").strip().casefold()
    position = _decode_trace_cursor(
        cursor,
        task_id=task_id,
        normalized_q=normalized_q,
        sort=resolved_sort,
    )
    task = await read_runtime_task(session, task_id)
    team_members = await _read_team_members(
        session,
        task_id=task_id,
        team_revision_id=task.current_team_revision_id,
    )
    index = _trace_index_statement(task_id=task_id, normalized_q=normalized_q).subquery()
    statement = select(index.c.kind, index.c.entry_id, index.c.occurred_at)
    if position is not None:
        statement = statement.where(
            _trace_keyset_clause(index, position=position, sort=resolved_sort)
        )
    order = (
        (
            index.c.occurred_at.asc(),
            index.c.kind.asc(),
            index.c.entry_id.asc(),
        )
        if resolved_sort == "occurred_at_asc"
        else (
            index.c.occurred_at.desc(),
            index.c.kind.desc(),
            index.c.entry_id.desc(),
        )
    )
    rows = tuple(await session.execute(statement.order_by(*order).limit(limit + 1)))
    page_rows = tuple(
        _TraceIndexRow(
            kind=row.kind,
            entry_id=row.entry_id,
            occurred_at=_as_utc(row.occurred_at),
        )
        for row in rows[:limit]
    )
    entries = await _read_trace_entries(session, task_id=task_id, index_rows=page_rows)
    next_cursor = None
    if len(rows) > limit and page_rows:
        last = page_rows[-1]
        next_cursor = _encode_trace_cursor(
            task_id=task_id,
            normalized_q=normalized_q,
            sort=resolved_sort,
            position=_TracePosition(last.occurred_at, last.kind, last.entry_id),
        )
    return SupportTaskTracePage(
        task_id=task_id,
        team_members=team_members,
        entries=entries,
        current_paths=(_manifest_file_reference(task),),
        next_cursor=next_cursor,
    )


def _trace_index_statement(
    *,
    task_id: str,
    normalized_q: str,
) -> CompoundSelect[tuple[str, str, datetime]]:
    dispatch = select(
        literal("dispatch").label("kind"),
        DispatchTurnModel.dispatch_id.label("entry_id"),
        DispatchTurnModel.created_at.label("occurred_at"),
    ).where(DispatchTurnModel.task_id == task_id)
    checkpoint = select(
        literal("checkpoint").label("kind"),
        AttemptCheckpointModel.checkpoint_id.label("entry_id"),
        AttemptCheckpointModel.recorded_at.label("occurred_at"),
    ).where(AttemptCheckpointModel.task_id == task_id)
    boundary = (
        select(
            literal("boundary").label("kind"),
            AcceptedBoundaryModel.accepted_boundary_id.label("entry_id"),
            AcceptedBoundaryModel.committed_at.label("occurred_at"),
        )
        .join(
            DispatchTurnModel,
            (DispatchTurnModel.task_id == AcceptedBoundaryModel.task_id)
            & (DispatchTurnModel.dispatch_id == AcceptedBoundaryModel.source_dispatch_id),
        )
        .where(AcceptedBoundaryModel.task_id == task_id)
    )
    if normalized_q:
        pattern = f"%{normalized_q}%"
        dispatch = dispatch.where(
            or_(
                func.lower(DispatchTurnModel.dispatch_id).like(pattern),
                func.lower(DispatchTurnModel.member_id).like(pattern),
                func.lower(DispatchTurnModel.opened_reason).like(pattern),
                func.lower(func.coalesce(DispatchTurnModel.closed_reason, "")).like(pattern),
            )
        )
        checkpoint = checkpoint.where(
            or_(
                func.lower(AttemptCheckpointModel.checkpoint_id).like(pattern),
                func.lower(AttemptCheckpointModel.attempt_id).like(pattern),
                func.lower(AttemptCheckpointModel.summary).like(pattern),
                func.lower(func.coalesce(AttemptCheckpointModel.details, "")).like(pattern),
                func.lower(func.coalesce(AttemptCheckpointModel.outcome, "")).like(pattern),
            )
        )
        boundary = boundary.where(
            or_(
                func.lower(AcceptedBoundaryModel.accepted_boundary_id).like(pattern),
                func.lower(AcceptedBoundaryModel.source_dispatch_id).like(pattern),
                func.lower(AcceptedBoundaryModel.checkpoint_id).like(pattern),
                func.lower(AcceptedBoundaryModel.outcome).like(pattern),
                func.lower(DispatchTurnModel.member_id).like(pattern),
            )
        )
    return union_all(dispatch, checkpoint, boundary)


def _trace_keyset_clause(
    index: Subquery,
    *,
    position: _TracePosition,
    sort: _TraceSort,
) -> ColumnElement[bool]:
    columns = index.c
    comparison = (
        columns.occurred_at > position.occurred_at
        if sort == "occurred_at_asc"
        else columns.occurred_at < position.occurred_at
    )
    kind_comparison = (
        columns.kind > position.kind if sort == "occurred_at_asc" else columns.kind < position.kind
    )
    id_comparison = (
        columns.entry_id > position.entry_id
        if sort == "occurred_at_asc"
        else columns.entry_id < position.entry_id
    )
    return or_(
        comparison,
        and_(columns.occurred_at == position.occurred_at, kind_comparison),
        and_(
            columns.occurred_at == position.occurred_at,
            columns.kind == position.kind,
            id_comparison,
        ),
    )


async def _read_trace_entries(
    session: AsyncSession,
    *,
    task_id: str,
    index_rows: tuple[_TraceIndexRow, ...],
) -> tuple[SupportTraceEntry, ...]:
    dispatch_ids = tuple(row.entry_id for row in index_rows if row.kind == "dispatch")
    checkpoint_ids = tuple(row.entry_id for row in index_rows if row.kind == "checkpoint")
    boundary_ids = tuple(row.entry_id for row in index_rows if row.kind == "boundary")

    dispatches = {
        dispatch.dispatch_id: _dispatch_entry(dispatch, capabilities)
        for dispatch, capabilities in await session.execute(
            select(DispatchTurnModel, DispatchCapabilitySetModel)
            .join(
                DispatchCapabilitySetModel,
                DispatchCapabilitySetModel.dispatch_id == DispatchTurnModel.dispatch_id,
            )
            .options(raiseload("*"))
            .where(
                DispatchTurnModel.task_id == task_id,
                DispatchTurnModel.dispatch_id.in_(dispatch_ids),
            )
        )
    }
    files_by_checkpoint = await _read_checkpoint_files(
        session,
        checkpoint_ids=checkpoint_ids,
    )
    checkpoints = {
        checkpoint.checkpoint_id: SupportCheckpointTraceEntry(
            checkpoint_id=checkpoint.checkpoint_id,
            attempt_id=checkpoint.attempt_id,
            outcome=(
                CheckpointOutcome(checkpoint.outcome) if checkpoint.outcome is not None else None
            ),
            summary=checkpoint.summary,
            details=checkpoint.details,
            files=files_by_checkpoint.get(checkpoint.checkpoint_id, ()),
            recorded_at=_as_utc(checkpoint.recorded_at),
        )
        for checkpoint in await session.scalars(
            select(AttemptCheckpointModel)
            .options(raiseload("*"))
            .where(
                AttemptCheckpointModel.task_id == task_id,
                AttemptCheckpointModel.checkpoint_id.in_(checkpoint_ids),
            )
        )
    }
    boundaries = {
        boundary.accepted_boundary_id: SupportBoundaryTraceEntry(
            source_dispatch_id=boundary.source_dispatch_id,
            member_id=member_id,
            boundary=CheckpointOutcome(boundary.outcome),
            checkpoint_id=boundary.checkpoint_id,
            successor_dispatch_id=boundary.successor_dispatch_id,
            occurred_at=_as_utc(boundary.committed_at),
        )
        for boundary, member_id in await session.execute(
            select(AcceptedBoundaryModel, DispatchTurnModel.member_id)
            .join(
                DispatchTurnModel,
                (DispatchTurnModel.task_id == AcceptedBoundaryModel.task_id)
                & (DispatchTurnModel.dispatch_id == AcceptedBoundaryModel.source_dispatch_id),
            )
            .options(raiseload("*"))
            .where(
                AcceptedBoundaryModel.task_id == task_id,
                AcceptedBoundaryModel.accepted_boundary_id.in_(boundary_ids),
            )
        )
    }
    entries_by_key: dict[tuple[str, str], SupportTraceEntry] = {}
    entries_by_key.update((("dispatch", entry_id), entry) for entry_id, entry in dispatches.items())
    entries_by_key.update(
        (("checkpoint", entry_id), entry) for entry_id, entry in checkpoints.items()
    )
    entries_by_key.update((("boundary", entry_id), entry) for entry_id, entry in boundaries.items())
    return tuple(entries_by_key[(row.kind, row.entry_id)] for row in index_rows)


async def _read_checkpoint_files(
    session: AsyncSession,
    *,
    checkpoint_ids: tuple[str, ...],
) -> dict[str, tuple[FileReference, ...]]:
    if not checkpoint_ids:
        return {}
    rows = await session.scalars(
        select(CheckpointFileReferenceModel)
        .where(CheckpointFileReferenceModel.checkpoint_id.in_(checkpoint_ids))
        .order_by(
            CheckpointFileReferenceModel.checkpoint_id,
            CheckpointFileReferenceModel.order_index,
        )
    )
    grouped: defaultdict[str, list[FileReference]] = defaultdict(list)
    for row in rows:
        grouped[row.checkpoint_id].append(FileReference(path=row.path, description=row.description))
    return {checkpoint_id: tuple(files) for checkpoint_id, files in grouped.items()}


async def _read_team_members(
    session: AsyncSession,
    *,
    task_id: str,
    team_revision_id: str,
) -> tuple[SupportTeamMemberEntry, ...]:
    root_member_id = await session.scalar(
        select(AssignmentModel.member_id)
        .join(
            TaskModel,
            (TaskModel.task_id == AssignmentModel.task_id)
            & (TaskModel.root_assignment_id == AssignmentModel.assignment_id),
        )
        .where(TaskModel.task_id == task_id)
    )
    if root_member_id is None:
        raise illegal_state_error(f"task '{task_id}' has no root Assignment")
    rows = tuple(
        (
            await session.execute(
                select(TeamRevisionMemberModel, MemberConfigurationModel)
                .join(
                    MemberConfigurationModel,
                    (MemberConfigurationModel.task_id == TeamRevisionMemberModel.task_id)
                    & (MemberConfigurationModel.member_id == TeamRevisionMemberModel.member_id)
                    & (
                        MemberConfigurationModel.member_configuration_id
                        == TeamRevisionMemberModel.member_configuration_id
                    ),
                )
                .options(raiseload("*"))
                .where(
                    TeamRevisionMemberModel.task_id == task_id,
                    TeamRevisionMemberModel.team_revision_id == team_revision_id,
                )
                .order_by(TeamRevisionMemberModel.preorder_index)
            )
        ).all()
    )
    child_ids_by_parent: dict[str, list[str]] = {}
    for selection, _configuration in rows:
        if selection.parent_member_id is not None:
            child_ids_by_parent.setdefault(selection.parent_member_id, []).append(
                selection.member_id
            )
    return tuple(
        SupportTeamMemberEntry(
            member_id=selection.member_id,
            parent_member_id=selection.parent_member_id,
            is_task_lead=selection.member_id == root_member_id,
            behavior=(
                MemberBehavior.MANAGER
                if selection.member_id in child_ids_by_parent
                else MemberBehavior.CONTRIBUTOR
            ),
            member_configuration_id=selection.member_configuration_id,
            member_branch_basis_id=selection.member_branch_basis_id,
            member_title=configuration.title,
            description=configuration.description,
            preorder_index=selection.preorder_index,
            child_member_ids=tuple(child_ids_by_parent.get(selection.member_id, ())),
        )
        for selection, configuration in rows
    )


def _dispatch_entry(
    dispatch: DispatchTurnModel,
    capabilities: DispatchCapabilitySetModel,
) -> SupportDispatchTraceEntry:
    return SupportDispatchTraceEntry(
        dispatch_id=dispatch.dispatch_id,
        predecessor_dispatch_id=dispatch.predecessor_dispatch_id,
        assignment_id=dispatch.assignment_id,
        attempt_id=dispatch.attempt_id,
        member_id=dispatch.member_id,
        status=cast(Literal["starting", "open", "closed"], dispatch.status),
        opened_reason=dispatch.opened_reason,
        closed_reason=dispatch.closed_reason,
        requested_provider=cast(
            Literal["codex", "claude", "openclaw"], dispatch.requested_provider
        ),
        resolved_provider=cast(Literal["codex", "claude", "openclaw"], dispatch.resolved_provider),
        selection_basis=cast(Literal["explicit", "default"], dispatch.provider_selection_basis),
        requested_extension_mode=cast(
            ManagedExtensionMode | None, dispatch.requested_extension_mode
        ),
        requested_extension_mode_source=cast(
            ExtensionModeResolutionSource | None,
            dispatch.requested_extension_mode_source,
        ),
        effective_extension_mode=cast(
            ManagedExtensionMode | None, dispatch.effective_extension_mode
        ),
        effective_extension_mode_source=cast(
            ExtensionModeResolutionSource | None,
            dispatch.effective_extension_mode_source,
        ),
        extension_inventory=(
            ProviderExtensionInventory.model_validate_json(dispatch.extension_inventory_json)
            if dispatch.extension_inventory_json is not None
            else None
        ),
        adapter_started_at=_as_utc_optional(dispatch.adapter_started_at),
        last_node_activity_at=_as_utc_optional(dispatch.last_node_activity_at),
        node_activity_revision=dispatch.node_activity_revision,
        effective_capabilities=_effective_capability_readback(capabilities),
        created_at=_as_utc(dispatch.created_at),
        closed_at=_as_utc_optional(dispatch.closed_at),
    )


def _actionable_items(
    task: ControllerTaskState,
    current_paths: tuple[FileReference, ...],
) -> tuple[SupportActionableItem, ...]:
    if task.status == "paused":
        return (
            SupportActionableItem(
                summary=f"Task is paused: {task.pause_reason}.",
                current_paths=current_paths,
                suggested_action="Inspect current truth before continuing or cancelling.",
            ),
        )
    return ()


def _manifest_file_reference(task: ControllerTaskState) -> FileReference:
    return task.workflow_manifest_ref


def _validate_trace_query(*, limit: int, sort: str) -> _TraceSort:
    if sort not in {"occurred_at_desc", "occurred_at_asc"}:
        raise invalid_request_shape_error("unknown trace sort")
    if not 1 <= limit <= 200:
        raise invalid_request_shape_error("trace limit must be between 1 and 200")
    return cast(_TraceSort, sort)


def _encode_trace_cursor(
    *,
    task_id: str,
    normalized_q: str,
    sort: _TraceSort,
    position: _TracePosition,
) -> str:
    payload = json.dumps(
        {
            "entry_id": position.entry_id,
            "kind": position.kind,
            "occurred_at": _as_utc(position.occurred_at).isoformat(),
            "q": normalized_q,
            "sort": sort,
            "task_id": task_id,
            "version": 1,
        },
        separators=(",", ":"),
    )
    token = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{_TRACE_CURSOR_PREFIX}{token}"


def _decode_trace_cursor(
    cursor: str | None,
    *,
    task_id: str,
    normalized_q: str,
    sort: _TraceSort,
) -> _TracePosition | None:
    if cursor is None:
        return None
    if not cursor.startswith(_TRACE_CURSOR_PREFIX):
        raise invalid_request_shape_error("trace cursor is no longer usable")
    try:
        token = cursor.removeprefix(_TRACE_CURSOR_PREFIX)
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        occurred_at = datetime.fromisoformat(payload["occurred_at"])
        kind = payload["kind"]
        entry_id = payload["entry_id"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise invalid_request_shape_error("trace cursor is no longer usable") from exc
    if (
        payload.get("version") != 1
        or payload.get("task_id") != task_id
        or payload.get("q") != normalized_q
        or payload.get("sort") != sort
        or kind not in {"dispatch", "checkpoint", "boundary"}
        or not isinstance(entry_id, str)
        or not entry_id
    ):
        raise invalid_request_shape_error("trace cursor is no longer usable")
    return _TracePosition(_as_utc(occurred_at), kind, entry_id)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _as_utc_optional(value: datetime | None) -> datetime | None:
    return _as_utc(value) if value is not None else None


def _effective_capability_readback(
    capabilities: DispatchCapabilitySetModel,
) -> SupportEffectiveCapabilityReadback:
    return SupportEffectiveCapabilityReadback(
        provider_native_access=EffectiveProviderNativeAccess.model_validate(
            {
                "effective": capabilities.provider_native_access,
                "source": capabilities.provider_native_access_source,
            }
        ),
        network_access=EffectiveNetworkAccess.model_validate(
            {
                "effective": capabilities.network_access,
                "source": capabilities.network_access_source,
            }
        ),
    )


__all__ = ["support_task_snapshot", "support_task_trace"]
