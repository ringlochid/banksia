from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import (
    MemberBranchBasisModel,
    MemberConfigurationModel,
    MemberModel,
    TaskModel,
    TeamRevisionMemberModel,
    TeamRevisionModel,
)
from banksia.workflows.contracts import NormalizedMember, PublishedWorkflowRevision


class TeamMaterializationError(ValueError):
    """Raised when an exact published Workflow cannot become a Task's first Team."""


@dataclass(frozen=True, slots=True)
class MaterializedMember:
    member_id: str
    parent_member_id: str | None
    member_configuration_id: str
    member_branch_basis_id: str
    parent_member_branch_basis_id: str | None
    preorder_index: int
    sibling_order: int
    member: NormalizedMember


@dataclass(frozen=True, slots=True)
class InitialTaskTeam:
    task_id: str
    team_revision_id: str
    root_member_id: str
    members: tuple[MaterializedMember, ...]


def plan_initial_task_team(
    workflow_revision: PublishedWorkflowRevision,
    task_id: str,
) -> InitialTaskTeam:
    """Build one deterministic complete preorder snapshot without catalog reads."""
    return _build_initial_task_team(workflow_revision, task_id)


async def materialize_initial_task_team(
    session: AsyncSession,
    workflow_revision: PublishedWorkflowRevision,
    *,
    task_id: str,
) -> InitialTaskTeam:
    """Stage the first complete Team and advance its Task pointer in one transaction."""

    plan = _build_initial_task_team(workflow_revision, task_id)
    await _claim_task_team_materialization(
        session,
        workflow_revision=workflow_revision,
        plan=plan,
    )
    _stage_members(session, plan)
    _stage_member_configurations(session, plan, workflow_revision)
    _stage_member_branch_bases(session, plan)
    _stage_team_revision(session, plan, workflow_revision)
    _stage_team_revision_members(session, plan)
    await session.flush()
    return plan


def _build_initial_task_team(
    workflow_revision: PublishedWorkflowRevision,
    task_id: str,
) -> InitialTaskTeam:
    normalized_task_id = task_id.strip()
    if not normalized_task_id:
        raise TeamMaterializationError("task_id must not be blank")

    task_token = _stable_token(normalized_task_id)
    planned: list[MaterializedMember] = []
    seen: set[str] = set()

    def visit(
        member: NormalizedMember,
        *,
        parent_member_id: str | None,
        parent_branch_basis_id: str | None,
        sibling_order: int,
    ) -> None:
        if member.id in seen:
            raise TeamMaterializationError(
                f"Workflow member id {member.id!r} is not unique in the complete tree"
            )
        seen.add(member.id)
        member_token = _stable_token(f"{normalized_task_id}\0{member.id}")
        configuration_id = f"member-configuration.{task_token}.{member_token}.1"
        branch_basis_id = f"member-branch-basis.{task_token}.{member_token}.1"
        planned.append(
            MaterializedMember(
                member_id=member.id,
                parent_member_id=parent_member_id,
                member_configuration_id=configuration_id,
                member_branch_basis_id=branch_basis_id,
                parent_member_branch_basis_id=parent_branch_basis_id,
                preorder_index=len(planned),
                sibling_order=sibling_order,
                member=member,
            )
        )
        for child_order, child in enumerate(member.children or ()):
            visit(
                child,
                parent_member_id=member.id,
                parent_branch_basis_id=branch_basis_id,
                sibling_order=child_order,
            )

    visit(
        workflow_revision.workflow.lead,
        parent_member_id=None,
        parent_branch_basis_id=None,
        sibling_order=0,
    )
    _validate_complete_tree(tuple(planned), root_member_id=workflow_revision.workflow.lead.id)
    return InitialTaskTeam(
        task_id=normalized_task_id,
        team_revision_id=f"team-revision.{task_token}.1",
        root_member_id=workflow_revision.workflow.lead.id,
        members=tuple(planned),
    )


async def _claim_task_team_materialization(
    session: AsyncSession,
    *,
    workflow_revision: PublishedWorkflowRevision,
    plan: InitialTaskTeam,
) -> None:
    claimed_task_id = await session.scalar(
        update(TaskModel)
        .where(
            TaskModel.task_id == plan.task_id,
            TaskModel.current_team_revision_id.is_(None),
            TaskModel.workflow_key == workflow_revision.workflow_id,
            TaskModel.workflow_revision_no == workflow_revision.revision_no,
            TaskModel.workflow_content_hash == workflow_revision.content_hash,
        )
        .values(current_team_revision_id=plan.team_revision_id)
        .returning(TaskModel.task_id)
    )
    if claimed_task_id is not None:
        return

    task = await session.scalar(select(TaskModel).where(TaskModel.task_id == plan.task_id))
    if task is None:
        raise TeamMaterializationError(f"Task {plan.task_id!r} does not exist")
    if task.current_team_revision_id is not None:
        raise TeamMaterializationError(f"Task {plan.task_id!r} already has a current TeamRevision")
    raise TeamMaterializationError(
        "Task Workflow pin does not match the exact PublishedWorkflowRevision"
    )


