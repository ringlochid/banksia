from __future__ import annotations

from banksia.runtime.prompt import (
    INSTRUCTION_ASSETS,
    InstructionAsset,
    instruction_asset_path,
    load_instruction_asset,
)


def test_target_prompt_asset_catalog_is_complete_and_packaged_as_text() -> None:
    assert INSTRUCTION_ASSETS == tuple(InstructionAsset)
    assert {asset.value for asset in INSTRUCTION_ASSETS} == {
        "shared/core",
        "shared/workspace-and-files",
        "shared/checkpoint",
        "positions/task-lead",
        "behaviors/manager-pre-wave",
        "behaviors/contributor",
        "actions/human-request",
        "actions/command-run",
        "situations/continuation",
    }
    for asset in INSTRUCTION_ASSETS:
        assert instruction_asset_path(asset).suffix == ".txt"
        assert load_instruction_asset(asset).strip()
