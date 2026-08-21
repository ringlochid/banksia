from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Any

import click
from pydantic import ValidationError

from banksia.platform.managed_services import ManagedServiceCommandError

from .help import help_command_for
from .prompts import debug_hint


class CliPrerequisiteError(click.ClickException):
    """Raised when an operation needs a missing setup prerequisite."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "setup_required",
        title: str = "Setup required",
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.title = title
        self.hint = hint


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
    if isinstance(exc, CliPrerequisiteError):
        return CliFailure(
            kind=exc.kind,
            title=exc.title,
            message=exc.format_message(),
            exit_code=exc.exit_code,
            hint=exc.hint or help_hint,
        )
    if isinstance(exc, click.exceptions.NoSuchOption):
        option = exc.option_name or exc.format_message()
        return CliFailure(
            kind="unknown_option",
            title="Unknown option",
            message=f'Oh My Subagents does not recognize option "{option}".',
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
            message=f'Oh My Subagents does not know the command "{command}".',
            exit_code=exc.exit_code,
            hint="Try: oms --help",
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


def unexpected_failure(
    exc: BaseException,
    argv: tuple[str, ...] = (),
) -> CliFailure:
    from banksia.interfaces.cli.commands.task import TaskStartCliError
    from banksia.persistence.forward_upgrade import DatabaseSchemaUpgradeUnavailableError
    from banksia.persistence.schema_contract import DatabaseSchemaMismatchError

    if isinstance(exc, TaskStartCliError):
        return CliFailure(
            kind=exc.kind,
            title="Task start failed",
            message=str(exc),
            exit_code=1,
            hint=exc.hint,
        )
    if isinstance(exc, DatabaseSchemaUpgradeUnavailableError):
        return CliFailure(
            kind="database_upgrade_unavailable",
            title="Database upgrade unavailable",
            message=str(exc),
            exit_code=1,
            hint=(
                "Oh My Subagents made no schema changes. Back up the database and inspect the "
                "reported differences. Use `oms db reset` only if you accept deletion "
                "of controller history."
            ),
            details={"difference_count": len(exc.messages)},
        )
    if isinstance(exc, DatabaseSchemaMismatchError):
        return CliFailure(
            kind="database_upgrade_required",
            title="Database upgrade required",
            message=str(exc),
            exit_code=1,
            hint=(
                "Preserve the database and run:\n"
                f"  {_database_upgrade_command(argv)}\n\n"
                "Use `oms db reset` only if you accept deletion of controller history."
            ),
        )
    if isinstance(exc, ManagedServiceCommandError):
        return _managed_service_failure(exc)
    if isinstance(exc, ValidationError):
        return _configuration_validation_failure(exc)
    message = str(exc).strip() or exc.__class__.__name__
    return CliFailure(
        kind="runtime_error",
        title="Oh My Subagents command failed",
        message=message,
        exit_code=1,
        hint=debug_hint(),
        details={"error_type": exc.__class__.__name__},
    )


def _database_upgrade_command(argv: tuple[str, ...]) -> str:
    command = ["oms", "db", "upgrade"]
    for index, argument in enumerate(argv):
        if argument == "--config" and index + 1 < len(argv):
            command.extend(("--config", argv[index + 1]))
            break
        if argument.startswith("--config="):
            command.extend(("--config", argument.partition("=")[2]))
            break
    return shlex.join(command)


def _managed_service_failure(exc: ManagedServiceCommandError) -> CliFailure:
    detail = f" The operating system reported: {exc.detail}" if exc.detail else ""
    return CliFailure(
        kind="managed_service_command_failed",
        title=f"Background service {exc.operation} failed",
        message=(
            f"The operating system could not {exc.operation} the Oh My Subagents "
            f"background service.{detail}"
        ),
        exit_code=1,
        hint=(
            "Inspect Oh My Subagents's portable service status and bounded log:\n"
            "  oms service status\n"
            "  oms service logs --lines 200\n\n"
            "Reconcile an outdated definition:\n"
            "  oms service install"
        ),
        details={
            "manager": exc.manager,
            "operation": exc.operation,
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
        message="\n".join(findings) or "Oh My Subagents configuration could not be validated.",
        exit_code=1,
        hint=(
            "Remove or correct the named setting in the selected config or service "
            "environment file, then rerun the command."
        ),
        details={"finding_count": len(findings)},
    )
