from __future__ import annotations

import os
from io import StringIO

import pytest
from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.interfaces.cli.commands.guided_presentation import (
    emit_provider_choices,
    emit_wizard_header,
)
from autoclaw.interfaces.cli.context import CliContext
from autoclaw.interfaces.cli.providers.contracts import (
    ProviderCheckOutcome,
    ProviderCheckSnapshot,
    ProviderStatusSnapshot,
)
from autoclaw.interfaces.cli.providers.presentation import (
    emit_provider_check,
    emit_provider_status,
)
from autoclaw.interfaces.cli.theme import build_rich_theme
from autoclaw.runtime.providers import ProviderCheckAxisStatus
from rich.console import Console


def test_provider_status_and_check_use_rich_semantic_panels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _force_rich_console(monkeypatch)
    status = ProviderStatusSnapshot.model_validate(
        {
            "kind": "codex",
            "product_status": "managed_target",
            "integration_available": True,
            "configured": True,
            "is_default": True,
            "configuration_fields_present": True,
            "service_identity": "tester",
            "native_home": "/tmp/codex-home",
            "route": {"enabled": True},
        }
    )
    check = ProviderCheckSnapshot(
        kind=ProviderKind.CODEX,
        outcome=ProviderCheckOutcome.READY,
        is_ready=True,
        service_identity="tester",
        native_home="/tmp/codex-home",
        authentication=ProviderCheckAxisStatus.PASSED,
        reachability=ProviderCheckAxisStatus.NOT_CHECKED,
        detail="codex_available",
    )

    emit_provider_status((status,))
    emit_provider_check(check)

    rendered = output.getvalue()
    assert "\x1b[" in rendered
    assert "Provider status" in rendered
    assert "Codex provider check" in rendered
    assert "Configured" in rendered
    assert "Found" in rendered
    assert "Not Tested" in rendered
    assert "╭" in rendered


def test_guided_setup_uses_rich_hierarchy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _force_rich_console(monkeypatch)

    emit_wizard_header("provider setup", "Choose and verify a provider route.")
    emit_provider_choices()

    rendered = output.getvalue()
    assert "\x1b[" in rendered
    assert "AutoClaw" in rendered
    assert "Provider routes" in rendered
    assert "Managed" in rendered
    assert "Experimental" in rendered
    assert "╭" in rendered


def test_rich_console_width_is_bounded_on_wide_terminals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(CliContext, "rich_enabled", lambda _self: True)
    monkeypatch.setattr(
        "autoclaw.interfaces.cli.context.shutil.get_terminal_size",
        lambda: os.terminal_size((240, 40)),
    )

    assert CliContext().console().width == 110


def _force_rich_console(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=True,
        color_system="truecolor",
        width=100,
        theme=build_rich_theme(),
    )
    monkeypatch.setattr(CliContext, "rich_enabled", lambda _self: True)
    monkeypatch.setattr(CliContext, "console", lambda _self, **_kwargs: console)
    return output
