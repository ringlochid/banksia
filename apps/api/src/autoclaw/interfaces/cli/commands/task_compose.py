from __future__ import annotations

import argparse

from autoclaw.definitions.registry.task_start import start_task_from_definition
from autoclaw.interfaces.cli.support import coerce_path, command_env, print_json
from autoclaw.platform.file_entrypoints import task_start_request_from_path


async def cmd_task_compose_start(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    with command_env(config_path=config_path, should_load_provider_secrets=True):
        request = task_start_request_from_path(args.file)
        response = await start_task_from_definition(request)

    payload = response.model_dump(mode="json")
    if args.json:
        print_json(payload)
    else:
        print(f"started task: {response.task_id}")
        print(f"flow status: {response.flow_status.value}")
        print(f"manifest: {response.workflow_manifest_ref.path}")
    return 0


__all__ = ["cmd_task_compose_start"]
