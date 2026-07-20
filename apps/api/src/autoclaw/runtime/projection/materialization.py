from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.models import (
    ArtifactCurrentPointerModel,
    ArtifactPublicationModel,
    AssignmentCriteriaRefModel,
    AssignmentModel,
    AttemptCheckpointModel,
    AttemptModel,
    FlowEdgeModel,
    FlowModel,
    FlowNodeModel,
    FlowRevisionModel,
    TaskModel,
    TransientLocalizationModel,
)
from autoclaw.runtime.projection.contracts import (
    ArtifactIndexEntry,
    ArtifactIndexReadback,
    AssignmentCriteriaReadback,
    AttemptAssignmentReadback,
    CriteriaReadback,
    LatestCheckpointReadback,
    ProjectionRef,
    TransientIndexEntry,
    TransientIndexReadback,
    WorkflowManifestEdge,
    WorkflowManifestNode,
    WorkflowManifestReadback,
    WorkflowManifestTask,
)
from autoclaw.runtime.projection.signals import (
    ArtifactProjection,
    AttemptAssignmentProjection,
    CriteriaProjection,
    LatestCheckpointProjection,
    SupportProjectionSignal,
    TransientProjection,
    WorkflowManifestProjection,
)
from autoclaw.runtime.task_root.paths import (
    artifact_index_json_path,
    assignment_json_path,
    assignment_markdown_path,
    checkpoint_json_path,
    checkpoint_markdown_path,
    criteria_file_path,
    manifest_json_path,
    manifest_markdown_path,
    transient_index_json_path,
)
from autoclaw.runtime.task_root.reads import read_task_root_paths
from autoclaw.runtime.task_root.writes import (
    encode_projection_json,
    replace_projection_files,
)


