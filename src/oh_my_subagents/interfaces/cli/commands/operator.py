from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import click

from oh_my_subagents.config import OperatorProvider, OperatorSettings
from oh_my_subagents.interfaces.cli.commands.presentation import (
    emit_completion,
    emit_key_value_panel,
    emit_warning,
    emit_wizard_header,
)
from oh_my_subagents.interfaces.cli.commands.provider_setup import (
    clone_namespace,
    collect_configured_provider_check,
    guide_specific_provider,
)
from oh_my_subagents.interfaces.cli.errors import CliPrerequisiteError
from oh_my_subagents.interfaces.cli.providers import (
    OperatorProviderRouteNotConfiguredError,
    OperatorSelectionMutationResult,
    OperatorSelectionRequest,
    OperatorSelectionSnapshot,
    disable_operator_selection,
    is_operator_provider_persisted,
    read_operator_selection,
    save_operator_selection,
)
from oh_my_subagents.interfaces.cli.providers.contracts import ProviderCheckSnapshot
from oh_my_subagents.interfaces.cli.providers.presentation import emit_provider_check
from oh_my_subagents.interfaces.cli.support import (
    coerce_path,
    print_json,
)
from oh_my_subagents.providers import ProviderKind

_OPERATOR_CHOICES = click.Choice(("Codex", "Claude"), case_sensitive=False)
_OPTIONAL_OPERATOR_CHOICES = click.Choice(
    ("Codex", "Claude", "Not now"),
    case_sensitive=False,
)


def cmd_operator_setup(args: argparse.Namespace) -> int:
    """Persist one explicit Operator selection without contacting a provider."""

    config_path = _require_initialized_config(args.config)
    if args.provider is None:
        raise click.UsageError(
            "--provider is required when Operator setup cannot prompt. Choose codex or claude."
        )
    request = _operator_request_from_args(args)
    result = _save_operator_or_raise(config_path, request)
    _emit_operator_mutation(
        "Operator setup complete",
        config_path,
        result,
        is_json_output=args.json,
    )
    return 0


def cmd_operator_status(args: argparse.Namespace) -> int:
    """Render passive persisted and effective Operator configuration."""

    config_path = _require_initialized_config(args.config)
    selection = read_operator_selection(config_path)
    if args.json:
        print_json(_operator_payload(config_path, selection))
    else:
        _emit_operator_status(config_path, selection)
    return 0


def cmd_operator_disable(args: argparse.Namespace) -> int:
    """Idempotently remove the persisted Operator selection."""

    config_path = _require_initialized_config(args.config)
    result = disable_operator_selection(config_path)
    _emit_operator_mutation(
        "Operator disabled",
        config_path,
        result,
        is_json_output=args.json,
        should_warn_environment_override=False,
    )
    if result.selection.is_environment_override and not args.json:
        emit_warning(
            "An environment override still selects Operator. Remove the "
            "OMS_OPERATOR__* override to disable it effectively."
        )
    return 0


def guide_operator_setup(args: argparse.Namespace) -> int:
    """Guide focused Operator configuration and diagnose its selected route."""

    config_path = _require_initialized_config(args.config)
    emit_wizard_header(
        "Operator setup",
        "Choose the provider for Oh My Subagents's separate workflow and run assistant.",
    )
    selection = read_operator_selection(config_path)
    _emit_operator_status(
        config_path,
        selection,
        should_emit_next_action=False,
    )
    selected = _select_operator_provider(
        args,
        is_optional=False,
        default_provider=selection.persisted.provider,
    )
    if selected is None:
        emit_warning("Operator setup cancelled. No Operator changes were made.")
        return 0
    return _guide_selected_operator(
        args,
        config_path,
        selected,
        current=selection.persisted,
        provider_checks={},
        should_emit_summary=True,
    )


def guide_optional_operator_setup(
    args: argparse.Namespace,
    *,
    should_emit_summary: bool = True,
    provider_checks: Mapping[ProviderKind, ProviderCheckSnapshot] | None = None,
) -> int:
    """Offer one optional first-run Operator choice when none is effective."""

    config_path = _require_initialized_config(args.config)
    current = read_operator_selection(config_path)
    if current.effective.provider is not None:
        return 0

    emit_wizard_header(
        "Operator setup",
        "Optional: choose the provider Oh My Subagents uses to draft workflows and operate runs.",
    )
    selected = _select_operator_provider(
        args,
        is_optional=True,
        default_provider=None,
    )
    if selected is None:
        emit_warning("Operator was not configured. You can add it later with 'oms operator setup'.")
        return 0
    return _guide_selected_operator(
        args,
        config_path,
        selected,
        current=current.persisted,
        provider_checks=provider_checks or {},
        should_emit_summary=should_emit_summary,
    )


