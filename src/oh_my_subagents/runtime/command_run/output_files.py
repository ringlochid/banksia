from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from oh_my_subagents.platform.workspace_files import select_workspace_file_operations
from oh_my_subagents.runtime.workspace.storage import (
    open_banksia_root,
    open_child_directory,
    open_task_root,
)


@dataclass(frozen=True, slots=True)
class CommandOutputFile:
    descriptor: int


def create_command_output_file(
    workspace: Path,
    *,
    task_id: str,
    run_id: str,
) -> CommandOutputFile:
    """Exclusively create one private Command Run directory and output stream."""

    operations = select_workspace_file_operations()
    with open_banksia_root(workspace, should_create=False) as banksia_root:
        if banksia_root is None:
            raise FileNotFoundError(workspace / ".banksia")
        with open_task_root(banksia_root, task_id) as task_root:
            with open_child_directory(task_root, "command-runs") as command_runs:
                run_root = operations.create_child_directory(command_runs, run_id)
                try:
                    output_descriptor = operations.create_output_descriptor(
                        run_root,
                        "output.log",
                    )
                except BaseException:
                    operations.remove_retained_tree(
                        command_runs,
                        run_id,
                        run_root,
                    )
                    raise
                finally:
                    run_root.close()

    return CommandOutputFile(descriptor=output_descriptor)


def close_command_output_file(output: CommandOutputFile) -> None:
    os.close(output.descriptor)


__all__ = [
    "CommandOutputFile",
    "close_command_output_file",
    "create_command_output_file",
]
