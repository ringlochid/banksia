from __future__ import annotations

import hashlib
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.definitions.contracts.registry import PolicyDefinitionFile, RoleDefinitionFile
from autoclaw.definitions.contracts.workflow import WorkflowDefinitionFile
from autoclaw.definitions.seeds import resolve_packaged_seed_definitions_root


async def seed_definition_registry(
    session: AsyncSession,
    *,
    definitions_root: Path | None = None,
) -> None:
    from autoclaw.definitions.registry.upsert import (
        upsert_policy_definition,
        upsert_role_definition,
        upsert_workflow_definition,
    )

    package_root_context = (
        nullcontext(definitions_root)
        if definitions_root is not None
        else resolve_packaged_seed_definitions_root()
    )
    with package_root_context as package_root:
        seed_root = package_root
        for path in _seed_file_paths(seed_root, "roles"):
            role = RoleDefinitionFile.model_validate(_load_yaml(path))
            await upsert_role_definition(
                session,
                role,
                source_path=_seed_source_identity(
                    seed_root=seed_root,
                    path=path,
                    override_root=definitions_root,
                ),
                should_allow_existing_update=False,
            )
        for path in _seed_file_paths(seed_root, "policies"):
            policy = PolicyDefinitionFile.model_validate(_load_yaml(path))
            await upsert_policy_definition(
                session,
                policy,
                source_path=_seed_source_identity(
                    seed_root=seed_root,
                    path=path,
                    override_root=definitions_root,
                ),
                should_allow_existing_update=False,
            )
        for path in _seed_file_paths(seed_root, "workflows"):
            workflow = WorkflowDefinitionFile.model_validate(_load_yaml(path))
            await upsert_workflow_definition(
                session,
                workflow,
                source_path=_seed_source_identity(
                    seed_root=seed_root,
                    path=path,
                    override_root=definitions_root,
                ),
                should_allow_existing_update=False,
            )


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping content in {path}")
    return payload


def _seed_file_paths(definitions_root: Path, kind: str) -> list[Path]:
    paths = sorted(definitions_root.joinpath(kind).glob("*.yaml"))
    if paths:
        return paths
    raise FileNotFoundError(
        f"missing seed definitions for '{kind}' in {definitions_root.joinpath(kind)}"
    )


def _seed_source_identity(
    *,
    seed_root: Path,
    path: Path,
    override_root: Path | None,
) -> str:
    relative_path = path.relative_to(seed_root).as_posix()
    if override_root is None:
        return f"seed://packaged/{relative_path}"
    override_root_fingerprint = hashlib.sha256(
        str(override_root.resolve()).encode("utf-8")
    ).hexdigest()[:12]
    return f"seed://override/{override_root_fingerprint}/{relative_path}"
