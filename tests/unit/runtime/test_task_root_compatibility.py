from __future__ import annotations

from pathlib import Path

import pytest

from oh_my_subagents.runtime.task_root import command_run_output_path
from oh_my_subagents.runtime.workspace.availability import task_workspace_root


@pytest.mark.parametrize("container_name", (".oms", ".banksia"))
def test_persisted_task_roots_accept_canonical_and_legacy_containers(
    tmp_path: Path,
    container_name: str,
) -> None:
    task_id = "t_01234567"
    workspace = tmp_path / "workspace"
    task_root = workspace / container_name / task_id

    assert task_workspace_root(task_root, task_id=task_id) == workspace
    assert (
        command_run_output_path(
            task_id=task_id,
            run_id="c_01234567",
            task_container_name=container_name,
        )
        == Path(container_name) / task_id / "command-runs" / "c_01234567" / "output.log"
    )


def test_persisted_task_root_rejects_an_unknown_container(tmp_path: Path) -> None:
    task_id = "t_01234567"

    with pytest.raises(RuntimeError, match="inconsistent persisted Task root"):
        task_workspace_root(tmp_path / ".other" / task_id, task_id=task_id)
