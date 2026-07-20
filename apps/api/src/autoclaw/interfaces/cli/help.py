from __future__ import annotations

ROOT_HELP_EPILOG = """Examples:
  autoclaw init --json
  autoclaw service status
  autoclaw definitions import --file ./reviewer.yaml
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
        return "autoclaw --help"
    return "autoclaw " + " ".join(command_tokens) + " --help"
