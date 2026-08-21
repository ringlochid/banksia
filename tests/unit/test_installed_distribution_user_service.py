from __future__ import annotations

from dataclasses import dataclass

import pytest

from banksia.platform.managed_services.windows_task_scheduler import (
    WindowsScheduledTaskSnapshot,
)
from scripts.testing.installed_distribution.user_service import (
    assert_windows_service_probe_is_safe,
)


@dataclass
class StubScheduler:
    snapshot: WindowsScheduledTaskSnapshot | None

    def inspect(self) -> WindowsScheduledTaskSnapshot | None:
        return self.snapshot

    def register(self, *, definition: str, user_id: str) -> None:
        raise AssertionError("register must not run during the safety check")

    def delete(self) -> None:
        raise AssertionError("delete must not run during the safety check")

    def start_task(self) -> None:
        raise AssertionError("start must not run during the safety check")

    def stop(self) -> None:
        raise AssertionError("stop must not run during the safety check")


def test_windows_service_probe_accepts_an_unused_native_task_slot() -> None:
    assert_windows_service_probe_is_safe(StubScheduler(snapshot=None))


def test_windows_service_probe_refuses_to_replace_an_existing_user_service() -> None:
    snapshot = WindowsScheduledTaskSnapshot(
        definition="<Task />",
        is_enabled=True,
        state=4,
        last_result=0,
        running_instance_count=1,
    )

    with pytest.raises(
        AssertionError,
        match=r"fixed Windows service task \\Banksia\\Controller already exists",
    ):
        assert_windows_service_probe_is_safe(StubScheduler(snapshot=snapshot))
