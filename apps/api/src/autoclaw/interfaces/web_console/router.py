from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from autoclaw.interfaces.web_console import (
    get_packaged_web_console_assets_root,
    is_packaged_web_console_available,
)

web_console_router = APIRouter(include_in_schema=False)
_NO_STORE_HEADERS = {"Cache-Control": "no-store"}


class WebConsoleRuntimeConfig(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True, serialize_by_alias=True)

    api_base_url: str = Field(serialization_alias="apiBaseUrl")


def mount_packaged_web_console(app: FastAPI) -> None:
    if not is_packaged_web_console_available():
        return

    assets_root = get_packaged_web_console_assets_root()
    nested_assets_root = assets_root / "assets"
    if nested_assets_root.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=nested_assets_root),
            name="web-console-assets",
        )
    app.include_router(web_console_router)


@web_console_router.get("/console/config")
async def get_web_console_runtime_config(request: Request) -> JSONResponse:
    runtime_config = WebConsoleRuntimeConfig(
        api_base_url=_request_origin(request),
    )
    return JSONResponse(
        content=runtime_config.model_dump(mode="json", by_alias=True),
        headers=_NO_STORE_HEADERS,
    )


@web_console_router.get("/")
@web_console_router.get("/tasks")
@web_console_router.get("/tasks/{console_path:path}")
@web_console_router.get("/definitions")
@web_console_router.get("/definitions/{console_path:path}")
@web_console_router.get("/task-start")
async def get_web_console_index(console_path: str = "") -> FileResponse:
    del console_path
    return _packaged_asset_response("index.html", media_type="text/html")


@web_console_router.get("/app-icon.png")
async def get_web_console_app_icon() -> FileResponse:
    return _packaged_asset_response("app-icon.png", media_type="image/png")


@web_console_router.get("/site.webmanifest")
async def get_web_console_manifest() -> FileResponse:
    return _packaged_asset_response("site.webmanifest", media_type="application/manifest+json")


def _packaged_asset_response(relative_path: str, *, media_type: str) -> FileResponse:
    asset_path = get_packaged_web_console_assets_root() / relative_path
    if not _is_packaged_asset_file(asset_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(asset_path, media_type=media_type)


def _is_packaged_asset_file(path: Path) -> bool:
    assets_root = get_packaged_web_console_assets_root().resolve()
    resolved_path = path.resolve()
    return resolved_path.is_file() and resolved_path.is_relative_to(assets_root)


def _request_origin(request: Request) -> str:
    return str(request.base_url).rstrip("/")
