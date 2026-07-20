from __future__ import annotations

from typing import Any

import pytest
from autoclaw.definitions.compiler import (
    MappingRolePolicyLookup,
    WorkflowRevisionMetadata,
    compile_workflow,
)
from autoclaw.definitions.contracts import WorkflowDefinitionFile

from .support import (
    WORKFLOW_COMPILER_TEST_VERSION,
    load_packaged_seed_lookup,
    load_packaged_workflow_payload,
)


@pytest.mark.parametrize(
    ("node_role", "lookup_builder", "error_pattern"),
    [
        (
            "missing_role",
            lambda lookup: MappingRolePolicyLookup(
                roles={key: value for key, value in lookup.roles.items() if key != "missing_role"},
                policies=lookup.policies,
            ),
            "role 'missing_role' does not resolve for node 'implement_change'",
        ),
        (
            "root_planning_lead",
            lambda lookup: lookup,
            (
                "role 'root_planning_lead' is incompatible with node kind "
                "'worker' for node 'implement_change'"
            ),
        ),
    ],
)
def test_compile_workflow_fails_for_missing_or_incompatible_roles(
    node_role: str,
    lookup_builder: Any,
    error_pattern: str,
) -> None:
    payload = load_packaged_workflow_payload("bounded_change")
    payload["root"]["children"][0]["role_id"] = node_role
    workflow = WorkflowDefinitionFile.model_validate(payload)

    base_lookup = load_packaged_seed_lookup()
    lookup = lookup_builder(base_lookup)

    with pytest.raises(ValueError, match=error_pattern):
        compile_workflow(
            workflow=workflow,
            workflow_revision=WorkflowRevisionMetadata(
                workflow_key=workflow.id,
                definition_revision_no=5,
            ),
            compiler_version=WORKFLOW_COMPILER_TEST_VERSION,
            lookup=lookup,
        )


@pytest.mark.parametrize(
    ("node_policy", "error_pattern"),
    [
        (
            "missing-policy",
            "policy 'missing-policy' does not resolve for node 'implement_change'",
        ),
        (
            "standard-parent",
            (
                "policy 'standard-parent' is incompatible with node kind "
                "'worker' for node 'implement_change'"
            ),
        ),
    ],
)
def test_compile_workflow_fails_for_missing_or_incompatible_policies(
    node_policy: str,
    error_pattern: str,
) -> None:
    payload = load_packaged_workflow_payload("bounded_change")
    payload["root"]["children"][0]["policy_id"] = node_policy
    workflow = WorkflowDefinitionFile.model_validate(payload)

    with pytest.raises(ValueError, match=error_pattern):
        compile_workflow(
            workflow=workflow,
            workflow_revision=WorkflowRevisionMetadata(
                workflow_key=workflow.id,
                definition_revision_no=5,
            ),
            compiler_version=WORKFLOW_COMPILER_TEST_VERSION,
            lookup=load_packaged_seed_lookup(),
        )
