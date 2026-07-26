"""Provider-neutral published Workflow fixture for generic behavior tests."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from banksia.workflows import (
    NormalizedMember,
    NormalizedWorkflow,
    PublishedWorkflowRevision,
    WorkflowProvenance,
)
from banksia.workflows.publication import publish_workflow_revision

GENERIC_WORKFLOW_ID = "generic-test-workflow"
GENERIC_BRANCHING_WORKFLOW_ID = "generic-branching-test-workflow"

_GENERIC_WORKFLOW = NormalizedWorkflow(
    kind="workflow",
    id=GENERIC_WORKFLOW_ID,
    description="Coordinate one bounded test assignment.",
    note="Keep the root and child responsibilities distinct.",
    lead=NormalizedMember(
        id="coordinator",
        title="Coordinator",
        description="Own the integrated result.",
        instruction="Coordinate the bounded work and integrate the result.",
        children=(
            NormalizedMember(
                id="worker",
                title="Worker",
                description="Own one bounded contribution.",
                instruction="Complete the assigned contribution and return the result.",
            ),
        ),
    ),
)

_GENERIC_BRANCHING_WORKFLOW = NormalizedWorkflow(
    kind="workflow",
    id=GENERIC_BRANCHING_WORKFLOW_ID,
    description="Coordinate nested and sibling test contributions.",
    note="Treat the nested contributions and peer review as distinct inputs.",
    lead=NormalizedMember(
        id="coordinator",
        title="Coordinator",
        description="Own the integrated result.",
        instruction="Coordinate the bounded work and integrate the contributions.",
        children=(
            NormalizedMember(
                id="branch-coordinator",
                title="Branch coordinator",
                description="Own one nested responsibility branch.",
                instruction="Coordinate the two bounded branch contributions.",
                children=(
                    NormalizedMember(
                        id="first-contributor",
                        title="First contributor",
                        description="Own the first bounded contribution.",
                        instruction="Complete the first contribution and return the result.",
                    ),
                    NormalizedMember(
                        id="second-contributor",
                        title="Second contributor",
                        description="Own the second bounded contribution.",
                        instruction="Complete the second contribution and return the result.",
                    ),
                ),
            ),
            NormalizedMember(
                id="peer-reviewer",
                title="Peer reviewer",
                description="Review the integrated result independently.",
                instruction="Return an independent review of the result.",
            ),
        ),
    ),
)


async def publish_generic_workflow(
    session_factory: async_sessionmaker[AsyncSession],
) -> PublishedWorkflowRevision:
    """Publish the ordinary two-member generic Workflow."""
    return await _publish_test_workflow(
        session_factory,
        workflow=_GENERIC_WORKFLOW,
    )


async def publish_generic_branching_workflow(
    session_factory: async_sessionmaker[AsyncSession],
) -> PublishedWorkflowRevision:
    """Publish the five-member generic branching Workflow."""
    return await _publish_test_workflow(
        session_factory,
        workflow=_GENERIC_BRANCHING_WORKFLOW,
    )


async def _publish_test_workflow(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow: NormalizedWorkflow,
) -> PublishedWorkflowRevision:
    async with session_factory() as session:
        published = await publish_workflow_revision(
            session,
            workflow=workflow,
            provenance=WorkflowProvenance.USER,
            should_update_current=True,
        )
        await session.commit()
        return published


__all__ = [
    "GENERIC_BRANCHING_WORKFLOW_ID",
    "GENERIC_WORKFLOW_ID",
    "publish_generic_branching_workflow",
    "publish_generic_workflow",
]
