from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest

import banksia.platform.managed_services.scheduled_tasks as scheduled_tasks_module
from banksia.platform.managed_services import (
    ManagedServiceExecutionState,
    ManagedServiceInstallationState,
    ManagedServiceStartupState,
    ManagedServiceTarget,
    ScheduledTaskUserServiceManager,
    WindowsScheduledTaskSnapshot,
    scheduled_task_definitions_match,
)


def test_scheduled_task_definition_is_current_user_and_least_privilege(
    tmp_path: Path,
) -> None:
    target = _target_with_special_paths(tmp_path)
    definition = ElementTree.fromstring(
        ScheduledTaskUserServiceManager(user_id="S-1-5-21-1234").render_definition(target)
    )
    namespace = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

    assert definition.findtext(".//t:UserId", namespaces=namespace) == "S-1-5-21-1234"
    assert (
        definition.findtext(".//t:LogonTrigger/t:UserId", namespaces=namespace) == "S-1-5-21-1234"
    )
    assert definition.findtext(".//t:LogonType", namespaces=namespace) == "InteractiveToken"
    assert definition.findtext(".//t:RunLevel", namespaces=namespace) == "LeastPrivilege"
    assert definition.findtext(".//t:MultipleInstancesPolicy", namespaces=namespace) == (
        "IgnoreNew"
    )
    assert definition.findtext(".//t:ExecutionTimeLimit", namespaces=namespace) == "PT0S"
    assert definition.findtext(".//t:Command", namespaces=namespace) == str(
        target.python_executable
    )


def test_scheduled_task_definition_accepts_task_scheduler_normalization(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    manager = ScheduledTaskUserServiceManager(
        task_scheduler=FakeWindowsTaskScheduler(),
        user_id="S-1-5-21-1234",
        identity_resolver=_resolve_test_windows_identity,
    )
    expected = manager.render_definition(target)
    normalized = _normalize_test_scheduled_task_definition(expected)

    assert scheduled_task_definitions_match(
        normalized,
        expected,
        resolve_identity=_resolve_test_windows_identity,
    )

    changed = normalized.replace("python.exe", "other-python.exe")
    assert not scheduled_task_definitions_match(
        changed,
        expected,
        resolve_identity=_resolve_test_windows_identity,
    )


def test_scheduled_task_manager_uses_idempotent_native_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduled_tasks_module.sys, "platform", "win32")
    task_scheduler = FakeWindowsTaskScheduler()
    manager = ScheduledTaskUserServiceManager(
        task_scheduler=task_scheduler,
        user_id="S-1-5-21-1234",
        identity_resolver=_resolve_test_windows_identity,
    )
    target = _target(tmp_path)

    installed = manager.install(target, should_start=True)
    started_again = manager.start(target)
    restarted = manager.restart(target)
    stopped = manager.stop(target)
    removed = manager.uninstall(target)

    assert installed.installation_state is ManagedServiceInstallationState.INSTALLED
    assert installed.execution_state is ManagedServiceExecutionState.RUNNING
    assert started_again.execution_state is ManagedServiceExecutionState.RUNNING
    assert restarted.execution_state is ManagedServiceExecutionState.RUNNING
    assert stopped.execution_state is ManagedServiceExecutionState.STOPPED
    assert removed.installation_state is ManagedServiceInstallationState.ABSENT
    assert task_scheduler.operations == [
        "register",
        "start",
        "stop",
        "start",
        "stop",
        "delete",
    ]


def test_scheduled_task_install_reenables_a_disabled_definition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduled_tasks_module.sys, "platform", "win32")
    task_scheduler = FakeWindowsTaskScheduler()
    manager = ScheduledTaskUserServiceManager(
        task_scheduler=task_scheduler,
        user_id="S-1-5-21-1234",
        identity_resolver=_resolve_test_windows_identity,
    )
    target = _target(tmp_path)
    manager.install(target, should_start=False)
    assert task_scheduler.snapshot is not None
    task_scheduler.snapshot = WindowsScheduledTaskSnapshot(
        definition=task_scheduler.snapshot.definition,
        is_enabled=False,
        state=1,
        last_result=0x00041302,
        running_instance_count=0,
    )

    inspection = manager.install(target, should_start=False)

    assert inspection.startup_state is ManagedServiceStartupState.ENABLED
    assert task_scheduler.operations == ["register", "register"]


class FakeWindowsTaskScheduler:
    def __init__(self) -> None:
        self.snapshot: WindowsScheduledTaskSnapshot | None = None
        self.operations: list[str] = []

    def inspect(self) -> WindowsScheduledTaskSnapshot | None:
        return self.snapshot

    def register(self, *, definition: str, user_id: str) -> None:
        assert user_id == "S-1-5-21-1234"
        self.operations.append("register")
        self.snapshot = WindowsScheduledTaskSnapshot(
            definition=_normalize_test_scheduled_task_definition(definition),
            is_enabled=True,
            state=3,
            last_result=0x00041303,
            running_instance_count=0,
        )

    def delete(self) -> None:
        self.operations.append("delete")
        self.snapshot = None

    def start_task(self) -> None:
        assert self.snapshot is not None
        self.operations.append("start")
        self.snapshot = WindowsScheduledTaskSnapshot(
            definition=self.snapshot.definition,
            is_enabled=True,
            state=4,
            last_result=0,
            running_instance_count=1,
        )

    def stop(self) -> None:
        assert self.snapshot is not None
        self.operations.append("stop")
        self.snapshot = WindowsScheduledTaskSnapshot(
            definition=self.snapshot.definition,
            is_enabled=True,
            state=3,
            last_result=0x00041306,
            running_instance_count=0,
        )


def _target(tmp_path: Path) -> ManagedServiceTarget:
    return ManagedServiceTarget(
        config_path=tmp_path / "config" / "config.toml",
        python_executable=tmp_path / "venv" / "python.exe",
        log_path=tmp_path / "logs" / "controller.log",
    )


def _target_with_special_paths(tmp_path: Path) -> ManagedServiceTarget:
    return ManagedServiceTarget(
        config_path=tmp_path / 'config % with space "桉树"' / "config.toml",
        python_executable=tmp_path / "venv with space" / "python%bin",
        log_path=tmp_path / "log with space" / "controller.log",
    )


def _normalize_test_scheduled_task_definition(definition: str) -> str:
    root = ElementTree.fromstring(definition)
    namespace = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    principal = root.find("./t:Principals/t:Principal", namespace)
    assert principal is not None
    run_level = principal.find("./t:RunLevel", namespace)
    assert run_level is not None
    principal.remove(run_level)
    trigger = root.find("./t:Triggers/t:LogonTrigger", namespace)
    assert trigger is not None
    trigger_enabled = trigger.find("./t:Enabled", namespace)
    assert trigger_enabled is not None
    trigger.remove(trigger_enabled)
    settings = root.find("./t:Settings", namespace)
    assert settings is not None
    task_enabled = settings.find("./t:Enabled", namespace)
    assert task_enabled is not None
    settings.remove(task_enabled)
    trigger_user = root.find("./t:Triggers/t:LogonTrigger/t:UserId", namespace)
    assert trigger_user is not None
    trigger_user.text = r"LOCSTUDIO\ring_"
    return ElementTree.tostring(root, encoding="unicode")


def _resolve_test_windows_identity(value: str) -> str:
    if value in {"S-1-5-21-1234", r"LOCSTUDIO\ring_"}:
        return "S-1-5-21-1234"
    return value
