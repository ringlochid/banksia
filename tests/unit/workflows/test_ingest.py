from __future__ import annotations

import json

import pytest

from oh_my_subagents.workflows import WorkflowInputError, canonical_workflow_bytes, parse_workflow
from oh_my_subagents.workflows.contracts import CodexProviderSelection

MINIMAL_WORKFLOW = {
    "kind": "workflow",
    "id": "test-workflow",
    "description": "A useful workflow.",
    "lead": {"id": "lead"},
}


def test_normalization_is_canonical_and_preserves_explicit_empty_children() -> None:
    workflow = parse_workflow(
        json.dumps(
            MINIMAL_WORKFLOW
            | {
                "note": "  \r\n",
                "lead": {
                    "id": "lead",
                    "title": "Lead\r\nowner",
                    "description": None,
                    "children": [],
                },
            }
        ),
        source_format="json",
    )

    assert workflow.note is None
    assert workflow.lead.title == "Lead\nowner"
    assert workflow.lead.children == ()
    assert canonical_workflow_bytes(workflow) == (
        b'{"description":"A useful workflow.","id":"test-workflow",'
        b'"kind":"workflow","lead":{"children":[],"id":"lead",'
        b'"title":"Lead\\nowner"}}'
    )


@pytest.mark.parametrize(
    ("document", "expected_source"),
    [
        (
            "kind: workflow\nid: duplicate\nid: duplicate-again\n"
            "description: test\nlead: {id: lead}\n",
            "parser.duplicate_key",
        ),
        (
            "kind: workflow\nid: anchored\ndescription: test\nlead: &lead {id: lead}\n",
            "parser.yaml_anchor",
        ),
        (
            "kind: workflow\nid: aliased\ndescription: test\nlead: &lead {id: lead}\ncopy: *lead\n",
            "parser.yaml_anchor",
        ),
        (
            "kind: workflow\nid: dated\ndescription: test\nlead: {id: lead, title: 2026-07-23}\n",
            "parser.yaml_scalar",
        ),
        (
            "kind: workflow\nid: first\ndescription: test\nlead: {id: lead}\n"
            "---\nkind: workflow\nid: second\ndescription: test\nlead: {id: lead}\n",
            "parser.document_count",
        ),
    ],
)
def test_yaml_rejects_non_json_authoring_features(
    document: str,
    expected_source: str,
) -> None:
    with pytest.raises(WorkflowInputError) as raised:
        parse_workflow(document, source_format="yaml")

    assert raised.value.issues[0].source == expected_source
    assert raised.value.issues[0].path.startswith("$")


def test_json_rejects_non_finite_values_before_model_validation() -> None:
    document = json.dumps(MINIMAL_WORKFLOW).replace(
        '"A useful workflow."',
        "NaN",
    )

    with pytest.raises(WorkflowInputError) as raised:
        parse_workflow(document, source_format="json")

    assert raised.value.issues[0].source == "parser.non_finite"


def test_semantic_validation_rejects_duplicate_member_ids_with_json_path() -> None:
    document = MINIMAL_WORKFLOW | {
        "lead": {
            "id": "lead",
            "children": [{"id": "duplicate"}, {"id": "duplicate"}],
        }
    }

    with pytest.raises(WorkflowInputError) as raised:
        parse_workflow(json.dumps(document), source_format="json")

    issue = raised.value.issues[0]
    assert issue.source == "semantic.member_id"
    assert issue.path == "$.lead.children[1].id"


def test_raw_size_limit_precedes_parser_work() -> None:
    with pytest.raises(WorkflowInputError) as raised:
        parse_workflow(b"{" + b" " * (1024 * 1024), source_format="json")

    assert raised.value.issues[0].source == "input.size"


def test_excessive_parser_nesting_and_invalid_unicode_have_stable_errors() -> None:
    nested = "[" * 2_000 + "0" + "]" * 2_000
    with pytest.raises(WorkflowInputError) as depth_error:
        parse_workflow(nested, source_format="json")
    assert depth_error.value.issues[0].source == "input.depth"

    with pytest.raises(WorkflowInputError) as encoding_error:
        parse_workflow("\ud800", source_format="json")
    assert encoding_error.value.issues[0].source == "input.encoding"


@pytest.mark.parametrize(
    ("provider", "effort"),
    [("codex", "ultra"), ("claude", "minimal")],
)
def test_provider_effort_rejects_values_outside_its_adapter_descriptor(
    provider: str,
    effort: str,
) -> None:
    document = MINIMAL_WORKFLOW | {
        "lead": {
            "id": "lead",
            "provider": {"kind": provider, "effort": effort},
        }
    }

    with pytest.raises(WorkflowInputError) as raised:
        parse_workflow(json.dumps(document), source_format="json")

    assert raised.value.issues[0].path == "$.lead.provider.effort"


def test_codex_max_effort_is_valid_for_task_members() -> None:
    document = MINIMAL_WORKFLOW | {
        "lead": {
            "id": "lead",
            "provider": {"kind": "codex", "effort": "max"},
        }
    }

    workflow = parse_workflow(json.dumps(document), source_format="json")

    assert isinstance(workflow.lead.provider, CodexProviderSelection)
    assert workflow.lead.provider.effort == "max"


def test_retired_openclaw_provider_is_rejected_at_authored_input() -> None:
    document = MINIMAL_WORKFLOW | {
        "lead": {
            "id": "lead",
            "provider": {"kind": "openclaw"},
        }
    }

    with pytest.raises(WorkflowInputError) as raised:
        parse_workflow(json.dumps(document), source_format="json")

    assert raised.value.issues[0].source == "provider.retired"
    assert raised.value.issues[0].path == "$.lead.provider.kind"


def test_hidden_direct_child_guard_rejects_without_becoming_authored_schema() -> None:
    document = MINIMAL_WORKFLOW | {
        "lead": {
            "id": "lead",
            "children": [{"id": f"child-{index}"} for index in range(33)],
        }
    }

    with pytest.raises(WorkflowInputError) as raised:
        parse_workflow(json.dumps(document), source_format="json")

    assert raised.value.issues[0].path == "$.lead.children"
    assert "controller direct-child limit" in raised.value.issues[0].message


def test_hidden_managed_provider_text_guard_rejects_without_becoming_authored_schema() -> None:
    document = MINIMAL_WORKFLOW | {
        "lead": {
            "id": "lead",
            "provider": {"kind": "codex", "model": "m" * 256},
        }
    }

    with pytest.raises(WorkflowInputError) as raised:
        parse_workflow(json.dumps(document), source_format="json")

    assert raised.value.issues[0].path == "$.lead.provider.model"
    assert "controller text limit" in raised.value.issues[0].message
