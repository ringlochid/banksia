from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TextIO

from autoclaw.interfaces.cli.terminal.theme import rich_enabled

SENSITIVE_OPTION_NAMES = {
    "--password",
    "--token",
}
AUTHORIZATION_VALUE_PATTERN = re.compile(
    r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(?!bearer\s+)([^\"'\s,}]+)"
)
SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)((?:api[_-]?key|password|secret|token)"
    r"[\"']?\s*[:=]\s*)([\"']?)([^\"'\s,}]+)"
)
BEARER_TOKEN_PATTERN = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._~+/=-]+)")

RICH_TOPIC_SYMBOLS = {
    "config": "→",
    "server": "→",
    "database": "🗄",
    "seed": "🌱",
    "service": "⚙️",
    "command": "→",
}
RICH_STATUS_SYMBOLS = {
    "step": "→",
    "done": "✓",
    "warn": "!",
    "fail": "✗",
}
PLAIN_STATUS_SYMBOLS = {
    "step": "->",
    "done": "OK",
    "warn": "WARN",
    "fail": "ERR",
}


@dataclass(frozen=True)
class CliProgress:
    is_enabled: bool
    is_rich: bool
    is_verbose: bool
    stream: TextIO

    @classmethod
    def from_args(
        cls,
        args: argparse.Namespace,
        *,
        stream: TextIO | None = None,
    ) -> CliProgress:
        is_json_output = bool(getattr(args, "json", False))
        return cls(
            is_enabled=not is_json_output,
            is_rich=not is_json_output and rich_enabled(args),
            is_verbose=bool(getattr(args, "verbose", False)),
            stream=stream or sys.stderr,
        )

    @classmethod
    def disabled(cls) -> CliProgress:
        return cls(
            is_enabled=False,
            is_rich=False,
            is_verbose=False,
            stream=sys.stderr,
        )

    def step(self, topic: str, message: str) -> None:
        self._write("step", topic, message)

    def done(self, topic: str, message: str) -> None:
        self._write("done", topic, message)

    def warn(self, topic: str, message: str) -> None:
        self._write("warn", topic, message)

    def fail(self, topic: str, message: str) -> None:
        self._write("fail", topic, message)

    def command(self, command_label: str) -> None:
        self.step("command", f"Running {redact_cli_text(command_label)}")

    def command_args(self, command_args: Sequence[str]) -> None:
        self.command(sanitize_command_label(command_args))

    def command_output(
        self,
        command_label: str,
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> None:
        if not self.is_enabled:
            return
        safe_label = redact_cli_text(command_label)
        if returncode == 0:
            self.done("command", f"{safe_label} completed")
            if self.is_verbose:
                self._write_command_streams(stdout=stdout, stderr=stderr)
            return
        self.fail("command", f"{safe_label} failed with exit code {returncode}")
        self._write_command_streams(stdout=stdout, stderr=stderr)

    def _write(self, status: str, topic: str, message: str) -> None:
        if not self.is_enabled:
            return
        symbol = self._symbol(status=status, topic=topic)
        print(f"{symbol} {message}", file=self.stream)

    def _symbol(self, *, status: str, topic: str) -> str:
        if not self.is_rich:
            return PLAIN_STATUS_SYMBOLS[status]
        if status == "step":
            return RICH_TOPIC_SYMBOLS.get(topic, RICH_STATUS_SYMBOLS[status])
        return RICH_STATUS_SYMBOLS[status]

    def _write_command_streams(self, *, stdout: str, stderr: str) -> None:
        safe_stdout = redact_cli_text(stdout).strip()
        safe_stderr = redact_cli_text(stderr).strip()
        if safe_stdout:
            self._write_block("stdout", safe_stdout)
        if safe_stderr:
            self._write_block("stderr", safe_stderr)

    def _write_block(self, label: str, text: str) -> None:
        print(f"   {label}:", file=self.stream)
        for line in text.splitlines():
            print(f"     {line}", file=self.stream)


def sanitize_command_label(command_args: Sequence[str]) -> str:
    sanitized: list[str] = []
    should_redact_next = False
    for arg in command_args:
        if should_redact_next:
            sanitized.append("<redacted>")
            should_redact_next = False
            continue
        if arg in SENSITIVE_OPTION_NAMES:
            sanitized.append(arg)
            should_redact_next = True
            continue
        sanitized.append(redact_cli_text(arg))
    return " ".join(sanitized)


def redact_cli_text(value: str) -> str:
    redacted = BEARER_TOKEN_PATTERN.sub(r"\1<redacted>", value)
    redacted = AUTHORIZATION_VALUE_PATTERN.sub(r"\1<redacted>", redacted)
    return SENSITIVE_VALUE_PATTERN.sub(_redact_sensitive_value, redacted)


def _redact_sensitive_value(match: re.Match[str]) -> str:
    prefix = match.group(1)
    quote = match.group(2)
    if quote:
        return f"{prefix}{quote}<redacted>{quote}"
    return f"{prefix}<redacted>"


__all__ = [
    "CliProgress",
    "redact_cli_text",
    "sanitize_command_label",
]
