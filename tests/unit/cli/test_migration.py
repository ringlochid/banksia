from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from oh_my_subagents.interfaces.cli.migration import migrate_from_banksia
from oh_my_subagents.platform.managed_services import (
    ManagedServiceCommandObserver,
    ManagedServiceExecutionState,
    ManagedServiceInspection,
    ManagedServiceInstallationState,
    ManagedServiceStartupState,
    ManagedServiceTarget,
)


def test_migration_copies_default_state_renames_files_and_is_idempotent(
    tmp_path: Path,
) -> None:
    source_config = tmp_path / "legacy-config" / "config.toml"
    target_config = tmp_path / "oms-config" / "config.toml"
    source_data = tmp_path / "legacy-data"
    target_data = tmp_path / "oms-data"
    source_config.parent.mkdir()
    source_data.mkdir()
    source_config.write_text(
        "\n".join(
            (
                "[paths]",
                f'data_dir = "{source_data.as_posix()}"',
                "",
                "[database]",
                f'url = "sqlite+aiosqlite:///{(source_data / "banksia.persistence").as_posix()}"',
                "",
            )
        ),
        encoding="utf-8",
    )
    (source_config.parent / "banksia.env").write_text(
        "ANTHROPIC_API_KEY=secret\n",
        encoding="utf-8",
    )
    (source_data / "banksia.persistence").write_bytes(b"database")
    (source_data / "history.backup").write_bytes(b"backup")

    first = migrate_from_banksia(
        source_config_path=source_config,
        target_config_path=target_config,
        source_default_data_dir=source_data,
        target_default_data_dir=target_data,
        should_migrate_service=False,
    )
    second = migrate_from_banksia(
        source_config_path=source_config,
        target_config_path=target_config,
        source_default_data_dir=source_data,
        target_default_data_dir=target_data,
        should_migrate_service=False,
    )

    config = tomllib.loads(target_config.read_text(encoding="utf-8"))
    assert config["paths"]["data_dir"] == str(target_data)
    assert config["database"]["url"] == (
        f"sqlite+aiosqlite:///{(target_data / 'oms.persistence').as_posix()}"
    )
    assert (target_data / "oms.persistence").read_bytes() == b"database"
    assert (target_data / "history.backup").read_bytes() == b"backup"
    assert (target_config.parent / "oms.env").read_text(encoding="utf-8") == (
        "ANTHROPIC_API_KEY=secret\n"
    )
    assert (source_data / "banksia.persistence").read_bytes() == b"database"
    assert first.copied_files
    assert second.copied_files == ()
    assert set(second.reused_files) == {
        target_config,
        target_config.parent / "oms.env",
        target_data / "oms.persistence",
        target_data / "history.backup",
    }


def test_migration_refuses_to_overwrite_different_oms_state(tmp_path: Path) -> None:
    source_config, target_config, source_data, target_data = _migration_paths(tmp_path)
    target_data.mkdir()
    (target_data / "oms.persistence").write_bytes(b"different")

    with pytest.raises(FileExistsError, match="different OMS state"):
        migrate_from_banksia(
            source_config_path=source_config,
            target_config_path=target_config,
            source_default_data_dir=source_data,
            target_default_data_dir=target_data,
            should_migrate_service=False,
        )

    assert not target_config.exists()
    assert (source_data / "banksia.persistence").read_bytes() == b"database"


def test_migration_preserves_custom_data_and_database_paths(tmp_path: Path) -> None:
    source_config = tmp_path / "legacy" / "config.toml"
    target_config = tmp_path / "oms" / "config.toml"
    custom_data = tmp_path / "custom-data"
    source_config.parent.mkdir()
    custom_data.mkdir()
    source_config.write_text(
        "\n".join(
            (
                "[paths]",
                f'data_dir = "{custom_data.as_posix()}"',
                "",
                "[database]",
                'url = "postgresql+asyncpg://localhost/controller"',
                "",
            )
        ),
        encoding="utf-8",
    )

    result = migrate_from_banksia(
        source_config_path=source_config,
        target_config_path=target_config,
        source_default_data_dir=tmp_path / "default-legacy-data",
        target_default_data_dir=tmp_path / "default-oms-data",
        should_migrate_service=False,
    )

    config = tomllib.loads(target_config.read_text(encoding="utf-8"))
    assert Path(config["paths"]["data_dir"]) == custom_data
    assert config["database"] == {
        "url": "postgresql+asyncpg://localhost/controller",
        "postgres_schema": "banksia",
    }
    assert result.source_data_dir is None
    assert result.target_data_dir is None


