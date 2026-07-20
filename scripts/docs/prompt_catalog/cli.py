from __future__ import annotations

import argparse

from scripts.docs.prompt_catalog.render import (
    PROMPT_CONTRACT_READBACK_PATH,
    render_prompt_contract_readback,
)
from scripts.docs.prompt_catalog.validation import validate_prompt_contract


def generate() -> int:
    errors = validate_prompt_contract(should_check_generated_readback=False)
    if errors:
        print_errors(errors)
        return 1
    PROMPT_CONTRACT_READBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROMPT_CONTRACT_READBACK_PATH.write_text(
        render_prompt_contract_readback(),
        encoding="utf-8",
    )
    print(f"Generated {PROMPT_CONTRACT_READBACK_PATH}")
    return 0


def validate() -> int:
    errors = validate_prompt_contract()
    if errors:
        print_errors(errors)
        return 1
    print("V2 prompt contract validation passed.")
    return 0


def print_errors(errors: tuple[str, ...]) -> None:
    for error in errors:
        print(f"ERROR: {error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("generate", "validate"))
    args = parser.parse_args(argv)
    if args.command == "generate":
        return generate()
    return validate()


if __name__ == "__main__":
    raise SystemExit(main())
