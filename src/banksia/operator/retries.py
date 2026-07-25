from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.operator.storage import OperatorSessionFactory
from banksia.persistence.models import (
    OperatorConversationModel,
    OperatorEffectModel,
    OperatorInvocationModel,
)
from banksia.runtime.clock import utc_now


class OperatorRetryClaimLostError(Exception):
    pass


async def store_operator_retry_invocation(
    session_factory: OperatorSessionFactory,
    *,
    conversation_id: str,
    invocation_id: str,
    idempotency_key: str,
    digest: str,
) -> bool:
    now = utc_now()
    async with session_factory() as session:
        async with session.begin():
            retry_basis = await _claim_retry_basis(
                session,
                conversation_id=conversation_id,
                now=now,
            )
            if retry_basis is None:
                return False
            latest, claim_generation = retry_basis
            await session.execute(
                update(OperatorEffectModel)
                .where(
                    OperatorEffectModel.invocation_id == latest.invocation_id,
                    OperatorEffectModel.state == "proposed",
                    OperatorEffectModel.confirmation_state == "available",
                )
                .values(
                    state="failed",
                    confirmation_state="expired",
                    ended_at=now,
                )
            )
            session.add(
                OperatorInvocationModel(
                    invocation_id=invocation_id,
                    conversation_id=conversation_id,
                    input_entry_id=latest.input_entry_id,
                    retry_basis_invocation_id=latest.invocation_id,
                    state="queued",
                    claim_generation=claim_generation,
                    provider_input=latest.provider_input,
                    retry_idempotency_key=idempotency_key,
                    retry_request_digest=digest,
                )
            )
    return True


async def _claim_retry_basis(
    session: AsyncSession,
    *,
    conversation_id: str,
    now: datetime,
) -> tuple[OperatorInvocationModel, int] | None:
    latest_invocation_id = (
        select(OperatorInvocationModel.invocation_id)
        .where(OperatorInvocationModel.conversation_id == conversation_id)
        .order_by(
            desc(OperatorInvocationModel.created_at),
            desc(OperatorInvocationModel.invocation_id),
        )
        .limit(1)
        .scalar_subquery()
    )
    retryable_latest = exists(
        select(OperatorInvocationModel.invocation_id).where(
            OperatorInvocationModel.invocation_id == latest_invocation_id,
            OperatorInvocationModel.state == "failed",
            OperatorInvocationModel.is_retry_safe.is_(True),
        )
    )
    claim = (
        await session.execute(
            update(OperatorConversationModel)
            .where(
                OperatorConversationModel.conversation_id == conversation_id,
                OperatorConversationModel.state == "failed",
                retryable_latest,
            )
            .values(
                state="running",
                claim_generation=(OperatorConversationModel.claim_generation + 1),
                updated_at=now,
            )
            .returning(OperatorConversationModel.claim_generation)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    if claim is None:
        return None
    latest = await session.scalar(
        select(OperatorInvocationModel).where(
            OperatorInvocationModel.invocation_id == latest_invocation_id
        )
    )
    if latest is None or latest.state != "failed" or not latest.is_retry_safe:
        raise OperatorRetryClaimLostError
    return latest, claim.claim_generation


__all__ = [
    "OperatorRetryClaimLostError",
    "store_operator_retry_invocation",
]
