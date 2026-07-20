from __future__ import annotations

from collections.abc import Sequence

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from autoclaw.definitions.contracts.workflow import ProviderKind
from autoclaw.interfaces.cli.context import CliContext
from autoclaw.interfaces.cli.providers.identity import authentication_method_label
from autoclaw.runtime.providers import ProviderAuthenticationMethod, ProviderCheckAxisStatus

from .contracts import (
    ProviderCheckOutcome,
    ProviderCheckSnapshot,
    ProviderConfigurationSnapshot,
    ProviderDefinitionSnapshot,
    ProviderIdentityOutcome,
    ProviderIdentitySnapshot,
    ProviderProductStatus,
    ProviderStatusSnapshot,
)


def emit_provider_definitions(
    definitions: Sequence[ProviderDefinitionSnapshot],
    *,
    context: CliContext | None = None,
) -> None:
    runtime = context or CliContext()
    if not runtime.rich_enabled():
        print("AutoClaw provider integrations")
        for definition in definitions:
            availability = "available" if definition.is_integration_available else "unavailable"
            print(
                f"{definition.kind.value}: {definition.product_status.value}; "
                f"{availability}; setup owner: {definition.setup_owner}"
            )
        return

    table = Table(box=box.SIMPLE_HEAD, header_style="heading", pad_edge=False)
    table.add_column("Provider", style="bold", no_wrap=True)
    table.add_column("Lane", no_wrap=True)
    table.add_column("Local", no_wrap=True)
    table.add_column("Ownership", overflow="fold")
    for definition in definitions:
        table.add_row(
            provider_display_name(definition.kind),
            _product_status_text(definition.product_status),
            _styled_state(
                "Available" if definition.is_integration_available else "Unavailable",
                "success" if definition.is_integration_available else "error",
            ),
            _setup_owner_label(definition.setup_owner),
        )
    runtime.console().print(
        Panel(
            table,
            title="Provider integrations",
            title_align="left",
            border_style="accent",
            padding=(0, 1),
        )
    )


def emit_provider_configuration(
    snapshot: ProviderConfigurationSnapshot,
    *,
    context: CliContext | None = None,
) -> None:
    runtime = context or CliContext()
    if not runtime.rich_enabled():
        print(f"Configured provider: {snapshot.provider.value}")
        print(f"Default provider: {snapshot.default_provider.value}")
        print(f"Default changed: {str(snapshot.is_default_changed).lower()}")
        if snapshot.product_status is ProviderProductStatus.EXPERIMENTAL:
            print("Product status: experimental selectable lane")
        return
    facts = Table.grid(padding=(0, 2))
    facts.add_column(style="muted", no_wrap=True)
    facts.add_column(overflow="fold")
    facts.add_row("Provider", provider_display_name(snapshot.provider))
    facts.add_row("Default", provider_display_name(snapshot.default_provider))
    facts.add_row("Default changed", "Yes" if snapshot.is_default_changed else "No")
    facts.add_row("Lane", _product_status_text(snapshot.product_status))
    runtime.console().print(
        Panel(
            Group(Text("✓  Route saved", style="bold success"), Text(), facts),
            title="Provider configuration",
            title_align="left",
            border_style="success",
            padding=(0, 1),
        )
    )