def _guide_selected_operator(
    args: argparse.Namespace,
    config_path: Path,
    provider: OperatorProvider,
    *,
    current: OperatorSettings,
    provider_checks: Mapping[ProviderKind, ProviderCheckSnapshot],
    should_emit_summary: bool,
) -> int:
    provider_kind = ProviderKind(provider.value)
    provider_check = provider_checks.get(provider_kind)
    if not is_operator_provider_persisted(config_path, provider):
        if not click.confirm(
            f"{provider.value.title()} is not configured. Configure it now?",
            default=True,
        ):
            emit_warning(
                f"Operator was not changed. Run 'oms providers configure "
                f"{provider.value}', then rerun 'oms operator setup'."
            )
            return 0
        provider_check = guide_specific_provider(
            _provider_setup_args(args, provider),
            config_path=config_path,
            provider=provider_kind,
        )

    model, effort = _prompt_operator_overrides(
        args,
        current=current,
        provider=provider,
    )
    result = _save_operator_or_raise(
        config_path,
        OperatorSelectionRequest(
            provider=provider,
            model=model,
            effort=effort,
        ),
    )
    if provider_check is None:
        if (
            not result.is_changed
            and should_emit_summary
            and not click.confirm(
                f"Check {provider.value.title()} readiness now?",
                default=True,
            )
        ):
            _emit_operator_setup_result(config_path, result)
            return 0
        provider_check = collect_configured_provider_check(
            config_path,
            provider_kind,
        )
        emit_provider_check(
            provider_check,
            is_compact=not should_emit_summary,
        )
    if should_emit_summary:
        _emit_operator_setup_result(
            config_path,
            result,
            next_action=(
                "oms serve" if provider_check.is_ready is True else result.selection.next_action
            ),
        )
    return 0 if provider_check.is_ready is True else 1


def _select_operator_provider(
    args: argparse.Namespace,
    *,
    is_optional: bool,
    default_provider: OperatorProvider | None,
) -> OperatorProvider | None:
    raw_provider = getattr(args, "provider", None)
    if raw_provider is not None:
        return OperatorProvider(raw_provider)
    choices = _OPTIONAL_OPERATOR_CHOICES if is_optional else _OPERATOR_CHOICES
    selected = str(
        click.prompt(
            "Operator provider",
            type=choices,
            default=(
                "Not now"
                if is_optional
                else (default_provider.value.title() if default_provider is not None else "Codex")
            ),
        )
    ).casefold()
    if selected == "not now":
        return None
    return OperatorProvider(selected)


def _prompt_operator_overrides(
    args: argparse.Namespace,
    *,
    current: OperatorSettings,
    provider: OperatorProvider,
) -> tuple[str | None, str | None]:
    supplied_model = getattr(args, "model", None)
    supplied_effort = getattr(args, "effort", None)
    if supplied_model is not None or supplied_effort is not None:
        return supplied_model, supplied_effort
    is_same_provider = current.provider == provider
    has_saved_overrides = is_same_provider and (
        current.model is not None or current.effort is not None
    )
    if not click.confirm(
        (
            "Change the saved Operator model or reasoning effort?"
            if has_saved_overrides
            else "Set an Operator-specific model or reasoning effort?"
        ),
        default=False,
    ):
        if is_same_provider:
            return current.model, current.effort
        return None, None
    return (
        _prompt_operator_override(
            "Operator model",
            current=current.model if is_same_provider else None,
        ),
        _prompt_operator_override(
            "Operator effort",
            current=current.effort if is_same_provider else None,
        ),
    )


def _prompt_operator_override(
    label: str,
    *,
    current: str | None,
) -> str | None:
    value = str(
        click.prompt(
            f"{label} ('-' for provider default)",
            default=current or "",
            show_default=current is not None,
        )
    ).strip()
    return None if value in {"", "-"} else value


def _provider_setup_args(
    args: argparse.Namespace,
    provider: OperatorProvider,
) -> argparse.Namespace:
    return clone_namespace(
        args,
        provider=provider.value,
        model=None,
        effort=None,
    )


