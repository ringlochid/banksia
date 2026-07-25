from __future__ import annotations

from typing import cast

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.operator.contracts import OperatorConversationView
from banksia.operator.effect_results import (
    build_immediate_effect_outcome,
    create_edit_undo_effect,
    effect_resource,
    effect_success_summary,
)
from banksia.operator.errors import (
    action_not_current,
    confirmation_not_found,
    effect_in_progress,
    idempotency_conflict,
)
from banksia.operator.operations import OperatorOperationExecutor, OperatorOperationName
from banksia.operator.operations.executor import (
    OPERATOR_TOOL_RESULT_ADAPTER,
    OperatorOperationScope,
    OperatorToolFailureResult,
    OperatorToolProposalResult,
    OperatorToolResult,
    OperatorToolSuccessResult,
    PreparedOperatorEffect,
)
from banksia.operator.storage import (
    OperatorConversationReader,
    OperatorSessionFactory,
    allocate_operator_id,
    create_operator_entry,
    digest_operator_request,
    model_payload,
)
from banksia.persistence.models import (
    OperatorConversationModel,
    OperatorEffectModel,
    OperatorInvocationModel,
)
from banksia.runtime.clock import utc_now


class OperatorEffectService:
    def __init__(
        self,
        *,
        session_factory: OperatorSessionFactory,
        reader: OperatorConversationReader,
        executor: OperatorOperationExecutor,
    ) -> None:
        self._session_factory = session_factory
        self._reader = reader
        self._executor = executor

    async def validate_operation_scope(
        self,
        scope: OperatorOperationScope,
    ) -> None:
        async with self._session_factory() as session:
            await self._validate_scope(session, scope, should_lock=False)

    async def propose_effect(
        self,
        *,
        scope: OperatorOperationScope,
        provider_call_id: str,
        operation: OperatorOperationName,
        request: BaseModel,
        guard: str | None,
        label: str,
        resource_scope: str,
        consequence: str,
    ) -> OperatorToolResult:
        request_payload = model_payload(request)
        digest = digest_operator_request(operation, provider_call_id, request_payload)
        async with self._session_factory() as session:
            async with session.begin():
                conversation, invocation = await self._validate_scope(session, scope)
                existing = await session.scalar(
                    select(OperatorEffectModel).where(
                        OperatorEffectModel.invocation_id == scope.invocation_id,
                        OperatorEffectModel.provider_call_id == provider_call_id,
                    )
                )
                if existing is not None:
                    return self._replay_effect(existing, operation, digest)
                confirmation_id = allocate_operator_id("confirm")
                proposal = OperatorToolProposalResult(
                    confirmation_id=confirmation_id,
                    label=label,
                    scope=resource_scope,
                    consequence=consequence,
                )
                entry = create_operator_entry(
                    conversation,
                    kind="action_proposal",
                    body={
                        "confirmation_id": confirmation_id,
                        "label": label,
                        "scope": resource_scope,
                        "consequence": consequence,
                    },
                )
                session.add(entry)
                session.add(
                    OperatorEffectModel(
                        effect_id=allocate_operator_id("effect"),
                        conversation_id=conversation.conversation_id,
                        invocation_id=invocation.invocation_id,
                        provider_call_id=provider_call_id,
                        operation=operation,
                        request_json=request_payload,
                        request_digest=digest,
                        action_guard=guard,
                        state="proposed",
                        confirmation_id=confirmation_id,
                        confirmation_state="available",
                        result_entry_id=entry.entry_id,
                        result_json=model_payload(proposal),
                    )
                )
            return proposal

    async def prepare_immediate_effect(
        self,
        *,
        scope: OperatorOperationScope,
        provider_call_id: str,
        operation: OperatorOperationName,
        request: BaseModel,
        guard: str | None,
    ) -> PreparedOperatorEffect:
        request_payload = model_payload(request)
        digest = digest_operator_request(operation, provider_call_id, request_payload)
        async with self._session_factory() as session:
            async with session.begin():
                conversation, invocation = await self._validate_scope(session, scope)
                existing = await session.scalar(
                    select(OperatorEffectModel).where(
                        OperatorEffectModel.invocation_id == scope.invocation_id,
                        OperatorEffectModel.provider_call_id == provider_call_id,
                    )
                )
                if existing is not None:
                    result = self._replay_effect(existing, operation, digest)
                    return PreparedOperatorEffect(
                        effect_id=existing.effect_id,
                        should_execute=False,
                        prior_result=result,
                    )
                effect = OperatorEffectModel(
                    effect_id=allocate_operator_id("effect"),
                    conversation_id=conversation.conversation_id,
                    invocation_id=invocation.invocation_id,
                    provider_call_id=provider_call_id,
                    operation=operation,
                    request_json=request_payload,
                    request_digest=digest,
                    action_guard=guard,
                    state="executing",
                    started_at=utc_now(),
                )
                session.add(effect)
            return PreparedOperatorEffect(
                effect_id=effect.effect_id,
                should_execute=True,
            )

    async def finish_immediate_effect(
        self,
        *,
        effect_id: str,
        result: dict[str, object] | None,
        failure_problem: str | None,
    ) -> OperatorToolResult:
        async with self._session_factory() as session:
            async with session.begin():
                effect = await session.get(
                    OperatorEffectModel,
                    effect_id,
                    with_for_update=True,
                )
                if effect is None:
                    raise RuntimeError("Operator effect disappeared before completion")
                if effect.state != "executing":
                    return self._stored_tool_result(effect)
                conversation = await session.get(
                    OperatorConversationModel,
                    effect.conversation_id,
                    with_for_update=True,
                )
                if conversation is None:
                    raise RuntimeError("Operator effect lost its conversation")
                tool_result, receipt_body = build_immediate_effect_outcome(
                    effect=effect,
                    result=result,
                    failure_problem=failure_problem,
                )
                undo_effect = create_edit_undo_effect(
                    effect=effect,
                    result=result,
                    receipt_body=receipt_body,
                )
                receipt = create_operator_entry(
                    conversation,
                    kind="effect_receipt",
                    body=receipt_body,
                )
                session.add(receipt)
                if undo_effect is not None:
                    session.add(undo_effect)
                effect.state = "succeeded" if failure_problem is None else "failed"
                effect.result_entry_id = receipt.entry_id
                effect.result_json = model_payload(tool_result)
                effect.ended_at = utc_now()
            return tool_result

    async def confirm_effect(
        self,
        *,
        conversation_id: str,
        confirmation_id: str,
        idempotency_key: str,
    ) -> OperatorConversationView:
        digest = digest_operator_request(
            "confirmation",
            f"{conversation_id}:{confirmation_id}",
            {},
        )
        effect = await self._read_confirmation(conversation_id, confirmation_id)
        replay = await self._confirmation_replay(
            effect,
            idempotency_key=idempotency_key,
            digest=digest,
        )
        if replay is not None:
            return replay
        operation = cast(OperatorOperationName, effect.operation)
        request = self._executor.parse_request(operation, effect.request_json)
        if not await self._executor.is_guard_current(
            operation,
            request,
            effect.action_guard,
        ):
            await self._expire_confirmation(effect.effect_id)
            raise action_not_current(await self._reader.read_view(conversation_id))
        is_claimed = await self._claim_confirmation(
            effect_id=effect.effect_id,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            digest=digest,
        )
        if not is_claimed:
            current_effect = await self._read_confirmation(
                conversation_id,
                confirmation_id,
            )
            replay = await self._confirmation_replay(
                current_effect,
                idempotency_key=idempotency_key,
                digest=digest,
            )
            if replay is not None:
                return replay
            raise action_not_current(await self._reader.read_view(conversation_id))
        try:
            result = await self._executor.execute_confirmed(
                operation,
                request,
                effect.action_guard,
            )
        except Exception:
            await self._finish_confirmation(
                effect.effect_id,
                result=None,
                state="failed",
            )
        except BaseException:
            await self._finish_confirmation(
                effect.effect_id,
                result=None,
                state="indeterminate",
            )
            raise
        else:
            await self._finish_confirmation(
                effect.effect_id,
                result=result,
                state="succeeded",
            )
        return await self._reader.read_view(conversation_id)

    async def recover_executing_effects(self) -> frozenset[str]:
        async with self._session_factory() as session:
            async with session.begin():
                crossed_invocations = set(
                    (
                        await session.scalars(
                            select(OperatorEffectModel.invocation_id).where(
                                OperatorEffectModel.state.in_(
                                    ("executing", "succeeded", "failed", "indeterminate")
                                )
                            )
                        )
                    ).all()
                )
                effects = tuple(
                    (
                        await session.scalars(
                            select(OperatorEffectModel).where(
                                OperatorEffectModel.state == "executing"
                            )
                        )
                    ).all()
                )
                for effect in effects:
                    crossed_invocations.add(effect.invocation_id)
                    conversation = await session.get(
                        OperatorConversationModel,
                        effect.conversation_id,
                        with_for_update=True,
                    )
                    invocation = await session.get(
                        OperatorInvocationModel,
                        effect.invocation_id,
                    )
                    if conversation is None or invocation is None:
                        continue
                    receipt = create_operator_entry(
                        conversation,
                        kind="effect_receipt",
                        body={
                            "summary": (
                                "Banksia could not prove whether the requested action "
                                "completed. Refresh the owning resource before acting."
                            )
                        },
                    )
                    session.add(receipt)
                    effect.state = "indeterminate"
                    effect.result_entry_id = receipt.entry_id
                    effect.result_json = model_payload(
                        OperatorToolFailureResult(
                            problem="operator_effect_indeterminate",
                        )
                    )
                    effect.ended_at = utc_now()
                    if invocation.state not in {"queued", "running"}:
                        conversation.state = "ready"
                        conversation.updated_at = utc_now()
        return frozenset(crossed_invocations)

    async def _validate_scope(
        self,
        session: AsyncSession,
        scope: OperatorOperationScope,
        *,
        should_lock: bool = True,
    ) -> tuple[OperatorConversationModel, OperatorInvocationModel]:
        conversation = await session.get(
            OperatorConversationModel,
            scope.conversation_id,
            with_for_update=should_lock,
        )
        invocation = await session.get(
            OperatorInvocationModel,
            scope.invocation_id,
            with_for_update=should_lock,
        )
        if (
            conversation is None
            or invocation is None
            or invocation.conversation_id != conversation.conversation_id
            or conversation.state != "running"
            or invocation.state != "running"
            or invocation.claim_generation != scope.claim_generation
            or conversation.claim_generation != scope.claim_generation
        ):
            raise RuntimeError("stale or cross-conversation Operator operation")
        return conversation, invocation

    def _replay_effect(
        self,
        effect: OperatorEffectModel,
        operation: OperatorOperationName,
        digest: str,
    ) -> OperatorToolResult:
        if effect.operation != operation or effect.request_digest != digest:
            return OperatorToolFailureResult(
                problem="operator_provider_call_conflict",
            )
        if effect.state == "executing":
            return OperatorToolFailureResult(problem="effect_in_progress")
        return self._stored_tool_result(effect)

    def _stored_tool_result(self, effect: OperatorEffectModel) -> OperatorToolResult:
        if effect.result_json is None:
            return OperatorToolFailureResult(
                problem="operator_effect_indeterminate",
            )
        return OPERATOR_TOOL_RESULT_ADAPTER.validate_python(effect.result_json)

    async def _read_confirmation(
        self,
        conversation_id: str,
        confirmation_id: str,
    ) -> OperatorEffectModel:
        async with self._session_factory() as session:
            effect = await session.scalar(
                select(OperatorEffectModel).where(
                    OperatorEffectModel.conversation_id == conversation_id,
                    OperatorEffectModel.confirmation_id == confirmation_id,
                )
            )
            if effect is None:
                raise confirmation_not_found()
            session.expunge(effect)
            return effect

    async def _confirmation_replay(
        self,
        effect: OperatorEffectModel,
        *,
        idempotency_key: str,
        digest: str,
    ) -> OperatorConversationView | None:
        if effect.confirmation_idempotency_key is None:
            if effect.state != "proposed" or effect.confirmation_state != "available":
                raise action_not_current(await self._reader.read_view(effect.conversation_id))
            return None
        if effect.confirmation_idempotency_key != idempotency_key:
            raise action_not_current(await self._reader.read_view(effect.conversation_id))
        if effect.confirmation_request_digest != digest:
            raise idempotency_conflict()
        if effect.state == "executing":
            raise effect_in_progress(await self._reader.read_view(effect.conversation_id))
        return await self._reader.read_view(effect.conversation_id)

    async def _expire_confirmation(self, effect_id: str) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                effect = await session.get(
                    OperatorEffectModel,
                    effect_id,
                    with_for_update=True,
                )
                if effect is None or effect.state != "proposed":
                    return
                effect.state = "failed"
                effect.confirmation_state = "expired"
                effect.ended_at = utc_now()

    async def _claim_confirmation(
        self,
        *,
        effect_id: str,
        conversation_id: str,
        idempotency_key: str,
        digest: str,
    ) -> bool:
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    effect_claim = (
                        await session.execute(
                            update(OperatorEffectModel)
                            .where(
                                OperatorEffectModel.effect_id == effect_id,
                                OperatorEffectModel.conversation_id == conversation_id,
                                OperatorEffectModel.state == "proposed",
                                OperatorEffectModel.confirmation_state == "available",
                            )
                            .values(
                                state="executing",
                                confirmation_state="consumed",
                                confirmation_idempotency_key=idempotency_key,
                                confirmation_request_digest=digest,
                                started_at=utc_now(),
                            )
                            .returning(OperatorEffectModel.effect_id)
                            .execution_options(synchronize_session=False)
                        )
                    ).one_or_none()
                    if effect_claim is None:
                        raise OperatorClaimLostError
                    conversation_claim = (
                        await session.execute(
                            update(OperatorConversationModel)
                            .where(
                                OperatorConversationModel.conversation_id == conversation_id,
                                OperatorConversationModel.state == "ready",
                            )
                            .values(
                                state="running",
                                claim_generation=(OperatorConversationModel.claim_generation + 1),
                                updated_at=utc_now(),
                            )
                            .returning(OperatorConversationModel.conversation_id)
                            .execution_options(synchronize_session=False)
                        )
                    ).one_or_none()
                    if conversation_claim is None:
                        raise OperatorClaimLostError
        except OperatorClaimLostError:
            return False
        return True

    async def _finish_confirmation(
        self,
        effect_id: str,
        *,
        result: dict[str, object] | None,
        state: str,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                effect = await session.get(
                    OperatorEffectModel,
                    effect_id,
                    with_for_update=True,
                )
                if effect is None or effect.state != "executing":
                    return
                conversation = await session.get(
                    OperatorConversationModel,
                    effect.conversation_id,
                    with_for_update=True,
                )
                if conversation is None:
                    return
                summary = (
                    effect_success_summary(effect.operation)
                    if state == "succeeded"
                    else (
                        "Banksia could not prove whether the requested action completed."
                        if state == "indeterminate"
                        else "Banksia could not apply the requested action."
                    )
                )
                body: dict[str, object] = {"summary": summary}
                if result is not None:
                    body.update(effect_resource(effect.operation, result))
                receipt = create_operator_entry(
                    conversation,
                    kind="effect_receipt",
                    body=body,
                )
                session.add(receipt)
                effect.state = state
                effect.result_entry_id = receipt.entry_id
                effect.result_json = (
                    model_payload(OperatorToolSuccessResult(result=result))
                    if result is not None
                    else model_payload(
                        OperatorToolFailureResult(
                            problem=f"operator_effect_{state}",
                        )
                    )
                )
                effect.ended_at = utc_now()
                conversation.state = "ready"
                conversation.updated_at = utc_now()


class OperatorClaimLostError(Exception):
    pass


__all__ = ["OperatorEffectService"]
