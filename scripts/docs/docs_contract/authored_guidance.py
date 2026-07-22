from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping

GENERIC_GUIDANCE_PATTERNS = (
    (
        "controller operation",
        re.compile(
            r"\b(?:add_child|update_child|remove_child|delegate_children|"
            r"open_human_request|start_command_run|get_current_context|set_work_plan)\b",
            re.IGNORECASE,
        ),
    ),
    ("Checkpoint teaching", re.compile(r"\bcheckpoints?\b", re.IGNORECASE)),
    ("Delegation Wave teaching", re.compile(r"\bdelegation waves?\b", re.IGNORECASE)),
    (
        "execution scheduling",
        re.compile(
            r"\b(?:delegate|run|execute|launch)\b[^.!?\n]{0,60}"
            r"\b(?:in parallel|sequentially|concurrently)\b|"
            r"\b(?:parallelize|sequence)\b[^.!?\n]{0,40}\b(?:child|work|assignment)",
            re.IGNORECASE,
        ),
    ),
    (
        "runtime wait",
        re.compile(
            r"\bwait for (?:a |the )?(?:child|children|wave|human request|command run)|"
            r"\bstop (?:the )?(?:dispatch|provider turn|turn) immediately\b",
            re.IGNORECASE,
        ),
    ),
    (
        "note or file-reference teaching",
        re.compile(
            r"(?:\.banksia/|\bnotes/|\bartifacts/|\bfile references?\b|"
            r"\b(?:write|create|read|update) (?:a |the |one )?(?:shared )?note\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "anti-relay teaching",
        re.compile(
            r"\b(?:do not|never) (?:simply )?(?:relay|repeat|forward)\b",
            re.IGNORECASE,
        ),
    ),
)
SEED_DEPENDENCY_PATTERNS = (
    (
        "OMC/OMX product",
        re.compile(r"\b(?:omc|omx|oh-my-claude(?:code)?|oh-my-codex)\b", re.IGNORECASE),
    ),
    (
        "OMC/OMX command",
        re.compile(
            r"(?:^|\s)/(?:team|autopilot|ultrawork|ralph|best-practice-research)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "OMC/OMX agent name",
        re.compile(
            r"\b(?:oracle|momus|metis|prometheus|hephaestus) (?:agent|subagent)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "OMC/OMX memory file",
        re.compile(
            r"(?:\.omc/|\.omx/|(?:^|[/`\s])(?:AGENTS|CLAUDE|MEMORY)\.md\b|"
            r"\b(?:team|shared) memory file\b)",
            re.IGNORECASE,
        ),
    ),
)
WORKFLOW_PROSE_FIELDS = frozenset({"description", "note", "title", "instruction"})


def generic_guidance_messages(
    *,
    fixture: Mapping[str, object],
    members: Iterable[Mapping[str, object]],
) -> Iterator[str]:
    authored_guidance: list[tuple[str, object]] = [("Workflow note", fixture.get("note"))]
    authored_guidance.extend(
        (f"Member {member.get('id', '<unknown>')!r} instruction", member.get("instruction"))
        for member in members
    )
    for location, prose in authored_guidance:
        if not isinstance(prose, str):
            continue
        for label, pattern in GENERIC_GUIDANCE_PATTERNS:
            if pattern.search(prose):
                yield (
                    f"{location} contains generic {label}; general runtime teaching "
                    "belongs in the system prompt"
                )


def seed_dependency_messages(fixture: Mapping[str, object]) -> Iterator[str]:
    for location, prose in iter_workflow_prose(fixture):
        for label, pattern in SEED_DEPENDENCY_PATTERNS:
            if pattern.search(prose):
                yield f"packaged seed {location} depends on {label}"


def iter_workflow_prose(
    value: object,
    *,
    location: str = "Workflow",
) -> Iterator[tuple[str, str]]:
    if not isinstance(value, Mapping):
        return
    member_id = value.get("id")
    current_location = (
        f"Member {member_id!r}" if isinstance(member_id, str) and "kind" not in value else location
    )
    for key, child in value.items():
        if key in WORKFLOW_PROSE_FIELDS and isinstance(child, str):
            yield f"{current_location} {key}", child
        elif key == "children" and isinstance(child, list):
            for nested_child in child:
                yield from iter_workflow_prose(nested_child, location=current_location)
        elif key == "lead":
            yield from iter_workflow_prose(child, location="Workflow lead")


__all__ = ["generic_guidance_messages", "seed_dependency_messages"]
