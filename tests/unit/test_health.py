from httpx import ASGITransport, AsyncClient

from banksia.main import app


async def test_healthz() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:18125",
    ) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "banksia-api"}


async def test_legacy_packaged_console_routes_are_not_mounted() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:18125",
    ) as client:
        responses = {
            path: await client.get(path)
            for path in (
                "/",
                "/console/config",
                "/app-icon.png",
                "/site.webmanifest",
                "/assets/legacy-console.js",
            )
        }

    assert {path: response.status_code for path, response in responses.items()} == {
        "/": 404,
        "/console/config": 404,
        "/app-icon.png": 404,
        "/site.webmanifest": 404,
        "/assets/legacy-console.js": 404,
    }
