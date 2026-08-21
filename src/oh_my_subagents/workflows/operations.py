from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from oh_my_subagents.workflows.contracts import (
    Identifier,
    MemberCapabilities,
    NormalizedWorkflow,
    ProviderSelection,
)
from oh_my_subagents.workflows.errors import WorkflowInputError, workflow_input_error
from oh_my_subagents.workflows.ingest import normalize_workflow_object


class _OperationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkflowPatch(_OperationModel):
    description: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def require_change(self) -> WorkflowPatch:
        if not self.model_fields_set:
            raise ValueError("Workflow patch must contain at least one field")
        return self


class MemberPatch(_OperationModel):
    title: str | None = None
    description: str | None = None
    instruction: str | None = None
    provider: ProviderSelection | None = None
    capabilities: MemberCapabilities | None = None

    @model_validator(mode="after")
    def require_change(self) -> MemberPatch:
        if not self.model_fields_set:
            raise ValueError("Member patch must contain at least one field")
        return self


class NewMember(_OperationModel):
    title: str | None = None
    description: str | None = None
    instruction: str | None = None
    provider: ProviderSelection | None = None
    capabilities: MemberCapabilities | None = None
    children: tuple[NewMember, ...] | None = None


class UpdateWorkflowOperation(_OperationModel):
    kind: Literal["update_workflow"]
    patch: WorkflowPatch


class AddMemberOperation(_OperationModel):
    kind: Literal["add_member"]
    parent_member_id: Identifier
    member: NewMember


class UpdateMemberOperation(_OperationModel):
    kind: Literal["update_member"]
    member_id: Identifier
    patch: MemberPatch


class RemoveMemberOperation(_OperationModel):
    kind: Literal["remove_member"]
    member_id: Identifier


DraftOperation = Annotated[
    UpdateWorkflowOperation | AddMemberOperation | UpdateMemberOperation | RemoveMemberOperation,
    Field(discriminator="kind"),
]
DRAFT_OPERATION_ADAPTER: TypeAdapter[DraftOperation] = TypeAdapter(DraftOperation)


def build_new_workflow(
    *,
    workflow_id: str,
    description: str,
    note: str | None = None,
    lead: NewMember | None = None,
    member_id_allocator: Callable[[], str] | None = None,
) -> NormalizedWorkflow:
    allocate_id = member_id_allocator or _new_workflow_member_id_allocator()
    payload: dict[str, object] = {
        "kind": "workflow",
        "id": workflow_id,
        "description": description,
        "lead": _new_member_payload(lead or NewMember(), allocate_id=allocate_id),
    }
    if note is not None:
        payload["note"] = note
    return _normalize_edited_workflow(payload)


def edit_normalized_workflow(
    workflow: NormalizedWorkflow,
    operation: DraftOperation,
    *,
    member_id_allocator: Callable[[], str] | None = None,
) -> NormalizedWorkflow:
    payload = workflow.model_dump(mode="json", exclude_none=True)
    if isinstance(operation, UpdateWorkflowOperation):
        _apply_patch(payload, operation.patch)
    elif isinstance(operation, AddMemberOperation):
        parent = _find_member(payload["lead"], operation.parent_member_id)
        if parent is None:
            raise _missing_member(operation.parent_member_id)
        allocate_id = member_id_allocator or _default_member_id_allocator(payload["lead"])
        new_member = _new_member_payload(operation.member, allocate_id=allocate_id)
        children = parent.setdefault("children", [])
        if not isinstance(children, list):  # pragma: no cover - normalized invariant
            raise TypeError("normalized member children must be a list")
        children.append(new_member)
    elif isinstance(operation, UpdateMemberOperation):
        member = _find_member(payload["lead"], operation.member_id)
        if member is None:
            raise _missing_member(operation.member_id)
        _apply_patch(member, operation.patch)
    else:
        if operation.member_id == workflow.lead.id:
            raise workflow_input_error(
                source="operation.remove_member",
                path="$.member_id",
                message="the lead Member cannot be removed",
            )
        if not _remove_member(payload["lead"], operation.member_id):
            raise _missing_member(operation.member_id)
    return _normalize_edited_workflow(payload)


def _normalize_edited_workflow(payload: object) -> NormalizedWorkflow:
    """Validate an edited draft while allowing other retired Members to remain repairable."""

    try:
        return normalize_workflow_object(payload)
    except WorkflowInputError as exc:
        if not exc.issues or any(issue.source != "provider.retired" for issue in exc.issues):
            raise
        return NormalizedWorkflow.model_validate(payload)


def _apply_patch(payload: dict[str, object], patch: BaseModel) -> None:
    for key, value in patch.model_dump(mode="json", exclude_unset=True).items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value


def _new_member_payload(
    member: NewMember,
    *,
    allocate_id: Callable[[], str],
) -> dict[str, object]:
    payload = member.model_dump(mode="json", exclude_none=True, exclude={"children"})
    result: dict[str, object] = {"id": allocate_id(), **payload}
    if member.children is not None:
        result["children"] = [
            _new_member_payload(child, allocate_id=allocate_id) for child in member.children
        ]
    return result


def _find_member(root: object, member_id: str) -> dict[str, object] | None:
    if not isinstance(root, dict):
        return None
    if root.get("id") == member_id:
        return cast(dict[str, object], root)
    children = root.get("children", [])
    if not isinstance(children, list):
        return None
    for child in children:
        found = _find_member(child, member_id)
        if found is not None:
            return found
    return None


def _remove_member(root: object, member_id: str) -> bool:
    if not isinstance(root, dict):
        return False
    children = root.get("children")
    if not isinstance(children, list):
        return False
    for index, child in enumerate(children):
        if isinstance(child, dict) and child.get("id") == member_id:
            del children[index]
            return True
        if _remove_member(child, member_id):
            return True
    return False


def _member_ids(root: object) -> set[str]:
    ids: set[str] = set()
    if not isinstance(root, dict):
        return ids
    member_id = root.get("id")
    if isinstance(member_id, str):
        ids.add(member_id)
    children = root.get("children", [])
    if isinstance(children, list):
        for child in children:
            ids.update(_member_ids(child))
    return ids


def _default_member_id_allocator(root: object) -> Callable[[], str]:
    used_ids = _member_ids(root)
    next_member_number = 1

    def allocate_id() -> str:
        nonlocal next_member_number
        while f"member-{next_member_number}" in used_ids:
            next_member_number += 1
        allocated = f"member-{next_member_number}"
        used_ids.add(allocated)
        next_member_number += 1
        return allocated

    return allocate_id


def _new_workflow_member_id_allocator() -> Callable[[], str]:
    next_member_number = 1

    def allocate_id() -> str:
        nonlocal next_member_number
        allocated = f"member-{next_member_number}"
        next_member_number += 1
        return allocated

    return allocate_id


def _missing_member(member_id: str) -> WorkflowInputError:
    return workflow_input_error(
        source="operation.member_id",
        path="$.member_id",
        message=f"Member {member_id!r} does not exist",
    )


__all__ = [
    "DRAFT_OPERATION_ADAPTER",
    "AddMemberOperation",
    "DraftOperation",
    "MemberPatch",
    "NewMember",
    "RemoveMemberOperation",
    "UpdateMemberOperation",
    "UpdateWorkflowOperation",
    "WorkflowPatch",
    "build_new_workflow",
    "edit_normalized_workflow",
]
