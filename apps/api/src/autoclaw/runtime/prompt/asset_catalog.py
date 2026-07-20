from __future__ import annotations

from enum import StrEnum
from functools import cache
from importlib.resources import files
from pathlib import PurePosixPath

from autoclaw.runtime.contracts.prompt import PromptFamily

ASSET_PACKAGE = "autoclaw.runtime.prompt.assets"


class InstructionAsset(StrEnum):
    AUTHORITY = "shared/authority"
    CONTEXT_ACCESS = "shared/context-access"
    CONTROL_TRANSFER = "shared/control-transfer"
    WORKER = "families/worker"
    PARENT_ROOT = "families/parent-root"


INSTRUCTION_ASSETS = (
    InstructionAsset.AUTHORITY,
    InstructionAsset.CONTEXT_ACCESS,
    InstructionAsset.CONTROL_TRANSFER,
    InstructionAsset.WORKER,
    InstructionAsset.PARENT_ROOT,
)
SHARED_INSTRUCTION_ASSETS = (
    InstructionAsset.AUTHORITY,
    InstructionAsset.CONTEXT_ACCESS,
    InstructionAsset.CONTROL_TRANSFER,
)
FAMILY_INSTRUCTION_ASSET = {
    PromptFamily.WORKER: InstructionAsset.WORKER,
    PromptFamily.PARENT_ROOT: InstructionAsset.PARENT_ROOT,
}


@cache
def load_instruction_asset(asset: InstructionAsset) -> str:
    path = instruction_asset_path(asset)
    resource = files(ASSET_PACKAGE).joinpath(*path.parts)
    return resource.read_bytes().decode("utf-8")


def instruction_asset_path(asset: InstructionAsset) -> PurePosixPath:
    return PurePosixPath("instructions", *asset.value.split("/")).with_suffix(".md")


def instruction_assets_for_family(family: PromptFamily) -> tuple[InstructionAsset, ...]:
    return (*SHARED_INSTRUCTION_ASSETS, FAMILY_INSTRUCTION_ASSET[family])


__all__ = [
    "INSTRUCTION_ASSETS",
    "InstructionAsset",
    "instruction_asset_path",
    "instruction_assets_for_family",
    "load_instruction_asset",
]
