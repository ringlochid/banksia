from __future__ import annotations

import hashlib
import json
from typing import NewType

from banksia.workflows.contracts import NormalizedWorkflow

CanonicalWorkflowBytes = NewType("CanonicalWorkflowBytes", bytes)


def canonical_workflow_bytes(workflow: NormalizedWorkflow) -> CanonicalWorkflowBytes:
    return CanonicalWorkflowBytes(_canonical_workflow_bytes(workflow))


def canonical_workflow_hash(workflow: NormalizedWorkflow) -> str:
    return hashlib.sha256(_canonical_workflow_bytes(workflow)).hexdigest()


def _canonical_workflow_bytes(workflow: NormalizedWorkflow) -> bytes:
    payload = workflow.model_dump(mode="json", exclude_none=True)
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


__all__ = [
    "CanonicalWorkflowBytes",
    "canonical_workflow_bytes",
]
