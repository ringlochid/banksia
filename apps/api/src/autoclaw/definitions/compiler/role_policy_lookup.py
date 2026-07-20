from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from autoclaw.definitions.contracts.registry import PolicyDefinitionInput, RoleDefinitionInput


class RoleRevisionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    definition: RoleDefinitionInput
    revision_no: int = Field(ge=1)


class PolicyRevisionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    definition: PolicyDefinitionInput
    revision_no: int = Field(ge=1)


class RolePolicyLookup(Protocol):
    def get_role(self, role_key: str) -> RoleRevisionDefinition | None: ...

    def get_policy(self, policy_key: str) -> PolicyRevisionDefinition | None: ...


class MappingRolePolicyLookup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    roles: Mapping[str, RoleRevisionDefinition]
    policies: Mapping[str, PolicyRevisionDefinition]

    def get_role(self, role_key: str) -> RoleRevisionDefinition | None:
        return self.roles.get(role_key)

    def get_policy(self, policy_key: str) -> PolicyRevisionDefinition | None:
        return self.policies.get(policy_key)
