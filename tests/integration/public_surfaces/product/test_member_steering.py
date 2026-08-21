from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.contracts.task import MemberSteerReceipt, TaskView
from oh_my_subagents.runtime.providers import (
    DispatchStartRequest,
    ProviderAdapterRegistry,
    ProviderCheckResult,
    ProviderCheckStatus,
    ProviderStartAccepted,
    ProviderSteerOutcome,
    ProviderStopOutcome,
)
from tests.helpers.executor_harness import seeded_async_executor
from tests.helpers.product_surface import product_http_client


class ActiveSteerAdapter:
    kind = ProviderKind.CODEX

    def __init__(self, dispatch_id: str) -> None:
        self.dispatch_id = dispatch_id
        self.messages: list[str] = []

    async def start(self, request: DispatchStartRequest) -> ProviderStartAccepted:
        del request
        raise AssertionError("steer proof must not start a provider")

    async def stop(self, dispatch_id: str) -> ProviderStopOutcome:
        del dispatch_id
        return ProviderStopOutcome.NOT_RUNNING

    async def can_steer(self, dispatch_id: str) -> bool:
        return dispatch_id == self.dispatch_id

    async def steer(self, dispatch_id: str, message: str) -> ProviderSteerOutcome:
        if not await self.can_steer(dispatch_id):
            return ProviderSteerOutcome.NOT_RUNNING
        self.messages.append(message)
        return ProviderSteerOutcome.DELIVERED

    async def read_availability(self) -> ProviderCheckResult:
        return ProviderCheckResult(
            kind=self.kind,
            status=ProviderCheckStatus.AVAILABLE,
            code="test_available",
        )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        yield


async def test_http_member_steer_records_exact_human_visible_activity(
    tmp_path: Path,
) -> None:
    message = "  Re-read AGENTS.md.\n\nThen continue with the current implementation.  "
    async with seeded_async_executor(tmp_path, suffix="product-member-steer") as (
        _executor,
        session_factory,
        ids,
        _signals,
    ):
        adapter = ActiveSteerAdapter(ids.current_dispatch_id)
        registry = ProviderAdapterRegistry((adapter,))
        async with product_http_client(
            session_factory,
            tmp_path=tmp_path,
            provider_adapters=registry,
        ) as client:
            current_response = await client.get(f"/api/tasks/{ids.task_id}")
            current = TaskView.model_validate(current_response.json())
            action = current.team.steer_action
            assert action is not None

            response = await client.post(
                action.href,
                json={"action_id": action.id, "message": message},
            )

        assert response.status_code == 200, response.text
        receipt = MemberSteerReceipt.model_validate(response.json())
        assert receipt.status == "delivered"
        assert adapter.messages == [message]
        activity = receipt.task.activities[-1]
        assert activity.kind == "member_steered"
        assert activity.title == "Member steered"
        assert activity.summary == message
        assert activity.member is not None
        assert activity.member.id == ids.root_member_id
