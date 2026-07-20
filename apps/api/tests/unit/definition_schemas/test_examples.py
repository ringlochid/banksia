from __future__ import annotations

from typing import Any

import pytest
from autoclaw.definitions.contracts import (
    PolicyDefinitionFile,
    PolicyDefinitionInput,
    RoleDefinitionFile,
    RoleDefinitionInput,
)

from .support import RoleOrPolicyDefinitionModel, load_role_policy_schema_examples


@pytest.mark.parametrize("payload", load_role_policy_schema_examples())
def test_role_and_policy_definition_schema_worked_yaml_examples_validate(
    payload: dict[str, Any],
) -> None:
    model_type: RoleOrPolicyDefinitionModel
    if "allowed_node_kinds" in payload:
        model_type = RoleDefinitionFile if payload.get("kind") == "role" else RoleDefinitionInput
    else:
        model_type = (
            PolicyDefinitionFile if payload.get("kind") == "policy" else PolicyDefinitionInput
        )

    validated = model_type.model_validate(payload)

    assert validated.id == payload["id"]
