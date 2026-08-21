from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "imports",
    (
        (
            "from oh_my_subagents.runtime.checkpoint import commit_checkpoint; "
            "from oh_my_subagents.runtime.node_operations import NodeOperationExecutor"
        ),
        (
            "from oh_my_subagents.runtime.node_operations import NodeOperationExecutor; "
            "from oh_my_subagents.runtime.checkpoint import commit_checkpoint"
        ),
    ),
)
def test_runtime_packages_import_in_either_order(imports: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", imports],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
