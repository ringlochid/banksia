import pytest
from autoclaw.definitions.contracts.workflow import NodeKind, ProviderKind
from autoclaw.runtime.contracts import ChildNodeDraft, ChildNodePatch
from autoclaw.runtime.node_operations.structural_candidate.models import (
    StructuralNodeCandidate,
)
from autoclaw.runtime.node_operations.structural_candidate.validation import (
    build_structural_revision_candidate,
)
from pydantic import ValidationError


def test_structural_candidate_accepts_a_nonliteral_root_node_key() -> None:
    root = StructuralNodeCandidate(
        node_key="primary",
        parent_node_key=None,
        structural_kind=NodeKind.ROOT,
        role_key="role.root",
        role_revision_no=1,
        role_description="Root role.",
        role_instruction=None,
        policy_key="policy.root",
        policy_revision_no=1,
        policy_description="Root policy.",
        policy_instruction=None,
        provider=None,
        description="Coordinate the task.",
        node_instruction=None,
        local_consumes=None,
        consumes=None,
        produces=None,
        own_criteria=(),
        criteria=(),
        child_defaults=None,
        child_node_keys=(),
        state="ready",
        current_assignment_id=None,
        order_index=0,
    )

    candidate = build_structural_revision_candidate(
        {root.node_key: root},
        previous_criteria={},
    )

    assert [node.node_key for node in candidate.nodes] == ["primary"]


def test_structural_draft_uses_the_strict_workflow_provider_shape() -> None:
    draft = ChildNodeDraft.model_validate(
        {
            "node_key": "implementation",
            "role": "engineer",
            "policy": "standard-worker",
            "provider": {"kind": "codex"},
            "description": "Implement the bounded change.",
        }
    )

    assert draft.provider is not None
    assert draft.provider.kind == ProviderKind.CODEX
    with pytest.raises(ValidationError, match="provider"):
        ChildNodeDraft.model_validate(
            {
                "node_key": "implementation",
                "role": "engineer",
                "policy": "standard-worker",
                "provider": "codex",
                "description": "Implement the bounded change.",
            }
        )
    with pytest.raises(ValidationError, match="provider"):
        ChildNodeDraft.model_validate(
            {
                "node_key": "implementation",
                "role": "engineer",
                "policy": "standard-worker",
                "provider": {"kind": "codex", "model": "gpt-future"},
                "description": "Implement the bounded change.",
            }
        )


def test_structural_provider_patch_distinguishes_omission_replace_and_clear() -> None:
    omitted = ChildNodePatch.model_validate({"description": "Keep the current provider."})
    replacement = ChildNodePatch.model_validate({"provider": {"kind": "claude"}})
    cleared = ChildNodePatch.model_validate({"provider": None})

    assert "provider" not in omitted.model_fields_set
    assert replacement.provider is not None
    assert replacement.provider.kind == ProviderKind.CLAUDE
    assert "provider" in replacement.model_fields_set
    assert cleared.provider is None
    assert "provider" in cleared.model_fields_set
