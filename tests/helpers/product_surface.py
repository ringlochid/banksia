from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from banksia.config import CodexSettings, RuntimeSettings, Settings, get_settings
from banksia.main import create_app
from banksia.persistence.session import get_db_session
from banksia.providers import ProviderKind
from banksia.runtime.dispatch.preparation import DispatchOpeningDependencies
from banksia.runtime.post_commit import CapturedRuntimeEffectPublisher


class AsyncSessionFactory(Protocol):
    def __call__(self, **local_kw: Any) -> AsyncSession: ...


@asynccontextmanager
async def product_http_client(
    session_factory: AsyncSessionFactory,
    *,
    tmp_path: Path,
    publisher: CapturedRuntimeEffectPublisher | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(should_enable_mcp_mounts=False)
    app.state.dispatch_opening_dependencies = product_dispatch_dependencies(tmp_path)
    if publisher is not None:
        app.state.runtime_effect_publisher = publisher

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = session_dependency
    settings = get_settings()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 43125)),
        base_url=f"http://127.0.0.1:{settings.api_port}",
    ) as client:
        yield client


def product_dispatch_dependencies(workspace: Path) -> DispatchOpeningDependencies:
    return DispatchOpeningDependencies.create(
        settings=Settings(
            controller_workspace=workspace,
            runtime=RuntimeSettings(default_provider=ProviderKind.CODEX),
            codex=CodexSettings(enabled=True),
        ),
        available_adapter_kinds={ProviderKind.CODEX},
        post_commit_publisher=CapturedRuntimeEffectPublisher(),
    )


def operator_payload(result: object) -> object:
    assert isinstance(result, tuple) and len(result) == 2
    return result[1]


__all__ = [
    "operator_payload",
    "product_dispatch_dependencies",
    "product_http_client",
]
