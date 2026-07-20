from __future__ import annotations

import pytest
from autoclaw.definitions.contracts.workflow import NodeKind
from autoclaw.runtime.contracts.prompt import (
    PROMPT_DYNAMIC_INPUT_KEYS,
    DispatchRequestRenderInput,
    OperatorContinueTrigger,
    PromptDynamicInput,
    PromptFamily,
    PromptLogicalRef,
    PromptRefKind,
    PromptTrigger,
)
from pydantic import TypeAdapter, ValidationError

from .samples import all_trigger_samples, sample_dynamic_input, sample_request


def test_dynamic_input_has_exact_six_section_contract() -> None:
    assert tuple(PromptDynamicInput.model_fields) == PROMPT_DYNAMIC_INPUT_KEYS


def test_contracts_forbid_unknown_fields() -> None:
    payload = sample_dynamic_input().model_dump(mode="json")
    payload["legacy_envelope"] = {}

    with pytest.raises(ValidationError):
        PromptDynamicInput.model_validate(payload)


def test_trigger_union_accepts_every_canonical_kind() -> None:
    adapter: TypeAdapter[PromptTrigger] = TypeAdapter(PromptTrigger)

    parsed = tuple(
        adapter.validate_python(trigger.model_dump(mode="json"))
        for trigger in all_trigger_samples()
    )

    assert tuple(trigger.kind for trigger in parsed) == (
        "root_start",
        "accepted_boundary",
        "child_return",
        "human_result",
        "command_result",
        "watchdog_recovery",
        "semantic_retry",
        "operator_continue",
    )


def test_trigger_union_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(PromptTrigger).validate_python({"kind": "provider_complete"})


@pytest.mark.parametrize(
    ("source_dispatch_id", "source_flow_id"),
    ((None, None), ("dispatch-1", "flow-1")),
)
def test_operator_continue_requires_one_exact_source(
    source_dispatch_id: str | None,
    source_flow_id: str | None,
) -> None:
    with pytest.raises(ValidationError, match="exactly one dispatch or flow-start source"):
        OperatorContinueTrigger(
            source_dispatch_id=source_dispatch_id,
            source_flow_id=source_flow_id,
            control_revision=2,
            pause_reason="Operator paused the flow.",
        )


def test_worker_rejects_parent_root_action_names() -> None:
    payload = sample_dynamic_input().model_dump(mode="json")
    payload["context"]["allowed_actions"].append("assign_child")

    with pytest.raises(ValidationError, match="worker prompt exposes parent/root actions"):
        PromptDynamicInput.model_validate(payload)


def test_request_rejects_family_node_mismatch() -> None:
    payload = sample_request().model_dump(mode="json")
    payload["family"] = PromptFamily.PARENT_ROOT

    with pytest.raises(ValidationError, match="invalid for node kind"):
        DispatchRequestRenderInput.model_validate(payload)


@pytest.mark.parametrize(
    "logical_path",
    ("/etc/passwd", "../outside", "workspace/../outside", r"workspace\\outside"),
)
def test_logical_ref_rejects_paths_outside_the_task_root(logical_path: str) -> None:
    with pytest.raises(ValidationError):
        PromptLogicalRef(
            kind=PromptRefKind.WORKSPACE,
            logical_path=logical_path,
            purpose="Inspect the file.",
            description="A task-root file.",
        )


def test_root_request_selects_parent_root_family() -> None:
    assert sample_request(node_kind=NodeKind.ROOT).family == PromptFamily.PARENT_ROOT
