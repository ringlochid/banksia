from __future__ import annotations

import argparse
from pathlib import Path

import autoclaw.interfaces.cli as cli
from autoclaw.config import get_settings
from autoclaw.main import create_app
from autoclaw.persistence.session import dispose_db_engine
from httpx import ASGITransport, AsyncClient


async def test_readyz_uses_real_database(tmp_path: Path) -> None:
    config_path = tmp_path / "autoclaw-config.toml"
    data_dir = tmp_path / "autoclaw-data"

    try:
        await cli.cmd_init(
            argparse.Namespace(
                config=str(config_path),
                data_dir=str(data_dir),
                database_url=None,
                host="127.0.0.1",
                port=8123,
                log_level="INFO",
                force=True,
                skip_db_upgrade=False,
                json=False,
            )
        )

        with cli.command_env(config_path=config_path):
            get_settings.cache_clear()
            app = create_app()
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://127.0.0.1:8123",
            ) as client:
                response = await client.get("/readyz")
    finally:
        await dispose_db_engine()

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "autoclaw-api"}
