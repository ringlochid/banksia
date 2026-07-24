from __future__ import annotations

import base64
import json
from typing import cast

from banksia.runtime.errors import invalid_request_shape_error

_WORKFLOW_SEARCH_CURSOR_PREFIX = "workflow-search."
_WORKFLOW_REVISION_CURSOR_PREFIX = "workflow-revisions."


def encode_workflow_search_cursor(
    workflow_id: str,
    *,
    normalized_query: str,
) -> str:
    return _encode_catalog_cursor(
        _WORKFLOW_SEARCH_CURSOR_PREFIX,
        {
            "q": normalized_query,
            "version": 1,
            "workflow_id": workflow_id,
        },
    )


def decode_workflow_search_cursor(
    cursor: str | None,
    *,
    normalized_query: str,
) -> str | None:
    if cursor is None:
        return None
    payload = _decode_catalog_cursor(cursor, prefix=_WORKFLOW_SEARCH_CURSOR_PREFIX)
    workflow_id = payload.get("workflow_id")
    if (
        payload.get("version") != 1
        or payload.get("q") != normalized_query
        or not isinstance(workflow_id, str)
        or not workflow_id
    ):
        raise invalid_request_shape_error("The Workflow search cursor is no longer usable.")
    return workflow_id


def encode_workflow_revision_cursor(
    revision_no: int,
    *,
    workflow_id: str,
) -> str:
    return _encode_catalog_cursor(
        _WORKFLOW_REVISION_CURSOR_PREFIX,
        {
            "revision_no": revision_no,
            "version": 1,
            "workflow_id": workflow_id,
        },
    )


def decode_workflow_revision_cursor(
    cursor: str | None,
    *,
    workflow_id: str,
) -> int | None:
    if cursor is None:
        return None
    payload = _decode_catalog_cursor(cursor, prefix=_WORKFLOW_REVISION_CURSOR_PREFIX)
    revision_no = payload.get("revision_no")
    if (
        payload.get("version") != 1
        or payload.get("workflow_id") != workflow_id
        or not isinstance(revision_no, int)
        or revision_no < 1
    ):
        raise invalid_request_shape_error("The Workflow revision cursor is no longer usable.")
    return revision_no


def _encode_catalog_cursor(prefix: str, payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f"{prefix}{encoded.rstrip('=')}"


def _decode_catalog_cursor(cursor: str, *, prefix: str) -> dict[str, object]:
    if not cursor.startswith(prefix):
        raise invalid_request_shape_error("The Workflow cursor is no longer usable.")
    try:
        token = cursor.removeprefix(prefix)
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise invalid_request_shape_error("The Workflow cursor is no longer usable.") from exc
    if not isinstance(payload, dict):
        raise invalid_request_shape_error("The Workflow cursor is no longer usable.")
    return cast(dict[str, object], payload)


__all__ = [
    "decode_workflow_revision_cursor",
    "decode_workflow_search_cursor",
    "encode_workflow_revision_cursor",
    "encode_workflow_search_cursor",
]
