from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.team import InitialTaskTeam
from banksia.workflows.contracts import ProviderSelection, PublishedWorkflowRevision

LEGACY_TEAM_ADAPTER_DELETE_AFTER = "WP-09"


class _LegacyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LegacyTeamNode(_LegacyModel):
    node_key: str
    parent_node_key: str | None = None
    child_node_keys: tuple[str, ...] = ()
    structural_kind: NodeKind
    member_id: str
    member_configuration_id: str
    member_branch_basis_id: str
    provider: ProviderSelection | None = None
    title: str | None = None
    description: str
    node_instruction: str | None = None
    order_index: int = Field(ge=0)


class LegacyTeamPlan(_LegacyModel):
    workflow_key: str
    definition_revision_no: int = Field(ge=1)
    compiler_version: str
    team_revision_id: str
    nodes: tuple[LegacyTeamNode, ...]


def project_legacy_team_plan(
    workflow_revision: PublishedWorkflowRevision,
    team: InitialTaskTeam,
) -> LegacyTeamPlan:
    """Project exact Team truth into residual Flow rows until WP-09 deletes them."""

    authored = {selected.member_id: selected.member for selected in team.members}
    child_ids: dict[str, list[str]] = {selected.member_id: [] for selected in team.members}
    for selected in team.members:
        if selected.parent_member_id is not None:
            child_ids[selected.parent_member_id].append(selected.member_id)

    nodes = tuple(
        LegacyTeamNode(
            node_key=selected.member_id,
            parent_node_key=selected.parent_member_id,
            child_node_keys=tuple(child_ids[selected.member_id]),
            structural_kind=_legacy_kind(
                is_root=selected.member_id == team.root_member_id,
                has_children=bool(child_ids[selected.member_id]),
            ),
            member_id=selected.member_id,
            member_configuration_id=selected.member_configuration_id,
            member_branch_basis_id=selected.member_branch_basis_id,
            provider=authored[selected.member_id].provider,
            title=authored[selected.member_id].title,
            description=authored[selected.member_id].description or "",
            node_instruction=authored[selected.member_id].instruction,
            order_index=selected.preorder_index,
        )
        for selected in team.members
    )
    if tuple(node.node_key for node in nodes) != tuple(
        selected.member_id for selected in team.members
    ):
        raise ValueError("legacy Team projection changed complete authored order")
    return LegacyTeamPlan(
        workflow_key=workflow_revision.workflow_id,
        definition_revision_no=workflow_revision.revision_no,
        compiler_version="wp02-legacy-team-adapter",
        team_revision_id=team.team_revision_id,
        nodes=nodes,
    )


def _legacy_kind(*, is_root: bool, has_children: bool) -> NodeKind:
    if is_root:
        return NodeKind.ROOT
    if has_children:
        return NodeKind.PARENT
    return NodeKind.WORKER


__all__ = [
    "LEGACY_TEAM_ADAPTER_DELETE_AFTER",
    "LegacyTeamNode",
    "LegacyTeamPlan",
    "project_legacy_team_plan",
]