def _emit_operator_setup_result(
    config_path: Path,
    result: OperatorSelectionMutationResult,
    *,
    next_action: str | None = None,
) -> None:
    _emit_operator_mutation(
        ("Operator setup complete" if result.is_changed else "Operator already configured"),
        config_path,
        result,
        is_json_output=False,
        should_include_changed=False,
        next_action=next_action,
    )


def _operator_request_from_args(
    args: argparse.Namespace,
) -> OperatorSelectionRequest:
    return OperatorSelectionRequest(
        provider=OperatorProvider(args.provider),
        model=args.model,
        effort=args.effort,
    )


def _save_operator_or_raise(
    config_path: Path,
    request: OperatorSelectionRequest,
) -> OperatorSelectionMutationResult:
    try:
        return save_operator_selection(config_path, request)
    except OperatorProviderRouteNotConfiguredError as exc:
        provider = exc.provider.value
        raise CliPrerequisiteError(
            f"{provider.title()} must be configured before Operator can use it. "
            f"Run 'oms providers configure {provider}', then rerun "
            f"'oms operator setup --provider {provider}'.",
            kind="operator_provider_not_configured",
            title="Operator setup needs a provider route",
            hint=(
                f"Run 'oms providers configure {provider}', then rerun "
                f"'oms operator setup --provider {provider}'."
            ),
        ) from exc


def _emit_operator_mutation(
    title: str,
    config_path: Path,
    result: OperatorSelectionMutationResult,
    *,
    is_json_output: bool,
    should_warn_environment_override: bool = True,
    should_include_changed: bool = True,
    next_action: str | None = None,
) -> None:
    payload = {
        **_operator_payload(config_path, result.selection),
        "changed": result.is_changed,
    }
    if is_json_output:
        print_json(payload)
        return
    persisted = result.selection.persisted
    rows = [
        ("Provider", _operator_provider_text(persisted.provider)),
        ("Model", persisted.model or "provider default"),
        ("Effort", persisted.effort or "provider default"),
    ]
    if should_include_changed:
        rows.append(("Changed", "yes" if result.is_changed else "no"))
    emit_completion(
        title,
        rows,
        next_action=next_action or result.selection.next_action,
    )
    if should_warn_environment_override and result.selection.is_environment_override:
        emit_warning("OMS_OPERATOR__* environment settings override the saved selection.")


def _emit_operator_status(
    config_path: Path,
    selection: OperatorSelectionSnapshot,
    *,
    should_emit_next_action: bool = True,
) -> None:
    persisted = selection.persisted
    effective = selection.effective
    rows = [
        ("Config", str(config_path)),
        ("Saved provider", _operator_provider_text(persisted.provider)),
        ("Saved model", persisted.model or "provider default"),
        ("Saved effort", persisted.effort or "provider default"),
        (
            "Provider route",
            "configured" if selection.is_provider_route_configured else "not configured",
        ),
    ]
    if selection.is_environment_override:
        rows.extend(
            (
                (
                    "Effective provider",
                    f"{_operator_provider_text(effective.provider)} (environment override)",
                ),
                ("Effective model", effective.model or "provider default"),
                ("Effective effort", effective.effort or "provider default"),
            )
        )
    emit_key_value_panel("Operator configuration", rows)
    if should_emit_next_action:
        click.echo(f"Next: {selection.next_action}")


def _operator_payload(
    config_path: Path,
    selection: OperatorSelectionSnapshot,
) -> dict[str, Any]:
    return {
        "ok": True,
        "config_path": str(config_path),
        "operator": {
            "persisted": selection.persisted.model_dump(mode="json"),
            "effective": selection.effective.model_dump(mode="json"),
            "environment_override": selection.is_environment_override,
            "provider_route_configured": selection.is_provider_route_configured,
        },
        "next_action": selection.next_action,
    }


def _operator_provider_text(provider: OperatorProvider | None) -> str:
    return provider.value if provider is not None else "none"


def _require_initialized_config(raw_config_path: str | Path) -> Path:
    config_path = coerce_path(raw_config_path)
    if not config_path.is_file():
        raise click.UsageError(
            f"Oh My Subagents is not initialized at {config_path}. Run 'oms init' first."
        )
    return config_path


__all__ = [
    "cmd_operator_disable",
    "cmd_operator_setup",
    "cmd_operator_status",
    "guide_operator_setup",
    "guide_optional_operator_setup",
]
