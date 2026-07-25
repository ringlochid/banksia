from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI

from banksia.interfaces.web_console import register_web_console_routes


async def test_explicit_console_routes_serve_only_packaged_pages_and_assets(
    tmp_path: Path,
) -> None:
    assets_root = tmp_path / "console"
    asset_directory = assets_root / "assets"
    asset_directory.mkdir(parents=True)
    (assets_root / "index.html").write_text(
        "<!doctype html><title>Banksia Console</title>",
        encoding="utf-8",
    )
    (asset_directory / "app.js").write_text(
        "document.body.dataset.ready = 'true';",
        encoding="utf-8",
    )
    app = FastAPI()

    assert register_web_console_routes(app, assets_root=assets_root)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        root = await client.get("/")
        library = await client.get("/workflows")
        studio = await client.get("/workflows/reviewed-delivery")
        runs = await client.get("/runs")
        asset = await client.get("/assets/app.js")
        unknown_browser = await client.get("/not-a-console-route")
        unknown_asset = await client.get("/assets/missing.js")
        unknown_api = await client.get("/api/not-a-product-route")

    assert root.status_code == 307
    assert root.headers["location"] == "/workflows"
    for response in (library, studio, runs):
        assert response.status_code == 200
        assert "Banksia Console" in response.text
    assert asset.status_code == 200
    assert "dataset.ready" in asset.text
    assert unknown_browser.status_code == 404
    assert unknown_asset.status_code == 404
    assert unknown_api.status_code == 404


def test_console_routes_are_omitted_when_the_build_is_not_staged(
    tmp_path: Path,
) -> None:
    app = FastAPI()

    assert not register_web_console_routes(app, assets_root=tmp_path / "missing")
    assert app.state.web_console_available is False
    assert all(
        getattr(route, "path", None) not in {"/workflows", "/runs", "/assets"}
        for route in app.routes
    )
