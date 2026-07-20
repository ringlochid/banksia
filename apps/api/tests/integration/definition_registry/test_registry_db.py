from __future__ import annotations

import shutil
from contextlib import nullcontext
from pathlib import Path

import autoclaw.definitions.registry.seeds as registry_seeds
import pytest
import yaml
from autoclaw.definitions.contracts.workflow import WorkflowDefinitionInput
from autoclaw.definitions.registry import (
    compile_current_workflow,
    load_current_policy,
    load_current_role,
    load_current_workflow,
    seed_definition_registry,
    upsert_workflow_definition,
)
from autoclaw.definitions.seeds import resolve_packaged_seed_definitions_root
from autoclaw.persistence import WorkflowRevisionModel
from sqlalchemy import func, select
from tests.helpers.definition_registry_runtime import initialized_registry


def _copy_seed_tree(target_root: Path) -> Path:
    seed_root = target_root / "seed-root"
    with resolve_packaged_seed_definitions_root() as resolved_packaged_root:
        shutil.copytree(Path(resolved_packaged_root), seed_root)
    return seed_root


def _rewrite_workflow_seed_description(
    seed_root: Path,
    *,
    workflow_key: str,
    description: str,
) -> None:
    for workflow_path in sorted((seed_root / "workflows").glob("*.yaml")):
        payload = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"expected mapping content in {workflow_path}")
        if payload.get("id") != workflow_key:
            continue
        payload["description"] = description
        workflow_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return
    raise FileNotFoundError(f"missing workflow seed for {workflow_key}")


async def test_init_seeds_definition_registry_and_compiles_current_workflow(
    tmp_path: Path,
) -> None:
    async with initialized_registry(tmp_path) as session_factory:
        async with session_factory() as session:
            role = await load_current_role(session, "planning_lead")
            policy = await load_current_policy(session, "standard-worker")
            workflow, compiled_plan = await compile_current_workflow(
                session,
                workflow_key="reviewed-change-release",
                compiler_version="registry-seeded-test",
            )

            assert role.revision_no == 1
            assert policy.revision_no == 1
            assert workflow.revision_no == 1
            assert compiled_plan.workflow_key == "reviewed-change-release"
            assert compiled_plan.definition_revision_no == workflow.revision_no
            assert compiled_plan.nodes[1].node_key == "change_subtree"


async def test_seed_registry_appends_seed_revision_without_clobbering_controller_current(
    tmp_path: Path,
) -> None:
    seed_root = _copy_seed_tree(tmp_path / "packaged-seed-refresh")
    updated_seed_description = (
        "Bounded workflow that creates one implementation change artifact. packaged refresh"
    )
    _rewrite_workflow_seed_description(
        seed_root,
        workflow_key="bounded-change",
        description=updated_seed_description,
    )

    async with initialized_registry(tmp_path) as session_factory:
        async with session_factory() as session:
            current = await load_current_workflow(session, "bounded-change")
            updated_definition = current.definition.model_copy(
                update={"description": f"{current.definition.description} updated"}
            )
            updated = await upsert_workflow_definition(
                session,
                updated_definition,
                source_path="test://updated-workflow",
            )
            await session.commit()
            assert updated.revision_no == 2

        with pytest.MonkeyPatch.context() as patched:
            patched.setattr(
                registry_seeds,
                "resolve_packaged_seed_definitions_root",
                lambda: nullcontext(seed_root),
            )
            async with session_factory() as session:
                await seed_definition_registry(session)
                await session.commit()

            async with session_factory() as session:
                await seed_definition_registry(session)
                await session.commit()

        async with session_factory() as session:
            current = await load_current_workflow(session, "bounded-change")
            revision_count = await session.scalar(
                select(func.count()).where(WorkflowRevisionModel.workflow_key == "bounded-change")
            )
            appended_seed_revision = await session.scalar(
                select(WorkflowRevisionModel).where(
                    WorkflowRevisionModel.workflow_key == "bounded-change",
                    WorkflowRevisionModel.revision_no == 3,
                )
            )

            assert appended_seed_revision is not None
            assert current.revision_no == 2
            assert current.definition.description.endswith("updated")
            assert revision_count == 3
            assert appended_seed_revision.content_json["description"] == updated_seed_description
            assert appended_seed_revision.source_path == (
                "seed://packaged/workflows/bounded_change.yaml"
            )


async def test_seed_registry_promotes_changed_packaged_workflow_revision_when_seed_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_root = _copy_seed_tree(tmp_path / "packaged-seed")
    updated_description = "Bounded workflow that creates one implementation change artifact. v2"
    _rewrite_workflow_seed_description(
        seed_root,
        workflow_key="bounded-change",
        description=updated_description,
    )

    async with initialized_registry(tmp_path) as session_factory:
        async with session_factory() as session:
            baseline_workflow = await load_current_workflow(
                session,
                "bounded-change",
            )
            baseline_description = baseline_workflow.definition.description

        monkeypatch.setattr(
            registry_seeds,
            "resolve_packaged_seed_definitions_root",
            lambda: nullcontext(seed_root),
        )
        async with session_factory() as session:
            await seed_definition_registry(session)
            await session.commit()

        async with session_factory() as session:
            current = await load_current_workflow(session, "bounded-change")
            revision_history_rows = await session.execute(
                select(
                    WorkflowRevisionModel.revision_no,
                    WorkflowRevisionModel.content_json,
                )
                .where(WorkflowRevisionModel.workflow_key == "bounded-change")
                .order_by(WorkflowRevisionModel.revision_no.asc())
            )
            revision_history = [
                (revision_no, str(content_json["description"]))
                for revision_no, content_json in revision_history_rows.all()
            ]
            current_revision = await session.scalar(
                select(WorkflowRevisionModel).where(
                    WorkflowRevisionModel.workflow_key == "bounded-change",
                    WorkflowRevisionModel.revision_no == current.revision_no,
                )
            )

            assert current_revision is not None
            assert current.revision_no == 2
            assert current.definition.description == updated_description
            assert current_revision.source_path == ("seed://packaged/workflows/bounded_change.yaml")
            assert revision_history == [
                (1, baseline_description),
                (2, updated_description),
            ]


async def test_invalid_workflow_does_not_advance_registry_currentness(
    tmp_path: Path,
) -> None:
    async with initialized_registry(tmp_path) as session_factory:
        async with session_factory() as session:
            current = await load_current_workflow(session, "bounded-change")
            invalid_definition = WorkflowDefinitionInput.model_validate(
                current.definition.model_dump()
                | {"root": current.definition.root.model_dump() | {"role_id": "missing-role"}}
            )

            with pytest.raises(ValueError, match="role 'missing-role'"):
                await upsert_workflow_definition(
                    session,
                    invalid_definition,
                    source_path="test://invalid-workflow",
                )
            await session.rollback()

        async with session_factory() as session:
            current = await load_current_workflow(session, "bounded-change")
            revision_count = await session.scalar(
                select(func.count()).where(WorkflowRevisionModel.workflow_key == "bounded-change")
            )

            assert current.revision_no == 1
            assert revision_count == 1
