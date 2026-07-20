from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSOLE_DIST_DIR = REPO_ROOT / "apps" / "console" / "dist"
PACKAGED_CONSOLE_ASSETS_DIR = (
    REPO_ROOT / "apps" / "api" / "src" / "autoclaw" / "interfaces" / "web_console" / "assets"
)
_DEVELOPMENT_ONLY_ASSET_NAMES = frozenset({"mockServiceWorker.js"})


def main() -> int:
    index_path = CONSOLE_DIST_DIR / "index.html"
    if not index_path.is_file():
        raise SystemExit(
            "Console dist is missing. Run `make console-build` before syncing package assets."
        )

    if PACKAGED_CONSOLE_ASSETS_DIR.exists():
        shutil.rmtree(PACKAGED_CONSOLE_ASSETS_DIR)
    shutil.copytree(
        CONSOLE_DIST_DIR,
        PACKAGED_CONSOLE_ASSETS_DIR,
        ignore=_exclude_development_assets,
    )
    return 0


def _exclude_development_assets(_directory: str, names: list[str]) -> set[str]:
    return {
        name for name in names if name in _DEVELOPMENT_ONLY_ASSET_NAMES or name.endswith(".map")
    }


if __name__ == "__main__":
    raise SystemExit(main())
