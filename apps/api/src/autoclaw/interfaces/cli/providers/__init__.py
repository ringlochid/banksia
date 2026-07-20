"""CLI-owned provider configuration and passive product readbacks."""

from autoclaw.interfaces.cli.providers.configuration import (
    ProviderConfigurationRequest,
    configure_provider,
    set_default_provider,
    set_openclaw_gateway_auth_mode,
)
from autoclaw.interfaces.cli.providers.identity import (
    authentication_method_choices,
    authentication_method_label,
    invoke_provider_identity_action,
    provider_secret_environment_key,
)
from autoclaw.interfaces.cli.providers.inspection import (
    collect_provider_check,
    collect_provider_definitions,
    collect_provider_statuses,
)

__all__ = [
    "ProviderConfigurationRequest",
    "authentication_method_choices",
    "authentication_method_label",
    "collect_provider_check",
    "collect_provider_definitions",
    "collect_provider_statuses",
    "configure_provider",
    "invoke_provider_identity_action",
    "provider_secret_environment_key",
    "set_default_provider",
    "set_openclaw_gateway_auth_mode",
]
