from __future__ import annotations

from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.runtime.contracts import (
    DelegatedMember,
    DelegateRequest,
    DelegateSuccess,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import NodeOperationAuthority
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations.follow_on import (
    CommittedNodeOperationFollowOn,
    CommittedNodeOperationResult,
)
from banksia.runtime.post_commit import DispatchStartDue
from banksia.runtime.task_root import read_task_root_paths

from .preparation import (
    prepare_wave_members,
    read_delegation_context,
    read_direct_targets,
    require_wave_size,
)
from .staging import stage_delegation_wave


async def commit_delegation_wave(
    session: AsyncSession,
    authority: NodeOperationAuthority,
    request: DelegateRequest,
    *,
    dependencies: DispatchOpeningDependencies,
) -> CommittedNodeOperationResult:
    """Atomically fan out one ordered set of direct-child Assignments."""

    context = await read_delegation_context(session, authority)
    require_wave_size(context.task, len(request.assignments))
    targets = await read_direct_targets(
        session,
        authority,
        request,
        team_revision_id=context.parent_selection.team_revision_id,
    )
    paths = await read_task_root_paths(session, authority.task_id)
    due_at = dependencies.clock()
    prepared_members = await prepare_wave_members(
        session,
        authority,
        request,
        targets=targets,
        context=context,
        workspace_path=paths.workspace_path,
        paths=paths,
        due_at=due_at,
        dependencies=dependencies,
    )

    try:
        await stage_delegation_wave(
            session,
            authority,
            wave_id=f"delegation-wave.{uuid4().hex}",
            wait_id=f"attempt-wait.{uuid4().hex}",
            members=prepared_members,
            committed_at=due_at,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="a selected child already received another open Assignment",
            is_retryable=False,
        ) from exc

    return CommittedNodeOperationResult(
        response=DelegateSuccess(
            members=tuple(
                DelegatedMember(child_id=member.authored.child_id) for member in prepared_members
            )
        ),
        follow_on=CommittedNodeOperationFollowOn(
            runtime_signals=tuple(
                DispatchStartDue(
                    dispatch_id=member.dispatch.dispatch_id,
                    provider_start_revision=0,
                    due_at=member.dispatch.due_at,
                )
                for member in prepared_members
            )
        ),
    )


__all__ = ["commit_delegation_wave"]
