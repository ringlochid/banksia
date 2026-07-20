from __future__ import annotations

import click
from rich.text import Text

from .context import CliContext
from .errors import CliFailure, failure_from_click_exception, unexpected_failure
from .json_output import emit_json
from .render import render_failure


def emit_click_exception(
    context: CliContext,
    exc: click.ClickException,
    argv: tuple[str, ...],
) -> None:
    _emit_failure(context, failure_from_click_exception(exc, argv))


def emit_unexpected_exception(context: CliContext, exc: BaseException) -> None:
    failure = unexpected_failure(exc)
    debug_exception = None if failure.kind == "configuration_invalid" else exc
    _emit_failure(context, failure, exc=debug_exception)


def emit_abort(context: CliContext) -> None:
    """Render an explicit cancellation without implying completed steps rolled back."""

    message = "Cancelled."
    if "setup" in context.argv:
        message = "Setup cancelled. Completed setup steps were kept."
    if context.is_json_output:
        emit_json(
            {
                "ok": False,
                "error": {
                    "kind": "cancelled",
                    "message": message,
                    "hint": None,
                    "details": [],
                },
            }
        )
        return
    context.console(is_stderr=True).print(Text(message, style="warn"))


def _emit_failure(
    context: CliContext,
    failure: CliFailure,
    *,
    exc: BaseException | None = None,
) -> None:
    if context.is_json_output:
        emit_json(
            {
                "ok": False,
                "error": {
                    "kind": failure.kind,
                    "message": failure.message,
                    "hint": failure.hint,
                    "details": failure.details,
                },
            }
        )
        return
    render_failure(context, failure, exc)
