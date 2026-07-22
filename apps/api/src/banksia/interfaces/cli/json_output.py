from __future__ import annotations

import json
from typing import Any

import click


def emit_json(payload: dict[str, Any]) -> None:
    click.echo(json.dumps(payload, indent=2, sort_keys=True))
