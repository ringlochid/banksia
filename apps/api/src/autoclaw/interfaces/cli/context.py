from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass

from rich.console import Console

from .theme import build_rich_theme

MAX_RICH_CONSOLE_WIDTH = 110


@dataclass(frozen=True)
class CliContext:
    is_json_output: bool = False
    is_plain: bool = False
    is_no_color: bool = False
    is_debug: bool = False
    argv: tuple[str, ...] = ()

    def overlay(
        self,
        *,
        is_json_output: bool | None = None,
        is_plain: bool | None = None,
        is_no_color: bool | None = None,
        is_debug: bool | None = None,
        argv: tuple[str, ...] | None = None,
    ) -> CliContext:
        return CliContext(
            is_json_output=self.is_json_output if is_json_output is None else is_json_output,
            is_plain=self.is_plain if is_plain is None else is_plain,
            is_no_color=self.is_no_color if is_no_color is None else is_no_color,
            is_debug=self.is_debug if is_debug is None else is_debug,
            argv=self.argv if argv is None else argv,
        )

    def rich_enabled(self) -> bool:
        if self.is_json_output or self.is_plain or self.is_no_color:
            return False
        if os.environ.get("NO_COLOR"):
            return False
        return sys.stdout.isatty()

    def console(self, *, is_stderr: bool = False) -> Console:
        is_rich = self.rich_enabled()
        return Console(
            stderr=is_stderr,
            force_terminal=is_rich,
            no_color=not is_rich,
            theme=build_rich_theme(),
            soft_wrap=False,
            width=(
                min(shutil.get_terminal_size().columns, MAX_RICH_CONSOLE_WIDTH) if is_rich else None
            ),
        )


def scan_cli_context(argv: list[str]) -> CliContext:
    return CliContext(
        is_json_output="--json" in argv,
        is_plain="--plain" in argv,
        is_no_color="--no-color" in argv,
        is_debug=(
            "--debug" in argv
            or os.environ.get("AUTOCLAW_DEBUG", "").lower() in {"1", "true", "yes", "on"}
        ),
        argv=tuple(argv),
    )
