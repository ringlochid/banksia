from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from autoclaw.persistence import RuntimeBase
from autoclaw.persistence.models import (
    AttemptCheckpointModel,
    DispatchTurnModel,
    FlowModel,
    FlowNodeModel,
    FlowRevisionModel,
)
from autoclaw.runtime.contracts.operation_failure import OperationFailureCode
from autoclaw.runtime.dispatch.authority import read_node_operation_authority
from autoclaw.runtime.errors import RuntimeOperationError
from autoclaw.runtime.node_operations.contracts import AddChildRequest, NodeOperationName
from autoclaw.runtime.node_operations.structural_revisions import adopt_structural_revision
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.helpers.executor_harness import (
    synchronized_transition_claims,
)
from tests.integration.runtime.node_operations.structural_revision_fixture import (
    StructuralRevisionContext,
    seeded_structural_revision_context,
)


async def test_exact_dispatch_cas_rejects_stale_d1_without_revision(
    tmp_path: Path,
) -> None:
    async with seeded_structural_revision_context(tmp_path, suffix="stale-d1") as context:
        async with context.session_factory() as session:
            authority = await read_node_operation_authority(
                cast(AsyncSession, session),
                context.scope,
            )
        now = datetime.now(tz=UTC)
        with context.engine.begin() as connection:
            dispatches = RuntimeBase.metadata.tables["dispatch_turns"]
            flows = RuntimeBase.metadata.tables["flows"]
            connection.execute(
                dispatches.update()
                .where(dispatches.c.dispatch_id == context.ids.current_dispatch_id)
                .values(status="closed", closed_at=now, closed_reason="boundary")
            )
            connection.execute(
                flows.update()
                .where(flows.c.flow_id == context.ids.flow_id)
                .values(current_dispatch_id=None)
            )
        request = _add_request(context.ids.flow_revision_id, "stale_candidate")
        with pytest.raises(RuntimeOperationError) as stale:
            async with context.session_factory() as session:
                await adopt_structural_revision(
                    cast(AsyncSession, session),
                    authority,
                    NodeOperationName.ADD_CHILD,
                    request,
                )

        assert stale.value.code.value == "conflict"
        assert stale.value.is_retryable is False
        assert await _revision_count(context) == 1


async def test_admitted_read_activity_does_not_invalidate_structural_adoption(
    tmp_path: Path,
) -> None:
    async with seeded_structural_revision_context(
        tmp_path,
        suffix="activity-independent",
    ) as context:
        async with context.session_factory() as session:
            authority = await read_node_operation_authority(
                cast(AsyncSession, session),
                context.scope,
            )

        await context.executor.execute(
            scope=context.scope,
            operation_name="get_current_context",
            arguments={},
        )
        async with context.session_factory() as session:
            result = await adopt_structural_revision(
                cast(AsyncSession, session),
                authority,
                NodeOperationName.ADD_CHILD,
                _add_request(context.ids.flow_revision_id, "activity_safe"),
            )

        assert result.response.model_dump()["target_node_key"] == "activity_safe"
        assert await _revision_count(context) == 2


async def test_terminal_checkpoint_rejects_structural_adoption_after_admission(
    tmp_path: Path,
) -> None:
    async with seeded_structural_revision_context(
        tmp_path,
        suffix="terminal-structure",
    ) as context:
        await context.executor.execute(
            scope=context.scope,
            operation_name="record_checkpoint",
            arguments={
                "checkpoint": {
                    "checkpoint_kind": "terminal",
                    "outcome": "blocked",
                    "handoff": {
                        "summary": "The current assignment is blocked.",
                        "next_step": "Return the matching boundary.",
                    },
                }
            },
        )
        current_context = await context.executor.execute(
            scope=context.scope,
            operation_name="get_current_context",
            arguments={},
        )

        with pytest.raises(RuntimeOperationError) as error:
            await context.executor.execute(
                scope=context.scope,
                operation_name="add_child",
                arguments=_add_request(
                    context.ids.flow_revision_id,
                    "terminal_candidate",
                ).model_dump(mode="json"),
            )

        async with context.session_factory() as session:
            dispatch = await session.get(
                DispatchTurnModel,
                context.ids.current_dispatch_id,
            )

        assert error.value.code == OperationFailureCode.ILLEGAL_STATE
        assert error.value.is_retryable is False
        assert "add_child" not in current_context.model_dump(mode="json")["allowed_actions"]
        assert dispatch is not None and dispatch.node_activity_revision == 3
        assert await _revision_count(context) == 1


