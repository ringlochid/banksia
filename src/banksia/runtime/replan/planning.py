from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from pydantic import BaseModel

from banksia.persistence.models import MemberConfigurationModel, TeamRevisionMemberModel
from banksia.runtime.contracts import (
    AddChildRequest,
    RemoveChildRequest,
    ReplanExistingMemberPatch,
    ReplanMemberPatch,
    ReplanNewMember,
    UpdateChildRequest,
)
from banksia.runtime.contracts.operation_failure import OperationFailureCode
from banksia.runtime.errors import RuntimeOperationError
from banksia.workflows.ingest import MAX_MEMBER_DEPTH, MAX_MEMBERS

type ReplanRequest = AddChildRequest | UpdateChildRequest | RemoveChildRequest
type MemberPatch = ReplanMemberPatch | ReplanExistingMemberPatch


@dataclass(slots=True)
class PlannedMember:
    """One mutable member selection used to construct a complete successor Team."""

    member_id: str
    parent_member_id: str | None
    title: str | None
    description: str | None
    instruction: str | None
    provider_json: dict[str, object] | None
    capabilities_json: dict[str, object] | None
    configuration_id: str
    branch_basis_id: str
    source_selection: TeamRevisionMemberModel | None
    source_configuration: MemberConfigurationModel | None
    children: list[str] = field(default_factory=list)
    has_configuration_change: bool = False
    has_branch_change: bool = False
    is_new: bool = False


@dataclass(frozen=True, slots=True)
class ReplanMutation:
    """A validated complete successor tree plus public mutation identities."""

    members: dict[str, PlannedMember]
    root_member_id: str
    created_ids: tuple[str, ...]
    updated_ids: tuple[str, ...]
    removed_ids: tuple[str, ...]
    affected_existing_ids: frozenset[str]


def build_replan_mutation(
    *,
    loaded: dict[str, PlannedMember],
    root_member_id: str,
    caller_member_id: str,
    request: ReplanRequest,
) -> ReplanMutation:
    """Apply one bounded subtree mutation without changing historical member IDs."""

    members = _clone_members(loaded)
    descendants = _descendant_ids(members, caller_member_id)
    created: list[str] = []
    updated: list[str] = []
    removed: list[str] = []
    affected: set[str] = set()
    branch_change_seeds: set[str] = set()
    if isinstance(request, AddChildRequest):
        _append_new_tree(members, caller_member_id, request.child, created)
        branch_change_seeds.add(caller_member_id)
    elif isinstance(request, UpdateChildRequest):
        _require_descendant(request.id, descendants)
        affected.update(_descendant_ids(members, request.id, include_self=True))
        _apply_patch_tree(
            members,
            request.id,
            request.patch,
            created,
            updated,
            branch_change_seeds,
        )
        if not created and not updated:
            raise _no_effect_update()
    else:
        _require_descendant(request.id, descendants)
        parent_member_id = members[request.id].parent_member_id
        assert parent_member_id is not None
        branch_change_seeds.add(parent_member_id)
        removed.extend(_preorder_ids(members, request.id))
        affected.update(removed)
        _remove_subtree(members, request.id)
    _refresh_branch_bases(members, branch_change_seeds)
    _validate_complete_tree(members, root_member_id)
    return ReplanMutation(
        members=members,
        root_member_id=root_member_id,
        created_ids=tuple(created),
        updated_ids=tuple(dict.fromkeys(updated)),
        removed_ids=tuple(removed),
        affected_existing_ids=frozenset(affected),
    )


def successor_preorder(mutation: ReplanMutation) -> tuple[PlannedMember, ...]:
    """Return the complete successor Team in stable parent-before-child order."""

    ordered: list[PlannedMember] = []

    def visit(member_id: str) -> None:
        member = mutation.members[member_id]
        ordered.append(member)
        for child_id in member.children:
            visit(child_id)

    visit(mutation.root_member_id)
    return tuple(ordered)


def _clone_members(loaded: dict[str, PlannedMember]) -> dict[str, PlannedMember]:
    return {
        member_id: PlannedMember(
            member_id=member.member_id,
            parent_member_id=member.parent_member_id,
            title=member.title,
            description=member.description,
            instruction=member.instruction,
            provider_json=member.provider_json,
            capabilities_json=member.capabilities_json,
            configuration_id=member.configuration_id,
            branch_basis_id=member.branch_basis_id,
            source_selection=member.source_selection,
            source_configuration=member.source_configuration,
            children=list(member.children),
        )
        for member_id, member in loaded.items()
    }


def _append_new_tree(
    members: dict[str, PlannedMember],
    parent_id: str,
    authored: ReplanNewMember,
    created: list[str],
) -> str:
    member_id = f"member-{uuid4().hex[:16]}"
    configuration_id = f"member-configuration.{uuid4().hex}"
    basis_id = f"member-branch-basis.{uuid4().hex}"
    member = PlannedMember(
        member_id=member_id,
        parent_member_id=parent_id,
        title=authored.title,
        description=authored.description,
        instruction=authored.instruction,
        provider_json=_dump_optional(authored.provider),
        capabilities_json=_dump_optional(authored.capabilities),
        configuration_id=configuration_id,
        branch_basis_id=basis_id,
        source_selection=None,
        source_configuration=None,
        has_configuration_change=True,
        has_branch_change=True,
        is_new=True,
    )
    members[member_id] = member
    members[parent_id].children.append(member_id)
    created.append(member_id)
    for child in authored.children or ():
        _append_new_tree(members, member_id, child, created)
    return member_id


