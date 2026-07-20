from __future__ import annotations

import json
import re

import pytest
from autoclaw.runtime.contracts.prompt import PROMPT_DYNAMIC_INPUT_KEYS
from autoclaw.runtime.prompt import render_dispatch_request, render_dynamic_input

from .samples import all_trigger_samples, sample_dynamic_input, sample_request


def test_dynamic_render_has_exactly_six_ordered_sections() -> None:
    rendered = render_dynamic_input(sample_dynamic_input())

    headings = tuple(re.findall(r"^# (.+)$", rendered, flags=re.MULTILINE))
    assert headings == tuple(key.title() for key in PROMPT_DYNAMIC_INPUT_KEYS)
    assert "# Plan\n\n```json\nnull\n```" in rendered


def test_dynamic_render_discloses_effective_capability_and_source() -> None:
    rendered = render_dynamic_input(sample_dynamic_input())

    assert '"effective": "full"' in rendered
    assert '"source": "default"' in rendered
    assert '"effective": "allow"' in rendered


def test_dynamic_render_discloses_bounded_readback_refs() -> None:
    rendered = render_dynamic_input(sample_dynamic_input())

    assert '"instructions": "_runtime/dispatch/dispatch-1/instructions.md"' in rendered
    assert '"input": "_runtime/dispatch/dispatch-1/input.md"' in rendered
    assert '"workflow_manifest": "_runtime/workflow-manifest.md"' in rendered


def test_render_is_byte_deterministic() -> None:
    dynamic_input = sample_dynamic_input()

    assert (
        render_dynamic_input(dynamic_input).encode() == render_dynamic_input(dynamic_input).encode()
    )


@pytest.mark.parametrize("trigger", all_trigger_samples(), ids=lambda trigger: trigger.kind)
def test_every_trigger_renders_as_valid_json(trigger: object) -> None:
    rendered = render_dynamic_input(sample_dynamic_input(trigger=trigger))  # type: ignore[arg-type]
    trigger_json = re.search(
        r"# Trigger\n\n```json\n(?P<body>.*?)\n```",
        rendered,
        flags=re.DOTALL,
    )

    assert trigger_json is not None
    assert json.loads(trigger_json.group("body"))["kind"] == trigger.kind  # type: ignore[attr-defined]


def test_child_checkpoint_is_not_duplicated_outside_trigger() -> None:
    child_return = all_trigger_samples()[2]
    rendered = render_dynamic_input(sample_dynamic_input(trigger=child_return))

    assert rendered.count('"checkpoint_id": "checkpoint-1"') == 1


def test_dispatch_request_has_only_instruction_and_input_lanes() -> None:
    rendered = render_dispatch_request(sample_request())

    assert tuple(rendered.model_dump()) == ("instructions_text", "input_text")
    assert "# Controller authority" in rendered.instructions_text
    assert "# Assignment" in rendered.input_text
