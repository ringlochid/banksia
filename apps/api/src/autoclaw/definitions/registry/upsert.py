from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.compiler import (
    PolicyRevisionDefinition,
    RoleRevisionDefinition,
    WorkflowRevisionMetadata,
    compile_workflow,
)
from autoclaw.definitions.contracts.registry import PolicyDefinitionInput, RoleDefinitionInput
from autoclaw.definitions.contracts.workflow import WorkflowDefinitionInput
from autoclaw.definitions.registry.current import (
    build_workflow_role_policy_lookup,
    load_current_policy,
    load_current_role,
    load_current_workflow,
)
from autoclaw.definitions.registry.revisions.ids import policy_revision_id, role_revision_id
from autoclaw.definitions.registry.revisions.types import (
    RegistryWorkflowDefinition,
    model_from_attrs,
)
from autoclaw.definitions.registry.revisions.writes import (
    insert_definition_revision,
    insert_workflow_revision,
    prepare_definition_revision_upsert,
)
from autoclaw.persistence.models import (
    PolicyDefinitionModel,
    PolicyRevisionModel,
    RoleDefinitionModel,
    RoleRevisionModel,
    WorkflowDefinitionModel,
    WorkflowRevisionModel,
)


async def upsert_workflow_definition(
    session: AsyncSession,
    definition: WorkflowDefinitionInput,
    *,
    source_path: str | None = None,
    should_allow_existing_update: bool = True,
) -> RegistryWorkflowDefinition:
    prepared, existing_result = await prepare_definition_revision_upsert(
        session,
        definition=definition,
        source_path=source_path,
        should_allow_existing_update=should_allow_existing_update,
        definition_model=WorkflowDefinitionModel,
        revision_model=WorkflowRevisionModel,
        definition_key_column=WorkflowDefinitionModel.workflow_key,
        revision_key_column=WorkflowRevisionModel.workflow_key,
        key_field="workflow",
        build_row=lambda: WorkflowDefinitionModel(
            workflow_key=definition.id,
            current_revision_no=None,
        ),
        build_result=lambda revision_no: _build_workflow_result(definition, revision_no),
        load_current=lambda: load_current_workflow(session, definition.id),
    )
    if existing_result is not None:
        return existing_result
    assert prepared is not None
    await _validate_candidate_workflow(
        session,
        definition=definition,
        revision_no=prepared.revision_no,
    )
    fallback_result = await insert_workflow_revision(
        session,
        definition_id=definition.id,
        source_path=source_path,
        prepared=prepared,
        build_result=lambda revision_no: _build_workflow_result(definition, revision_no),
    )
    return fallback_result or _build_workflow_result(definition, prepared.revision_no)


async def upsert_role_definition(
    session: AsyncSession,
    definition: RoleDefinitionInput,
    *,
    source_path: str | None = None,
    should_allow_existing_update: bool = True,
) -> RoleRevisionDefinition:
    prepared, existing_result = await prepare_definition_revision_upsert(
        session,
        definition=definition,
        source_path=source_path,
        should_allow_existing_update=should_allow_existing_update,
        definition_model=RoleDefinitionModel,
        revision_model=RoleRevisionModel,
        definition_key_column=RoleDefinitionModel.role_key,
        revision_key_column=RoleRevisionModel.role_key,
        key_field="role",
        build_row=lambda: RoleDefinitionModel(
            role_key=definition.id,
            current_revision_no=None,
        ),
        build_result=lambda revision_no: _build_role_result(definition, revision_no),
        load_current=lambda: load_current_role(session, definition.id),
    )
    if existing_result is not None:
        return existing_result
    assert prepared is not None
    fallback_result = await insert_definition_revision(
        session,
        definition_id=definition.id,
        prepared=prepared,
        revision_model=RoleRevisionModel,
        revision_key_column=RoleRevisionModel.role_key,
        build_revision=lambda: RoleRevisionModel(
            role_revision_id=role_revision_id(definition.id, prepared.revision_no),
            role_key=definition.id,
            revision_no=prepared.revision_no,
            content_hash=prepared.content_hash,
            content_json=prepared.content_json,
            source_path=source_path,
        ),
        build_result=lambda revision_no: _build_role_result(definition, revision_no),
    )
    return fallback_result or _build_role_result(definition, prepared.revision_no)


async def upsert_policy_definition(
    session: AsyncSession,
    definition: PolicyDefinitionInput,
    *,
    source_path: str | None = None,
    should_allow_existing_update: bool = True,
) -> PolicyRevisionDefinition:
    prepared, existing_result = await prepare_definition_revision_upsert(
        session,
        definition=definition,
        source_path=source_path,
        should_allow_existing_update=should_allow_existing_update,
        definition_model=PolicyDefinitionModel,
        revision_model=PolicyRevisionModel,
        definition_key_column=PolicyDefinitionModel.policy_key,
        revision_key_column=PolicyRevisionModel.policy_key,
        key_field="policy",
        build_row=lambda: PolicyDefinitionModel(
            policy_key=definition.id,
            current_revision_no=None,
        ),
        build_result=lambda revision_no: _build_policy_result(definition, revision_no),
        load_current=lambda: load_current_policy(session, definition.id),
    )
    if existing_result is not None:
        return existing_result
    assert prepared is not None
    fallback_result = await insert_definition_revision(
        session,
        definition_id=definition.id,
        prepared=prepared,
        revision_model=PolicyRevisionModel,
        revision_key_column=PolicyRevisionModel.policy_key,
        build_revision=lambda: PolicyRevisionModel(
            policy_revision_id=policy_revision_id(definition.id, prepared.revision_no),
            policy_key=definition.id,
            revision_no=prepared.revision_no,
            content_hash=prepared.content_hash,
            content_json=prepared.content_json,
            source_path=source_path,
        ),
        build_result=lambda revision_no: _build_policy_result(definition, revision_no),
    )
    return fallback_result or _build_policy_result(definition, prepared.revision_no)


async def _validate_candidate_workflow(
    session: AsyncSession,
    *,
    definition: WorkflowDefinitionInput,
    revision_no: int,
) -> None:
    lookup = await build_workflow_role_policy_lookup(session, definition)
    compile_workflow(
        workflow=definition,
        workflow_revision=model_from_attrs(
            WorkflowRevisionMetadata,
            workflow_key=definition.id,
            definition_revision_no=revision_no,
        ),
        compiler_version="registry-guard",
        lookup=lookup,
    )


def _build_workflow_result(
    definition: WorkflowDefinitionInput,
    revision_no: int,
) -> RegistryWorkflowDefinition:
    return model_from_attrs(
        RegistryWorkflowDefinition,
        definition=definition,
        revision_no=revision_no,
    )


def _build_role_result(
    definition: RoleDefinitionInput,
    revision_no: int,
) -> RoleRevisionDefinition:
    return model_from_attrs(
        RoleRevisionDefinition,
        definition=definition,
        revision_no=revision_no,
    )


def _build_policy_result(
    definition: PolicyDefinitionInput,
    revision_no: int,
) -> PolicyRevisionDefinition:
    return model_from_attrs(
        PolicyRevisionDefinition,
        definition=definition,
        revision_no=revision_no,
    )
