from __future__ import annotations

from datetime import datetime
from enum import Enum
from xml.etree import ElementTree

from pydantic import BaseModel

from oh_my_subagents.product_identity import LEGACY_BANKSIA_IDENTITY, OMS_IDENTITY
from oh_my_subagents.runtime.contracts.prompt import (
    PROMPT_DYNAMIC_INPUT_KEYS,
    DispatchRequestRenderInput,
    PromptContinuation,
    PromptDynamicInput,
    RenderedDispatchRequest,
)
from oh_my_subagents.runtime.prompt.instructions import render_request_instructions

_COLLECTION_ITEM_TAGS = {
    "argv": "arg",
    "available_actions": "action",
    "created_ids": "id",
    "direct_team": "member",
    "files": "file",
    "human_request": "kind",
    "items": "item",
    "members": "member",
    "options": "option",
    "removed_ids": "id",
    "steps": "step",
    "steering": "steer",
    "updated_ids": "id",
}
_BOOLEAN_FIELDS = frozenset(("must_stop", "output_complete"))
_JSON_FIELDS = frozenset(("item_responses", "response_schema"))


def render_dispatch_request(request: DispatchRequestRenderInput) -> RenderedDispatchRequest:
    return RenderedDispatchRequest(
        instructions_text=render_request_instructions(request),
        input_text=render_dynamic_input(request.dynamic_input),
    )


def render_dynamic_input(dynamic_input: PromptDynamicInput) -> str:
    if tuple(type(dynamic_input).model_fields) != PROMPT_DYNAMIC_INPUT_KEYS:
        raise ValueError("dynamic prompt input field order does not match the canonical contract")
    root = ElementTree.Element(OMS_IDENTITY.dispatch_request_root)
    for field_name in PROMPT_DYNAMIC_INPUT_KEYS:
        value = getattr(dynamic_input, field_name)
        if value is None:
            continue
        _append_value(root, field_name, value)
    ElementTree.indent(root, space="  ")
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True) + "\n"


def parse_prompt_continuation(input_text: str) -> PromptContinuation | None:
    """Read the exact Continuation from one committed Oh My Subagents Dispatch input."""

    try:
        root = ElementTree.fromstring(input_text)
    except ElementTree.ParseError as exc:
        raise ValueError("committed Dispatch input is not well-formed XML") from exc
    if root.tag not in {
        OMS_IDENTITY.dispatch_request_root,
        LEGACY_BANKSIA_IDENTITY.dispatch_request_root,
    }:
        raise ValueError("committed Dispatch input has an unsupported root element")
    element = root.find("continuation")
    if element is None:
        return None
    value = _element_value(element)
    if not isinstance(value, dict):
        raise ValueError("committed Dispatch Continuation has an invalid shape")
    return PromptContinuation.model_validate(value)


def _append_value(parent: ElementTree.Element, name: str, value: object) -> None:
    element = ElementTree.SubElement(parent, name)
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            field_value = getattr(value, field_name)
            if field_value is None:
                continue
            if field_name in _JSON_FIELDS:
                field = ElementTree.SubElement(element, field_name)
                _append_json_value(field, field_value)
            else:
                _append_value(element, field_name, field_value)
        return
    if isinstance(value, (tuple, list)):
        item_tag = _COLLECTION_ITEM_TAGS.get(name)
        if item_tag is None:
            raise ValueError(f"no fixed XML item tag is defined for '{name}'")
        for item in value:
            _append_value(element, item_tag, item)
        return
    if isinstance(value, dict):
        _append_json_value(element, value)
        return
    if isinstance(value, Enum):
        element.text = str(value.value)
        return
    if isinstance(value, bool):
        element.text = "true" if value else "false"
        return
    if isinstance(value, datetime):
        element.text = value.isoformat().replace("+00:00", "Z")
        return
    element.text = str(value)


def _append_json_value(parent: ElementTree.Element, value: object) -> None:
    if isinstance(value, BaseModel):
        _append_json_value(parent, value.model_dump(mode="json"))
        return
    if value is None:
        ElementTree.SubElement(parent, "null")
        return
    if isinstance(value, bool):
        element = ElementTree.SubElement(parent, "boolean")
        element.text = "true" if value else "false"
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        element = ElementTree.SubElement(parent, "number")
        element.text = str(value)
        return
    if isinstance(value, str):
        element = ElementTree.SubElement(parent, "string")
        element.text = value
        return
    if isinstance(value, (tuple, list)):
        array = ElementTree.SubElement(parent, "array")
        for item in value:
            item_element = ElementTree.SubElement(array, "item")
            _append_json_value(item_element, item)
        return
    if isinstance(value, dict):
        object_element = ElementTree.SubElement(parent, "object")
        for key, item in value.items():
            entry = ElementTree.SubElement(object_element, "entry")
            key_element = ElementTree.SubElement(entry, "key")
            key_element.text = str(key)
            item_element = ElementTree.SubElement(entry, "value")
            _append_json_value(item_element, item)
        return
    raise TypeError(f"unsupported JSON value type: {type(value).__name__}")


def _element_value(element: ElementTree.Element) -> object:
    if element.tag in _JSON_FIELDS:
        return _read_json_value(element)
    if element.tag in _COLLECTION_ITEM_TAGS:
        return [_element_value(child) for child in element]
    children = list(element)
    if not children:
        if element.tag in _BOOLEAN_FIELDS:
            if element.text not in {"true", "false"}:
                raise ValueError(f"encoded Boolean field '{element.tag}' is invalid")
            return element.text == "true"
        return element.text or ""
    return {child.tag: _element_value(child) for child in children}


def _read_json_value(element: ElementTree.Element) -> object:
    children = list(element)
    if len(children) != 1:
        raise ValueError("encoded JSON value must have exactly one typed child")
    typed = children[0]
    if typed.tag == "null":
        return None
    if typed.tag == "boolean":
        return typed.text == "true"
    if typed.tag == "number":
        text = typed.text or ""
        return float(text) if any(marker in text for marker in (".", "e", "E")) else int(text)
    if typed.tag == "string":
        return typed.text or ""
    if typed.tag == "array":
        return [_read_json_value(item) for item in typed]
    if typed.tag == "object":
        result: dict[str, object] = {}
        for entry in typed:
            key = entry.findtext("key")
            value = entry.find("value")
            if key is None or value is None:
                raise ValueError("encoded JSON object entry is incomplete")
            result[key] = _read_json_value(value)
        return result
    raise ValueError(f"encoded JSON value has unsupported type '{typed.tag}'")


__all__ = [
    "parse_prompt_continuation",
    "render_dispatch_request",
    "render_dynamic_input",
]