class _CriteriaSource(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    owner_node_key: str
    slot: str
    description: str
    criteria: tuple[str, ...]
    version: int = Field(ge=1)
    path: str


async def project_support_signal(
    session: AsyncSession,
    signal: SupportProjectionSignal,
) -> None:
    """Materialize one exact support signal from a fresh controller read."""

    match signal:
        case WorkflowManifestProjection():
            await project_workflow_manifest(session, signal)
        case CriteriaProjection():
            await project_criteria(session, signal)
        case AttemptAssignmentProjection():
            await project_attempt_assignment(session, signal)
        case LatestCheckpointProjection():
            await project_latest_checkpoint(session, signal)
        case ArtifactProjection():
            await project_artifact_index(session, signal)
        case TransientProjection():
            await project_transient_index(session, signal)
        case _:
            raise TypeError(f"unsupported support projection signal: {type(signal).__name__}")


async def project_workflow_manifest(
    session: AsyncSession,
    signal: WorkflowManifestProjection,
) -> bool:
    flow = await session.get(FlowModel, signal.flow_id)
    if flow is None or flow.active_flow_revision_id != signal.active_flow_revision_id:
        return False
    revision = await session.get(FlowRevisionModel, signal.active_flow_revision_id)
    task = await session.get(TaskModel, flow.task_id)
    if revision is None or revision.flow_id != flow.flow_id or task is None:
        return False

    nodes = tuple(
        (
            await session.scalars(
                select(FlowNodeModel)
                .where(FlowNodeModel.flow_revision_id == revision.flow_revision_id)
                .order_by(FlowNodeModel.order_index)
            )
        ).all()
    )
    edges = tuple(
        (
            await session.scalars(
                select(FlowEdgeModel)
                .where(FlowEdgeModel.flow_revision_id == revision.flow_revision_id)
                .order_by(FlowEdgeModel.order_index)
            )
        ).all()
    )
    payload = WorkflowManifestReadback(
        flow_id=flow.flow_id,
        active_flow_revision_id=revision.flow_revision_id,
        workflow_key=task.workflow_key,
        task=WorkflowManifestTask(
            task_id=task.task_id,
            task_key=task.task_key,
            title=task.title,
            summary=task.summary,
        ),
        nodes=tuple(_manifest_node(node) for node in nodes),
        edges=tuple(
            WorkflowManifestEdge(
                provider_node_key=edge.provider_node_key,
                consumer_node_key=edge.consumer_node_key,
                kind=edge.kind,
                slot=edge.slot,
                description=edge.description,
            )
            for edge in edges
        ),
    )
    paths = await read_task_root_paths(session, task.task_id)
    _replace_files(
        {
            manifest_json_path(paths): encode_projection_json(payload),
            manifest_markdown_path(paths): _manifest_markdown(payload).encode(),
        }
    )
    return True


async def project_criteria(session: AsyncSession, signal: CriteriaProjection) -> bool:
    revision = await session.get(FlowRevisionModel, signal.flow_revision_id)
    if revision is None:
        return False
    flow = await session.get(FlowModel, revision.flow_id)
    if flow is None or flow.active_flow_revision_id != signal.flow_revision_id:
        return False
    node = await session.scalar(
        select(FlowNodeModel).where(
            FlowNodeModel.flow_revision_id == signal.flow_revision_id,
            FlowNodeModel.node_key == signal.owner_node_key,
        )
    )
    if node is None:
        return False
    criterion = _find_criterion(node.criteria_json, signal)
    if criterion is None:
        return False

    payload = _criteria_readback(signal.flow_revision_id, criterion)
    paths = await read_task_root_paths(session, flow.task_id)
    content = _criteria_markdown(payload).encode()
    _replace_files(
        {
            criteria_file_path(paths=paths, slot=signal.slot, version=signal.version): content,
            criteria_file_path(paths=paths, slot=signal.slot): content,
        }
    )
    return True


async def project_attempt_assignment(
    session: AsyncSession,
    signal: AttemptAssignmentProjection,
) -> bool:
    assignment = await session.get(AssignmentModel, signal.assignment_id)
    attempt = await session.get(AttemptModel, signal.attempt_id)
    if (
        assignment is None
        or attempt is None
        or assignment.flow_revision_id != signal.flow_revision_id
        or attempt.assignment_id != assignment.assignment_id
    ):
        return False
    criteria = tuple(
        (
            await session.scalars(
                select(AssignmentCriteriaRefModel)
                .where(AssignmentCriteriaRefModel.assignment_id == assignment.assignment_id)
                .order_by(AssignmentCriteriaRefModel.order_index)
            )
        ).all()
    )
    payload = AttemptAssignmentReadback(
        assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id,
        flow_revision_id=assignment.flow_revision_id,
        assignment_key=assignment.assignment_key,
        node_key=assignment.node_key,
        parent_assignment_id=assignment.parent_assignment_id,
        retry_of_attempt_id=attempt.retry_of_attempt_id,
        summary=assignment.summary,
        instruction=assignment.instruction,
        criteria=tuple(
            AssignmentCriteriaReadback(
                slot=criterion.slot,
                version=criterion.version,
                logical_path=criterion.logical_path,
                description=criterion.description,
            )
            for criterion in criteria
        ),
        consumes=tuple(assignment.consumes_json),
        produces=tuple(assignment.produces_json),
    )
    paths = await read_task_root_paths(session, assignment.task_id)
    _replace_files(
        {
            assignment_json_path(paths=paths, attempt_id=attempt.attempt_id): (
                encode_projection_json(payload)
            ),
            assignment_markdown_path(paths=paths, attempt_id=attempt.attempt_id): (
                _assignment_markdown(payload).encode()
            ),
        }
    )
    return True


async def project_latest_checkpoint(
    session: AsyncSession,
    signal: LatestCheckpointProjection,
) -> bool:
    attempt = await session.get(AttemptModel, signal.attempt_id)
    if attempt is None or attempt.latest_checkpoint_id != signal.checkpoint_id:
        return False
    checkpoint = await session.get(AttemptCheckpointModel, signal.checkpoint_id)
    if checkpoint is None or checkpoint.attempt_id != attempt.attempt_id:
        return False
    artifacts = tuple(
        (
            await session.scalars(
                select(ArtifactPublicationModel)
                .where(ArtifactPublicationModel.checkpoint_id == checkpoint.checkpoint_id)
                .order_by(ArtifactPublicationModel.slot, ArtifactPublicationModel.version)
            )
        ).all()
    )
    transients = tuple(
        (
            await session.scalars(
                select(TransientLocalizationModel)
                .where(TransientLocalizationModel.checkpoint_id == checkpoint.checkpoint_id)
                .order_by(TransientLocalizationModel.localized_at)
            )
        ).all()
    )
    payload = LatestCheckpointReadback(
        checkpoint_id=checkpoint.checkpoint_id,
        task_id=checkpoint.task_id,
        flow_id=checkpoint.flow_id,
        assignment_id=checkpoint.assignment_id,
        attempt_id=checkpoint.attempt_id,
        authoring_dispatch_id=checkpoint.authoring_dispatch_id,
        checkpoint_kind=checkpoint.checkpoint_kind,
        outcome=checkpoint.outcome,
        summary=checkpoint.summary,
        evidence=checkpoint.evidence_json,
        criteria_results=tuple(checkpoint.criteria_results_json),
        artifacts=tuple(
            ProjectionRef(
                source_id=artifact.artifact_publication_id,
                logical_path=artifact.logical_path,
                description=artifact.description,
                slot=artifact.slot,
                version=artifact.version,
            )
            for artifact in artifacts
        ),
        transients=tuple(
            ProjectionRef(
                source_id=transient.transient_localization_id,
                logical_path=transient.localized_logical_path,
                description=transient.description,
            )
            for transient in transients
        ),
        recorded_at=checkpoint.recorded_at,
    )
    paths = await read_task_root_paths(session, checkpoint.task_id)
    _replace_files(
        {
            checkpoint_json_path(paths=paths, attempt_id=attempt.attempt_id): (
                encode_projection_json(payload)
            ),
            checkpoint_markdown_path(paths=paths, attempt_id=attempt.attempt_id): (
                _checkpoint_markdown(payload).encode()
            ),
        }
    )
    return True


async def project_artifact_index(session: AsyncSession, signal: ArtifactProjection) -> bool:
    publication = await session.get(
        ArtifactPublicationModel,
        signal.artifact_publication_id,
    )
    if publication is None or publication.version != signal.version:
        return False
    pointer = await session.scalar(
        select(ArtifactCurrentPointerModel).where(
            ArtifactCurrentPointerModel.current_publication_id
            == publication.artifact_publication_id,
            ArtifactCurrentPointerModel.current_version == publication.version,
        )
    )
    if pointer is None:
        return False
    publications = tuple(
        (
            await session.scalars(
                select(ArtifactPublicationModel)
                .where(ArtifactPublicationModel.attempt_id == publication.attempt_id)
                .order_by(ArtifactPublicationModel.slot, ArtifactPublicationModel.version)
            )
        ).all()
    )
    current_ids = set(
        (
            await session.scalars(
                select(ArtifactCurrentPointerModel.current_publication_id).where(
                    ArtifactCurrentPointerModel.assignment_id == publication.assignment_id
                )
            )
        ).all()
    )
    payload = ArtifactIndexReadback(
        task_id=publication.task_id,
        assignment_id=publication.assignment_id,
        attempt_id=publication.attempt_id,
        publications=tuple(
            ArtifactIndexEntry(
                artifact_publication_id=item.artifact_publication_id,
                checkpoint_id=item.checkpoint_id,
                slot=item.slot,
                version=item.version,
                logical_path=item.logical_path,
                description=item.description,
                supersedes_publication_id=item.supersedes_publication_id,
                supersedes_version=item.supersedes_version,
                is_current=item.artifact_publication_id in current_ids,
                published_at=item.published_at,
            )
            for item in publications
        ),
    )
    paths = await read_task_root_paths(session, publication.task_id)
    _replace_files(
        {
            artifact_index_json_path(paths=paths, attempt_id=publication.attempt_id): (
                encode_projection_json(payload)
            )
        }
    )
    return True


async def project_transient_index(
    session: AsyncSession,
    signal: TransientProjection,
) -> bool:
    source = await session.get(
        TransientLocalizationModel,
        signal.transient_localization_id,
    )
    if source is None:
        return False
    localizations = tuple(
        (
            await session.scalars(
                select(TransientLocalizationModel)
                .where(TransientLocalizationModel.attempt_id == source.attempt_id)
                .order_by(
                    TransientLocalizationModel.localized_at,
                    TransientLocalizationModel.transient_localization_id,
                )
            )
        ).all()
    )
    payload = TransientIndexReadback(
        task_id=source.task_id,
        assignment_id=source.assignment_id,
        attempt_id=source.attempt_id,
        localizations=tuple(
            TransientIndexEntry(
                transient_localization_id=item.transient_localization_id,
                checkpoint_id=item.checkpoint_id,
                source_logical_path=item.source_logical_path,
                localized_logical_path=item.localized_logical_path,
                description=item.description,
                retention_status=item.retention_status,
                localized_at=item.localized_at,
                expires_at=item.expires_at,
                removed_at=item.removed_at,
            )
            for item in localizations
        ),
    )
    paths = await read_task_root_paths(session, source.task_id)
    _replace_files(
        {
            transient_index_json_path(paths=paths, attempt_id=source.attempt_id): (
                encode_projection_json(payload)
            )
        }
    )
    return True


def _manifest_node(node: FlowNodeModel) -> WorkflowManifestNode:
    return WorkflowManifestNode(
        node_key=node.node_key,
        parent_node_key=node.parent_node_key,
        child_node_keys=tuple(node.child_node_keys_json),
        node_kind=node.structural_kind,
        role_key=node.role_key,
        role_revision_no=node.role_revision_no,
        policy_key=node.policy_key,
        policy_revision_no=node.policy_revision_no,
        description=node.description,
        node_instruction=node.node_instruction,
        consumes=node.consumes_json,
        produces=node.produces_json,
        criteria=tuple(
            _criteria_readback(node.flow_revision_id, _CriteriaSource.model_validate(item))
            for item in node.criteria_json
        ),
    )


def _find_criterion(
    values: list[dict[str, object]],
    signal: CriteriaProjection,
) -> _CriteriaSource | None:
    for value in values:
        criterion = _CriteriaSource.model_validate(value)
        if (
            criterion.owner_node_key == signal.owner_node_key
            and criterion.slot == signal.slot
            and criterion.version == signal.version
        ):
            return criterion
    return None


def _criteria_readback(flow_revision_id: str, source: _CriteriaSource) -> CriteriaReadback:
    return CriteriaReadback(
        flow_revision_id=flow_revision_id,
        owner_node_key=source.owner_node_key,
        slot=source.slot,
        version=source.version,
        description=source.description,
        criteria=source.criteria,
        logical_path=source.path,
    )


def _replace_files(files: Mapping[Path, bytes]) -> None:
    replace_projection_files(files)


def _manifest_markdown(payload: WorkflowManifestReadback) -> str:
    lines = [
        "# Workflow manifest",
        "",
        f"- Flow: `{payload.flow_id}`",
        f"- Active revision: `{payload.active_flow_revision_id}`",
        f"- Workflow: `{payload.workflow_key or 'unspecified'}`",
        "",
        "## Nodes",
    ]
    for node in payload.nodes:
        lines.extend(
            [
                "",
                f"### {node.node_key}",
                "",
                f"- Kind: `{node.node_kind}`",
                f"- Parent: `{node.parent_node_key or 'none'}`",
                f"- Role: `{node.role_key}` revision {node.role_revision_no}",
                f"- Policy: `{node.policy_key}` revision {node.policy_revision_no}",
                f"- Description: {node.description}",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _criteria_markdown(payload: CriteriaReadback) -> str:
    lines = [f"# {payload.slot}", "", payload.description, ""]
    lines.extend(f"- {criterion}" for criterion in payload.criteria)
    return "\n".join(lines).rstrip() + "\n"


def _assignment_markdown(payload: AttemptAssignmentReadback) -> str:
    lines = [
        "# Assignment",
        "",
        f"- Assignment: `{payload.assignment_id}`",
        f"- Attempt: `{payload.attempt_id}`",
        f"- Flow revision: `{payload.flow_revision_id}`",
        f"- Node: `{payload.node_key}`",
        "",
        "## Summary",
        "",
        payload.summary,
    ]
    if payload.instruction:
        lines.extend(["", "## Instruction", "", payload.instruction])
    return "\n".join(lines).rstrip() + "\n"


def _checkpoint_markdown(payload: LatestCheckpointReadback) -> str:
    lines = [
        "# Latest checkpoint",
        "",
        f"- Checkpoint: `{payload.checkpoint_id}`",
        f"- Attempt: `{payload.attempt_id}`",
        f"- Kind: `{payload.checkpoint_kind}`",
        f"- Outcome: `{payload.outcome or 'none'}`",
        "",
        "## Summary",
        "",
        payload.summary,
    ]
    if payload.evidence:
        lines.extend(
            ["", "## Evidence", "", "```json", json.dumps(payload.evidence, sort_keys=True), "```"]
        )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "project_artifact_index",
    "project_attempt_assignment",
    "project_criteria",
    "project_latest_checkpoint",
    "project_support_signal",
    "project_transient_index",
    "project_workflow_manifest",
]
