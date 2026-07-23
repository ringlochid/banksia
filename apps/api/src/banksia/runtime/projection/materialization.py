from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.models import FlowModel, FlowRevisionModel
from banksia.runtime.projection.signals import (
    SupportProjectionSignal,
    WorkflowManifestProjection,
)
from banksia.runtime.task_root.reads import read_task_root_paths
from banksia.runtime.task_root.writes import replace_projection_files
from banksia.runtime.team import render_current_team_manifest


async def project_support_signal(
    session: AsyncSession,
    signal: SupportProjectionSignal,
) -> None:
    """Materialize the one retained controller projection from a fresh read."""

    if not isinstance(signal, WorkflowManifestProjection):
        raise TypeError(f"unsupported support projection signal: {type(signal).__name__}")
    await project_workflow_manifest(session, signal)


async def project_workflow_manifest(
    session: AsyncSession,
    signal: WorkflowManifestProjection,
) -> bool:
    flow = await session.get(FlowModel, signal.flow_id)
    if flow is None or flow.active_flow_revision_id != signal.active_flow_revision_id:
        return False
    revision = await session.get(FlowRevisionModel, signal.active_flow_revision_id)
    if revision is None or revision.flow_id != flow.flow_id:
        return False

    content = await render_current_team_manifest(session, task_id=flow.task_id)
    paths = await read_task_root_paths(session, flow.task_id)
    replace_projection_files({paths.task_root / "manifest.md": content.encode()})
    return True


__all__ = ["project_support_signal", "project_workflow_manifest"]
