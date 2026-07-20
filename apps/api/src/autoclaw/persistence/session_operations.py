from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.persistence.session import get_session_factory

ResultT = TypeVar("ResultT")


async def read_session_operation(
    operation: Callable[[AsyncSession], Awaitable[ResultT]],
    *,
    session: AsyncSession | None = None,
) -> ResultT:
    """Run a database read with the supplied session or a short owned session."""

    if session is not None:
        return await operation(session)

    async with get_session_factory()() as owned_session:
        return await operation(owned_session)


async def write_session_operation(
    operation: Callable[[AsyncSession], Awaitable[ResultT]],
    *,
    session: AsyncSession | None = None,
) -> ResultT:
    """Run and commit one database write, rolling it back on interruption or failure."""

    if session is not None:
        return await _commit_session_operation(operation, session)

    async with get_session_factory()() as owned_session:
        return await _commit_session_operation(operation, owned_session)


async def _commit_session_operation(
    operation: Callable[[AsyncSession], Awaitable[ResultT]],
    session: AsyncSession,
) -> ResultT:
    try:
        result = await operation(session)
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return result


__all__ = ["read_session_operation", "write_session_operation"]
