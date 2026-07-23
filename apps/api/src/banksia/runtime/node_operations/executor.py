from __future__ import annotations

import logging
from collections.abc import Mapping

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.persistence.session import get_session_factory
from banksia.runtime.clock import utc_now
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.dispatch.authority import (
    NodeOperationAuthority,
    claim_exact_node_operation_transition,
    read_node_operation_authority,
    refresh_node_activity,
)
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.errors import RuntimeOperationError
from banksia.runtime.node_operations.activity import (
    NodeActivitySignal,
    NodeActivitySignalPublisher,
)
from banksia.runtime.node_operations.catalog import (
    get_node_operation_descriptor,
    list_node_operation_descriptors_for_kind,
)
from banksia.runtime.node_operations.contracts import (
    NodeOperationCapability,
    NodeOperationDescriptor,
    NodeOperationName,
    NodeOperationScope,
    OpenHumanRequestRequest,
)
from banksia.runtime.node_operations.core_handlers import execute_core_node_operation
from banksia.runtime.node_operations.follow_on import (
    CommittedNodeOperationFollowOn,
    CommittedNodeOperationResult,
    SupportProjectionPublisher,
    committed_node_operation_follow_on,
)
from banksia.runtime.node_operations.replan_replay import (
    read_committed_replan_replay,
)
from banksia.runtime.node_operations.state_legality import (
    node_operation_requires_transition_claim,
    read_node_operation_state_token,
    require_state_legal_node_operation,
)
from banksia.runtime.post_commit.publisher import RuntimeEffectPublisher

logger = logging.getLogger(__name__)
_REPLAN_OPERATION_NAMES = frozenset(
    {
        NodeOperationName.ADD_CHILD,
        NodeOperationName.UPDATE_CHILD,
        NodeOperationName.REMOVE_CHILD,
    }
)
_REPLAN_CONFLICT_NEXT_STEP = (
    "Reread the current Dispatch, workflow manifest, and owned subtree, then rebuild "
    "the mutation against fresh authority. Do not replay the closed source Dispatch."
)