def emit_provider_identity(
    snapshot: ProviderIdentitySnapshot,
    *,
    context: CliContext | None = None,
) -> None:
    runtime = context or CliContext()
    if not runtime.rich_enabled():
        print(f"Provider {snapshot.action}: {snapshot.provider.value}")
        print(f"Outcome: {snapshot.outcome.value}")
        print(f"Detail: {snapshot.detail}")
        if snapshot.authentication_method is not None:
            print(
                "Authentication: "
                f"{_display_authentication_method_label(snapshot.authentication_method)}"
            )
        print(f"Identity: {snapshot.service_identity}")
        print(f"Native home: {snapshot.native_home}")
        if snapshot.outcome is ProviderIdentityOutcome.SUCCEEDED and snapshot.action == "login":
            print(f"Next: autoclaw providers check {snapshot.provider.value}")
        return

    style = {
        ProviderIdentityOutcome.SUCCEEDED: "success",
        ProviderIdentityOutcome.PARTIAL: "warn",
        ProviderIdentityOutcome.NOT_INSTALLED: "error",
        ProviderIdentityOutcome.FAILED: "error",
    }[snapshot.outcome]
    facts = Table.grid(padding=(0, 2))
    facts.add_column(style="muted", no_wrap=True)
    facts.add_column(overflow="fold")
    facts.add_row("Provider", provider_display_name(snapshot.provider))
    facts.add_row("Action", snapshot.action.title())
    facts.add_row("Result", snapshot.outcome.value.replace("_", " ").title())
    if snapshot.authentication_method is not None:
        facts.add_row(
            "Method",
            _display_authentication_method_label(snapshot.authentication_method),
        )
    facts.add_row("Runtime identity", snapshot.service_identity)
    facts.add_row("Native home", snapshot.native_home)
    facts.add_row("Detail", snapshot.detail)
    runtime.console().print(
        Panel(
            facts,
            title=f"{provider_display_name(snapshot.provider)} provider {snapshot.action}",
            title_align="left",
            border_style=style,
            padding=(0, 1),
        )
    )
    if snapshot.outcome is ProviderIdentityOutcome.SUCCEEDED and snapshot.action == "login":
        runtime.console().print(
            Text.assemble(
                ("Next  ", "muted"),
                (f"autoclaw providers check {snapshot.provider.value}", "accent"),
            )
        )


def emit_provider_status(
    statuses: Sequence[ProviderStatusSnapshot],
    *,
    context: CliContext | None = None,
) -> None:
    runtime = context or CliContext()
    if runtime.rich_enabled():
        _emit_rich_provider_status(statuses, runtime)
        return
    _emit_plain_provider_status(statuses)


def emit_provider_check(
    snapshot: ProviderCheckSnapshot,
    *,
    context: CliContext | None = None,
    is_compact: bool = False,
) -> None:
    runtime = context or CliContext()
    if runtime.rich_enabled():
        _emit_rich_provider_check(snapshot, runtime, is_compact=is_compact)
        return
    _emit_plain_provider_check(snapshot, is_compact=is_compact)


def provider_display_name(provider: ProviderKind) -> str:
    if provider is ProviderKind.OPENCLAW:
        return "OpenClaw"
    return provider.value.title()


def _emit_rich_provider_status(
    statuses: Sequence[ProviderStatusSnapshot],
    context: CliContext,
) -> None:
    table = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        header_style="heading",
        pad_edge=False,
        row_styles=("", "dim"),
    )
    table.add_column("Provider", no_wrap=True)
    table.add_column("Route", no_wrap=True)
    table.add_column("Integration", no_wrap=True)
    table.add_column("Support", no_wrap=True)
    for status in statuses:
        provider = Text(provider_display_name(status.kind), style="bold")
        if status.is_default:
            provider.append("  default", style="accent")
        provider.append(f"\n{status.native_home}", style="muted")
        route = _styled_state(
            "Configured" if status.is_configured else "Not configured",
            "success" if status.is_configured else "muted",
        )
        integration = _styled_state(
            "Available" if status.is_integration_available else "Unavailable",
            "success" if status.is_integration_available else "error",
        )
        support = _product_status_text(status.product_status)
        table.add_row(provider, route, integration, support)

    body = Group(
        table,
        Text.assemble(
            ("Runtime identity  ", "muted"),
            (statuses[0].service_identity if statuses else "unknown", "bold"),
        ),
    )
    context.console().print(
        Panel(
            body,
            title="Provider status",
            title_align="left",
            border_style="accent",
            padding=(0, 1),
        )
    )
    _emit_rich_status_next_step(statuses, context)


def _emit_plain_provider_status(statuses: Sequence[ProviderStatusSnapshot]) -> None:
    print("Provider status")
    for status in statuses:
        suffix = " (default)" if status.is_default else ""
        print(f"{provider_display_name(status.kind)}{suffix}")
        print(f"  Route: {'configured' if status.is_configured else 'not configured'}")
        print(f"  Integration: {'available' if status.is_integration_available else 'unavailable'}")
        print(f"  Support: {_product_status_label(status.product_status)}")
        print(f"  Identity: {status.service_identity}")
        print(f"  Native home: {status.native_home}")
    print("Local configuration only. Verify readiness with:")
    print(f"  {_provider_status_next_command(statuses)}")


