from __future__ import annotations

import json

import pytest

from banksia.workflows import (
    AddMemberOperation,
    NormalizedWorkflow,
    RemoveMemberOperation,
    UpdateMemberOperation,
    WorkflowInputError,
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