class NodeOperationExecutor:
    def __init__(
        self,
        *,
        publish_activity_signal: NodeActivitySignalPublisher | None = None,
        runtime_effect_publisher: RuntimeEffectPublisher | None = None,
        support_projection_publisher: SupportProjectionPublisher | None = None,
        dispatch_opening_dependencies: DispatchOpeningDependencies | None = None,
    ) -> None:
        self._publish_activity_signal = publish_activity_signal
        self._runtime_effect_publisher = runtime_effect_publisher
        self._support_projection_publisher = support_projection_publisher
        self._dispatch_opening_dependencies = dispatch_opening_dependencies

    async def list_operations(
        self,
        scope: NodeOperationScope,
    ) -> tuple[NodeOperationDescriptor, ...]:
        session_factory = get_session_factory()
        async with session_factory() as session:
            authority = await read_node_operation_authority(session, scope)
            return tuple(
                descriptor
                for descriptor in list_node_operation_descriptors_for_kind(authority.node_kind)
                if _capability_allows(descriptor, authority, None)
            )

    async def allowed_human_request_kinds(
        self,
        scope: NodeOperationScope,
    ) -> tuple[str, ...]:
        session_factory = get_session_factory()
        async with session_factory() as session:
            authority = await read_node_operation_authority(session, scope)
            capabilities = authority.capabilities
            return tuple(
                kind
                for kind in ("input", "direction", "approval", "review")
                if getattr(capabilities, f"human_{kind}", "deny") == "allow"
            )

    async def execute(
        self,
        *,
        scope: NodeOperationScope,
        operation_name: str | NodeOperationName,
        arguments: Mapping[str, object],
    ) -> BaseModel:
        descriptor, request = _resolve_node_operation_request(operation_name, arguments)
        occurred_at = utc_now()
        session_factory = get_session_factory()
        try:
            async with session_factory() as admission_session:
                replay = await read_committed_replan_replay(
                    admission_session,
                    task_id=scope.task_id,
                    dispatch_id=scope.dispatch_id,
                    provider_start_revision=scope.provider_start_revision,
                    operation_name=descriptor.name.value,
                    request=request,
                )
                if replay is not None:
                    return replay
                authority = await read_node_operation_authority(admission_session, scope)
                _authorize(descriptor, authority, request)
                activity = await refresh_node_activity(
                    admission_session,
                    authority,
                    occurred_at=occurred_at,
                )
                await admission_session.commit()
        except IntegrityError as exc:
            raise _persistence_rejection(scope, descriptor, exc) from exc
        except RuntimeOperationError as exc:
            normalized = _normalize_replan_conflict(descriptor, exc)
            if normalized is exc:
                raise
            raise normalized from exc

        await self._publish_activity(
            NodeActivitySignal(
                task_id=scope.task_id,
                dispatch_id=scope.dispatch_id,
                activity_revision=activity.activity_revision,
                occurred_at=activity.occurred_at,
            )
        )
        try:
            result, follow_on = await self._commit_node_operation(
                scope=scope,
                descriptor=descriptor,
                request=request,
            )
        except RuntimeOperationError as exc:
            normalized = _normalize_replan_conflict(descriptor, exc)
            if normalized is exc:
                raise
            raise normalized from exc
        self._publish_follow_on(follow_on)
        return result

    async def _commit_node_operation(
        self,
        *,
        scope: NodeOperationScope,
        descriptor: NodeOperationDescriptor,
        request: BaseModel,
    ) -> tuple[BaseModel, CommittedNodeOperationFollowOn]:
        session_factory = get_session_factory()
        async with session_factory() as operation_session:
            try:
                return await self._execute_node_operation_transaction(
                    operation_session,
                    scope=scope,
                    descriptor=descriptor,
                    request=request,
                )
            except IntegrityError as exc:
                await operation_session.rollback()
                raise _persistence_rejection(scope, descriptor, exc) from exc

    async def _execute_node_operation_transaction(
        self,
        session: AsyncSession,
        *,
        scope: NodeOperationScope,
        descriptor: NodeOperationDescriptor,
        request: BaseModel,
    ) -> tuple[BaseModel, CommittedNodeOperationFollowOn]:
        authority = await read_node_operation_authority(session, scope)
        _authorize(descriptor, authority, request)
        authority = await _claim_unchanged_node_operation_state(
            session,
            scope=scope,
            descriptor=descriptor,
            request=request,
            authority=authority,
        )
        await require_state_legal_node_operation(session, authority, descriptor.name)
        result = await execute_core_node_operation(
            session,
            authority,
            descriptor.name,
            request,
            dispatch_opening_dependencies=self._dispatch_opening_dependencies,
        )
        if result is None:
            from banksia.runtime.node_operations.domain_handlers import (
                execute_controller_node_operation,
            )

            result = await execute_controller_node_operation(
                session,
                authority,
                descriptor.name,
                request,
                dispatch_opening_dependencies=self._dispatch_opening_dependencies,
            )
        handler_follow_on = CommittedNodeOperationFollowOn()
        if isinstance(result, CommittedNodeOperationResult):
            handler_follow_on = result.follow_on
            result = result.response
        if not isinstance(result, descriptor.success_model):
            result = descriptor.success_model.model_validate(result)
        derived_follow_on = committed_node_operation_follow_on(
            operation_name=descriptor.name,
            authority=authority,
            request=request,
            response=result,
        )
        return result, handler_follow_on.combined_with(derived_follow_on)

    async def _publish_activity(self, signal: NodeActivitySignal) -> None:
        if self._publish_activity_signal is None:
            return
        try:
            await self._publish_activity_signal(signal)
        except Exception:
            logger.exception(
                "failed to publish Node activity scheduling hint",
                extra={
                    "task_id": signal.task_id,
                    "dispatch_id": signal.dispatch_id,
                    "activity_revision": signal.activity_revision,
                },
            )

    def _publish_follow_on(self, follow_on: CommittedNodeOperationFollowOn) -> None:
        if self._runtime_effect_publisher is not None:
            for runtime_signal in follow_on.runtime_signals:
                try:
                    self._runtime_effect_publisher.publish(runtime_signal)
                except Exception:
                    logger.exception(
                        "failed to publish committed Node runtime hint",
                        extra={"runtime_effect_signal": type(runtime_signal).__name__},
                    )
        if self._support_projection_publisher is not None:
            for projection_signal in follow_on.projection_signals:
                try:
                    self._support_projection_publisher.publish(projection_signal)
                except Exception:
                    logger.exception(
                        "failed to publish committed Node support-projection hint",
                        extra={
                            "support_projection_signal": type(projection_signal).__name__,
                        },
                    )


