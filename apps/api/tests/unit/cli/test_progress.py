from __future__ import annotations

import argparse
from io import StringIO

from autoclaw.interfaces.cli.progress import CliProgress, sanitize_command_label


def test_cli_progress_suppresses_json_output() -> None:
    stream = StringIO()
    progress = CliProgress.from_args(
        argparse.Namespace(json=True, plain=True, no_color=False, verbose=True),
        stream=stream,
    )

    progress.step("database", "Running database upgrade")
    progress.command_output(
        "providers check --stdin",
        0,
        "Patched config\n",
        "",
    )

    assert stream.getvalue() == ""


def test_cli_progress_verbose_redacts_nested_output() -> None:
    stream = StringIO()
    progress = CliProgress.from_args(
        argparse.Namespace(json=False, plain=True, no_color=False, verbose=True),
        stream=stream,
    )

    progress.command_output(
        "providers check --stdin",
        0,
        'token="live-token"\nAuthorization: Bearer abc.def\n',
        "password=secret-password\n",
    )

    output = stream.getvalue()
    assert "providers check --stdin completed" in output
    assert 'token="<redacted>"' in output
    assert "Authorization: Bearer <redacted>" in output
    assert "password=<redacted>" in output
    assert "live-token" not in output
    assert "abc.def" not in output
    assert "secret-password" not in output


def test_sanitize_command_label_redacts_sensitive_option_values() -> None:
    label = sanitize_command_label(
        (
            "providers",
            "check",
            "--token",
            "secret-token",
        )
    )

    assert label == "providers check --token <redacted>"
