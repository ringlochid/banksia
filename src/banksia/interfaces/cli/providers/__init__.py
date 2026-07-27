"""CLI-owned provider configuration and passive product readbacks."""

from banksia.interfaces.cli.providers.configuration import (
    ProviderConfigurationRequest,
    configure_provider,
    set_default_provider,
    set_openclaw_gateway_auth_mode,
)
from banksia.interfaces.cli.providers.identity import (
    authentication_method_choices,
    authentication_method_label,
    invoke_provider_identity_action,
    provider_secret_environment_key,
)
from banksia.interfaces.cli.providers.inspection import (
    collect_provider_check,
    collect_provider_definitions,
    collect_provider_statuses,
)
from banksia.interfaces.cli.providers.operator_selection import (
    OperatorProviderRouteNotConfiguredError,
    OperatorSelectionMutationResult,
    OperatorSelectionRequest,
    OperatorSelectionSnapshot,
    disable_operator_selection,
    is_operator_provider_persisted,
    read_operator_selection,
    save_operator_selection,
)

__all__ = [
    "OperatorProviderRouteNotConfiguredError",
    "OperatorSelectionMutationResult",
    "OperatorSelectionRequest",
    "OperatorSelectionSnapshot",
    "ProviderConfigurationRequest",
    "authentication_method_choices",
    "authentication_method_label",
    "collect_provider_check",
    "collect_provider_definitions",
    "collect_provider_statuses",
    "configure_provider",
    "disable_operator_selection",
    "invoke_provider_identity_action",
    "is_operator_provider_persisted",
    "provider_secret_environment_key",
    "read_operator_selection",
    "save_operator_selection",
    "set_default_provider",
    "set_openclaw_gateway_auth_mode",
]
