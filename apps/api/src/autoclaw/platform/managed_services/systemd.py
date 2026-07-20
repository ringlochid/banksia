from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from autoclaw.platform.managed_services.resources import get_systemd_service_template
from autoclaw.platform.provider_environment import (
    ensure_private_environment_file,
    provider_environment_file_path,
    read_provider_secret_environment,
)

from .contracts import (
    ManagedServiceCommandError,
    ManagedServiceStatus,
    ServiceInstallRequest,
    ServiceUninstallRequest,
)

DEFAULT_SERVICE_ENV_TEXT = """# AutoClaw-managed provider credentials.
# Use `autoclaw setup` or `autoclaw providers login`; do not add other settings.
"""
SYSTEMD_TEMPLATE_RESOURCE = ("systemd", "autoclaw.service")


class SystemdUserServiceManager:
    def render_systemd_service_unit(
        self,
        *,
        python_bin: Path,
        config_path: Path,
    ) -> str:
        return render_systemd_service_unit(
            python_bin=python_bin,
            config_path=config_path,
        )

    def install(self, request: ServiceInstallRequest) -> None:
        require_supported_systemd()
        unit_dir = request.unit_dir or get_linux_user_unit_dir()
        unit_path = unit_dir / build_service_unit_name(request.service_name)
        env_file = provider_environment_file_path(request.config_path)
        unit_dir.mkdir(parents=True, exist_ok=True)
        ensure_private_environment_file(
            env_file,
            initial_text=DEFAULT_SERVICE_ENV_TEXT,
        )
        read_provider_secret_environment(env_file)
        unit_path.write_text(
            render_systemd_service_unit(
                python_bin=Path(sys.executable),
                config_path=request.config_path,
            ),
            encoding="utf-8",
        )
        execute_systemctl("daemon-reload", command_observer=request.command_observer)
        execute_systemctl(
            "enable",
            build_service_unit_name(request.service_name),
            command_observer=request.command_observer,
        )
        if not request.should_skip_start:
            execute_systemctl(
                "restart",
                build_service_unit_name(request.service_name),
                command_observer=request.command_observer,
            )

    def uninstall(self, request: ServiceUninstallRequest) -> None:
        require_supported_systemd()
        unit_dir = request.unit_dir or get_linux_user_unit_dir()
        unit_path = unit_dir / build_service_unit_name(request.service_name)
        execute_systemctl(
            "disable",
            "--now",
            build_service_unit_name(request.service_name),
            should_check=False,
        )
        unit_path.unlink(missing_ok=True)
        if request.should_remove_env_file:
            provider_environment_file_path(request.config_path).unlink(missing_ok=True)
        execute_systemctl("daemon-reload")

    def start(self, service_name: str) -> ManagedServiceStatus:
        require_supported_systemd()
        execute_systemctl("start", build_service_unit_name(service_name))
        return read_systemd_status(service_name)

    def stop(self, service_name: str) -> ManagedServiceStatus:
        require_supported_systemd()
        execute_systemctl("stop", build_service_unit_name(service_name))
        return read_systemd_status(service_name)

    def restart(self, service_name: str) -> ManagedServiceStatus:
        require_supported_systemd()
        execute_systemctl("restart", build_service_unit_name(service_name))
        return read_systemd_status(service_name)

    def status(self, service_name: str) -> ManagedServiceStatus:
        require_supported_systemd()
        return read_systemd_status(service_name)


def render_systemd_service_unit(
    *,
    python_bin: Path,
    config_path: Path,
) -> str:
    template_path = get_systemd_service_template()
    rendered = template_path.read_text(encoding="utf-8")
    replacements = {
        "@AUTOCLAW_PYTHON@": _escape_systemd_quoted_value(str(python_bin)),
        "@AUTOCLAW_CONFIG@": _escape_systemd_quoted_value(str(config_path)),
        "@AUTOCLAW_ENV_FILE@": _escape_systemd_unquoted_path(
            str(provider_environment_file_path(config_path))
        ),
    }
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


def read_systemd_status(service_name: str) -> ManagedServiceStatus:
    unit_name = build_service_unit_name(service_name)
    result = execute_systemctl(
        "show",
        unit_name,
        "--property=LoadState,UnitFileState,ActiveState,SubState,FragmentPath",
        should_check=False,
    )
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    load_state = values.get("LoadState")
    unit_file_state = values.get("UnitFileState")
    active_state = values.get("ActiveState")
    sub_state = values.get("SubState")
    fragment_path = values.get("FragmentPath") or None
    installed = load_state not in {None, "", "not-found"}
    enabled = unit_file_state in {"enabled", "linked", "static", "generated"}
    running = active_state == "active"
    return ManagedServiceStatus(
        manager="systemd-user",
        service_name=unit_name,
        is_installed=installed,
        is_enabled=enabled,
        is_running=running,
        is_healthy=None,
        fragment_path=fragment_path,
        active_state=active_state,
        sub_state=sub_state,
    )


def require_supported_systemd() -> None:
    if not is_systemd_supported():
        raise RuntimeError(
            "AutoClaw managed service commands currently support Linux systemd --user only"
        )


def execute_systemctl(
    *args: str,
    should_check: bool = True,
    command_observer: Callable[[tuple[str, ...]], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = (resolve_systemctl_bin(), "--user", *args)
    if command_observer is not None:
        command_observer(command)
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
    )
    if should_check and completed.returncode != 0:
        detail = _bounded_command_detail(completed.stderr or completed.stdout)
        raise ManagedServiceCommandError(
            command=command,
            return_code=completed.returncode,
            detail=detail,
        )
    return completed


def get_linux_user_unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def build_service_unit_name(name: str) -> str:
    return name if name.endswith(".service") else f"{name}.service"


def resolve_systemctl_bin() -> str:
    return os.environ.get("AUTOCLAW_SYSTEMCTL_BIN", "systemctl")


def is_systemd_supported() -> bool:
    return os.name != "nt" and sys.platform.startswith("linux")


def _bounded_command_detail(value: str, *, limit: int = 600) -> str | None:
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"


def _escape_systemd_quoted_value(value: str) -> str:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("managed service paths must fit on one line")
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")


def _escape_systemd_unquoted_path(value: str) -> str:
    escaped = _escape_systemd_quoted_value(value)
    return escaped.replace(" ", "\\x20").replace("\t", "\\x09")


__all__ = [
    "DEFAULT_SERVICE_ENV_TEXT",
    "SystemdUserServiceManager",
    "build_service_unit_name",
    "execute_systemctl",
    "get_linux_user_unit_dir",
    "is_systemd_supported",
    "read_systemd_status",
    "render_systemd_service_unit",
    "require_supported_systemd",
    "resolve_systemctl_bin",
]
