from __future__ import annotations

import json

from autoclaw.runtime.contracts.prompt import (
    PROMPT_DYNAMIC_INPUT_KEYS,
    DispatchRequestRenderInput,
    PromptDynamicInput,
    RenderedDispatchRequest,
)
from autoclaw.runtime.prompt.instructions import render_request_instructions


def render_dispatch_request(request: DispatchRequestRenderInput) -> RenderedDispatchRequest:
    return RenderedDispatchRequest(
        instructions_text=render_request_instructions(
            family=request.family,
            guidance=request.guidance,
        ),
        input_text=render_dynamic_input(request.dynamic_input),
    )


def render_dynamic_input(dynamic_input: PromptDynamicInput) -> str:
    payload = dynamic_input.model_dump(mode="json")
    if tuple(payload) != PROMPT_DYNAMIC_INPUT_KEYS:
        raise ValueError("dynamic prompt input field order does not match the canonical contract")

    sections = []
    for key in PROMPT_DYNAMIC_INPUT_KEYS:
        encoded = json.dumps(payload[key], ensure_ascii=False, indent=2)
        sections.append(f"# {key.title()}\n\n```json\n{encoded}\n```")
    return "\n\n".join(sections) + "\n"


__all__ = ["render_dispatch_request", "render_dynamic_input"]
