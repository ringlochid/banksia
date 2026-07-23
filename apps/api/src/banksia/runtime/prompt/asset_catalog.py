from __future__ import annotations

from enum import StrEnum
from functools import cache
from importlib.resources import files
from pathlib import PurePosixPath

from banksia.runtime.contracts.prompt import PromptDynamicInput
from banksia.runtime.contracts.team_read import MemberBehavior

ASSET_PACKAGE = "banksia.runtime.prompt.assets"


class InstructionAsset(StrEnum):
    CORE = "shared/core"
    WORKSPACE_AND_FILES = "shared/workspace-and-files"
    CHECKPOINT = "shared/checkpoint"
    TASK_LEAD = "positions/task-lead"
    MANAGER_PRE_WAVE = "behaviors/manager-pre-wave"
    CONTRIBUTOR = "behaviors/contributor"
    HUMAN_REQUEST = "actions/human-request"
    COMMAND_RUN = "actions/command-run"
    CONTINUATION = "situations/continuation"


INSTRUCTION_ASSETS = tuple(InstructionAsset)
_BASE_ASSETS = (
    InstructionAsset.CORE,
    InstructionAsset.WORKSPACE_AND_FILES,
    InstructionAsset.CHECKPOINT,
)


@cache
def load_instruction_asset(asset: InstructionAsset) -> str:
    path = instruction_asset_path(asset)
    resource = files(ASSET_PACKAGE).joinpath(*path.parts)
    return resource.read_bytes().decode("utf-8")


def instruction_asset_path(asset: InstructionAsset) -> PurePosixPath:
    return PurePosixPath(*asset.value.split("/")).with_suffix(".txt")


def instruction_assets_for_request(
    dynamic_input: PromptDynamicInput,
) -> tuple[InstructionAsset, ...]:
    selected: list[InstructionAsset] = list(_BASE_ASSETS)
    member = dynamic_input.current_member
    actions = frozenset(dynamic_input.available_actions)
    if member.position == "task_lead":
        selected.append(InstructionAsset.TASK_LEAD)
    selected.append(
        InstructionAsset.MANAGER_PRE_WAVE
        if member.behavior is MemberBehavior.MANAGER
        else InstructionAsset.CONTRIBUTOR
    )
    if "open_human_request" in actions and member.effective_capabilities.human_request:
        selected.append(InstructionAsset.HUMAN_REQUEST)
    if "start_command_run" in actions and member.effective_capabilities.command_run == "allow":
        selected.append(InstructionAsset.COMMAND_RUN)
    if dynamic_input.continuation is not None:
        selected.append(InstructionAsset.CONTINUATION)
    return tuple(selected)


__all__ = [
    "INSTRUCTION_ASSETS",
    "InstructionAsset",
    "instruction_asset_path",
    "instruction_assets_for_request",
    "load_instruction_asset",
]
