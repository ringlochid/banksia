from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from banksia.runtime.contracts.team_read import (
    DirectTeamMemberRead,
    EffectiveCapabilitiesRead,
    MemberBehavior,
)
from banksia.workflows.contracts import (
    Identifier,
    MemberCapabilities,
    ProviderSelection,
)
from banksia.workflows.ingest import (
    MAX_MEMBER_DEPTH,
    MAX_MEMBERS,
    normalize_optional_member_prose,
)

_OptionalProse = Annotated[str, Field(max_length=16384)] | None
_MAX_DIRECT_CHILDREN = 32
type ReplanOperation = Literal["add_child", "update_child", "remove_child"]


class _ReplanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReplanNewMember(_ReplanModel):
    title: _OptionalProse = None
    description: _OptionalProse = None
    instruction: _OptionalProse = None
    provider: ProviderSelection | None = None
    capabilities: MemberCapabilities | None = None
    children: tuple[ReplanNewMember, ...] | None = None

    @field_validator("title", "description", "instruction", mode="before")
    @classmethod
    def normalize_optional_prose(cls, value: object) -> object:
        return _normalize_optional_prose(value)

    @model_validator(mode="after")
    def reject_explicit_empty_children(self) -> ReplanNewMember:
        if "children" in self.model_fields_set and not self.children:
            raise ValueError("children: [] is ambiguous; omit children for a leaf")
        _enforce_hidden_direct_child_limit(self.children)
        return self


class ReplanExistingMemberPatch(_ReplanModel):
    id: Identifier
    title: _OptionalProse = None
    description: _OptionalProse = None
    instruction: _OptionalProse = None
    provider: ProviderSelection | None = None
    capabilities: MemberCapabilities | None = None
    children: tuple[ReplanExistingMemberPatch | ReplanNewMember, ...] | None = None

    @field_validator("title", "description", "instruction", mode="before")
    @classmethod
    def normalize_optional_prose(cls, value: object) -> object:
        return _normalize_optional_prose(value)

    @model_validator(mode="after")
    def require_patch_and_reject_empty_children(self) -> ReplanExistingMemberPatch:
        fields = self.model_fields_set - {"id"}
        if not fields:
            raise ValueError("existing child update must contain at least one changed field")
        if "children" in fields and not self.children:
            raise ValueError("children: [] is ambiguous; omit children to preserve them")
        _enforce_hidden_direct_child_limit(self.children)
        _reject_duplicate_existing_children(self.children)
        return self


class ReplanMemberPatch(_ReplanModel):
    title: _OptionalProse = None
    description: _OptionalProse = None
    instruction: _OptionalProse = None
    provider: ProviderSelection | None = None
    capabilities: MemberCapabilities | None = None
    children: tuple[ReplanExistingMemberPatch | ReplanNewMember, ...] | None = None

    @field_validator("title", "description", "instruction", mode="before")
    @classmethod
    def normalize_optional_prose(cls, value: object) -> object:
        return _normalize_optional_prose(value)

    @model_validator(mode="after")
    def require_patch_and_reject_empty_children(self) -> ReplanMemberPatch:
        if not self.model_fields_set:
            raise ValueError("member patch must contain at least one changed field")
        if "children" in self.model_fields_set and not self.children:
            raise ValueError("children: [] is ambiguous; use remove_child explicitly")
        _enforce_hidden_direct_child_limit(self.children)
        _reject_duplicate_existing_children(self.children)
        return self


class AddChildRequest(_ReplanModel):
    child: ReplanNewMember

    @model_validator(mode="after")
    def enforce_tree_bounds(self) -> AddChildRequest:
        _validate_new_tree(self.child)
        return self


class UpdateChildRequest(_ReplanModel):
    id: Identifier
    patch: ReplanMemberPatch

    @model_validator(mode="after")
    def enforce_tree_bounds(self) -> UpdateChildRequest:
        _validate_patch_tree(self.patch)
        return self


class RemoveChildRequest(_ReplanModel):
    id: Identifier


class ReplanSuccess(_ReplanModel):
    operation: ReplanOperation
    created_ids: tuple[Identifier, ...] = ()
    updated_ids: tuple[Identifier, ...] = ()
    removed_ids: tuple[Identifier, ...] = ()
    direct_team: tuple[DirectTeamMemberRead, ...]
    behavior: MemberBehavior
    effective_capabilities: EffectiveCapabilitiesRead
    available_actions: tuple[Identifier, ...]
    must_stop: Literal[True] = True

    @model_validator(mode="after")
    def validate_fresh_member_view(self) -> ReplanSuccess:
        expected_behavior = (
            MemberBehavior.MANAGER if self.direct_team else MemberBehavior.CONTRIBUTOR
        )
        if self.behavior is not expected_behavior:
            raise ValueError("replan behavior must match the direct-team shape")
        if tuple(dict.fromkeys(self.available_actions)) != self.available_actions:
            raise ValueError("replan available actions must be unique")
        return self


def _validate_new_tree(root: ReplanNewMember) -> None:
    member_count = 0

    def visit(member: ReplanNewMember, depth: int) -> None:
        nonlocal member_count
        member_count += 1
        if member_count > MAX_MEMBERS:
            raise ValueError(f"replan request exceeds {MAX_MEMBERS} new Members")
        if depth > MAX_MEMBER_DEPTH:
            raise ValueError(f"replan member tree depth exceeds {MAX_MEMBER_DEPTH}")
        for child in member.children or ():
            visit(child, depth + 1)

    visit(root, 1)


def _validate_patch_tree(root: ReplanMemberPatch) -> None:
    member_count = 0

    def visit(
        member: ReplanExistingMemberPatch | ReplanNewMember,
        depth: int,
    ) -> None:
        nonlocal member_count
        member_count += 1
        if member_count > MAX_MEMBERS:
            raise ValueError(f"replan request exceeds {MAX_MEMBERS} nested entries")
        if depth > MAX_MEMBER_DEPTH:
            raise ValueError(f"replan member tree depth exceeds {MAX_MEMBER_DEPTH}")
        for child in member.children or ():
            visit(child, depth + 1)

    for child in root.children or ():
        visit(child, 1)


def _normalize_optional_prose(value: object) -> object:
    if not isinstance(value, str):
        return value
    return normalize_optional_member_prose(value)


def _enforce_hidden_direct_child_limit(children: tuple[object, ...] | None) -> None:
    if children is not None and len(children) > _MAX_DIRECT_CHILDREN:
        raise ValueError(
            f"Member exceeds the controller direct-child limit of {_MAX_DIRECT_CHILDREN}"
        )


def _reject_duplicate_existing_children(
    children: tuple[ReplanExistingMemberPatch | ReplanNewMember, ...] | None,
) -> None:
    existing_ids = [
        child.id for child in children or () if isinstance(child, ReplanExistingMemberPatch)
    ]
    if len(existing_ids) != len(set(existing_ids)):
        raise ValueError("children cannot reference the same existing Member more than once")


__all__ = [
    "AddChildRequest",
    "RemoveChildRequest",
    "ReplanExistingMemberPatch",
    "ReplanMemberPatch",
    "ReplanNewMember",
    "ReplanOperation",
    "ReplanSuccess",
    "UpdateChildRequest",
]
