from __future__ import annotations

from autoclaw.definitions.compiler import (
    MappingRolePolicyLookup,
    PolicyRevisionDefinition,
    RoleRevisionDefinition,
)


def resolve_pinned_role_policy(
    lookup: MappingRolePolicyLookup,
    *,
    role_key: str,
    role_revision_no: int,
    policy_key: str,
    policy_revision_no: int,
) -> tuple[RoleRevisionDefinition, PolicyRevisionDefinition]:
    role = lookup.get_role(role_key)
    if role is None:
        raise ValueError(f"missing role definition for '{role_key}'")
    if role.revision_no != role_revision_no:
        raise ValueError(
            "role "
            f"'{role_key}' resolved revision {role.revision_no} but node pins "
            f"{role_revision_no}"
        )

    policy = lookup.get_policy(policy_key)
    if policy is None:
        raise ValueError(f"missing policy definition for '{policy_key}'")
    if policy.revision_no != policy_revision_no:
        raise ValueError(
            "policy "
            f"'{policy_key}' resolved revision {policy.revision_no} but node pins "
            f"{policy_revision_no}"
        )
    return role, policy
