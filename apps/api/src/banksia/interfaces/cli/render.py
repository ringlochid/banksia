from __future__ import annotations

import sys
import traceback

from rich.panel import Panel
from rich.text import Text

from .context import CliContext
from .errors import CliFailure


def render_failure(
    context: CliContext,
    failure: CliFailure,
    exc: BaseException | None = None,
) -> None:
    if context.rich_enabled():
        console = context.console()
        body = Text()
        body.append(failure.message, style="error")
        if failure.hint:
            body.append(f"\n\n{failure.hint}", style="muted")
        console.print(Panel.fit(body, title=failure.title, border_style="error"))
        if context.is_debug and exc is not None:
            trace = "".join(traceback.format_exception(exc))
            console.print(Panel(trace.rstrip(), title="Traceback", border_style="warn"))
        return

    print(failure.title)
    print(f"Reason: {failure.message}")
    if failure.hint:
        print(failure.hint)
    if context.is_debug and exc is not None:
        traceback.print_exception(exc, file=sys.stdout)
