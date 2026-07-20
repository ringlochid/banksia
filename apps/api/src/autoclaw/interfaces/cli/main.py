from __future__ import annotations

import sys

import click

from .context import scan_cli_context
from .failure_output import emit_abort, emit_click_exception, emit_unexpected_exception
from .root import cli


def build_parser() -> click.Group:
    return cli


def main(argv: list[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    runtime = scan_cli_context(argv_list)
    normalized_argv = _normalize_debug_option(argv_list)
    try:
        result = cli.main(
            args=normalized_argv,
            prog_name="autoclaw",
            standalone_mode=False,
            obj=runtime,
        )
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    except click.ClickException as exc:
        emit_click_exception(runtime, exc, runtime.argv)
        return int(exc.exit_code)
    except click.exceptions.Abort:
        emit_abort(runtime)
        return 2
    except BaseException as exc:
        emit_unexpected_exception(runtime, exc)
        return 1
    return int(result) if isinstance(result, int) else 0


def _normalize_debug_option(argv: list[str]) -> list[str]:
    """Accept the root debug flag before or after a subcommand."""

    separator = argv.index("--") if "--" in argv else len(argv)
    command_args = argv[:separator]
    trailing_args = argv[separator:]
    if "--debug" not in command_args:
        return argv
    return ["--debug", *(item for item in command_args if item != "--debug"), *trailing_args]
