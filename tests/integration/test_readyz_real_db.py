from __future__ import annotations

import argparse
from pathlib import Path

from httpx import ASGITransport, AsyncClient

import banksia.interfaces.cli as cli
from banksia.config import get_settings
from banksia.main import create_app
from banksia.persistence.session import dispose_db_engine


async def test_readyz_uses_real_database(tmp_path: Path) -> None:
    config_path = tmp_path / "banksia-config.toml"
    data_dir = tmp_path / "banksia-data"

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
    assert response.json() == {"status": "ready", "service": "banksia-api"}
