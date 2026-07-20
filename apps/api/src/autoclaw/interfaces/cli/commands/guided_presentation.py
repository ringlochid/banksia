from __future__ import annotations

from collections.abc import Sequence

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from autoclaw.interfaces.cli.context import CliContext


def emit_wizard_header(title: str, subtitle: str) -> None:
    context = CliContext()
    if not context.rich_enabled():
        print(f"AutoClaw {title}")
        print(subtitle)
        return
    heading = Text("AutoClaw", style="bold")
    heading.append(f"  /  {title}", style="heading")
    context.console().print(
        Panel(
            Group(heading, Text(subtitle, style="muted")),
            border_style="accent",
            padding=(0, 1),
        )
    )


def emit_key_value_panel(title: str, rows: Sequence[tuple[str, str]]) -> None:
    context = CliContext()
    if not context.rich_enabled():
        print(title)
        for label, value in rows:
            print(f"  {label}: {value}")
        return
    table = Table.grid(padding=(0, 2))
    table.add_column(style="muted", no_wrap=True)
    table.add_column(overflow="fold")
    for label, value in rows:
        table.add_row(label, Text(value))
    context.console().print(
        Panel(
            table,
            title=title,
            title_align="left",
            border_style="muted",
            padding=(0, 1),
        )
    )


def emit_provider_choices() -> None:
    context = CliContext()
    if not context.rich_enabled():
        print("Available provider routes")
        print("  codex     Managed Codex SDK integration")
        print("  claude    Managed Claude SDK integration")
        print("  openclaw  Experimental client; Gateway and MCP are user-managed")
        return
    table = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        header_style="heading",
        pad_edge=False,
    )
    table.add_column("Provider", style="bold", no_wrap=True)
    table.add_column("Lane", no_wrap=True)
    table.add_column("Ownership")
    table.add_row("Codex", Text("Managed", style="success"), "AutoClaw SDK integration")
    table.add_row("Claude", Text("Managed", style="success"), "AutoClaw SDK integration")
    table.add_row(
        "OpenClaw",
        Text("Experimental", style="warn"),
        "AutoClaw client; user-managed Gateway/MCP",
    )
    context.console().print(
        Panel(
            table,
            title="Provider routes",
            title_align="left",
            border_style="accent",
            padding=(0, 1),
        )
    )


def emit_step(message: str) -> None:
    _emit_status_line("→", message, "accent")


def emit_success(message: str) -> None:
    _emit_status_line("✓", message, "success")


def emit_warning(message: str) -> None:
    _emit_status_line("!", message, "warn")


def emit_completion(
    title: str,
    rows: Sequence[tuple[str, str]],
    *,
    next_action: str,
) -> None:
    context = CliContext()
    if not context.rich_enabled():
        print(title)
        for label, value in rows:
            print(f"  {label}: {value}")
        print(f"Next: {next_action}")
        return
    table = Table.grid(padding=(0, 2))
    table.add_column(style="muted", no_wrap=True)
    table.add_column()
    for label, value in rows:
        table.add_row(label, value)
    context.console().print(
        Panel(
            Group(Text("✓ Complete", style="bold success"), Text(), table),
            title=title,
            title_align="left",
            border_style="success",
            padding=(0, 1),
        )
    )
    context.console().print(Text.assemble(("Next  ", "muted"), (next_action, "accent")))


def _emit_status_line(symbol: str, message: str, style: str) -> None:
    context = CliContext()
    if not context.rich_enabled():
        print(message)
        return
    context.console().print(Text.assemble((f"{symbol}  ", style), (message, "")))


__all__ = [
    "emit_completion",
    "emit_key_value_panel",
    "emit_provider_choices",
    "emit_step",
    "emit_success",
    "emit_warning",
    "emit_wizard_header",
]
