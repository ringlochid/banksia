from __future__ import annotations

from banksia.runtime.contracts.prompt import (
    PROMPT_DYNAMIC_INPUT_KEYS,
    PROMPT_TRIGGER_KINDS,
    PromptDynamicInput,
)
from banksia.runtime.prompt import (
    INSTRUCTION_ASSETS,
    instruction_asset_path,
    load_instruction_asset,
)

from scripts.docs.prompt_catalog.render import (
    PROMPT_CONTRACT_READBACK_PATH,
    render_prompt_contract_readback,
)

PROMPT_CONTRACT_PATH = PROMPT_CONTRACT_READBACK_PATH.parents[2] / "system-prompts.md"
EXPECTED_ASSET_PATHS = (
    "shared/core.txt",
    "shared/workspace-and-files.txt",
    "shared/checkpoint.txt",
    "positions/task-lead.txt",
    "behaviors/manager-pre-wave.txt",
    "behaviors/contributor.txt",
    "actions/human-request.txt",
    "actions/command-run.txt",
    "situations/continuation.txt",
)
STABLE_TARGET_ASSET_PATHS = tuple(
    path for path in EXPECTED_ASSET_PATHS if path != "behaviors/manager-pre-wave.txt"
)


def validate_prompt_contract(*, should_check_generated_readback: bool = True) -> tuple[str, ...]:
    errors: list[str] = []
    asset_paths = tuple(instruction_asset_path(asset).as_posix() for asset in INSTRUCTION_ASSETS)
    if asset_paths != EXPECTED_ASSET_PATHS:
        errors.append("instruction assets do not match the staged Banksia prompt set")

    for asset in INSTRUCTION_ASSETS:
        try:
            content = load_instruction_asset(asset)
        except (FileNotFoundError, UnicodeDecodeError) as error:
            errors.append(f"cannot load {instruction_asset_path(asset)}: {error}")
            continue
        if not content.strip():
            errors.append(f"instruction asset is empty: {instruction_asset_path(asset)}")

    errors.extend(validate_stable_asset_bodies())

    if tuple(PromptDynamicInput.model_fields) != PROMPT_DYNAMIC_INPUT_KEYS:
        errors.append("dynamic prompt input does not expose the canonical ordered sections")

    if len(PROMPT_TRIGGER_KINDS) != 8 or len(set(PROMPT_TRIGGER_KINDS)) != 8:
        errors.append("prompt trigger kinds must contain exactly eight distinct variants")

    if should_check_generated_readback:
        if not PROMPT_CONTRACT_READBACK_PATH.is_file():
            errors.append("generated Task-member prompt contract readback is missing")
        elif (
            PROMPT_CONTRACT_READBACK_PATH.read_text(encoding="utf-8")
            != render_prompt_contract_readback()
        ):
            errors.append("generated Task-member prompt contract readback is stale")

    return tuple(errors)


def validate_stable_asset_bodies() -> tuple[str, ...]:
    """Keep shipped non-temporary prompt assets byte-exact with normative canon."""

    try:
        contract = PROMPT_CONTRACT_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return (f"cannot read normative prompt contract: {error}",)

    loaded_by_path: dict[str, str] = {}
    for asset in INSTRUCTION_ASSETS:
        try:
            loaded_by_path[instruction_asset_path(asset).as_posix()] = load_instruction_asset(asset)
        except (FileNotFoundError, UnicodeDecodeError):
            continue
    errors: list[str] = []
    for path in STABLE_TARGET_ASSET_PATHS:
        expected = _extract_exact_source_body(contract, path=path)
        if expected is None:
            errors.append(f"normative prompt contract has no exact source body for {path}")
            continue
        actual = loaded_by_path.get(path)
        if actual is not None and actual != expected:
            errors.append(f"instruction asset differs from normative exact source body: {path}")
    return tuple(errors)


def _extract_exact_source_body(contract: str, *, path: str) -> str | None:
    heading = f"### `{path}`"
    lines = contract.splitlines()
    try:
        heading_index = lines.index(heading)
        opening_index = lines.index("```text", heading_index + 1)
        closing_index = lines.index("```", opening_index + 1)
    except ValueError:
        return None
    return "\n".join(lines[opening_index + 1 : closing_index]) + "\n"


__all__ = [
    "EXPECTED_ASSET_PATHS",
    "PROMPT_CONTRACT_PATH",
    "STABLE_TARGET_ASSET_PATHS",
    "validate_prompt_contract",
    "validate_stable_asset_bodies",
]
