from __future__ import annotations

from autoclaw.interfaces.cli.commands.bootstrap import (
    cmd_db_reset,
    cmd_db_upgrade,
    cmd_init,
    cmd_serve,
    settings_to_config_text,
)
from autoclaw.interfaces.cli.commands.config_view import (
    cmd_config_path,
    cmd_config_show,
)
from autoclaw.interfaces.cli.commands.definitions import cmd_definitions_import
from autoclaw.interfaces.cli.commands.service import (
    DEFAULT_SERVICE_NAME,
    cmd_service_install,
    cmd_service_render,
    cmd_service_restart,
    cmd_service_start,
    cmd_service_status,
    cmd_service_stop,
    cmd_service_uninstall,
    render_service_unit,
)
from autoclaw.interfaces.cli.commands.task_compose import cmd_task_compose_start
from autoclaw.interfaces.cli.support import command_env, print_json

from .main import build_parser, main

__all__ = [
    "DEFAULT_SERVICE_NAME",
    "build_parser",
    "cmd_config_path",
    "cmd_config_show",
    "cmd_db_reset",
    "cmd_db_upgrade",
    "cmd_definitions_import",
    "cmd_init",
    "cmd_serve",
    "cmd_service_install",
    "cmd_service_render",
    "cmd_service_restart",
    "cmd_service_start",
    "cmd_service_status",
    "cmd_service_stop",
    "cmd_service_uninstall",
    "cmd_task_compose_start",
    "command_env",
    "main",
    "print_json",
    "render_service_unit",
    "settings_to_config_text",
]
