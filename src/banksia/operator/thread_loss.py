from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.operator.failure_entries import build_provider_failure_body
from banksia.operator.provider import OperatorProviderInvocation
from banksia.operator.storage import (
    OperatorSessionFactory,
    create_operator_entry_at_sequence,
)
from banksia.persistence.models import (
    OperatorConversationModel,
    OperatorEffectModel,
    OperatorInvocationModel,
)
from banksia.runtime.clock import utc_now


class OperatorThreadLossClaimLostError(Exception):
    pass


async def finalize_operator_thread_loss(
    session_factory: OperatorSessionFactory,
    invocation: OperatorProviderInvocation,
    *,
    problem: str,
    explanation: str,
    provider_turn_reference: str | None = None,
) -> None:
    async with session_factory() as session:
        try:
            async with session.begin():
                input_entry_id = await _claim_lost_thread_invocation(
                    session,
                    invocation,
                    problem=problem,
                    provider_turn_reference=provider_turn_reference,
                )
                if input_entry_id is None:
                    return
                next_entry_sequence = await _claim_lost_thread_conversation(
                    session,
                    invocation,
                )
                if next_entry_sequence is None:
                    raise OperatorThreadLossClaimLostError
                await _expire_thread_actions(session, invocation.invocation_id)
                session.add(
                    create_operator_entry_at_sequence(
                        conversation_id=invocation.conversation_id,
                        sequence=next_entry_sequence - 1,
                        kind="recoverable_error",
                        body=build_provider_failure_body(
                            invocation.conversation_id,
                            problem=problem,
                            explanation=explanation,
                            is_thread_lost=True,
                        ),
                        causal_entry_id=input_entry_id,
                    )
                )
        except OperatorThreadLossClaimLostError:
            return


async def _claim_lost_thread_invocation(
    session: AsyncSession,
    invocation: OperatorProviderInvocation,
    *,
    problem: str,
    provider_turn_reference: str | None,
) -> str | None:
    claimed = (
        await session.execute(
            update(OperatorInvocationModel)
            .where(
                OperatorInvocationModel.invocation_id == invocation.invocation_id,
                OperatorInvocationModel.conversation_id == invocation.conversation_id,
                OperatorInvocationModel.claim_generation == invocation.claim_generation,
                OperatorInvocationModel.state == "running",
            )
            .values(
                state="provider_thread_lost",
                provider_turn_reference=provider_turn_reference,
                failure_problem=problem,
                is_retry_safe=False,
                ended_at=utc_now(),
            )
            .returning(OperatorInvocationModel.input_entry_id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if claimed is None else claimed.input_entry_id


async def _claim_lost_thread_conversation(
    session: AsyncSession,
    invocation: OperatorProviderInvocation,
) -> int | None:
    claimed = (
        await session.execute(
            update(OperatorConversationModel)
            .where(
                OperatorConversationModel.conversation_id == invocation.conversation_id,
                OperatorConversationModel.state == "running",
                OperatorConversationModel.claim_generation == invocation.claim_generation,
            )
            .values(
                state="provider_thread_lost",
                next_entry_sequence=(OperatorConversationModel.next_entry_sequence + 1),
                updated_at=utc_now(),
            )
            .returning(OperatorConversationModel.next_entry_sequence)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    return None if claimed is None else claimed.next_entry_sequence


async def _expire_thread_actions(
    session: AsyncSession,
    invocation_id: str,
) -> None:
    await session.execute(
        update(OperatorEffectModel)
        .where(
            OperatorEffectModel.invocation_id == invocation_id,
            OperatorEffectModel.state == "proposed",
            OperatorEffectModel.confirmation_state == "available",
        )
        .values(
            state="failed",
            confirmation_state="expired",
            ended_at=utc_now(),
        )
    )


__all__ = ["finalize_operator_thread_loss"]
