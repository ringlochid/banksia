from __future__ import annotations

import math
from collections.abc import Hashable
from pathlib import Path
from typing import Any

import yaml
from yaml.error import Mark
from yaml.nodes import MappingNode, Node
from yaml.tokens import AliasToken

YAML_MERGE_TAG = "tag:yaml.org,2002:merge"


class StrictYamlError(ValueError):
    """Raised when a maintained YAML fixture is not a single JSON-compatible tree."""

    def __init__(self, message: str, *, mark: Mark | None = None) -> None:
        super().__init__(message)
        self.problem_mark = mark


class StrictYamlLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate, merge, and non-string mapping keys."""

    def construct_mapping(self, node: Node, deep: bool = False) -> dict[Hashable, Any]:
        if not isinstance(node, MappingNode):
            raise StrictYamlError("expected a mapping node")

        mapping: dict[Hashable, Any] = {}
        for key_node, value_node in node.value:
            if key_node.tag == YAML_MERGE_TAG:
                raise StrictYamlError(
                    "YAML merge keys are not allowed",
                    mark=key_node.start_mark,
                )
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise StrictYamlError(
                    "YAML mapping keys must be strings",
                    mark=key_node.start_mark,
                )
            if key in mapping:
                raise StrictYamlError(
                    f"duplicate YAML mapping key {key!r}",
                    mark=key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def load_strict_yaml(path: Path) -> object:
    """Load one maintained YAML document without YAML graph or non-JSON behavior."""

    text = path.read_text(encoding="utf-8")
    for token in yaml.scan(text, Loader=StrictYamlLoader):
        if isinstance(token, AliasToken):
            raise StrictYamlError("YAML aliases are not allowed", mark=token.start_mark)

    loader = StrictYamlLoader(text)
    try:
        value = loader.get_single_data()
    finally:
        loader.dispose()
    validate_json_compatible(value)
    return value


def validate_json_compatible(value: object, *, location: str = "$") -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise StrictYamlError(f"{location} contains a non-finite number")
    if isinstance(value, list):
        for index, child in enumerate(value):
            validate_json_compatible(child, location=f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise StrictYamlError(f"{location} contains a non-string mapping key")
            validate_json_compatible(child, location=f"{location}.{key}")
        return
    raise StrictYamlError(f"{location} contains non-JSON YAML value {type(value).__name__}")


__all__ = ["StrictYamlError", "load_strict_yaml"]
