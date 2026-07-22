from __future__ import annotations

import hashlib
import json


def canonical_content_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def workflow_revision_id(workflow_key: str, revision_no: int) -> str:
    return f"workflow-revision.{workflow_key}.{revision_no:03d}"


def role_revision_id(role_key: str, revision_no: int) -> str:
    return f"role-revision.{role_key}.{revision_no:03d}"


def policy_revision_id(policy_key: str, revision_no: int) -> str:
    return f"policy-revision.{policy_key}.{revision_no:03d}"
