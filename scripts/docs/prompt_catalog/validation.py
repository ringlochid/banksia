from __future__ import annotations

from autoclaw.runtime.contracts.prompt import (
    PROMPT_DYNAMIC_INPUT_KEYS,
    PROMPT_TRIGGER_KINDS,
    PromptDynamicInput,
    PromptFamily,
)
from autoclaw.runtime.prompt import (
    INSTRUCTION_ASSETS,
    instruction_asset_path,
    instruction_assets_for_family,
    load_instruction_asset,
)

from scripts.docs.prompt_catalog.render import (
    PROMPT_CONTRACT_READBACK_PATH,
    render_prompt_contract_readback,
)

EXPECTED_ASSET_PATHS = (
    "instructions/shared/authority.md",
    "instructions/shared/context-access.md",
    "instructions/shared/control-transfer.md",
    "instructions/families/worker.md",
    "instructions/families/parent-root.md",
)


def validate_prompt_contract(*, should_check_generated_readback: bool = True) -> tuple[str, ...]:
    errors: list[str] = []
    asset_paths = tuple(instruction_asset_path(asset).as_posix() for asset in INSTRUCTION_ASSETS)
    if asset_paths != EXPECTED_ASSET_PATHS:
        errors.append("instruction assets do not match the canonical five-file set")

    for asset in INSTRUCTION_ASSETS:
        try:
            content = load_instruction_asset(asset)
        except (FileNotFoundError, UnicodeDecodeError) as error:
            errors.append(f"cannot load {instruction_asset_path(asset)}: {error}")
            continue
        if not content.strip():
            errors.append(f"instruction asset is empty: {instruction_asset_path(asset)}")

    if tuple(PromptDynamicInput.model_fields) != PROMPT_DYNAMIC_INPUT_KEYS:
        errors.append("dynamic prompt input does not expose the canonical six ordered keys")

    shared_prefix = INSTRUCTION_ASSETS[:3]
    for family in PromptFamily:
        family_assets = instruction_assets_for_family(family)
        if family_assets[:3] != shared_prefix or len(family_assets) != 4:
            errors.append(f"{family.value} does not use three shared assets then one family asset")

    if len(PROMPT_TRIGGER_KINDS) != 8 or len(set(PROMPT_TRIGGER_KINDS)) != 8:
        errors.append("prompt trigger kinds must contain exactly eight distinct variants")

    if should_check_generated_readback:
        if not PROMPT_CONTRACT_READBACK_PATH.is_file():
            errors.append("generated V2 prompt contract readback is missing")
        elif (
            PROMPT_CONTRACT_READBACK_PATH.read_text(encoding="utf-8")
            != render_prompt_contract_readback()
        ):
            errors.append("generated V2 prompt contract readback is stale")

    return tuple(errors)


__all__ = ["EXPECTED_ASSET_PATHS", "validate_prompt_contract"]
