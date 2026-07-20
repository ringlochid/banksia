from __future__ import annotations

from pathlib import Path


def is_packaged_web_console_available() -> bool:
    return get_packaged_web_console_assets_root().joinpath("index.html").is_file()


def get_packaged_web_console_assets_root() -> Path:
    return Path(__file__).resolve().parent / "assets"