def test_migration_replaces_legacy_service_and_preserves_running_state(
    tmp_path: Path,
) -> None:
    source_config, target_config, source_data, target_data = _migration_paths(tmp_path)
    operations: list[str] = []
    legacy = FakeServiceManager(
        "banksia.service",
        installed=True,
        execution_state=ManagedServiceExecutionState.RUNNING,
        operations=operations,
    )
    canonical = FakeServiceManager(
        "oh-my-subagents.service",
        installed=False,
        execution_state=ManagedServiceExecutionState.STOPPED,
        operations=operations,
    )

    result = migrate_from_banksia(
        source_config_path=source_config,
        target_config_path=target_config,
        source_default_data_dir=source_data,
        target_default_data_dir=target_data,
        legacy_service_manager=legacy,
        canonical_service_manager=canonical,
    )

    assert result.service_migrated is True
    assert result.service_started is True
    assert operations == [
        "inspect:banksia.service",
        "inspect:oh-my-subagents.service",
        "uninstall:banksia.service",
        "install:oh-my-subagents.service:start",
    ]


def _migration_paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    source_config = tmp_path / "legacy-config" / "config.toml"
    target_config = tmp_path / "oms-config" / "config.toml"
    source_data = tmp_path / "legacy-data"
    target_data = tmp_path / "oms-data"
    source_config.parent.mkdir()
    source_data.mkdir()
    source_config.write_text(
        "\n".join(
            (
                "[paths]",
                f'data_dir = "{source_data.as_posix()}"',
                "",
                "[database]",
                f'url = "sqlite+aiosqlite:///{(source_data / "banksia.persistence").as_posix()}"',
                "",
            )
        ),
        encoding="utf-8",
    )
    (source_data / "banksia.persistence").write_bytes(b"database")
    return source_config, target_config, source_data, target_data


class FakeServiceManager:
    manager_name = "fake"
    readiness_timeout_seconds = 0.0

    def __init__(
        self,
        service_name: str,
        *,
        installed: bool,
        execution_state: ManagedServiceExecutionState,
        operations: list[str],
    ) -> None:
        self.service_name = service_name
        self.installed = installed
        self.execution_state = execution_state
        self.operations = operations

    def render_definition(self, target: ManagedServiceTarget) -> str:
        del target
        return "definition"

    def inspect(self, target: ManagedServiceTarget) -> ManagedServiceInspection:
        del target
        self.operations.append(f"inspect:{self.service_name}")
        return self._inspection()

    def install(
        self,
        target: ManagedServiceTarget,
        *,
        should_start: bool,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        del target, command_observer
        suffix = "start" if should_start else "no-start"
        self.operations.append(f"install:{self.service_name}:{suffix}")
        self.installed = True
        self.execution_state = (
            ManagedServiceExecutionState.RUNNING
            if should_start
            else ManagedServiceExecutionState.STOPPED
        )
        return self._inspection()

    def uninstall(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        del target, command_observer
        self.operations.append(f"uninstall:{self.service_name}")
        self.installed = False
        self.execution_state = ManagedServiceExecutionState.STOPPED
        return self._inspection()

    def _inspection(self) -> ManagedServiceInspection:
        return ManagedServiceInspection(
            manager=self.manager_name,
            service_name=self.service_name,
            definition_path=None,
            installation_state=(
                ManagedServiceInstallationState.INSTALLED
                if self.installed
                else ManagedServiceInstallationState.ABSENT
            ),
            startup_state=(
                ManagedServiceStartupState.ENABLED
                if self.installed
                else ManagedServiceStartupState.DISABLED
            ),
            execution_state=self.execution_state,
            is_definition_current=self.installed,
        )

    def start(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        del target, command_observer
        self.execution_state = ManagedServiceExecutionState.RUNNING
        return self._inspection()

    def stop(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        del target, command_observer
        self.execution_state = ManagedServiceExecutionState.STOPPED
        return self._inspection()

    def restart(
        self,
        target: ManagedServiceTarget,
        *,
        command_observer: ManagedServiceCommandObserver | None = None,
    ) -> ManagedServiceInspection:
        return self.start(target, command_observer=command_observer)
