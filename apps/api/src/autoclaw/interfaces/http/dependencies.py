from __future__ import annotations

from typing import cast

from fastapi import Request

from autoclaw.runtime.dispatch.preparation import DispatchOpeningDependencies
from autoclaw.runtime.node_operations.follow_on import SupportProjectionPublisher
from autoclaw.runtime.post_commit import RuntimeEffectPublisher

LOCAL_OPERATOR_ACTOR_REF = "local_operator"


async def read_control_actor_ref() -> str:
    """Return stable provenance for the locally admitted operator surface."""
    return LOCAL_OPERATOR_ACTOR_REF


async def read_runtime_effect_publisher(request: Request) -> RuntimeEffectPublisher | None:
    return cast(
        RuntimeEffectPublisher | None,
        getattr(request.app.state, "runtime_effect_publisher", None),
    )


async def read_dispatch_opening_dependencies(request: Request) -> DispatchOpeningDependencies:
    dependencies = getattr(request.app.state, "dispatch_opening_dependencies", None)
    if not isinstance(dependencies, DispatchOpeningDependencies):
        raise RuntimeError("dispatch opening dependencies are unavailable")
    return dependencies


async def read_support_projection_publisher(request: Request) -> SupportProjectionPublisher | None:
    return cast(
        SupportProjectionPublisher | None,
        getattr(request.app.state, "support_projection_publisher", None),
    )
