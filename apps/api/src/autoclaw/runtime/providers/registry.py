from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import AsyncExitStack, asynccontextmanager

from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.runtime.providers.contracts import ProviderAdapter


class ProviderAdapterRegistry:
    """Exact provider-kind routing and lifespan ownership without fallback."""

    def __init__(self, adapters: Iterable[ProviderAdapter]) -> None:
        adapters_by_kind: dict[ProviderKind, ProviderAdapter] = {}
        for adapter in adapters:
            if adapter.kind in adapters_by_kind:
                raise ValueError(f"duplicate provider adapter: {adapter.kind.value}")
            adapters_by_kind[adapter.kind] = adapter
        self._adapters_by_kind = adapters_by_kind
        self._is_active = False

    @property
    def available_kinds(self) -> frozenset[ProviderKind]:
        return frozenset(self._adapters_by_kind)

    def get(self, kind: ProviderKind) -> ProviderAdapter:
        try:
            return self._adapters_by_kind[kind]
        except KeyError as exc:
            raise LookupError(f"provider adapter unavailable: {kind.value}") from exc

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[ProviderAdapterRegistry]:
        if self._is_active:
            raise RuntimeError("provider adapter registry lifespan is already active")

        async with AsyncExitStack() as stack:
            for adapter in self._adapters_by_kind.values():
                await stack.enter_async_context(adapter.lifespan())
            self._is_active = True
            try:
                yield self
            finally:
                self._is_active = False


__all__ = ["ProviderAdapterRegistry"]
