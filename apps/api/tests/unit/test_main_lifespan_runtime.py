from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Self, cast

import autoclaw.main as main_module
import pytest
from autoclaw.main import create_app
from autoclaw.runtime.post_commit import DispatchStartDue, RuntimeEffectSignal


class RecordingAsyncOwner:
    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events

    async def __aenter__(self) -> Self:
        self._events.append(f"enter:{self._name}")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self._events.append(f"exit:{self._name}")

    async def publish_startup(self, signal: RuntimeEffectSignal) -> bool:
        del signal
        return True


async def test_lifespan_keeps_publishers_alive_until_runtime_owners_stop(
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

    async def ensure_schema() -> None:
        events.append("schema")

    async def cleanup_requests(**kwargs: object) -> dict[str, int]:
        del kwargs
        events.append("request_cleanup")
        return {}

    async def audit_runtime(**kwargs: object) -> dict[str, object]:
        publish = cast(
            Callable[[RuntimeEffectSignal], Awaitable[bool]],
            kwargs["publish"],
        )
        assert await publish(DispatchStartDue("dispatch.startup", 1, main_module.utc_now()))
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
        "cleanup_aged_dispatch_request_directories",
        cleanup_requests,
    )
    monkeypatch.setattr(main_module, "audit_startup_runtime_effects", audit_runtime)
    monkeypatch.setattr(
        main_module,
        "audit_startup_support_projections",
        audit_projections,
    )
    monkeypatch.setattr(main_module, "dispose_db_engine", dispose_engine)

    async with app.router.lifespan_context(app):
        events.append("serving")

    assert events == [
        "schema",
        "request_cleanup",
        "enter:command",
        "enter:projection",
        "enter:router",
        "enter:scheduler",
        "runtime_audit",
        "projection_audit",
        "serving",
        "exit:scheduler",
        "exit:router",
        "exit:projection",
        "exit:command",
        "dispose",
    ]


__all__ = []
