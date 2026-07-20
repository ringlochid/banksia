from __future__ import annotations

import asyncio
from types import TracebackType
from typing import cast
from unittest.mock import AsyncMock

import autoclaw.persistence.session_operations as session_operations
import pytest
from sqlalchemy.ext.asyncio import AsyncSession


class _RecordingSessionContext:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> AsyncSession:
        self.entered = True
        return self.session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.exited = True


class _RecordingSessionFactory:
    def __init__(self, context: _RecordingSessionContext) -> None:
        self.context = context
        self.call_count = 0

    def __call__(self) -> _RecordingSessionContext:
        self.call_count += 1
        return self.context


async def test_read_session_operation_reuses_injected_session_without_committing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session_mock()
    monkeypatch.setattr(session_operations, "get_session_factory", _reject_owned_session)

    async def read(active_session: AsyncSession) -> str:
        assert active_session is session
        return "read"

    result = await session_operations.read_session_operation(
        read,
        session=cast(AsyncSession, session),
    )

    assert result == "read"
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


async def test_read_session_operation_owns_and_closes_session_without_committing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session_mock()
    context = _RecordingSessionContext(cast(AsyncSession, session))
    factory = _RecordingSessionFactory(context)
    monkeypatch.setattr(session_operations, "get_session_factory", lambda: factory)

    result = await session_operations.read_session_operation(
        lambda active_session: _identity(active_session)
    )

    assert result is session
    assert factory.call_count == 1
    assert context.entered is True
    assert context.exited is True
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


async def test_write_session_operation_commits_injected_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session_mock()
    monkeypatch.setattr(session_operations, "get_session_factory", _reject_owned_session)

    result = await session_operations.write_session_operation(
        lambda active_session: _constant(active_session, "written"),
        session=cast(AsyncSession, session),
    )

    assert result == "written"
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()


async def test_write_session_operation_commits_and_closes_owned_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session_mock()
    context = _RecordingSessionContext(cast(AsyncSession, session))
    factory = _RecordingSessionFactory(context)
    monkeypatch.setattr(session_operations, "get_session_factory", lambda: factory)

    result = await session_operations.write_session_operation(
        lambda active_session: _constant(active_session, "written")
    )

    assert result == "written"
    assert factory.call_count == 1
    assert context.entered is True
    assert context.exited is True
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()


async def test_write_session_operation_rolls_back_and_closes_owned_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session_mock()
    context = _RecordingSessionContext(cast(AsyncSession, session))
    factory = _RecordingSessionFactory(context)
    monkeypatch.setattr(session_operations, "get_session_factory", lambda: factory)

    async def fail(active_session: AsyncSession) -> None:
        assert active_session is session
        raise ValueError("write failed")

    with pytest.raises(ValueError, match="write failed"):
        await session_operations.write_session_operation(fail)

    assert context.exited is True
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()


async def test_write_session_operation_rolls_back_cancellation() -> None:
    session = _session_mock()

    async def cancel(active_session: AsyncSession) -> None:
        assert active_session is session
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await session_operations.write_session_operation(
            cancel,
            session=cast(AsyncSession, session),
        )

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()


def _session_mock() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


def _reject_owned_session() -> None:
    raise AssertionError("an injected session must not create an owned session")


async def _identity(session: AsyncSession) -> AsyncSession:
    return session


async def _constant(session: AsyncSession, value: str) -> str:
    del session
    return value
