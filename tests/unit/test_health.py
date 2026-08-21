from httpx import ASGITransport, AsyncClient

from oh_my_subagents.main import app


async def test_healthz() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:18125",
    ) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "banksia-api"}


async def test_legacy_packaged_console_routes_remain_removed() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:18125",
    ) as client:
        responses = {
            path: await client.get(path)
            for path in (
                "/console/config",
                "/app-icon.png",
                "/site.webmanifest",
                "/assets/legacy-console.js",
            )
        }

    assert {path: response.status_code for path, response in responses.items()} == {
        "/console/config": 404,
        "/app-icon.png": 404,
        "/site.webmanifest": 404,
        "/assets/legacy-console.js": 404,
    }


async def test_product_routes_have_no_root_alias_and_unknown_api_stays_404() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:18125",
    ) as client:
        old_task_search = await client.get("/tasks")
        old_draft_create = await client.post("/workflow-drafts", json={})
        unknown_api = await client.get("/api/not-a-product-route")

    assert old_task_search.status_code == 404
    assert old_draft_create.status_code == 404
    assert unknown_api.status_code == 404
