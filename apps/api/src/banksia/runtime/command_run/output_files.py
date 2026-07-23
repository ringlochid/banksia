from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from banksia.runtime.workspace.storage import (
    open_banksia_root,
    open_child_directory,
    open_task_root,
)

_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600


@dataclass(frozen=True, slots=True)
class CommandOutputFile:
    descriptor: int


def create_command_output_file(
    workspace: Path,
    *,
    task_id: str,
    run_id: str,
) -> CommandOutputFile:
    """Exclusively create one Command Run directory and its sole output file."""

    with open_banksia_root(workspace, should_create=False) as banksia_descriptor:
        if banksia_descriptor is None:
            raise FileNotFoundError(workspace / ".banksia")
        with open_task_root(banksia_descriptor, task_id) as task_descriptor:
            with open_child_directory(task_descriptor, "command-runs") as runs_descriptor:
                os.mkdir(run_id, _DIRECTORY_MODE, dir_fd=runs_descriptor)
                try:
                    with open_child_directory(runs_descriptor, run_id) as run_descriptor:
                        output_descriptor = os.open(
                            "output.log",
                            _output_create_flags(),
                            _FILE_MODE,
                            dir_fd=run_descriptor,
                        )
                except BaseException:
                    os.rmdir(run_id, dir_fd=runs_descriptor)
                    raise

    return CommandOutputFile(descriptor=output_descriptor)


def close_command_output_file(output: CommandOutputFile) -> None:
    os.close(output.descriptor)


def _output_create_flags() -> int:
    return os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


__all__ = [
    "CommandOutputFile",
    "close_command_output_file",
    "create_command_output_file",
]
