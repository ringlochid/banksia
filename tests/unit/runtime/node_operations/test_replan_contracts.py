from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from oh_my_subagents.runtime.contracts import AddChildRequest, UpdateChildRequest


def test_recursive_replan_contract_distinguishes_omission_and_rejects_ambiguity() -> None:
    omitted = UpdateChildRequest.model_validate(
        {"id": "child", "patch": {"instruction": "Keep the existing title."}}
    )
    cleared = UpdateChildRequest.model_validate({"id": "child", "patch": {"title": None}})

    assert "title" not in omitted.patch.model_fields_set
    assert "title" in cleared.patch.model_fields_set
    assert cleared.model_dump(mode="json", exclude_unset=True)["patch"] == {"title": None}

    invalid_requests: tuple[tuple[type[BaseModel], dict[str, object]], ...] = (
        (AddChildRequest, {"parent_id": "root", "child": {"title": "Reviewer"}}),
        (AddChildRequest, {"child": {"title": "Reviewer", "children": []}}),
        (
            UpdateChildRequest,
            {
                "id": "child",
                "patch": {
                    "children": [
                        {"id": "nested", "title": "First"},
                        {"id": "nested", "title": "Second"},
                    ]
                },
            },
        ),
        (
            AddChildRequest,
            {
                "child": {
                    "title": "Reviewer",
                    "children": [{"title": f"Leaf {index}"} for index in range(33)],
                }
            },
        ),
    )
    for model, payload in invalid_requests:
        with pytest.raises(ValidationError):
            model.model_validate(payload)
