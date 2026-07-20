from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import autoclaw.persistence.session as persistence_session
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine


def test_postgres_engine_configuration_does_not_install_sqlite_transaction_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    postgres_engine = cast(AsyncEngine, object())

    def capture_engine(database_url: str, **engine_kwargs: Any) -> AsyncEngine:
        captured["database_url"] = database_url
        captured["engine_kwargs"] = engine_kwargs
        return postgres_engine

    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://autoclaw@localhost/autoclaw",
        database_echo=False,
        postgres_schema="autoclaw_test",
    )
    monkeypatch.setattr(persistence_session, "get_settings", lambda: settings)
    monkeypatch.setattr(persistence_session, "create_async_engine", capture_engine)

    async def build_engine() -> AsyncEngine:
        try:
            return persistence_session.get_async_engine()
        finally:
            persistence_session._ENGINE_BY_LOOP.clear()
            persistence_session._SESSION_FACTORY_BY_LOOP.clear()

    assert asyncio.run(build_engine()) is postgres_engine
    assert captured == {
        "database_url": settings.database_url,
        "engine_kwargs": {
            "echo": False,
            "pool_pre_ping": True,
            "connect_args": {"server_settings": {"search_path": "autoclaw_test"}},
            "execution_options": {"schema_translate_map": {None: "autoclaw_test"}},
        },
    }
