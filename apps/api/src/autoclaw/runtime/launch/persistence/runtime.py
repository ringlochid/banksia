from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.runtime.contracts import (
    RuntimeBootstrapInput,
    RuntimeBootstrapResult,
)
from autoclaw.runtime.launch.bootstrap.context import build_launch_bootstrap_persistence_context
from autoclaw.runtime.launch.bootstrap.projection import build_launch_bootstrap_result
from autoclaw.runtime.launch.bootstrap.rows import stage_launch_bootstrap_rows
from autoclaw.runtime.launch.persistence.attempts import stage_launch_attempt_rows


async def persist_bootstrap_runtime_from_precomputed(
    session: AsyncSession,
    bootstrap_input: RuntimeBootstrapInput,
    *,
    should_commit: bool = True,
) -> RuntimeBootstrapResult:
    result = build_launch_bootstrap_result(bootstrap_input)
    context = build_launch_bootstrap_persistence_context(
        bootstrap_input=bootstrap_input,
    )
    await stage_launch_bootstrap_rows(
        session,
        bootstrap_input=bootstrap_input,
        result=result,
        context=context,
    )
    await stage_launch_attempt_rows(
        session,
        bootstrap_input=bootstrap_input,
        result=result,
        flow_id=context.flow_id,
    )
    if not should_commit:
        return result
    await session.commit()
    return result
