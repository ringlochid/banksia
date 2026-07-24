from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

import banksia.interfaces.mcp.operator.product_tools as product_tools
from banksia.interfaces.mcp.operator.server import (
    OperatorEffectPublishers,
    create_operator_mcp_server,
)
from banksia.persistence.models import HumanRequestModel
from banksia.runtime.contracts.task import (
    HumanRequestResponseReceipt,
    HumanRequestView,
)
from banksia.runtime.node_operations import NodeOperationExecutor, NodeOperationScope
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher
from banksia.runtime.product.human_requests import read_product_human_request
from tests.helpers.executor_harness import AsyncSessionFactory, seeded_async_executor
from tests.helpers.lineage_seed import RuntimeIds
from tests.helpers.product_surface import (
    operator_payload,
    product_dispatch_dependencies,
    product_http_client,
)

type Surface = Literal["http", "operator"]
type HumanResponseKind = Literal["answer", "cancel"]


@pytest.mark.parametrize("surface", ("http", "operator"))
@pytest.mark.parametrize("response_kind", ("answer", "cancel"))
async def test_human_request_mutations_share_typed_action_guard_and_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: Surface,
    response_kind: HumanResponseKind,
) -> None:
    publisher = CapturedRuntimeEffectPublisher()
    suffix = f"product-human-{surface}-{response_kind}"
    async with seeded_async_executor(
        tmp_path,
        suffix=suffix,
        runtime_effect_publisher=publisher,
    ) as (executor, session_factory, ids, _signals):
        request_id, request_view = await _open_product_human_request(
            executor,
            session_factory,
            ids,
        )
        action = request_view.action if response_kind == "answer" else request_view.cancel_action
        assert action is not None
        input_payload = _human_response_input(response_kind)

        if surface == "http":
            async with product_http_client(
                session_factory,
                tmp_path=tmp_path,
                publisher=publisher,
            ) as client:
                response = await client.post(
                    f"/tasks/{ids.task_id}/human-requests/{request_id}/responses",
                    json={"action_id": action.id, "input": input_payload},
                )
            assert response.status_code == 200, response.text
            receipt = HumanRequestResponseReceipt.model_validate(response.json())
        else:
            monkeypatch.setattr(product_tools, "get_session_factory", lambda: session_factory)
            result = await create_operator_mcp_server(
                effect_publishers=OperatorEffectPublishers(
                    dispatch_opening_dependencies=product_dispatch_dependencies(tmp_path),
                    runtime_effect_publisher=publisher,
                )
            ).call_tool(
                "human_request_respond",
                {
                    "task_id": ids.task_id,
                    "request_id": request_id,
                    "action_id": action.id,
                    "input": input_payload,
                },
            )
            receipt = HumanRequestResponseReceipt.model_validate(operator_payload(result))

        async with session_factory() as session:
            source = await session.get(HumanRequestModel, request_id)

    expected_status = "answered" if response_kind == "answer" else "cancelled"
    assert receipt.receipt_id.startswith("receipt.")
    assert receipt.is_continuation_pending is True
    assert receipt.request.status == expected_status
    assert receipt.request.action is None
    assert receipt.request.cancel_action is None
    assert receipt.request.resolution is not None
    assert source is not None
    assert source.status == ("resolved" if response_kind == "answer" else "cancelled")
    assert receipt.request.resolution.resolved_at == source.resolved_at
    assert "answered_at" not in receipt.request.model_dump(mode="json")


async def _open_product_human_request(
    executor: NodeOperationExecutor,
    session_factory: AsyncSessionFactory,
    ids: RuntimeIds,
) -> tuple[str, HumanRequestView]:
    opened = await executor.execute(
        scope=NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        ),
        operation_name="open_human_request",
        arguments={
            "request": {
                "kind": "direction",
                "summary": "Choose the delivery direction.",
                "items": [
                    {
                        "id": "direction",
                        "prompt": "Which direction?",
                        "options": [
                            {"id": "a", "title": "Direction A"},
                            {"id": "b", "title": "Direction B"},
                        ],
                    }
                ],
            }
        },
    )
    request_id = str(opened.model_dump()["request_id"])
    async with session_factory() as session:
        view = await read_product_human_request(
            session,
            task_id=ids.task_id,
            request_id=request_id,
        )
    return request_id, view


def _human_response_input(response_kind: HumanResponseKind) -> dict[str, object]:
    if response_kind == "answer":
        return {
            "kind": "answer",
            "item_responses": {
                "direction": {"kind": "option", "option_id": "a"},
            },
        }
    return {"kind": "cancel", "confirmed": True}
