from __future__ import annotations

from pathlib import Path

from oh_my_subagents.config import (
    OperatorProvider,
    OperatorSettings,
    Settings,
)
from oh_my_subagents.interfaces.cli.commands.config_view import build_settings_payload


def test_config_readback_redacts_database_password(tmp_path: Path) -> None:
    payload = build_settings_payload(
        Settings(database_url="postgresql+asyncpg://operator:secret@localhost/oms"),
        tmp_path / "config.toml",
    )

    assert payload["database"]["url"] == ("postgresql+asyncpg://operator:***@localhost/oms")
    assert "secret" not in str(payload)


def test_config_readback_includes_nonsecret_operator_selection(tmp_path: Path) -> None:
    payload = build_settings_payload(
        Settings(
            operator=OperatorSettings(
                provider=OperatorProvider.CODEX,
                model="gpt-operator",
                effort="high",
            )
        ),
        tmp_path / "config.toml",
    )

    assert payload["operator"] == {
        "provider": "codex",
        "model": "gpt-operator",
        "effort": "high",
    }