def _resolve_node_operation_request(
    operation_name: str | NodeOperationName,
    arguments: Mapping[str, object],
) -> tuple[NodeOperationDescriptor, BaseModel]:
    try:
        descriptor = get_node_operation_descriptor(operation_name)
    except (KeyError, ValueError) as exc:
        raise RuntimeOperationError(
            code=OperationFailureCode.INVALID_REQUEST_SHAPE,
            summary=f"unknown Node operation '{operation_name}'",
            is_retryable=False,
        ) from exc
    return descriptor, descriptor.request_model.model_validate(dict(arguments))


def _persistence_rejection(
    scope: NodeOperationScope,
    descriptor: NodeOperationDescriptor,
    exc: IntegrityError,
) -> RuntimeOperationError:
    logger.exception(
        "controller persistence rejected a Node operation",
        exc_info=exc,
        extra={
            "task_id": scope.task_id,
            "dispatch_id": scope.dispatch_id,
            "operation_name": descriptor.name.value,
        },
    )
    return RuntimeOperationError(
        code=OperationFailureCode.INTERNAL_ERROR,
        summary="controller persistence rejected the operation and rolled back its state change",
        is_retryable=False,
    )


def _normalize_replan_conflict(
    descriptor: NodeOperationDescriptor,
    exc: RuntimeOperationError,
) -> RuntimeOperationError:
    if descriptor.name not in _REPLAN_OPERATION_NAMES or exc.code != OperationFailureCode.CONFLICT:
        return exc
    return RuntimeOperationError(
        code=exc.code,
        summary=exc.summary,
        is_retryable=True,
        suggested_next_step=_REPLAN_CONFLICT_NEXT_STEP,
        status_code_override=exc.status_code_override,
    )


async def _claim_unchanged_node_operation_state(
    session: AsyncSession,
    *,
    scope: NodeOperationScope,
    descriptor: NodeOperationDescriptor,
    request: BaseModel,
    authority: NodeOperationAuthority,
) -> NodeOperationAuthority:
    if not node_operation_requires_transition_claim(descriptor.name):
        return authority

    state_token = await read_node_operation_state_token(session, authority)
    await claim_exact_node_operation_transition(session, authority)
    current_state_token = await read_node_operation_state_token(session, authority)
    if current_state_token != state_token:
        raise RuntimeOperationError(
            code=OperationFailureCode.CONFLICT,
            summary="another Node operation changed exact dispatch state",
            is_retryable=False,
        )
    current_authority = await read_node_operation_authority(session, scope)
    _authorize(descriptor, current_authority, request)
    return current_authority


def _authorize(
    descriptor: NodeOperationDescriptor,
    authority: NodeOperationAuthority,
    request: BaseModel,
) -> None:
    if authority.node_kind not in descriptor.allowed_node_kinds:
        raise RuntimeOperationError(
            code=OperationFailureCode.ILLEGAL_CALLER,
            summary=f"{authority.node_kind.value} cannot call {descriptor.name.value}",
            is_retryable=False,
        )
    if not _capability_allows(descriptor, authority, request):
        raise RuntimeOperationError(
            code=OperationFailureCode.CAPABILITY_REJECTED,
            summary=f"current capability denies {descriptor.name.value}",
            is_retryable=False,
        )


def _capability_allows(
    descriptor: NodeOperationDescriptor,
    authority: NodeOperationAuthority,
    request: BaseModel | None,
) -> bool:
    if descriptor.required_capability == NodeOperationCapability.COMMAND_RUN:
        return authority.capabilities.command_run == "allow"
    if descriptor.required_capability != NodeOperationCapability.HUMAN_REQUEST:
        return True
    if request is None:
        return any(
            decision == "allow"
            for decision in (
                authority.capabilities.human_direction,
                authority.capabilities.human_approval,
                authority.capabilities.human_input,
                authority.capabilities.human_review,
            )
        )
    assert isinstance(request, OpenHumanRequestRequest)
    decisions = {
        "direction": authority.capabilities.human_direction,
        "approval": authority.capabilities.human_approval,
        "input": authority.capabilities.human_input,
        "review": authority.capabilities.human_review,
    }
    return decisions[request.request.kind.value] == "allow"


__all__ = ["NodeOperationExecutor"]
