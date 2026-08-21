from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.persistence.models import (
    MemberConfigurationModel,
    TaskModel,
    TeamRevisionMemberModel,
)
from oh_my_subagents.runtime.team.materialization import InitialTaskTeam
from oh_my_subagents.workflows.contracts import PublishedWorkflowRevision


@dataclass(frozen=True, slots=True)
class TeamManifestMember:
    member_id: str
    parent_member_id: str | None
    title: str | None
    description: str | None
    instruction: str | None
    provider: dict[str, object] | None
    capabilities: dict[str, object] | None
    origin: str


def render_initial_team_manifest(
    *,
    task_id: str,
    workflow_revision: PublishedWorkflowRevision,
    initial_team: InitialTaskTeam,
) -> str:
    """Render the admitted Workflow-backed team through the stable manifest format."""

    members = tuple(
        TeamManifestMember(
            member_id=selected.member_id,
            parent_member_id=selected.parent_member_id,
            title=selected.member.title,
            description=selected.member.description,
            instruction=selected.member.instruction,
            provider=(
                selected.member.provider.model_dump(mode="json", exclude_none=True)
                if selected.member.provider is not None
                else None
            ),
            capabilities=(
                selected.member.capabilities.model_dump(mode="json", exclude_none=True)
                if selected.member.capabilities is not None
                else None
            ),
            origin="authored Workflow",
        )
        for selected in initial_team.members
    )
    return render_team_manifest(
        task_id=task_id,
        workflow_id=workflow_revision.workflow_id,
        lead_member_id=initial_team.root_member_id,
        members=members,
    )


async def render_current_team_manifest(
    session: AsyncSession,
    *,
    task_id: str,
) -> str:
    """Render the Task's current controller-owned TeamRevision."""

    task = await session.get(TaskModel, task_id)
    if task is None:
        raise ValueError(f"Task {task_id!r} does not exist")
    if task.current_team_revision_id is None:
        raise ValueError(f"Task {task_id!r} has no current TeamRevision")

    rows = tuple(
        (
            await session.execute(
                select(TeamRevisionMemberModel, MemberConfigurationModel)
                .join(
                    MemberConfigurationModel,
                    and_(
                        MemberConfigurationModel.task_id == TeamRevisionMemberModel.task_id,
                        MemberConfigurationModel.member_id == TeamRevisionMemberModel.member_id,
                        MemberConfigurationModel.member_configuration_id
                        == TeamRevisionMemberModel.member_configuration_id,
                    ),
                )
                .where(
                    TeamRevisionMemberModel.task_id == task_id,
                    TeamRevisionMemberModel.team_revision_id == task.current_team_revision_id,
                )
                .order_by(TeamRevisionMemberModel.preorder_index)
            )
        ).all()
    )
    if not rows or rows[0][0].parent_member_id is not None:
        raise ValueError(f"Task {task_id!r} has an invalid current TeamRevision")
    members = tuple(
        TeamManifestMember(
            member_id=selection.member_id,
            parent_member_id=selection.parent_member_id,
            title=configuration.title,
            description=configuration.description,
            instruction=configuration.instruction,
            provider=configuration.requested_provider_json,
            capabilities=configuration.requested_capabilities_json,
            origin=(
                "authored Workflow"
                if configuration.basis_kind == "workflow_revision"
                else "Task replan"
            ),
        )
        for selection, configuration in rows
    )
    return render_team_manifest(
        task_id=task_id,
        workflow_id=task.workflow_key,
        lead_member_id=members[0].member_id,
        members=members,
    )


def render_team_manifest(
    *,
    task_id: str,
    workflow_id: str,
    lead_member_id: str,
    members: tuple[TeamManifestMember, ...],
) -> str:
    """Render one human organization chart without runtime bookkeeping."""

    child_parents = {
        member.parent_member_id for member in members if member.parent_member_id is not None
    }
    lines = [
        "# Oh My Subagents team",
        "",
        f"- Task: `{task_id}`",
        f"- Workflow: `{workflow_id}`",
        f"- Lead: `{lead_member_id}`",
        "",
        "Hierarchy and sibling order describe responsibility, not execution time.",
        "",
        "## Members",
        "",
    ]
    depth_by_member: dict[str, int] = {}
    for member in members:
        depth = (
            0 if member.parent_member_id is None else depth_by_member[member.parent_member_id] + 1
        )
        depth_by_member[member.member_id] = depth
        prefix = "  " * depth
        role = "Manager" if member.member_id in child_parents else "Contributor"
        lines.append(f"{prefix}- `{member.member_id}` — {role}")
        for label, value in (
            ("Title", member.title),
            ("Description", member.description),
            ("Instruction", member.instruction),
        ):
            if value is not None:
                lines.append(f"{prefix}  - {label}: {_single_line(value)}")
        if member.provider is not None:
            lines.append(f"{prefix}  - Provider: `{_render_json(member.provider)}`")
        if member.capabilities is not None:
            lines.append(
                f"{prefix}  - Requested capabilities: `{_render_json(member.capabilities)}`"
            )
        lines.append(f"{prefix}  - Origin: {member.origin}")
    return "\n".join(lines) + "\n"


def _render_json(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _single_line(value: str) -> str:
    return " ".join(value.splitlines()) if "\n" in value else value


__all__ = [
    "TeamManifestMember",
    "render_current_team_manifest",
    "render_initial_team_manifest",
    "render_team_manifest",
]
