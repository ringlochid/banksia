from __future__ import annotations

import json

from autoclaw.interfaces.http.router import api_router
from fastapi import FastAPI


def build_openapi_document() -> dict[str, object]:
    app = FastAPI(title="AutoClaw API", version="0.0.0")
    app.include_router(api_router)
    return app.openapi()


def main() -> None:
    print(json.dumps(build_openapi_document(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