def _apply_patch_tree(
    members: dict[str, PlannedMember],
    member_id: str,
    patch: MemberPatch,
    created: list[str],
    updated: list[str],
    branch_change_seeds: set[str],
) -> None:
    member = members[member_id]
    configurable_fields = {
        "title",
        "description",
        "instruction",
        "provider",
        "capabilities",
    }
    changed = patch.model_fields_set & configurable_fields
    for field_name in changed:
        value = getattr(patch, field_name)
        target_name = (
            f"{field_name}_json" if field_name in {"provider", "capabilities"} else field_name
        )
        normalized = _dump_optional(value) if field_name in {"provider", "capabilities"} else value
        if getattr(member, target_name) != normalized:
            setattr(member, target_name, normalized)
            member.has_configuration_change = True
    if member.has_configuration_change and member_id not in updated:
        updated.append(member_id)
        branch_change_seeds.add(member_id)
    if "children" not in patch.model_fields_set:
        return
    for child_patch in patch.children or ():
        if isinstance(child_patch, ReplanNewMember):
            _append_new_tree(members, member_id, child_patch, created)
            branch_change_seeds.add(member_id)
            continue
        child = members.get(child_patch.id)
        if child is None or child.parent_member_id != member_id:
            raise _invalid_target("nested existing updates must identify a current direct child")
        _apply_patch_tree(
            members,
            child.member_id,
            child_patch,
            created,
            updated,
            branch_change_seeds,
        )


def _remove_subtree(members: dict[str, PlannedMember], member_id: str) -> None:
    parent_id = members[member_id].parent_member_id
    assert parent_id is not None
    members[parent_id].children.remove(member_id)
    for removed_id in _preorder_ids(members, member_id):
        members.pop(removed_id)


def _refresh_branch_bases(
    members: dict[str, PlannedMember],
    branch_change_seeds: set[str],
) -> None:
    changed_branch_ids: set[str] = set()
    for seed_member_id in branch_change_seeds:
        member_id: str | None = seed_member_id
        while member_id is not None and member_id not in changed_branch_ids:
            member = members.get(member_id)
            if member is None:
                raise _invalid_target("replan branch change has a missing ancestor")
            changed_branch_ids.add(member_id)
            member_id = member.parent_member_id

    for member_id, member in members.items():
        member.has_branch_change = member.is_new or member_id in changed_branch_ids
        if member.has_configuration_change and not member.is_new:
            member.configuration_id = f"member-configuration.{uuid4().hex}"
        if member.has_branch_change and not member.is_new:
            member.branch_basis_id = f"member-branch-basis.{uuid4().hex}"


def _validate_complete_tree(
    members: dict[str, PlannedMember],
    root_member_id: str,
) -> None:
    if root_member_id not in members or members[root_member_id].parent_member_id is not None:
        raise _invalid_target("replan candidate must retain exactly one root")
    seen: set[str] = set()

    def visit(member_id: str, depth: int) -> None:
        if depth > MAX_MEMBER_DEPTH:
            raise _invalid_target(f"replan exceeds the maximum depth of {MAX_MEMBER_DEPTH}")
        if member_id in seen:
            raise _invalid_target("replan candidate is cyclic or selects a Member twice")
        seen.add(member_id)
        member = members[member_id]
        if len(member.children) > 32:
            raise _invalid_target("a Member cannot have more than 32 direct children")
        for child_id in member.children:
            child = members.get(child_id)
            if child is None or child.parent_member_id != member_id:
                raise _invalid_target("replan candidate contains an invalid parent link")
            visit(child_id, depth + 1)

    visit(root_member_id, 1)
    if len(seen) != len(members):
        raise _invalid_target("replan candidate contains a disconnected Member")
    if len(seen) > MAX_MEMBERS:
        raise _invalid_target(f"replan exceeds the maximum Team size of {MAX_MEMBERS}")


def _descendant_ids(
    members: dict[str, PlannedMember],
    member_id: str,
    *,
    include_self: bool = False,
) -> set[str]:
    if member_id not in members:
        raise _invalid_target("current caller Member is absent from the Team")
    descendants = set(_preorder_ids(members, member_id))
    if not include_self:
        descendants.remove(member_id)
    return descendants


def _preorder_ids(members: dict[str, PlannedMember], member_id: str) -> list[str]:
    ordered = [member_id]
    for child_id in members[member_id].children:
        ordered.extend(_preorder_ids(members, child_id))
    return ordered


def _require_descendant(member_id: str, descendants: set[str]) -> None:
    if member_id not in descendants:
        raise _invalid_target("replan target must be inside the current caller's subtree")


def _dump_optional(value: BaseModel | None) -> dict[str, object] | None:
    if value is None:
        return None
    return value.model_dump(mode="json", exclude_none=True)


def _invalid_target(summary: str) -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.ILLEGAL_TARGET_RELATION,
        summary=summary,
        is_retryable=False,
    )


def _no_effect_update() -> RuntimeOperationError:
    return RuntimeOperationError(
        code=OperationFailureCode.ILLEGAL_STATE,
        summary="update_child does not change the current Team",
        is_retryable=False,
    )


__all__ = [
    "PlannedMember",
    "ReplanMutation",
    "ReplanRequest",
    "build_replan_mutation",
    "successor_preorder",
]
