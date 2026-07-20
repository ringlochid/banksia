from __future__ import annotations

import pytest
from autoclaw.runtime.startup_audit import (
    STARTUP_AUDIT_PAGE_GUARD,
    STARTUP_AUDIT_PAGE_SIZE,
    StartupAuditPage,
    StartupAuditPaginationError,
    audit_startup_source_family,
)


@pytest.mark.asyncio
async def test_startup_audit_pages_and_routes_exact_sources() -> None:
    requested_pages: list[tuple[int | None, int]] = []
    routed_sources: list[str] = []

    async def fetch_page(
        cursor: int | None,
        page_size: int,
    ) -> StartupAuditPage[str, int]:
        requested_pages.append((cursor, page_size))
        if cursor is None:
            return StartupAuditPage(sources=("dispatch-1", "dispatch-2"), next_cursor=2)
        return StartupAuditPage(sources=("dispatch-3",), next_cursor=None)

    async def route_source(source: str) -> None:
        routed_sources.append(source)

    routed_count = await audit_startup_source_family(
        family_name="provider_start",
        fetch_page=fetch_page,
        route_source=route_source,
        cursor_advances=lambda previous, candidate: candidate > previous,
    )

    assert requested_pages == [
        (None, STARTUP_AUDIT_PAGE_SIZE),
        (2, STARTUP_AUDIT_PAGE_SIZE),
    ]
    assert routed_sources == ["dispatch-1", "dispatch-2", "dispatch-3"]
    assert routed_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("next_cursor", [5, 4])
async def test_startup_audit_rejects_non_advancing_cursor(next_cursor: int) -> None:
    async def fetch_page(
        cursor: int | None,
        page_size: int,
    ) -> StartupAuditPage[str, int]:
        del page_size
        if cursor is None:
            return StartupAuditPage(sources=("dispatch-1",), next_cursor=5)
        return StartupAuditPage(sources=("dispatch-2",), next_cursor=next_cursor)

    async def route_source(source: str) -> None:
        del source

    with pytest.raises(StartupAuditPaginationError, match="non-advancing cursor"):
        await audit_startup_source_family(
            family_name="provider_start",
            fetch_page=fetch_page,
            route_source=route_source,
            cursor_advances=lambda previous, candidate: candidate > previous,
        )


@pytest.mark.asyncio
async def test_startup_audit_rejects_oversized_page_before_routing() -> None:
    routed_sources: list[int] = []

    async def fetch_page(
        cursor: int | None,
        page_size: int,
    ) -> StartupAuditPage[int, int]:
        del cursor, page_size
        return StartupAuditPage(
            sources=tuple(range(STARTUP_AUDIT_PAGE_SIZE + 1)),
            next_cursor=None,
        )

    async def route_source(source: int) -> None:
        routed_sources.append(source)

    with pytest.raises(StartupAuditPaginationError, match="201 sources"):
        await audit_startup_source_family(
            family_name="provider_start",
            fetch_page=fetch_page,
            route_source=route_source,
            cursor_advances=lambda previous, candidate: candidate > previous,
        )

    assert routed_sources == []


@pytest.mark.asyncio
async def test_startup_audit_fails_at_nonconfigurable_page_guard() -> None:
    pages_fetched = 0

    async def fetch_page(
        cursor: int | None,
        page_size: int,
    ) -> StartupAuditPage[int, int]:
        nonlocal pages_fetched
        del page_size
        pages_fetched += 1
        next_cursor = 1 if cursor is None else cursor + 1
        return StartupAuditPage(sources=(), next_cursor=next_cursor)

    async def route_source(source: int) -> None:
        del source

    with pytest.raises(
        StartupAuditPaginationError,
        match=rf"{STARTUP_AUDIT_PAGE_GUARD}-page bug guard",
    ):
        await audit_startup_source_family(
            family_name="provider_start",
            fetch_page=fetch_page,
            route_source=route_source,
            cursor_advances=lambda previous, candidate: candidate > previous,
        )

    assert pages_fetched == STARTUP_AUDIT_PAGE_GUARD
