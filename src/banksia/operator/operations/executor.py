from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from banksia.operator.operations.catalog import (
    OPERATOR_OPERATION_BY_NAME,
    OperatorOperationName,
)
from banksia.operator.operations.product import OperatorProductOperations


@dataclass(frozen=True, slots=True)
class OperatorOperationScope:
    conversation_id: str
    invocation_id: str
    claim_generation: int


class OperatorToolSuccessResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["result"] = "result"
    result: dict[str, object]


class OperatorToolProposalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["proposal"] = "proposal"
    confirmation_id: str
    label: str
    scope: str
    consequence: str


class OperatorToolFailureResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["failure"] = "failure"
    problem: str


OperatorToolResult = Annotated[
    OperatorToolSuccessResult | OperatorToolProposalResult | OperatorToolFailureResult,
    Field(discriminator="kind"),
]
OPERATOR_TOOL_RESULT_ADAPTER: TypeAdapter[OperatorToolResult] = TypeAdapter(OperatorToolResult)


class PreparedOperatorEffect(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    effect_id: str
    should_execute: bool
    prior_result: OperatorToolResult | None = None


class OperatorEffectOwner(Protocol):
    async def validate_operation_scope(
        self,
        scope: OperatorOperationScope,
    ) -> None: ...

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
    ) -> OperatorToolResult: ...

    async def prepare_immediate_effect(
        self,
        *,
        scope: OperatorOperationScope,
        provider_call_id: str,
        operation: OperatorOperationName,
        request: BaseModel,
        guard: str | None,
    ) -> PreparedOperatorEffect: ...

    async def finish_immediate_effect(
        self,
        *,
        effect_id: str,
        result: dict[str, object] | None,
        failure_problem: str | None,
    ) -> OperatorToolResult: ...


class OperatorOperationExecutor:
    def __init__(self, product_operations: OperatorProductOperations) -> None:
        self._product_operations = product_operations
        self._effect_owner: OperatorEffectOwner | None = None

    def bind_effect_owner(self, owner: OperatorEffectOwner) -> None:
        if self._effect_owner is not None and self._effect_owner is not owner:
            raise RuntimeError("Operator effect owner is already bound")
        self._effect_owner = owner

    async def execute(
        self,
        *,
        scope: OperatorOperationScope,
        provider_call_id: str,
        operation_name: str,
        arguments: object,
    ) -> OperatorToolResult:
        if not provider_call_id.strip():
            return OperatorToolFailureResult(
                problem="invalid_operator_provider_call",
            )
        spec = OPERATOR_OPERATION_BY_NAME.get(cast(OperatorOperationName, operation_name))
        if spec is None:
            return OperatorToolFailureResult(
                problem="unsupported_operator_operation",
            )
        try:
            request = spec.request_model.model_validate(arguments)
        except ValidationError:
            return OperatorToolFailureResult(problem="invalid_operator_operation")
        try:
            owner = self._require_effect_owner()
            await owner.validate_operation_scope(scope)
            if spec.effect_policy == "read":
                result = await self._product_operations.execute(spec.name, request)
                return OperatorToolSuccessResult(result=self._validate_result(spec.name, result))
            if spec.effect_policy == "proposal":
                try:
                    proposal = await self._product_operations.resolve_proposal(
                        spec.name,
                        request,
                    )
                except Exception:
                    return OperatorToolFailureResult(
                        problem="operator_action_not_current",
                    )
                return await owner.propose_effect(
                    scope=scope,
                    provider_call_id=provider_call_id,
                    operation=spec.name,
                    request=request,
                    guard=proposal.guard,
                    label=proposal.label,
                    resource_scope=proposal.resource_scope,
                    consequence=proposal.consequence,
                )
            guard = await self._product_operations.read_guard(spec.name, request)
            prepared = await owner.prepare_immediate_effect(
                scope=scope,
                provider_call_id=provider_call_id,
                operation=spec.name,
                request=request,
                guard=guard,
            )
            if not prepared.should_execute:
                if prepared.prior_result is None:
                    raise RuntimeError("completed Operator effect has no result")
                return prepared.prior_result
            return await self._execute_prepared_effect(
                effect_id=prepared.effect_id,
                operation=spec.name,
                request=request,
            )
        except Exception:
            return OperatorToolFailureResult(problem="operator_operation_failed")

    async def execute_confirmed(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
        guard: str | None,
    ) -> dict[str, object]:
        result = await self._product_operations.execute(
            operation,
            request,
            is_confirmed=True,
            confirmed_guard=guard,
        )
        return self._validate_result(operation, result)

    async def is_guard_current(
        self,
        operation: OperatorOperationName,
        request: BaseModel,
        guard: str | None,
    ) -> bool:
        return await self._product_operations.is_guard_current(operation, request, guard)

    async def is_stored_proposal_current(
        self,
        operation_name: str,
        payload: object,
        guard: str | None,
    ) -> bool:
        spec = OPERATOR_OPERATION_BY_NAME.get(cast(OperatorOperationName, operation_name))
        if spec is None or spec.effect_policy != "proposal":
            return False
        try:
            request = spec.request_model.model_validate(payload)
        except ValidationError:
            return False
        return await self.is_guard_current(spec.name, request, guard)

    def parse_request(
        self,
        operation: OperatorOperationName,
        payload: object,
    ) -> BaseModel:
        return OPERATOR_OPERATION_BY_NAME[operation].request_model.model_validate(payload)

    async def _execute_prepared_effect(
        self,
        *,
        effect_id: str,
        operation: OperatorOperationName,
        request: BaseModel,
    ) -> OperatorToolResult:
        owner = self._require_effect_owner()
        try:
            result = await self._product_operations.execute(operation, request)
            result = self._validate_result(operation, result)
        except Exception:
            return await owner.finish_immediate_effect(
                effect_id=effect_id,
                result=None,
                failure_problem="operator_operation_failed",
            )
        return await owner.finish_immediate_effect(
            effect_id=effect_id,
            result=result,
            failure_problem=None,
        )

    def _validate_result(
        self,
        operation: OperatorOperationName,
        result: object,
    ) -> dict[str, object]:
        validated = OPERATOR_OPERATION_BY_NAME[operation].result_model.model_validate(result)
        return cast(
            dict[str, object],
            validated.model_dump(mode="json", exclude_none=True),
        )

    def _require_effect_owner(self) -> OperatorEffectOwner:
        if self._effect_owner is None:
            raise RuntimeError("Operator effect owner is unavailable")
        return self._effect_owner


__all__ = [
    "OPERATOR_TOOL_RESULT_ADAPTER",
    "OperatorEffectOwner",
    "OperatorOperationExecutor",
    "OperatorOperationScope",
    "OperatorToolFailureResult",
    "OperatorToolProposalResult",
    "OperatorToolResult",
    "OperatorToolSuccessResult",
    "PreparedOperatorEffect",
]