def _emit_rich_status_next_step(
    statuses: Sequence[ProviderStatusSnapshot],
    context: CliContext,
) -> None:
    note = Text()
    note.append("Local configuration only. ", style="muted")
    note.append("Verify readiness with  ")
    note.append(_provider_status_next_command(statuses), style="accent")
    context.console().print(note)


def _provider_status_next_command(statuses: Sequence[ProviderStatusSnapshot]) -> str:
    configured = [status for status in statuses if status.is_configured]
    if len(configured) == 1:
        return f"autoclaw providers check {configured[0].kind.value}"
    if len(configured) > 1:
        return "autoclaw providers check <provider>"
    if len(statuses) == 1:
        return f"autoclaw providers configure {statuses[0].kind.value}"
    return "autoclaw setup"


def _emit_rich_provider_check(
    snapshot: ProviderCheckSnapshot,
    context: CliContext,
    *,
    is_compact: bool,
) -> None:
    result_text, result_style, border_style = _check_result_style(snapshot)
    summary = Text()
    summary.append("✓ " if snapshot.is_ready is True else "! ", style=result_style)
    summary.append(result_text, style=f"bold {result_style}")

    facts = Table.grid(padding=(0, 2))
    facts.add_column(style="muted", no_wrap=True)
    facts.add_column(overflow="fold")
    facts.add_row("Credential", _credential_axis_text(snapshot.authentication))
    if snapshot.authentication_method is not None:
        facts.add_row("Method", _authentication_method_text(snapshot.authentication_method))
    facts.add_row("Reachability", _reachability_axis_text(snapshot.reachability))
    if not is_compact:
        facts.add_row("Runtime identity", Text(snapshot.service_identity))
        facts.add_row("Native home", Text(snapshot.native_home))
        facts.add_row("Diagnostic", Text(snapshot.detail, style="muted"))

    followup = None if is_compact else _rich_check_followup(snapshot)
    body = (
        Group(summary, Text(), facts)
        if followup is None
        else Group(summary, Text(), facts, Text(), followup)
    )
    context.console().print(
        Panel(
            body,
            title=f"{provider_display_name(snapshot.kind)} provider check",
            title_align="left",
            border_style=border_style,
            padding=(0, 1),
        )
    )


def _emit_plain_provider_check(
    snapshot: ProviderCheckSnapshot,
    *,
    is_compact: bool,
) -> None:
    result_text, _, _ = _check_result_style(snapshot)
    print(f"{provider_display_name(snapshot.kind)} provider check")
    print(f"  Result: {result_text.casefold()}")
    print(f"  Credential: {_credential_axis_label(snapshot.authentication)}")
    if snapshot.authentication_method is not None:
        print(f"  Method: {_display_authentication_method_label(snapshot.authentication_method)}")
    print(f"  Reachability: {_reachability_axis_label(snapshot.reachability)}")
    if is_compact:
        return
    print(f"  Runtime identity: {snapshot.service_identity}")
    print(f"  Native home: {snapshot.native_home}")
    print(f"  Diagnostic: {snapshot.detail}")
    if snapshot.limitations:
        print("Notes:")
        for limitation in snapshot.limitations:
            print(f"  - {limitation}")
    next_step = _provider_check_next_step(snapshot)
    if next_step is not None:
        print(f"Next: {next_step}")
    elif _has_unchecked_axis(snapshot):
        print("No model request was sent; live provider access is exercised by the first task.")


def _rich_check_followup(snapshot: ProviderCheckSnapshot) -> Group | None:
    parts: list[Text | Table] = []
    if snapshot.limitations:
        notes = Table.grid(padding=(0, 1))
        notes.add_column(style="accent", no_wrap=True)
        notes.add_column(style="muted", overflow="fold")
        for limitation in snapshot.limitations:
            notes.add_row("•", limitation)
        parts.extend((Text("Notes", style="heading"), notes))
    next_step = _provider_check_next_step(snapshot)
    if next_step is not None:
        if parts:
            parts.append(Text())
        parts.append(Text.assemble(("Next  ", "muted"), (next_step, "accent")))
    elif _has_unchecked_axis(snapshot):
        if parts:
            parts.append(Text())
        parts.append(
            Text(
                "No model request was sent; live provider access is exercised by the first task.",
                style="muted",
            )
        )
    return Group(*parts) if parts else None


