from __future__ import annotations

from pathlib import Path

import pytest
from autoclaw.config import OpenClawSettings, Settings
from autoclaw.interfaces.cli.commands.config_view import REDACTED_VALUE, build_settings_payload


@pytest.mark.parametrize(
    "gateway_url",
    [
        "ws://gateway-user:gateway-secret@127.0.0.1:18789",
        "ws://gateway-user:gateway-secret@[::1",
    ],
)
def test_config_readback_redacts_openclaw_gateway_url_userinfo(
    tmp_path: Path,
    gateway_url: str,
) -> None:
    payload = build_settings_payload(
        Settings(
            openclaw=OpenClawSettings(
                enabled=True,
                gateway_url=gateway_url,
            )
        ),
        tmp_path / "config.toml",
    )

    assert payload["openclaw"]["gateway_url"] == REDACTED_VALUE
    assert "gateway-user" not in str(payload)
    assert "gateway-secret" not in str(payload)


def test_config_readback_retains_non_secret_openclaw_gateway_url(tmp_path: Path) -> None:
    payload = build_settings_payload(
        Settings(
            openclaw=OpenClawSettings(
                enabled=True,
                gateway_url="ws://127.0.0.1:18789",
            )
        ),
        tmp_path / "config.toml",
    )

    assert payload["openclaw"]["gateway_url"] == "ws://127.0.0.1:18789"
    assert "security" not in payload


def test_config_readback_redacts_database_password(tmp_path: Path) -> None:
    payload = build_settings_payload(
        Settings(database_url="postgresql+asyncpg://operator:secret@localhost/autoclaw"),
        tmp_path / "config.toml",
    )

    assert payload["database"]["url"] == ("postgresql+asyncpg://operator:***@localhost/autoclaw")
    assert "secret" not in str(payload)
