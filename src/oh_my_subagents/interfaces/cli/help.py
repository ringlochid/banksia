from __future__ import annotations

ROOT_HELP_EPILOG = """Examples:
  oms init --json
  oms service status
  oms workflow import --file ./advanced-reviewed-code-change.yaml
"""


def help_command_for(argv: tuple[str, ...]) -> str:
    command_tokens: list[str] = []
    for token in argv:
        if token.startswith("-"):
            break
        command_tokens.append(token)
        if len(command_tokens) >= 2:
            break
    if not command_tokens:
        return "oms --help"
    return "oms " + " ".join(command_tokens) + " --help"
