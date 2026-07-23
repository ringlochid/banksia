from __future__ import annotations

import argparse

from banksia.interfaces.cli.support import coerce_path, command_env, print_json
from banksia.platform.file_entrypoints import task_start_request_from_path
from banksia.runtime.task_start import start_task


async def cmd_task_compose_start(args: argparse.Namespace) -> int:
    config_path = coerce_path(args.config)
    with command_env(config_path=config_path, should_load_provider_secrets=True):
        request = task_start_request_from_path(args.file)
        response = await start_task(request)

    payload = response.model_dump(mode="json")
    if args.json:
        print_json(payload)
    else:
        print(f"started task: {response.task_id}")
        print(f"flow status: {response.flow_status.value}")
        print(f"manifest: {response.workflow_manifest_ref.path}")
    return 0


__all__ = ["cmd_task_compose_start"]
