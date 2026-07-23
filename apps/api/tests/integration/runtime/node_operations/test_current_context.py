from __future__ import annotations

from pathlib import Path

from banksia.config import ClaudeSettings, CodexSettings, RuntimeSettings, Settings
from banksia.persistence.models import (
    DispatchRequestModel,
    FlowNodeModel,
    MemberConfigurationModel,
)
from banksia.providers import ProviderKind
from banksia.runtime.node_operations import NodeOperationScope
from banksia.runtime.prompt import render_dynamic_input
from tests.helpers.executor_harness import seeded_executor
from tests.helpers.team_persistence_seed import member_configuration_id
from tests.unit.runtime_prompt_rendering.samples import sample_dynamic_input


async def test_current_context_uses_dispatch_vocabulary_and_fresh_legal_actions(
    tmp_path: Path,
) -> None:
    provider_settings = Settings(
        runtime=RuntimeSettings(default_provider=ProviderKind.CLAUDE),
        codex=CodexSettings(enabled=True),
        claude=ClaudeSettings(
            enabled=True,
            model="claude-context-model",
            effort="high",
        ),
    )
    async with seeded_executor(
        tmp_path,
        suffix="current-context",
        provider_settings=provider_settings,
        available_adapter_kinds=(ProviderKind.CODEX, ProviderKind.CLAUDE),
    ) as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            child = await session.get(FlowNodeModel, ids.child_node_id)
            child_configuration = await session.get(
                MemberConfigurationModel,
                member_configuration_id(ids, "child"),
            )
            assert child is not None
            assert child_configuration is not None
            child.provider_kind = None
            child_configuration.requested_provider_json = None
            await session.commit()

        context = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="get_current_context",
            arguments={},
        )

    payload = context.model_dump(mode="json")
    assert payload["task"] == {
        "id": ids.task_id,
        "workflow_id": "workflow.target",
    }
    assert payload["dispatch"] == {
        "id": ids.current_dispatch_id,
        "attempt_id": ids.root_attempt_id,
        "assignment_id": ids.root_assignment_id,
    }
    assert payload["assignment"]["id"] == ids.root_assignment_id
    assert payload["assignment"]["prompt"]
    assert payload["continuation"] is None
    assert payload["current_member"]["behavior"] == "manager"
    assert payload["current_member"]["position"] == "task_lead"
    assert payload["current_member"]["provider"]["name"] == "codex"
    assert payload["direct_team"][0]["id"] == "child"
    assert payload["direct_team"][0]["participation"] == "required"
    assert payload["direct_team"][0]["provider"] == {
        "name": "claude",
        "model": "claude-context-model",
        "effort": "high",
        "gateway_profile": None,
        "sandbox": {
            "mode": "full_access",
            "network": "allow",
        },
    }
    assert payload["available_actions"] == [
        "get_current_context",
        "set_work_plan",
        "checkpoint",
        "open_human_request",
        "start_command_run",
        "add_child",
        "update_child",
        "remove_child",
    ]
    assert payload["workspace"]["task_directory"].startswith(".banksia/")
    assert payload["workspace"]["manifest"].endswith("/manifest.md")
    assert payload["observed_at"].endswith("Z")
    assert "trigger" not in payload
    assert "readback_refs" not in payload
    assert "network_access" not in payload


async def test_current_context_returns_exact_committed_nested_continuation(
    tmp_path: Path,
) -> None:
    committed_input = render_dynamic_input(sample_dynamic_input(manager=True, continuation=True))
    async with seeded_executor(tmp_path, suffix="current-context-continuation") as (
        executor,
        session_factory,
        ids,
        _signals,
    ):
        async with session_factory() as session:
            request = await session.get(DispatchRequestModel, ids.current_dispatch_id)
            assert request is not None
            request.input = committed_input
            await session.commit()

        context = await executor.execute(
            scope=NodeOperationScope(
                task_id=ids.task_id,
                dispatch_id=ids.current_dispatch_id,
            ),
            operation_name="get_current_context",
            arguments={},
        )

    continuation = context.model_dump(mode="json")["continuation"]
    assert continuation["trigger"]["kind"] == "child_return"
    assert continuation["trigger"]["result"]["assignment"]["prompt"] == (
        "Review the exact implementation."
    )
    assert continuation["trigger"]["result"]["checkpoint"]["files"][0] == {
        "path": ".banksia/t_7m4k2d9x/artifacts/review.md",
        "description": "Independent review.",
    }
