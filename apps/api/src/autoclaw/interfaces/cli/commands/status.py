from __future__ import annotations

import argparse

from autoclaw.config import load_settings
from autoclaw.interfaces.cli.commands.config_view import redact_database_url
from autoclaw.interfaces.cli.commands.guided_presentation import emit_key_value_panel
from autoclaw.interfaces.cli.providers import collect_provider_statuses
from autoclaw.interfaces.cli.providers.inspection import providers_payload
from autoclaw.interfaces.cli.providers.presentation import emit_provider_status
from autoclaw.interfaces.cli.support import (
    coerce_path,
    command_env,
    print_json,
    service_provider_identity_env,
)


def cmd_status(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    with command_env(config_path=config_path):
        settings = load_settings()
        with service_provider_identity_env():
            providers = collect_provider_statuses(settings)
    default_provider = (
        settings.runtime.default_provider.value
        if settings.runtime.default_provider is not None
        else None
    )
    payload = {
        "ok": True,
        "config": {
            "path": str(config_path),
            "exists": config_path.is_file(),
            "data_dir": str(settings.data_dir),
        },
        "database": {
            "configured_url": redact_database_url(settings.database_url),
            "schema": "not_checked",
        },
        "service": {"status": "not_checked"},
        "default_provider": default_provider,
        "providers": providers_payload(providers),
    }
    if args.json:
        print_json(payload)
    else:
        emit_key_value_panel(
            "AutoClaw status",
            (
                (
                    "Config",
                    f"{config_path} ({'present' if config_path.is_file() else 'missing'})",
                ),
                ("Data", str(settings.data_dir)),
                ("Default provider", default_provider or "Not configured"),
                ("Database", "Not inspected by passive status"),
                ("Service", "Run autoclaw service status"),
            ),
        )
        emit_provider_status(providers)
    return 0


__all__ = ["cmd_status"]
