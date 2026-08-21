from __future__ import annotations

from pathlib import Path
from typing import Any

from oh_my_subagents.config import ClaudeSettings, CodexSettings, RuntimeSettings, Settings
from oh_my_subagents.persistence.models import (
    DispatchRequestModel,
    MemberConfigurationModel,
)
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.node_operations import NodeOperationScope
from oh_my_subagents.runtime.prompt import render_dynamic_input
from tests.helpers.executor_harness import seeded_executor
from tests.helpers.runtime_prompt_samples import sample_dynamic_input
from tests.helpers.team_persistence_seed import member_configuration_id


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
            child_configuration = await session.get(
                MemberConfigurationModel,
                member_configuration_id(ids, "child"),
            )
            assert child_configuration is not None
            child_configuration.requested_provider_json = None
            await session.commit()

        scope = NodeOperationScope(
            task_id=ids.task_id,
            dispatch_id=ids.current_dispatch_id,
        )
        listed_operations = await executor.list_operations(scope)
        context = await executor.execute(
            scope=scope,
            operation_name="get_current_context",
            arguments={},
        )

    payload = context.model_dump(mode="json")
    _assert_current_context_payload(
        payload,
        task_id=ids.task_id,
        dispatch_id=ids.current_dispatch_id,
        attempt_id=ids.root_attempt_id,
        assignment_id=ids.root_assignment_id,
    )
    assert tuple(payload["available_actions"]) == tuple(
        descriptor.name.value for descriptor in listed_operations
    )


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
    assert continuation["trigger"]["kind"] == "delegation_wave_settled"
    member = continuation["trigger"]["result"]["members"][0]
    assert member["assignment"]["prompt"] == ("Review the exact implementation.")
    assert member["checkpoint"]["files"][0] == {
        "path": ".oms/t_7m4k2d9x/artifacts/review.md",
        "description": "Independent review.",
    }


def _assert_current_context_payload(
    payload: dict[str, Any],
    *,
    task_id: str,
    dispatch_id: str,
    attempt_id: str,
    assignment_id: str,
) -> None:
    assert payload["task"] == {
        "id": task_id,
        "workflow_id": "workflow.target",
    }
    assert payload["dispatch"] == {
        "id": dispatch_id,
        "attempt_id": attempt_id,
        "assignment_id": assignment_id,
    }
    assert payload["assignment"]["id"] == assignment_id
    assert payload["assignment"]["prompt"]
    assert payload["continuation"] is None
    assert payload["current_member"]["behavior"] == "manager"
    assert payload["current_member"]["position"] == "task_lead"
    assert payload["current_member"]["provider"]["kind"] == "codex"
    assert payload["direct_team"][0]["id"] == "child"
    assert payload["direct_team"][0]["participation"] == "required"
    assert payload["direct_team"][0]["provider"] == {
        "kind": "claude",
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
        "add_child",
        "update_child",
        "remove_child",
        "open_human_request",
        "start_command_run",
    ]
    assert payload["workspace"]["task_directory"].startswith(".oms/")
    assert payload["workspace"]["manifest"].endswith("/manifest.md")
    assert payload["observed_at"].endswith("Z")
    assert "trigger" not in payload
    assert "readback_refs" not in payload
    assert "network_access" not in payload
