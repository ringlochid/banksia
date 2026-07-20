from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator, Generator
from importlib import import_module
from pathlib import Path
from tempfile import gettempdir
from typing import Protocol, cast
from uuid import uuid4

import pytest
import pytest_asyncio

os.environ["AUTOCLAW_ENV"] = "test"
os.environ["AUTOCLAW_DEBUG"] = "false"
_TEST_CONFIG_PATH = Path(gettempdir()) / (f"autoclaw-pytest-{os.getpid()}-{uuid4().hex}.toml")
if _TEST_CONFIG_PATH.exists():
    raise RuntimeError(f"pytest config isolation path unexpectedly exists: {_TEST_CONFIG_PATH}")
os.environ["AUTOCLAW_CONFIG"] = str(_TEST_CONFIG_PATH)


class _CachedSettingsLoader(Protocol):
    def cache_clear(self) -> None: ...


# Import dynamically only after the hermetic environment is complete.
get_settings = cast(
    _CachedSettingsLoader,
    import_module("autoclaw.config").get_settings,
)

get_settings.cache_clear()


_QUIET_SQLALCHEMY_LOGS = "quiet_sqlalchemy_logs"
_SQLALCHEMY_LOGGER_NAMES = (
    "sqlalchemy",
    "sqlalchemy.engine",
    "sqlalchemy.engine.Engine",
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{_QUIET_SQLALCHEMY_LOGS}: silence noisy SQLAlchemy loggers for the marked tests.",
    )


def _has_marker(request: pytest.FixtureRequest, marker_name: str) -> bool:
    return request.node.get_closest_marker(marker_name) is not None


@pytest.fixture(autouse=True)
def quiet_sqlalchemy_logs_for_selected_e2e_tests(
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    if not _has_marker(request, _QUIET_SQLALCHEMY_LOGS):
        yield
        return

    logger_state: list[tuple[logging.Logger, int, bool]] = []
    for logger_name in _SQLALCHEMY_LOGGER_NAMES:
        logger = logging.getLogger(logger_name)
        logger_state.append((logger, logger.level, logger.propagate))
        logger.setLevel(logging.WARNING)
        logger.propagate = False
    try:
        yield
    finally:
        for logger, level, propagate in logger_state:
            logger.setLevel(level)
            logger.propagate = propagate


@pytest_asyncio.fixture(autouse=True)
async def cleanup_runtime_async_state() -> AsyncGenerator[None, None]:
    try:
        yield
    finally:
        from autoclaw.persistence.session import dispose_test_db_engine

        await dispose_test_db_engine()
