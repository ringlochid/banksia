from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductIdentity:
    distribution_name: str
    import_package: str
    application_name: str
    database_filename: str
    provider_environment_filename: str
    task_container_name: str
    system_prompt_root: str
    dispatch_request_root: str
    node_mcp_server_name: str
    node_mcp_transport_name: str
    operator_mcp_server_name: str
    systemd_service_name: str
    launchd_service_name: str
    scheduled_task_service_name: str
    service_logger_name: str


OMS_IDENTITY = ProductIdentity(
    distribution_name="oh-my-subagents",
    import_package="oh_my_subagents",
    application_name="oh-my-subagents",
    database_filename="oms.persistence",
    provider_environment_filename="oms.env",
    task_container_name=".oms",
    system_prompt_root="oms_system",
    dispatch_request_root="oms_dispatch_request",
    node_mcp_server_name="oms_node",
    node_mcp_transport_name="oms-node-managed",
    operator_mcp_server_name="oms_operator",
    systemd_service_name="oh-my-subagents.service",
    launchd_service_name="io.github.ringlochid.oh-my-subagents",
    scheduled_task_service_name=r"\Oh My Subagents\Controller",
    service_logger_name="oh_my_subagents.service",
)

LEGACY_BANKSIA_IDENTITY = ProductIdentity(
    distribution_name="banksia",
    import_package="banksia",
    application_name="banksia",
    database_filename="banksia.persistence",
    provider_environment_filename="banksia.env",
    task_container_name=".banksia",
    system_prompt_root="banksia_system",
    dispatch_request_root="banksia_dispatch_request",
    node_mcp_server_name="banksia_node",
    node_mcp_transport_name="banksia-node-managed",
    operator_mcp_server_name="banksia_operator",
    systemd_service_name="banksia.service",
    launchd_service_name="io.github.ringlochid.banksia",
    scheduled_task_service_name=r"\Banksia\Controller",
    service_logger_name="banksia.service",
)


__all__ = [
    "LEGACY_BANKSIA_IDENTITY",
    "OMS_IDENTITY",
    "ProductIdentity",
]
