from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from typing import Any, ParamSpec, TypeVar

import click

from autoclaw.config import CONFIG_ENV_VAR
from autoclaw.paths import default_config_path

P = ParamSpec("P")
T = TypeVar("T")


def config_option(function: Callable[P, T]) -> Callable[P, T]:
    return click.option("--config", default=default_config_text, show_default=True)(function)


def output_options(function: Callable[P, T]) -> Callable[P, T]:
    function = click.option(
        "--verbose",
        is_flag=True,
        help="Show nested command output when available.",
    )(function)
    function = click.option(
        "--no-color",
        is_flag=True,
        help="Disable ANSI color output.",
    )(function)
    function = click.option("--plain", is_flag=True, help="Disable rich styling.")(function)
    function = click.option(
        "--json",
        "json_output",
        is_flag=True,
        help="Emit JSON output only.",
    )(function)
    return function


def build_argument_namespace(**kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def invoke_handler_result(result: int | Any) -> int:
    if asyncio.iscoroutine(result):
        exit_code = int(asyncio.run(result))
    else:
        exit_code = int(result)
    if exit_code != 0:
        raise click.exceptions.Exit(exit_code)
    return exit_code


def default_config_text() -> str:
    return os.environ.get(CONFIG_ENV_VAR, str(default_config_path()))


def package_version() -> str:
    try:
        return version("autoclaw")
    except PackageNotFoundError:
        return "0.1.1"


__all__ = [
    "build_argument_namespace",
    "config_option",
    "default_config_text",
    "invoke_handler_result",
    "output_options",
    "package_version",
]
