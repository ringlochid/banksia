from __future__ import annotations

import argparse

from scripts.docs.prompt_catalog.validation import validate_prompt_contract


def validate() -> int:
    errors = validate_prompt_contract()
    if errors:
        print_errors(errors)
        return 1
    print("Task-member prompt contract validation passed.")
    return 0


def print_errors(errors: tuple[str, ...]) -> None:
    for error in errors:
        print(f"ERROR: {error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate",))
    parser.parse_args(argv)
    return validate()


if __name__ == "__main__":
    raise SystemExit(main())