def _check_result_style(snapshot: ProviderCheckSnapshot) -> tuple[str, str, str]:
    if snapshot.is_ready is True:
        return "Ready", "success", "success"
    if snapshot.outcome is ProviderCheckOutcome.LOCAL_PREREQUISITES_READY:
        return "Local prerequisites ready", "warn", "warn"
    return "Needs attention", "error", "error"


def _credential_axis_text(status: ProviderCheckAxisStatus) -> Text:
    style = {
        ProviderCheckAxisStatus.PASSED: "success",
        ProviderCheckAxisStatus.FAILED: "error",
        ProviderCheckAxisStatus.NOT_CHECKED: "muted",
    }[status]
    return Text(_credential_axis_label(status).title(), style=style)


def _reachability_axis_text(status: ProviderCheckAxisStatus) -> Text:
    style = {
        ProviderCheckAxisStatus.PASSED: "success",
        ProviderCheckAxisStatus.FAILED: "error",
        ProviderCheckAxisStatus.NOT_CHECKED: "muted",
    }[status]
    return Text(_reachability_axis_label(status).title(), style=style)


def _credential_axis_label(status: ProviderCheckAxisStatus) -> str:
    return {
        ProviderCheckAxisStatus.PASSED: "found",
        ProviderCheckAxisStatus.FAILED: "missing or rejected",
        ProviderCheckAxisStatus.NOT_CHECKED: "not inspected",
    }[status]


def _reachability_axis_label(status: ProviderCheckAxisStatus) -> str:
    return {
        ProviderCheckAxisStatus.PASSED: "reachable",
        ProviderCheckAxisStatus.FAILED: "unreachable",
        ProviderCheckAxisStatus.NOT_CHECKED: "not tested",
    }[status]


def _authentication_method_text(method: ProviderAuthenticationMethod) -> Text:
    return Text(_display_authentication_method_label(method), style="accent")


def _display_authentication_method_label(method: ProviderAuthenticationMethod) -> str:
    label = authentication_method_label(method)
    return f"{label[0].upper()}{label[1:]}"


def _product_status_text(status: ProviderProductStatus) -> Text:
    style = "warn" if status is ProviderProductStatus.EXPERIMENTAL else "success"
    return _styled_state(_product_status_label(status).title(), style)


def _product_status_label(status: ProviderProductStatus) -> str:
    if status is ProviderProductStatus.EXPERIMENTAL:
        return "experimental"
    return "managed"


def _setup_owner_label(owner: str) -> str:
    if owner == "shared":
        return "AutoClaw route; user-managed provider runtime"
    if owner == "user":
        return "User managed"
    return "AutoClaw managed"


def _styled_state(label: str, style: str) -> Text:
    return Text(label, style=style)


def _provider_check_next_step(snapshot: ProviderCheckSnapshot) -> str | None:
    command = f"autoclaw providers check {snapshot.kind.value}"
    if snapshot.is_ready is True:
        return None
    if snapshot.outcome is ProviderCheckOutcome.NOT_CONFIGURED:
        return f"autoclaw providers configure {snapshot.kind.value}"
    if snapshot.outcome is ProviderCheckOutcome.AUTHENTICATION_FAILED:
        return f"autoclaw providers login {snapshot.kind.value}"
    if snapshot.outcome is ProviderCheckOutcome.LOCAL_PREREQUISITES_READY:
        return f"autoclaw providers login {snapshot.kind.value}"
    if snapshot.outcome is ProviderCheckOutcome.NOT_INSTALLED:
        if snapshot.kind is ProviderKind.OPENCLAW:
            return f"Install OpenClaw, then rerun: {command}"
        return f"Repair the AutoClaw installation, then rerun: {command}"
    if snapshot.outcome is ProviderCheckOutcome.UNREACHABLE:
        return f"Check provider connectivity, then rerun: {command}"
    if snapshot.outcome is ProviderCheckOutcome.INCOMPATIBLE:
        return f"Review the provider route, then rerun: {command}"
    return f"autoclaw --debug providers check {snapshot.kind.value}"


def _has_unchecked_axis(snapshot: ProviderCheckSnapshot) -> bool:
    return ProviderCheckAxisStatus.NOT_CHECKED in {
        snapshot.authentication,
        snapshot.reachability,
    }


__all__ = [
    "emit_provider_check",
    "emit_provider_configuration",
    "emit_provider_definitions",
    "emit_provider_identity",
    "emit_provider_status",
    "provider_display_name",
]
