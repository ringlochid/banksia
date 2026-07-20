from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "imports",
    (
        (
            "from autoclaw.runtime.checkpoint import "
            "require_legal_checkpoint_successor; "
            "from autoclaw.runtime.node_operations import NodeOperationExecutor"
        ),
        (
            "from autoclaw.runtime.node_operations import NodeOperationExecutor; "
            "from autoclaw.runtime.checkpoint import "
            "require_legal_checkpoint_successor"
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
