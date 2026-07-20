from autoclaw.main import app
from httpx import ASGITransport, AsyncClient


async def test_healthz() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:18125",
    ) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "autoclaw-api"}
