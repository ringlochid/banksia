from __future__ import annotations

import json

import pytest

from banksia.workflows import (
    AddMemberOperation,
    NewMember,
    NormalizedWorkflow,
    RemoveMemberOperation,
    UpdateMemberOperation,
    WorkflowInputError,
    build_new_workflow,
    edit_normalized_workflow,
    parse_workflow,
)


def _workflow() -> NormalizedWorkflow:
    return parse_workflow(
        json.dumps(
            {
                "kind": "workflow",
                "id": "draft-test",
                "description": "Draft operation proof.",
                "lead": {
                    "id": "lead",
                    "children": [{"id": "existing", "title": "Existing"}],
                },
            }
        ),
        source_format="json",
    )


def test_add_member_allocates_stable_ids_in_preorder() -> None:
    updated = edit_normalized_workflow(
        _workflow(),
        AddMemberOperation.model_validate(
            {
                "kind": "add_member",
                "parent_member_id": "lead",
                "member": {
                    "title": "Parent",
                    "children": [{"title": "Child"}],
                },
            }
        ),
    )

    assert updated.lead.children is not None
    added = updated.lead.children[-1]
    assert added.id == "member-1"
    assert added.children is not None
    assert added.children[0].id == "member-2"


def test_build_new_workflow_allocates_the_complete_initial_tree_in_preorder() -> None:
    workflow = build_new_workflow(
        workflow_id="new-workflow",
        description="Controller-created Workflow.",
        lead=NewMember.model_validate(
            {
                "title": "Lead",
                "children": [
                    {"title": "First child"},
                    {
                        "title": "Second child",
                        "children": [{"title": "Grandchild"}],
                    },
                ],
            }
        ),
    )

    assert workflow.lead.id == "member-1"
    assert workflow.lead.children is not None
    assert tuple(child.id for child in workflow.lead.children) == ("member-2", "member-3")
    assert workflow.lead.children[1].children is not None
    assert workflow.lead.children[1].children[0].id == "member-4"


def test_update_member_null_clears_optional_fields() -> None:
    updated = edit_normalized_workflow(
        _workflow(),
        UpdateMemberOperation.model_validate(
            {
                "kind": "update_member",
                "member_id": "existing",
                "patch": {"title": None},
            }
        ),
    )

    assert updated.lead.children is not None
    assert updated.lead.children[0].title is None


def test_remove_member_rejects_lead() -> None:
    with pytest.raises(WorkflowInputError) as raised:
        edit_normalized_workflow(
            _workflow(),
            RemoveMemberOperation(kind="remove_member", member_id="lead"),
        )

    assert raised.value.issues[0].source == "operation.remove_member"


def test_legacy_workflow_can_be_repaired_one_member_at_a_time() -> None:
    workflow = NormalizedWorkflow.model_validate(
        {
            "kind": "workflow",
            "id": "legacy-openclaw",
            "description": "Repairable historical Workflow.",
            "lead": {
                "id": "lead",
                "provider": {"kind": "openclaw"},
                "children": [
                    {"id": "child", "provider": {"kind": "openclaw"}},
                ],
            },
        }
    )

    partly_repaired = edit_normalized_workflow(
        workflow,
        UpdateMemberOperation.model_validate(
            {
                "kind": "update_member",
                "member_id": "lead",
                "patch": {"provider": {"kind": "codex"}},
            }
        ),
    )
    repaired = edit_normalized_workflow(
        partly_repaired,
        UpdateMemberOperation.model_validate(
            {
                "kind": "update_member",
                "member_id": "child",
                "patch": {"provider": {"kind": "claude"}},
            }
        ),
    )

    assert partly_repaired.lead.provider is not None
    assert partly_repaired.lead.provider.kind == "codex"
    assert partly_repaired.lead.children is not None
    assert partly_repaired.lead.children[0].provider is not None
    assert partly_repaired.lead.children[0].provider.kind == "openclaw"
    assert repaired.lead.children is not None
    assert repaired.lead.children[0].provider is not None
    assert repaired.lead.children[0].provider.kind == "claude"
