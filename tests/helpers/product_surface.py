from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from oh_my_subagents.config import CodexSettings, RuntimeSettings, Settings, get_settings
from oh_my_subagents.main import create_app
from oh_my_subagents.persistence.session import get_db_session
from oh_my_subagents.providers import ProviderKind
from oh_my_subagents.runtime.dispatch.preparation import DispatchOpeningDependencies
from oh_my_subagents.runtime.post_commit import CapturedRuntimeEffectPublisher
from oh_my_subagents.runtime.providers import ProviderAdapterRegistry


class AsyncSessionFactory(Protocol):
    def __call__(self, **local_kw: Any) -> AsyncSession: ...


@asynccontextmanager
async def product_http_client(
    session_factory: AsyncSessionFactory,
    *,
    tmp_path: Path,
    publisher: CapturedRuntimeEffectPublisher | None = None,
    provider_adapters: ProviderAdapterRegistry | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(should_enable_mcp_mounts=False)
    app.state.dispatch_opening_dependencies = product_dispatch_dependencies(tmp_path)
    if publisher is not None:
        app.state.runtime_effect_publisher = publisher
    if provider_adapters is not None:
        app.state.provider_adapter_registry = provider_adapters

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


__all__ = [
    "product_dispatch_dependencies",
    "product_http_client",
]
