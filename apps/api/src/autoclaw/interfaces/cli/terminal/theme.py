from __future__ import annotations

import argparse
import os
import sys

from autoclaw.interfaces.cli.terminal.palette import LOBSTER_PALETTE


def rich_enabled(args: argparse.Namespace | None = None) -> bool:
    if args is not None and getattr(args, "plain", False):
        return False
    if args is not None and getattr(args, "no_color", False):
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def accent(text: str, *, is_rich: bool) -> str:
    return _color(text, LOBSTER_PALETTE["accent_bright"]) if is_rich else text


def error(text: str, *, is_rich: bool) -> str:
    return _color(text, LOBSTER_PALETTE["error"]) if is_rich else text


def heading(text: str, *, is_rich: bool) -> str:
    return _color(text, LOBSTER_PALETTE["accent"], bold=True) if is_rich else text


def muted(text: str, *, is_rich: bool) -> str:
    return _color(text, LOBSTER_PALETTE["muted"]) if is_rich else text


def success(text: str, *, is_rich: bool) -> str:
    return _color(text, LOBSTER_PALETTE["success"]) if is_rich else text


def warn(text: str, *, is_rich: bool) -> str:
    return _color(text, LOBSTER_PALETTE["warn"]) if is_rich else text


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _color(value: str, hex_value: str, *, bold: bool = False) -> str:
    red, green, blue = _hex_to_rgb(hex_value)
    prefix = "\033[1;" if bold else "\033["
    return f"{prefix}38;2;{red};{green};{blue}m{value}\033[0m"


__all__ = [
    "accent",
    "error",
    "heading",
    "muted",
    "rich_enabled",
    "success",
    "warn",
]