def _stage_members(session: AsyncSession, plan: InitialTaskTeam) -> None:
    session.add_all(
        MemberModel(task_id=plan.task_id, member_id=selected.member_id) for selected in plan.members
    )


def _stage_member_configurations(
    session: AsyncSession,
    plan: InitialTaskTeam,
    workflow_revision: PublishedWorkflowRevision,
) -> None:
    workflow_basis = (
        f"workflow:{workflow_revision.workflow_id}:"
        f"{workflow_revision.revision_no}:{workflow_revision.content_hash}"
    )
    session.add_all(
        MemberConfigurationModel(
            member_configuration_id=selected.member_configuration_id,
            task_id=plan.task_id,
            member_id=selected.member_id,
            predecessor_member_configuration_id=None,
            title=selected.member.title,
            description=selected.member.description,
            instruction=selected.member.instruction,
            requested_provider_json=(
                selected.member.provider.model_dump(mode="json", exclude_none=True)
                if selected.member.provider is not None
                else None
            ),
            requested_capabilities_json=(
                selected.member.capabilities.model_dump(mode="json", exclude_none=True)
                if selected.member.capabilities is not None
                else None
            ),
            basis_kind="workflow_revision",
            basis_id=workflow_basis,
        )
        for selected in plan.members
    )


def _stage_member_branch_bases(
    session: AsyncSession,
    plan: InitialTaskTeam,
) -> None:
    session.add_all(
        MemberBranchBasisModel(
            member_branch_basis_id=selected.member_branch_basis_id,
            task_id=plan.task_id,
            member_id=selected.member_id,
            member_configuration_id=selected.member_configuration_id,
            parent_member_id=selected.parent_member_id,
            parent_member_branch_basis_id=selected.parent_member_branch_basis_id,
        )
        for selected in plan.members
    )


def _stage_team_revision(
    session: AsyncSession,
    plan: InitialTaskTeam,
    workflow_revision: PublishedWorkflowRevision,
) -> None:
    session.add(
        TeamRevisionModel(
            team_revision_id=plan.team_revision_id,
            task_id=plan.task_id,
            revision_no=1,
            predecessor_team_revision_id=None,
            root_member_id=plan.root_member_id,
            workflow_key=workflow_revision.workflow_id,
            workflow_revision_no=workflow_revision.revision_no,
            workflow_content_hash=workflow_revision.content_hash,
            provenance_json={
                "kind": "published_workflow_revision",
                "workflow_id": workflow_revision.workflow_id,
                "revision_no": workflow_revision.revision_no,
                "content_hash": workflow_revision.content_hash,
            },
        )
    )


def _stage_team_revision_members(
    session: AsyncSession,
    plan: InitialTaskTeam,
) -> None:
    session.add_all(
        TeamRevisionMemberModel(
            task_id=plan.task_id,
            team_revision_id=plan.team_revision_id,
            member_id=selected.member_id,
            parent_member_id=selected.parent_member_id,
            member_configuration_id=selected.member_configuration_id,
            member_branch_basis_id=selected.member_branch_basis_id,
            preorder_index=selected.preorder_index,
            sibling_order=selected.sibling_order,
        )
        for selected in plan.members
    )


def _stable_token(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:24]


def _validate_complete_tree(
    members: tuple[MaterializedMember, ...],
    *,
    root_member_id: str,
) -> None:
    if not members or members[0].member_id != root_member_id:
        raise TeamMaterializationError("TeamRevision must start with its exact root Member")
    if members[0].parent_member_id is not None or members[0].preorder_index != 0:
        raise TeamMaterializationError("TeamRevision root has an invalid parent or order")

    seen: set[str] = set()
    next_sibling_order: dict[str, int] = {}
    for index, member in enumerate(members):
        if member.preorder_index != index:
            raise TeamMaterializationError("TeamRevision preorder indices must be contiguous")
        if member.member_id in seen:
            raise TeamMaterializationError("TeamRevision selects one row per Member")
        if member.parent_member_id is not None:
            if member.parent_member_id not in seen:
                raise TeamMaterializationError("TeamRevision parent must precede its child")
            expected_order = next_sibling_order.get(member.parent_member_id, 0)
            if member.sibling_order != expected_order:
                raise TeamMaterializationError("TeamRevision sibling order must be contiguous")
            next_sibling_order[member.parent_member_id] = expected_order + 1
        seen.add(member.member_id)


__all__ = [
    "InitialTaskTeam",
    "MaterializedMember",
    "TeamMaterializationError",
    "materialize_initial_task_team",
    "plan_initial_task_team",
]
