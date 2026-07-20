from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import click
from pydantic import ValidationError

from autoclaw.platform.managed_services import ManagedServiceCommandError

from .help import help_command_for
from .prompts import debug_hint


@dataclass(frozen=True)
class CliFailure:
    kind: str
    title: str
    message: str
    exit_code: int
    hint: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def failure_from_click_exception(exc: click.ClickException, argv: tuple[str, ...]) -> CliFailure:
    help_hint = f"Try: {help_command_for(argv)}"
    if isinstance(exc, click.exceptions.NoSuchOption):
        option = exc.option_name or exc.format_message()
        return CliFailure(
            kind="unknown_option",
            title="Unknown option",
            message=f'AutoClaw does not recognize option "{option}".',
            exit_code=exc.exit_code,
            hint=help_hint,
            details={"option": option},
        )
    if isinstance(exc, click.exceptions.UsageError) and exc.format_message().startswith(
        "No such command"
    ):
        command = exc.format_message().split("'", 2)[1]
        return CliFailure(
            kind="unknown_command",
            title="Unknown command",
            message=f'AutoClaw does not know the command "{command}".',
            exit_code=exc.exit_code,
            hint="Try: autoclaw --help",
            details={"command": command},
        )
    if isinstance(exc, click.exceptions.MissingParameter):
        parameter = exc.param_hint or exc.format_message()
        return CliFailure(
            kind="missing_parameter",
            title="Missing input",
            message=f"Missing required input: {parameter}.",
            exit_code=exc.exit_code,
            hint=help_hint,
            details={"parameter": str(parameter)},
        )
    if isinstance(exc, click.exceptions.BadParameter):
        return CliFailure(
            kind="bad_parameter",
            title="Invalid value",
            message=exc.format_message(),
            exit_code=exc.exit_code,
            hint=help_hint,
        )
    return CliFailure(
        kind="parse_error",
        title="Command parse failed",
        message=exc.format_message(),
        exit_code=exc.exit_code,
        hint=help_hint,
    )


def unexpected_failure(exc: BaseException) -> CliFailure:
    if isinstance(exc, ManagedServiceCommandError):
        return _managed_service_failure(exc)
    if isinstance(exc, ValidationError):
        return _configuration_validation_failure(exc)
    message = str(exc).strip() or exc.__class__.__name__
    return CliFailure(
        kind="runtime_error",
        title="AutoClaw command failed",
        message=message,
        exit_code=1,
        hint=debug_hint(),
        details={"error_type": exc.__class__.__name__},
    )


def _managed_service_failure(exc: ManagedServiceCommandError) -> CliFailure:
    service_name = exc.service_name or "the managed service"
    detail = f" systemctl reported: {exc.detail}" if exc.detail else ""
    return CliFailure(
        kind="managed_service_command_failed",
        title=f"Managed service {exc.action} failed",
        message=f"systemd could not {exc.action} {service_name}.{detail}",
        exit_code=1,
        hint=(
            "Inspect the unit:\n"
            f"  systemctl --user status {service_name} --no-pager\n"
            f"  journalctl --user -u {service_name} -n 50 --no-pager\n\n"
            "Reconcile an outdated managed unit:\n"
            "  autoclaw service install"
        ),
        details={
            "action": exc.action,
            "service_name": exc.service_name,
            "return_code": exc.return_code,
        },
    )


def _configuration_validation_failure(exc: ValidationError) -> CliFailure:
    findings: list[str] = []
    for finding in exc.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in finding["loc"])
        prefix = f"{location}: " if location else ""
        findings.append(f"{prefix}{finding['msg']}")
    return CliFailure(
        kind="configuration_invalid",
        title="Configuration invalid",
        message="\n".join(findings) or "AutoClaw configuration could not be validated.",
        exit_code=1,
        hint=(
            "Remove or correct the named setting in the selected config or service "
            "environment file, then rerun the command."
        ),
        details={"finding_count": len(findings)},
    )
