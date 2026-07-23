from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from banksia.runtime.contracts.member import NodeKind
from banksia.runtime.team import InitialTaskTeam
from banksia.workflows.contracts import ProviderSelection, PublishedWorkflowRevision

LEGACY_TEAM_ADAPTER_DELETE_AFTER = "WP-09"


class _LegacyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LegacyConsumeSelector(_LegacyModel):
    slot: str
    is_required: bool = True


class LegacyConsumeBuckets(_LegacyModel):
    artifacts: tuple[LegacyConsumeSelector, ...] = ()
    criteria: tuple[LegacyConsumeSelector, ...] = ()


class LegacyProduceSlot(_LegacyModel):
    slot: str
    description: str
    file_hint: str | None = None


class LegacyProduceBuckets(_LegacyModel):
    artifacts: tuple[LegacyProduceSlot, ...] = ()


class LegacyCriteriaDeclaration(_LegacyModel):
    owner_node_key: str
    slot: str
    description: str
    criteria: tuple[str, ...]


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
    consumes: LegacyConsumeBuckets | None = None
    produces: LegacyProduceBuckets | None = None
    criteria: tuple[LegacyCriteriaDeclaration, ...] = ()
    child_defaults: None = None
    order_index: int = Field(ge=0)


class LegacyDependencyEdge(_LegacyModel):
    consumer_node_key: str
    provider_node_key: str
    kind: str
    slot: str
    description: str
    order_index: int = Field(ge=0)


class LegacyTeamPlan(_LegacyModel):
    workflow_key: str
    definition_revision_no: int = Field(ge=1)
    compiler_version: str
    team_revision_id: str
    nodes: tuple[LegacyTeamNode, ...]
    dependency_edges: tuple[LegacyDependencyEdge, ...] = ()


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
    "LegacyConsumeBuckets",
    "LegacyConsumeSelector",
    "LegacyCriteriaDeclaration",
    "LegacyDependencyEdge",
    "LegacyProduceBuckets",
    "LegacyProduceSlot",
    "LegacyTeamNode",
    "LegacyTeamPlan",
    "project_legacy_team_plan",
]
