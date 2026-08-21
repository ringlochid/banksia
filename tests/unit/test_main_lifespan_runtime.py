from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Self, cast

import pytest

import oh_my_subagents.main as main_module
from oh_my_subagents.main import create_app
from oh_my_subagents.operator import OperatorRunnerStatus
from oh_my_subagents.runtime.clock import utc_now
from oh_my_subagents.runtime.post_commit import DispatchStartDue, RuntimeEffectSignal


class RecordingAsyncOwner:
    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events
        self._is_active = False
        self._product_call_started = asyncio.Event()

    async def __aenter__(self) -> Self:
        self._is_active = True
        self._events.append(f"enter:{self._name}")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self._is_active = False
        self._events.append(f"exit:{self._name}")

    async def publish_startup(self, signal: RuntimeEffectSignal) -> bool:
        del signal
        return True

    async def run_product_tool_call(self) -> None:
        assert self._is_active
        self._events.append(f"product-call-started:{self._name}")
        self._product_call_started.set()
        try:
            await asyncio.Future[None]()
        except asyncio.CancelledError:
            assert self._is_active
            self._events.append(f"product-call-cancelled:{self._name}")
            raise

    async def wait_for_product_call(self) -> None:
        await self._product_call_started.wait()


class RecordingOperatorService:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def repair_stranded_turns(self) -> int:
        self._events.append("operator_repair")
        return 2


class RecordingOperatorRunner:
    def __init__(
        self,
        events: list[str],
        *,
        product_dependency: RecordingAsyncOwner | None = None,
    ) -> None:
        self._events = events
        self._product_dependency = product_dependency
        self._active_turn: asyncio.Task[None] | None = None
        self.status = OperatorRunnerStatus(
            availability="available",
            configured_provider="codex",
            explanation="Operator is ready.",
        )

    async def start_product_tool_call(self) -> None:
        assert self._product_dependency is not None
        self._active_turn = asyncio.create_task(self._product_dependency.run_product_tool_call())
        await self._product_dependency.wait_for_product_call()

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        self._events.append("enter:operator")
        try:
            yield
        finally:
            if self._active_turn is not None:
                self._active_turn.cancel()
                outcomes = await asyncio.gather(
                    self._active_turn,
                    return_exceptions=True,
                )
                assert isinstance(outcomes[0], asyncio.CancelledError)
            self._events.append("exit:operator")


def test_app_composes_one_operator_prompt_tool_catalog_and_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runner = RecordingOperatorRunner(events)
    tools = (object(),)
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(main_module, "read_operator_system_prompt", lambda: "operator prompt")
    monkeypatch.setattr(main_module, "build_operator_tools", lambda **_kwargs: tools)

    def build_runner(**kwargs: object) -> RecordingOperatorRunner:
        calls.append(kwargs)
        return runner

    monkeypatch.setattr(main_module, "build_operator_turn_runner", build_runner)

    app = create_app(should_enable_mcp_mounts=False)

    assert app.state.operator_turn_runner is runner
    assert app.state.operator_conversation_service.read_status().availability == "available"
    assert calls == [
        {
            "settings": main_module.get_settings(),
            "system_prompt": "operator prompt",
            "tools": tools,
        }
    ]


def _patch_lifespan_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: list[str],
    projection: RecordingAsyncOwner,
) -> None:
    async def ensure_schema() -> None:
        events.append("schema")

    async def recover_task_workspaces(*args: object, **kwargs: object) -> tuple[object, ...]:
        del args, kwargs
        events.append("task_workspace_recovery")
        return ()

    async def pause_retired_provider_tasks(*args: object, **kwargs: object) -> int:
        del args, kwargs
        events.append("provider_retirement")
        return 0

    async def audit_runtime(**kwargs: object) -> dict[str, object]:
        publish = cast(
            Callable[[RuntimeEffectSignal], Awaitable[bool]],
            kwargs["publish"],
        )
        assert await publish(DispatchStartDue("dispatch.startup", 1, utc_now()))
        routed_signal_types = kwargs["routed_signal_types"]
        assert isinstance(routed_signal_types, tuple)
        assert DispatchStartDue in routed_signal_types
        events.append("runtime_audit")
        return {}

    async def audit_projections(**kwargs: object) -> dict[str, int]:
        assert kwargs["publish"] == projection.publish_startup
        events.append("projection_audit")
        return {}

    async def dispose_engine() -> None:
        events.append("dispose")

    monkeypatch.setattr(main_module, "ensure_database_schema", ensure_schema)
    monkeypatch.setattr(
        main_module,
        "recover_task_workspace_admissions",
        recover_task_workspaces,
    )
    monkeypatch.setattr(
        main_module,
        "pause_tasks_using_retired_providers",
        pause_retired_provider_tasks,
    )
    monkeypatch.setattr(main_module, "audit_startup_runtime_effects", audit_runtime)
    monkeypatch.setattr(
        main_module,
        "audit_startup_support_projections",
        audit_projections,
    )
    monkeypatch.setattr(main_module, "dispose_db_engine", dispose_engine)


async def test_lifespan_drains_operator_turn_before_product_dependencies_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    app = create_app(should_enable_mcp_mounts=False)
    router = RecordingAsyncOwner("router", events)
    projection = RecordingAsyncOwner("projection", events)
    scheduler = RecordingAsyncOwner("scheduler", events)
    command_owner = RecordingAsyncOwner("command", events)
    app.state.runtime_effect_router = router
    app.state.support_projection_owner = projection
    app.state.deadline_scheduler = scheduler
    app.state.command_process_owner = command_owner
    app.state.operator_conversation_service = RecordingOperatorService(events)
    operator_runner = RecordingOperatorRunner(
        events,
        product_dependency=router,
    )
    app.state.operator_turn_runner = operator_runner
    _patch_lifespan_dependencies(monkeypatch, events=events, projection=projection)

    async with app.router.lifespan_context(app):
        await operator_runner.start_product_tool_call()
        events.append("serving")

    assert events == [
        "schema",
        "operator_repair",
        "provider_retirement",
        "task_workspace_recovery",
        "enter:command",
        "enter:projection",
        "enter:router",
        "enter:scheduler",
        "enter:operator",
        "runtime_audit",
        "projection_audit",
        "product-call-started:router",
        "serving",
        "product-call-cancelled:router",
        "exit:operator",
        "exit:scheduler",
        "exit:router",
        "exit:projection",
        "exit:command",
        "dispose",
    ]
    assert app.state.operator_startup_repair_count == 2


__all__ = []
