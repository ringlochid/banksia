from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles


def register_web_console_routes(
    app: FastAPI,
    *,
    assets_root: Path | None = None,
) -> bool:
    """Register only the product-owned Console routes when a build is present."""

    root = assets_root or Path(str(files("banksia.interfaces.web_console").joinpath("assets")))
    index_path = root / "index.html"
    static_root = root / "assets"
    if not index_path.is_file() or not static_root.is_dir():
        app.state.web_console_available = False
        return False

    async def workflow_library() -> FileResponse:
        return FileResponse(index_path)

    async def workflow_studio(workflow_id: str) -> FileResponse:
        del workflow_id
        return FileResponse(index_path)

    async def run_library() -> FileResponse:
        return FileResponse(index_path)

    async def run_start() -> FileResponse:
        return FileResponse(index_path)

    async def run_studio(task_id: str) -> FileResponse:
        del task_id
        return FileResponse(index_path)

    async def console_root() -> RedirectResponse:
        return RedirectResponse("/workflows")

    app.add_api_route(
        "/",
        console_root,
        methods=["GET"],
        include_in_schema=False,
        name="console-root",
    )
    app.add_api_route(
        "/workflows",
        workflow_library,
        methods=["GET"],
        include_in_schema=False,
        name="console-workflow-library",
    )
    app.add_api_route(
        "/workflows/{workflow_id}",
        workflow_studio,
        methods=["GET"],
        include_in_schema=False,
        name="console-workflow-studio",
    )
    app.add_api_route(
        "/runs",
        run_library,
        methods=["GET"],
        include_in_schema=False,
        name="console-run-library",
    )
    app.add_api_route(
        "/runs/new",
        run_start,
        methods=["GET"],
        include_in_schema=False,
        name="console-run-start",
    )
    app.add_api_route(
        "/runs/{task_id}",
        run_studio,
        methods=["GET"],
        include_in_schema=False,
        name="console-run-studio",
    )
    app.mount(
        "/assets",
        StaticFiles(directory=static_root, check_dir=True),
        name="console-assets",
    )
    app.state.web_console_available = True
    return True
