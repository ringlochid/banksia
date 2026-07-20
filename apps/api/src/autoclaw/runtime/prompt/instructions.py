from __future__ import annotations

from autoclaw.runtime.contracts.prompt import PromptFamily, PromptInstructionGuidance
from autoclaw.runtime.prompt.asset_catalog import (
    instruction_assets_for_family,
    load_instruction_asset,
)

GUIDANCE_SECTIONS = (
    ("Workflow guidance", "workflow"),
    ("Role guidance", "role"),
    ("Node guidance", "node"),
    ("Policy guidance", "policy"),
)


def render_request_instructions(
    *,
    family: PromptFamily,
    guidance: PromptInstructionGuidance,
) -> str:
    sections = [
        load_instruction_asset(asset).strip() for asset in instruction_assets_for_family(family)
    ]
    sections.extend(render_guidance_sections(guidance))
    return "\n\n".join(sections).rstrip() + "\n"


def render_guidance_sections(guidance: PromptInstructionGuidance) -> tuple[str, ...]:
    rendered: list[str] = []
    for heading, field_name in GUIDANCE_SECTIONS:
        values = getattr(guidance, field_name)
        body = "\n\n".join(values) if values else "None."
        rendered.append(f"# {heading}\n\n{body}")
    return tuple(rendered)


__all__ = ["render_request_instructions"]
