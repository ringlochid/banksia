from __future__ import annotations

from collections.abc import Iterator

from .support import (
    EXPECTED_WORKFLOW_IDS,
    REFERENCE_DEFINITIONS_ROOT,
    assert_expected_role_and_policy_ids,
    load_definition_tree,
    load_first_yaml_fence,
    load_registry_catalog,
    load_workflow_ids,
    resolve_committed_seed_definitions_root,
)


def _normalize_definition_payload(payload: object) -> object:
    if isinstance(payload, dict):
        return {key: _normalize_definition_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_normalize_definition_payload(value) for value in payload]
    if isinstance(payload, str):
        return payload.rstrip("\n")
    return payload


def _iter_workflow_nodes(node: dict[str, object]) -> Iterator[dict[str, object]]:
    yield node
    children = node.get("children")
    if not isinstance(children, list):
        return
    for child in children:
        if isinstance(child, dict):
            yield from _iter_workflow_nodes(child)


def test_packaged_role_and_policy_seed_definitions_validate() -> None:
    with resolve_committed_seed_definitions_root() as definitions_root:
        roles, policies = load_registry_catalog(definitions_root)

    assert_expected_role_and_policy_ids(roles, policies)


def test_standard_root_seed_policies_are_unbounded_by_default() -> None:
    with resolve_committed_seed_definitions_root() as definitions_root:
        _, policies = load_registry_catalog(definitions_root)

    assert policies["standard-root"].budget_spec is None
    assert policies["standard-root-human-request"].budget_spec is None
    assert policies["standard-parent"].budget_spec is not None
    assert policies["standard-parent"].budget_spec.child_assignment_limit == 20
    assert policies["standard-worker"].budget_spec is not None
    assert policies["standard-worker"].budget_spec.retry_limit == 1


def test_packaged_workflow_seed_definitions_validate_against_packaged_catalog() -> None:
    with resolve_committed_seed_definitions_root() as definitions_root:
        roles, policies = load_registry_catalog(definitions_root)
        workflow_ids = load_workflow_ids(
            definitions_root,
            roles=roles,
            policies=policies,
        )

    assert workflow_ids == EXPECTED_WORKFLOW_IDS


def test_packaged_workflow_seed_nodes_use_target_portable_contract() -> None:
    with resolve_committed_seed_definitions_root() as definitions_root:
        roles, policies = load_registry_catalog(definitions_root)
        packaged_tree = load_definition_tree(definitions_root)

        for relative_path, workflow in packaged_tree.items():
            if not relative_path.startswith("workflows/"):
                continue
            root = workflow["root"]
            assert isinstance(root, dict)
            for node in _iter_workflow_nodes(root):
                node_key = node.get("node_key")
                assert isinstance(node_key, str)
                assert {"id", "role", "policy", "provider_preference"}.isdisjoint(node)

                expected_kind = (
                    "root" if node is root else "parent" if node.get("children") else "worker"
                )
                assert node.get("kind") == expected_kind, (
                    f"{relative_path}:{node_key} must declare kind {expected_kind}"
                )

                role_id = node.get("role_id")
                assert isinstance(role_id, str) and role_id in roles, (
                    f"{relative_path}:{node_key} must attach a packaged seed role"
                )
                policy_id = node.get("policy_id")
                assert isinstance(policy_id, str) and policy_id in policies, (
                    f"{relative_path}:{node_key} must attach a packaged seed policy"
                )


def test_packaged_seed_tree_contains_expected_definition_files() -> None:
    with resolve_committed_seed_definitions_root() as definitions_root:
        packaged_tree = load_definition_tree(definitions_root)

    assert set(packaged_tree) == {
        "policies/standard_parent.yaml",
        "policies/standard_parent_human_request.yaml",
        "policies/standard_root.yaml",
        "policies/standard_root_human_request.yaml",
        "policies/standard_worker.yaml",
        "policies/standard_worker_command_run.yaml",
        "policies/standard_worker_human_request.yaml",
        "roles/architect.yaml",
        "roles/bug_fix_engineer.yaml",
        "roles/bug_triage.yaml",
        "roles/code_reviewer.yaml",
        "roles/core_architect.yaml",
        "roles/engineer.yaml",
        "roles/failure_analyst.yaml",
        "roles/frontend_code_reviewer.yaml",
        "roles/frontend_contract_integrator.yaml",
        "roles/frontend_engineer.yaml",
        "roles/frontend_visual_verifier.yaml",
        "roles/market_researcher.yaml",
        "roles/marketing_strategist.yaml",
        "roles/planner.yaml",
        "roles/planning_lead.yaml",
        "roles/product_discovery_researcher.yaml",
        "roles/product_planner.yaml",
        "roles/product_reviewer.yaml",
        "roles/product_story_strategist.yaml",
        "roles/project_manager.yaml",
        "roles/release_operator.yaml",
        "roles/replan_planner.yaml",
        "roles/researcher.yaml",
        "roles/reviewer.yaml",
        "roles/root_planning_lead.yaml",
        "roles/scope_reviewer.yaml",
        "roles/test_verifier.yaml",
        "roles/delivery_planner.yaml",
        "workflows/bugfix_review_release.yaml",
        "workflows/core_only_build.yaml",
        "workflows/feature_implementation.yaml",
        "workflows/frontend_feature_slice.yaml",
        "workflows/idea_discovery.yaml",
        "workflows/bounded_change.yaml",
        "workflows/marketing_campaign.yaml",
        "workflows/mvp_build.yaml",
        "workflows/reviewed_change_release.yaml",
        "workflows/staged_delivery_release.yaml",
        "workflows/delivery_batch.yaml",
        "workflows/planning_only.yaml",
        "workflows/project_management_delivery.yaml",
        "workflows/topic_research_brief.yaml",
    }


def test_reference_role_and_policy_pages_mirror_packaged_seed_definitions() -> None:
    with resolve_committed_seed_definitions_root() as definitions_root:
        packaged_tree = load_definition_tree(definitions_root)

    for relative_path, seed_payload in packaged_tree.items():
        category, _ = relative_path.split("/")
        if category == "workflows":
            continue
        page_stem = seed_payload["id"].replace("_", "-")

        reference_payload = load_first_yaml_fence(
            REFERENCE_DEFINITIONS_ROOT / category / f"{page_stem}.md"
        )

        assert _normalize_definition_payload(reference_payload) == _normalize_definition_payload(
            seed_payload
        )