async def test_structural_adoption_and_terminal_checkpoint_have_one_winner(
    tmp_path: Path,
) -> None:
    async with seeded_structural_revision_context(
        tmp_path,
        suffix="structure-terminal-race",
    ) as context:
        async with synchronized_transition_claims():
            results = await asyncio.wait_for(
                asyncio.gather(
                    context.executor.execute(
                        scope=context.scope,
                        operation_name="add_child",
                        arguments=_add_request(
                            context.ids.flow_revision_id,
                            "race_candidate",
                        ).model_dump(mode="json"),
                    ),
                    context.executor.execute(
                        scope=context.scope,
                        operation_name="record_checkpoint",
                        arguments={
                            "checkpoint": {
                                "checkpoint_kind": "terminal",
                                "outcome": "blocked",
                                "handoff": {
                                    "summary": "The current assignment is blocked.",
                                    "next_step": "Return the matching boundary.",
                                },
                            }
                        },
                    ),
                    return_exceptions=True,
                ),
                timeout=5,
            )

        errors = [result for result in results if isinstance(result, BaseException)]
        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeOperationError)
        assert errors[0].code == OperationFailureCode.CONFLICT
        async with context.session_factory() as session:
            checkpoint_count = await session.scalar(
                select(func.count())
                .select_from(AttemptCheckpointModel)
                .where(
                    AttemptCheckpointModel.authoring_dispatch_id == context.ids.current_dispatch_id
                )
            )
        revision_count = await _revision_count(context)
        assert (revision_count, int(checkpoint_count or 0)) in {(2, 0), (1, 1)}


async def test_stale_candidates_have_one_winner_and_no_orphan_revision_rows(
    tmp_path: Path,
) -> None:
    async with seeded_structural_revision_context(tmp_path, suffix="winner") as context:
        async with context.session_factory() as session:
            first_authority = await read_node_operation_authority(
                cast(AsyncSession, session),
                context.scope,
            )
        async with context.session_factory() as session:
            second_authority = await read_node_operation_authority(
                cast(AsyncSession, session),
                context.scope,
            )
        request = _add_request(context.ids.flow_revision_id, "only_winner")
        async with context.session_factory() as session:
            await adopt_structural_revision(
                cast(AsyncSession, session),
                first_authority,
                NodeOperationName.ADD_CHILD,
                request,
            )
        with pytest.raises(RuntimeOperationError) as loser:
            async with context.session_factory() as session:
                await adopt_structural_revision(
                    cast(AsyncSession, session),
                    second_authority,
                    NodeOperationName.ADD_CHILD,
                    request,
                )

        assert loser.value.code.value == "conflict"
        assert loser.value.is_retryable is False
        assert await _revision_count(context) == 2
        async with context.session_factory() as session:
            revisions = list(
                await session.scalars(
                    select(FlowRevisionModel).order_by(FlowRevisionModel.revision_index)
                )
            )
            active = await session.get(FlowModel, context.ids.flow_id)
            node_count = await session.scalar(select(func.count()).select_from(FlowNodeModel))
        assert active is not None
        assert active.active_flow_revision_id == revisions[-1].flow_revision_id
        assert node_count == 8 + 9


def _add_request(revision_id: str, node_key: str) -> AddChildRequest:
    return AddChildRequest.model_validate(
        {
            "expected_structural_revision_id": revision_id,
            "payload": {
                "target_parent_node_key": "branch",
                "child": {
                    "node_key": node_key,
                    "role": "role.target",
                    "policy": "policy.target",
                    "description": f"{node_key} worker.",
                },
            },
        }
    )


async def _revision_count(context: StructuralRevisionContext) -> int:
    async with context.session_factory() as session:
        value = await session.scalar(select(func.count()).select_from(FlowRevisionModel))
    return int(value or 0)
