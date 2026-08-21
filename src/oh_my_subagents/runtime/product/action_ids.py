from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterable

_ACTION_PREFIX = "action."


def product_action_id(*parts: object) -> str:
    """Return a stable opaque guard derived from exact current controller facts."""

    material = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return f"{_ACTION_PREFIX}{digest}"


def select_action_kind(
    supplied_action_id: str,
    candidates: Iterable[tuple[str, str]],
) -> str | None:
    for action_id, kind in candidates:
        if hmac.compare_digest(supplied_action_id, action_id):
            return kind
    return None


__all__ = ["product_action_id", "select_action_kind"]
